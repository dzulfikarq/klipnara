"use client";

import { useRouter } from "next/navigation";
import { AlertCircle, ArrowLeft, ArrowRight, CheckCircle2, Clock3, Download, ExternalLink, FileVideo2, Info, LoaderCircle, LockKeyhole, Play, RotateCcw, Scissors, Upload, Video, Youtube } from "lucide-react";
import { ChangeEvent, useCallback, useEffect, useRef, useState } from "react";
import { API, ApiRequestError, formatBytes, formatDuration, request } from "@/lib/api";
import { formatTimestamp, isYouTubeMetadataRouteNotFound, parseTimestamp, parseYouTubeUrl, quickClipYouTubeReference, validateClipRange, YOUTUBE_METADATA_PATH } from "@/lib/youtube-clip.mjs";
import { YouTubeClipPlayer, YouTubePlayerApi } from "./youtube-clip-player";

type Source = { id: string; name: string; duration: number; width: number; height: number; size_bytes: number; video_codec: string; audio_codec: string | null };
type YouTubeMetadata = { title: string | null; channel: string | null; thumbnail_url: string | null; duration_seconds: number | null; embeddable: boolean | null };
type YouTubeInfo = { video_id: string; canonical_url: string; start_seconds: number | null; metadata_status: string; metadata_message: string | null; metadata: YouTubeMetadata | null };
type Job = { id: string; status: string; phase: string; progress: number | null; message: string };
type ImportCapabilities = { available: boolean; reason: string | null; notice: string | null };
type YouTubeImportJob = { id: string; status: string; phase: string; progress: number | null; message: string; source_id: string | null; source: Source | null };
type Props = { onBack: () => void };

const stepNames = ["URL", "Preview & Trim", "Impor Sumber Video", "Quick Clip Editor"];
const activeJobStatuses = new Set(["queued", "preparing", "rendering"]);
const activeImportStatuses = new Set(["queued", "preparing", "importing", "processing"]);

export function YouTubeClipFlow({ onBack }: Props) {
  const router = useRouter();
  const fileInput = useRef<HTMLInputElement>(null);
  const importFinalizeStarted = useRef("");
  const [step, setStep] = useState(1);
  const [url, setUrl] = useState("");
  const [loadedUrl, setLoadedUrl] = useState("");
  const [info, setInfo] = useState<YouTubeInfo | null>(null);
  const [metadataBusy, setMetadataBusy] = useState(false);
  const [startText, setStartText] = useState("00:00");
  const [endText, setEndText] = useState("01:00");
  const [playhead, setPlayhead] = useState(0);
  const [playerDuration, setPlayerDuration] = useState<number | null>(null);
  const [player, setPlayer] = useState<YouTubePlayerApi | null>(null);
  const [playerError, setPlayerError] = useState("");
  const [playerReload, setPlayerReload] = useState(0);
  const [sourceMode, setSourceMode] = useState<"library" | "upload">("library");
  const [sources, setSources] = useState<Source[]>([]);
  const [source, setSource] = useState<Source | null>(null);
  const [sourcesLoading, setSourcesLoading] = useState(true);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [importCapabilities, setImportCapabilities] = useState<ImportCapabilities>({ available: false, reason: "Memeriksa adapter lokal…", notice: null });
  const [importJob, setImportJob] = useState<YouTubeImportJob | null>(null);
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState("");
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [autoImportedSourceId, setAutoImportedSourceId] = useState("");
  const [title, setTitle] = useState("");
  const [resolution, setResolution] = useState<"720" | "1080">("720");
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [clipId, setClipId] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    request<Source[]>("/sources")
      .then((items) => { if (alive) setSources(items); })
      .catch((reason) => { if (alive) setError((reason as Error).message); })
      .finally(() => { if (alive) setSourcesLoading(false); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    let alive = true;
    request<ImportCapabilities>("/youtube-clips/import-capabilities")
      .then((result) => { if (alive) setImportCapabilities(result); })
      .catch(() => { if (alive) setImportCapabilities({ available: false, reason: "Backend belum menyediakan adapter impor otomatis. Perbarui backend ke Klipnara V2.6.0 atau gunakan sumber lokal.", notice: null }); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!job || !activeJobStatuses.has(job.status)) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await request<Job>(`/jobs/${job.id}`);
        if (!alive) return;
        setJob(next);
        if (next.status === "completed" && clipId) { router.push(`/clips/${clipId}`); return; }
        if (["failed", "cancelled", "completed"].includes(next.status)) return;
        timer = setTimeout(poll, 900);
      } catch (reason) {
        if (alive) {
          setError((reason as Error).message);
          timer = setTimeout(poll, 1500);
        }
      }
    };
    timer = setTimeout(poll, 650);
    return () => { alive = false; clearTimeout(timer); };
  }, [job?.id, job?.status, clipId, router]);

  useEffect(() => {
    if (!importJob || !activeImportStatuses.has(importJob.status)) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await request<YouTubeImportJob>(`/youtube-clips/imports/${importJob.id}`);
        if (!alive) return;
        setImportJob(next);
        if (activeImportStatuses.has(next.status)) timer = setTimeout(poll, 900);
      } catch (reason) {
        if (alive) {
          setImportError((reason as Error).message);
          timer = setTimeout(poll, 1500);
        }
      }
    };
    timer = setTimeout(poll, 500);
    return () => { alive = false; clearTimeout(timer); };
  }, [importJob?.id, importJob?.status]);

  const parsedStart = parseTimestamp(startText);
  const parsedEnd = parseTimestamp(endText);
  const originalDuration = info?.metadata?.duration_seconds || playerDuration;
  const youtubeRange = validateClipRange(parsedStart, parsedEnd, originalDuration);
  const localRange = source ? validateClipRange(parsedStart, parsedEnd, source.duration) : null;
  const running = Boolean(job && activeJobStatuses.has(job.status));

  const showInformation = (result: YouTubeInfo, sourceUrl: string) => {
    const start = result.start_seconds ?? 0;
    const duration = result.metadata?.duration_seconds;
    const end = duration && start < duration ? Math.floor(Math.min(start + 60, duration)) : start + 60;
    setInfo(result);
    setLoadedUrl(sourceUrl);
    setStartText(formatTimestamp(start));
    setEndText(formatTimestamp(end > start ? end : start + 60));
    setPlayhead(start);
    setTitle(result.metadata?.title || "");
    setSource(null); setAutoImportedSourceId(""); setJob(null); setClipId(""); setImportJob(null); setImportError(""); setRightsConfirmed(false);
    setStep(2);
  };

  const loadInformation = async () => {
    if (metadataBusy) return;
    if (info && loadedUrl === url) { setStep(2); return; }
    setError(""); setMetadataBusy(true); setPlayerError(""); setPlayerDuration(null); setPlayer(null);
    try {
      const result = await request<YouTubeInfo>(YOUTUBE_METADATA_PATH, { method: "POST", body: JSON.stringify({ url }) });
      showInformation(result, url);
    } catch (reason) {
      if (reason instanceof ApiRequestError && isYouTubeMetadataRouteNotFound(reason.status, reason.path)) {
        const parsed = parseYouTubeUrl(url);
        if (parsed) {
          showInformation({
            ...parsed,
            metadata: null,
            metadata_status: "route_not_found",
            metadata_message: "POST /api/youtube-clips/metadata mengembalikan HTTP 404: route/backend tidak cocok, bukan hasil pemeriksaan YouTube. Cek NEXT_PUBLIC_API_URL dan backend V2.5. Preview tetap dicoba; format ID ini bukan bukti video tersedia. Quick Clip lokal tetap bisa dilanjutkan, tetapi tanpa provenance dan re-probe durasi V2.5.",
          }, url);
        } else setError("Backend metadata route mengembalikan HTTP 404. URL juga tidak lolos validasi format lokal; video belum diverifikasi.");
      } else setError((reason as Error).message);
    }
    finally { setMetadataBusy(false); }
  };

  const updateUrl = (value: string) => {
    setUrl(value); setLoadedUrl(""); setInfo(null); setSource(null); setAutoImportedSourceId(""); setPlayer(null); setPlayerDuration(null);
    setStep(1); setError(""); setJob(null); setClipId(""); setImportJob(null); setImportError(""); setRightsConfirmed(false); importFinalizeStarted.current = "";
  };

  const captureTime = (kind: "start" | "end") => {
    const value = formatTimestamp(playhead);
    if (kind === "start") setStartText(value); else setEndText(value);
  };

  const resetRange = () => {
    const duration = originalDuration;
    setStartText("00:00");
    setEndText(formatTimestamp(duration ? Math.floor(Math.min(60, duration)) || 60 : 60));
    setPlayhead(0);
    player?.seekTo(0, true);
  };

  const replayRange = () => {
    if (!player || parsedStart === null || parsedEnd === null || !youtubeRange.valid) return;
    setPlayerError(""); player.seekTo(parsedStart, true); player.playVideo();
  };

  const uploadSource = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    setError(""); setUploadBusy(true);
    setAutoImportedSourceId("");
    try {
      const form = new FormData(); form.append("file", file);
      const created = await request<Source>("/sources/upload", { method: "POST", body: form });
      setSource(created); setSources((items) => [created, ...items.filter((item) => item.id !== created.id)]);
    } catch (reason) { setError((reason as Error).message); }
    finally { setUploadBusy(false); }
  };

  const selectSource = (sourceId: string) => { setError(""); setAutoImportedSourceId(""); setSource(sources.find((item) => item.id === sourceId) || null); };

  const createQuickClip = async () => {
    if (!info || !source || parsedStart === null || parsedEnd === null || !localRange?.valid) return;
    if (!title.trim()) { setError("Judul klip wajib diisi."); return; }
    setError(""); setBusy(true); setJob(null); setClipId("");
    try {
      const youtubeReference = quickClipYouTubeReference(info);
      const result = await request<{ id: string; clip_id: string; status: string }>(`/sources/${source.id}/quick-clips`, {
        method: "POST",
        body: JSON.stringify({
          title: title.trim(), start: parsedStart, end: parsedEnd, resolution,
          ...(youtubeReference && { youtube_reference: youtubeReference }),
        }),
      });
      setClipId(result.clip_id);
      setJob({ id: result.id, status: result.status, phase: result.status, progress: null, message: "Quick Clip masuk antrean render lokal" });
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };

  const startAutomaticImport = async () => {
    if (importBusy || importRunning || busy) return;
    if (!info || parsedStart === null || parsedEnd === null || !youtubeRange.valid) return;
    if (!importCapabilities.available) { setImportError(importCapabilities.reason || "Adapter impor otomatis tidak tersedia."); return; }
    if (!rightsConfirmed) { setImportError("Konfirmasi izin pengambilan dan penggunaan konten sebelum memakai adapter lokal."); return; }
    setImportError(""); setImportBusy(true); setImportJob(null); setJob(null); setClipId("");
    importFinalizeStarted.current = "";
    try {
      const created = await request<{ id: string; status: string; phase: string }>("/youtube-clips/imports", {
        method: "POST",
        body: JSON.stringify({ url: info.canonical_url, start: parsedStart, end: parsedEnd, rights_confirmed: rightsConfirmed }),
      });
      setImportJob({ ...created, progress: null, message: "Menunggu impor segmen", source_id: null, source: null });
    } catch (reason) { setImportError((reason as Error).message); }
    finally { setImportBusy(false); }
  };

  const createImportedQuickClip = useCallback(async (importId: string, importedSource: Source) => {
    if (!info || parsedStart === null || parsedEnd === null) return;
    setImportError(""); setBusy(true); setSource(importedSource); setAutoImportedSourceId(importedSource.id);
    setSources((items) => [importedSource, ...items.filter((item) => item.id !== importedSource.id)]);
    try {
      const result = await request<{ id: string; clip_id: string; status: string }>(`/sources/${importedSource.id}/quick-clips`, {
        method: "POST",
        body: JSON.stringify({
          title: title.trim() || `Quick Clip ${info.video_id}`,
          start: 0,
          end: importedSource.duration,
          resolution,
          youtube_reference: {
            canonical_url: info.canonical_url,
            video_id: info.video_id,
            start: parsedStart,
            end: parsedEnd,
          },
        }),
      });
      setClipId(result.clip_id);
      setJob({ id: result.id, status: result.status, phase: result.status, progress: null, message: `Segmen ${importId.slice(0, 8)} siap · Quick Clip masuk antrean render` });
    } catch (reason) {
      setImportError(`Segmen sudah masuk Source Library, tetapi Quick Clip belum dibuat: ${(reason as Error).message}`);
    } finally { setBusy(false); }
  }, [info, parsedStart, parsedEnd, resolution, title]);

  const retryAutomaticImport = async () => {
    if (!importJob || !rightsConfirmed) return;
    setImportError(""); setImportBusy(true); importFinalizeStarted.current = "";
    try {
      const created = await request<{ id: string; status: string; phase: string }>(`/youtube-clips/imports/${importJob.id}/retry`, {
        method: "POST", body: JSON.stringify({ rights_confirmed: rightsConfirmed }),
      });
      setImportJob({ ...created, progress: null, message: "Retry menunggu impor segmen", source_id: null, source: null });
    } catch (reason) { setImportError((reason as Error).message); }
    finally { setImportBusy(false); }
  };

  const cancelAutomaticImport = async () => {
    if (!importJob) return;
    try {
      await request(`/youtube-clips/imports/${importJob.id}/cancel`, { method: "POST" });
      setImportJob({ ...importJob, status: "cancelled", phase: "cancelled", message: "Impor dibatalkan pengguna" });
    } catch (reason) { setImportError((reason as Error).message); }
  };

  const retryJob = async () => {
    if (!job) return;
    setError(""); setBusy(true);
    try {
      const retried = await request<{ id: string; status: string }>(`/jobs/${job.id}/retry`, { method: "POST", body: "{}" });
      setJob({ id: retried.id, status: retried.status, phase: retried.status, progress: null, message: "Quick Clip masuk antrean retry" });
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };

  const cancelJob = async () => {
    if (!job) return;
    try { await request(`/jobs/${job.id}/cancel`, { method: "POST" }); setJob({ ...job, status: "cancelled", phase: "cancelled", message: "Render dibatalkan pengguna" }); }
    catch (reason) { setError((reason as Error).message); }
  };

  useEffect(() => {
    if (importJob?.status !== "ready" || !importJob.source || importFinalizeStarted.current === importJob.id) return;
    importFinalizeStarted.current = importJob.id;
    void createImportedQuickClip(importJob.id, importJob.source);
  }, [importJob?.id, importJob?.status, importJob?.source, createImportedQuickClip]);

  const rangeMessage = (valid: ReturnType<typeof validateClipRange>, duration: number | null, local = false) => {
    if (!valid.valid) {
      if (valid.reason === "invalid") return "Gunakan format MM:SS atau HH:MM:SS.";
      if (valid.reason === "order") return "End Time harus lebih besar dari Start Time.";
      return `End Time melewati durasi ${local ? "file lokal" : "video YouTube"} (${formatTimestamp(duration || 0)}).`;
    }
    if (!valid.durationKnown) return `Rentang ${formatTimestamp(valid.selectedDuration || 0)} valid secara format; durasi asli belum diketahui, jadi batas video belum diverifikasi.`;
    return `Rentang valid · ${formatTimestamp(valid.selectedDuration || 0)} · durasi ${formatTimestamp(duration || 0)}${local ? " · file lokal" : ""}.`;
  };

  const importPhase = job
    ? job.status === "completed" ? "ready" : "processing"
    : importJob?.status === "ready" ? "processing" : importJob?.phase || "";
  const importPhaseIndex = ["preparing", "importing", "processing", "ready"].indexOf(importPhase);
  const importProgress = job?.progress ?? importJob?.progress ?? null;
  const importRunning = Boolean(importJob && activeImportStatuses.has(importJob.status));

  return <>
    <div className="page-intro">
      <button type="button" className="back-link mode-back" onClick={onBack} disabled={importRunning || running}><ArrowLeft size={14}/> Semua mode</button>
      <div className="eyebrow">YOUTUBE CLIP · PREVIEW + IMPOR SEGMEN OPSIONAL</div>
      <h1>YouTube Clip</h1>
      <p>Preview timestamp, impor segmen jika adapter lokal tersedia dan penggunaan diizinkan, lalu lanjutkan ke Quick Clip Editor.</p>
    </div>

    <nav className="youtube-clip-steps" aria-label="Langkah YouTube Clip">
      {stepNames.map((name, index) => {
        const number = index + 1;
        return <button key={name} type="button" aria-current={step === number ? "step" : undefined} className={step === number ? "active" : step > number ? "complete" : ""} disabled={number >= step || importRunning || running} onClick={() => number < step && setStep(number)}><i>{step > number ? "✓" : number}</i><span>{name}</span></button>;
      })}
    </nav>

    <div className="youtube-clip-layout">
      <div className="youtube-clip-main">
        {step === 1 && <section className="panel form-panel youtube-clip-panel">
          <div className="step-heading"><span className="step-number">01</span><div><h2>Paste YouTube URL</h2><p>URL standar, youtu.be, atau Shorts.</p></div><Youtube size={19} className="youtube-step-icon"/></div>
          <label className="field" htmlFor="youtube-clip-url"><span>URL video YouTube</span><input id="youtube-clip-url" type="text" inputMode="url" maxLength={2048} autoComplete="url" placeholder="https://www.youtube.com/watch?v=…" value={url} disabled={metadataBusy} onChange={(event) => updateUrl(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void loadInformation(); }}/></label>
          <small className="youtube-url-help">Didukung: youtube.com/watch?v=…, youtu.be/…, youtube.com/shorts/… · parameter `t` / `start` dibaca jika valid.</small>
          {error && <div className="notice notice-error"><AlertCircle size={16}/><span>{error}</span></div>}
          <div className="youtube-boundary-note"><LockKeyhole size={14}/><span>URL divalidasi dan dipakai untuk preview. Impor otomatis terpisah, opsional, dan tunduk pada izin konten serta batas platform.</span></div>
          <div className="youtube-step-actions"><span>Metadata opsional · preview tergantung izin embed dan jaringan.</span><button type="button" className="button button-primary" onClick={() => void loadInformation()} disabled={metadataBusy || !url.trim()}>{metadataBusy ? <LoaderCircle size={15} className="spin"/> : <Video size={15}/>} Ambil Informasi Video <ArrowRight size={15}/></button></div>
        </section>}

        {step === 2 && info && <>
          <section className="panel form-panel youtube-clip-panel">
            <div className="step-heading"><span className="step-number">02</span><div><h2>Preview & Trim</h2><p>Pilih rentang berdasarkan posisi player; timing preview dapat berbeda dari trim FFmpeg.</p></div><span className="required-label">IFRAME API</span></div>
            <div className="youtube-player-frame"><YouTubeClipPlayer key={`${info.video_id}-${playerReload}`} videoId={info.video_id} startAt={info.start_seconds ?? 0} endAt={parsedEnd ?? 0} reloadKey={playerReload} onPlayer={setPlayer} onTime={setPlayhead} onDuration={setPlayerDuration} onPlaying={() => undefined} onError={(message) => { setPlayerError(message); setPlayer(null); }}/></div>
            {playerError && <div className="youtube-player-error"><AlertCircle size={15}/><span>{playerError}</span><button type="button" className="button button-outline small-button" onClick={() => { setPlayerError(""); setPlayerReload((key) => key + 1); }}>Coba muat ulang</button></div>}
            {info.metadata_status !== "available" && info.metadata_message && <div className={`youtube-metadata-note ${info.metadata_status === "route_not_found" ? "youtube-route-error" : ""}`} role="status"><Info size={14}/><span>{info.metadata_message}</span></div>}
            {info.metadata?.embeddable === false && <div className="youtube-player-error"><AlertCircle size={15}/><span>YouTube Data API menandai video ini tidak dapat di-embed. Metadata tidak membuka batasan pemilik.</span></div>}
            <div className={`youtube-video-info${info.metadata?.thumbnail_url ? "" : " without-thumbnail"}`}>
              {info.metadata?.thumbnail_url && <img src={info.metadata.thumbnail_url} alt="Thumbnail video YouTube" loading="lazy" referrerPolicy="no-referrer"/>}
              <div><strong>{info.metadata?.title || "Judul tidak tersedia"}</strong><span>{info.metadata?.channel || "Channel tidak tersedia"}</span><small>ID {info.video_id} · {originalDuration ? `durasi ${formatTimestamp(originalDuration)}` : "durasi belum diketahui"}</small><a href={info.canonical_url} target="_blank" rel="noreferrer">Buka URL canonical <ExternalLink size={12}/></a></div>
            </div>
            <label className="field youtube-original-url"><span>URL asli yang ditempel</span><input readOnly value={url}/></label>
            <div className="youtube-timestamp-grid">
              <label className="field"><span>Start Time</span><input type="text" inputMode="numeric" aria-label="YouTube Start Time" aria-invalid={parsedStart === null} value={startText} onChange={(event) => setStartText(event.target.value)} placeholder="MM:SS / HH:MM:SS"/><small>Contoh: 14:09</small></label>
              <button type="button" className="button button-outline" disabled={!player} onClick={() => captureTime("start")}>Gunakan {formatTimestamp(playhead)} sebagai Start</button>
              <label className="field"><span>End Time</span><input type="text" inputMode="numeric" aria-label="YouTube End Time" aria-invalid={parsedEnd === null} value={endText} onChange={(event) => setEndText(event.target.value)} placeholder="MM:SS / HH:MM:SS"/><small>Selected Duration: {parsedStart !== null && parsedEnd !== null && parsedEnd > parsedStart ? formatTimestamp(parsedEnd - parsedStart) : "—"}</small></label>
              <button type="button" className="button button-outline" disabled={!player} onClick={() => captureTime("end")}>Gunakan {formatTimestamp(playhead)} sebagai End</button>
            </div>
            <div className={`timestamp-validation ${youtubeRange.valid ? youtubeRange.durationKnown ? "valid" : "unknown" : "invalid"}`} role="status">{!youtubeRange.valid ? <AlertCircle size={15}/> : youtubeRange.durationKnown ? <CheckCircle2 size={15}/> : <Info size={15}/>}<span>{rangeMessage(youtubeRange, originalDuration)}</span></div>
            <div className="youtube-player-controls"><span><Clock3 size={13}/> Playhead {formatTimestamp(playhead)}</span><button type="button" className="button button-outline" disabled={!player || !youtubeRange.valid} onClick={replayRange}><Play size={13}/> Putar Ulang Rentang</button><button type="button" className="button button-quiet" onClick={resetRange}><RotateCcw size={13}/> Reset</button></div>
            <div className="youtube-step-actions"><button type="button" className="button button-outline" onClick={() => setStep(1)}><ArrowLeft size={14}/> Ubah URL</button><button type="button" className="button button-primary" disabled={!youtubeRange.valid} onClick={() => { setError(""); setStep(3); }}>Pilih sumber segmen <ArrowRight size={14}/></button></div>
          </section>
        </>}

        {step === 3 && info && <section className="panel form-panel youtube-clip-panel">
          <div className="step-heading"><span className="step-number">03</span><div><h2>Impor Sumber Video</h2><p>Impor segmen pilihan sebagai source lokal, atau gunakan file lokal sebagai alternatif.</p></div><span className="required-label">OPSIONAL</span></div>
          <section className="youtube-auto-import">
            <div className="youtube-auto-import-heading"><div><strong>Impor & Buat Klip</strong><span>Adapter lokal yt-dlp mengambil rentang {parsedStart !== null ? formatTimestamp(parsedStart) : startText}–{parsedEnd !== null ? formatTimestamp(parsedEnd) : endText}; hasil masuk Source Library lalu Quick Clip existing merendernya.</span></div><Download size={18}/></div>
            {importCapabilities.notice && <div className="youtube-metadata-note"><Info size={14}/><span>{importCapabilities.notice}</span></div>}
            {!importCapabilities.available && <div className="youtube-player-error"><AlertCircle size={15}/><span>{importCapabilities.reason || "Adapter impor otomatis tidak tersedia."} Gunakan Source Library atau upload MP4/MOV di bawah.</span></div>}
            <label className="field"><span>Judul klip</span><input maxLength={120} value={title} onChange={(event) => setTitle(event.target.value)} placeholder={`Quick Clip ${info.video_id}`}/></label>
            <label className="field"><span>Resolusi output</span><select value={resolution} onChange={(event) => setResolution(event.target.value as "720" | "1080")}><option value="720">720 × 1280 · Default</option><option value="1080">1080 × 1920</option></select></label>
            <label className="youtube-rights-confirm"><input type="checkbox" checked={rightsConfirmed} onChange={(event) => setRightsConfirmed(event.target.checked)}/><span>Saya memiliki hak/izin untuk mengambil, memotong, dan menggunakan konten ini serta telah memastikan metode ini diizinkan. Saya paham yt-dlp bukan metode resmi YouTube dan Klipnara tidak melewati pembatasan akses.</span></label>
            <div className="youtube-import-stages" aria-label="Progress impor YouTube">
              {["Preparing", "Importing", "Processing", "Ready"].map((label, index) => <div key={label} className={`youtube-import-stage ${index < importPhaseIndex ? "done" : index === importPhaseIndex ? "active" : ""} ${["failed", "cancelled"].includes(importJob?.status || job?.status || "") && index === importPhaseIndex ? "failed" : ""}`}><i>{index < importPhaseIndex ? "✓" : index + 1}</i><span>{label}</span></div>)}
            </div>
            {(importJob || job) && <div className={`job-progress ${(importJob?.status === "failed" || job?.status === "failed") ? "job-failed" : ""}`}><div className="job-progress-top"><span className="job-progress-icon">{importJob?.status === "failed" || job?.status === "failed" ? <AlertCircle size={17}/> : importRunning || running || importBusy || busy ? <LoaderCircle size={17} className="spin"/> : <CheckCircle2 size={17}/>}</span><div><strong>{job ? job.message : importJob?.message || "Menyiapkan impor"}</strong><span>{job ? `Quick Clip · ${job.phase}` : importJob?.phase || ""}</span></div>{importRunning && <button type="button" className="button button-quiet" onClick={() => void cancelAutomaticImport()}>Batalkan</button>}{running && <button type="button" className="button button-quiet" onClick={() => void cancelJob()}>Batalkan</button>}{job && ["failed", "cancelled"].includes(job.status) && <button type="button" className="button button-quiet" onClick={() => void retryJob()} disabled={busy}>Coba lagi</button>}</div>{importProgress !== null && <div className="progress-track"><span style={{ width: `${Math.round(importProgress * 100)}%` }}/></div>}</div>}
            {importError && <div className="notice notice-error"><AlertCircle size={16}/><span>{importError}</span></div>}
            <div className="youtube-step-actions"><button type="button" className="button button-outline" onClick={() => setStep(2)} disabled={importRunning || running}><ArrowLeft size={14}/> Kembali ke Timestamp</button><button type="button" className="button button-primary" onClick={() => void startAutomaticImport()} disabled={!importCapabilities.available || !rightsConfirmed || !youtubeRange.valid || importBusy || busy || importRunning || running || importJob?.status === "ready" || Boolean(job && ["failed", "cancelled", "completed"].includes(job.status))}>{importBusy || importRunning || busy ? <LoaderCircle size={15} className="spin"/> : <Download size={15}/>} Impor & Buat Klip <ArrowRight size={14}/></button></div>
            {importJob && ["failed", "cancelled"].includes(importJob.status) && <button type="button" className="button button-outline" onClick={() => void retryAutomaticImport()} disabled={importBusy || !rightsConfirmed || !importCapabilities.available}>Coba impor lagi</button>}
            {importJob?.status === "ready" && importJob.source && importError && !job && <button type="button" className="button button-outline" onClick={() => { importFinalizeStarted.current = ""; void createImportedQuickClip(importJob.id, importJob.source!); }} disabled={busy}>Buat Quick Clip dari Source yang sudah diimpor</button>}
          </section>

          <section className="youtube-local-fallback">
            <div className="youtube-fallback-heading"><strong>Alternatif: gunakan sumber lokal</strong><span>Jika adapter tidak tersedia, gagal, atau pengambilan tidak diizinkan, pilih video yang berhak kamu proses.</span></div>
            <div className="source-tabs youtube-source-tabs"><button type="button" className={sourceMode === "library" ? "selected" : ""} onClick={() => { setError(""); setSourceMode("library"); setSource(null); setAutoImportedSourceId(""); }} disabled={importRunning || running}><Video size={14}/> Source Library</button><button type="button" className={sourceMode === "upload" ? "selected" : ""} onClick={() => { setError(""); setSourceMode("upload"); setSource(null); setAutoImportedSourceId(""); }} disabled={importRunning || running}><Upload size={14}/> Upload MP4/MOV</button></div>
            {sourceMode === "library" ? <label className="field"><span>Video tersimpan</span><select value={source?.id || ""} onChange={(event) => selectSource(event.target.value)} disabled={sourcesLoading || importRunning || running}><option value="">{sourcesLoading ? "Memuat Source Library…" : "Pilih file yang boleh diproses…"}</option>{sources.map((item) => <option key={item.id} value={item.id}>{item.name} · {formatDuration(item.duration)}</option>)}</select><small>Source Library hanya alternatif; otomatisasi tidak menghapus atau mengubah sumber lama.</small></label> : <div className="youtube-upload-box"><FileVideo2 size={23}/><div><strong>Upload MP4/MOV milikmu atau yang boleh diproses</strong><small>Validasi ukuran, format, dan durasi memakai jalur ingest existing.</small></div><input ref={fileInput} type="file" accept="video/mp4,video/quicktime,.mp4,.mov" hidden onChange={(event) => void uploadSource(event)}/><button type="button" className="button button-outline" onClick={() => fileInput.current?.click()} disabled={uploadBusy || importRunning || running}>{uploadBusy ? <LoaderCircle size={14} className="spin"/> : <Upload size={14}/>} Pilih File</button></div>}
            {source && <div className="youtube-local-source"><video src={`${API}/api/sources/${source.id}/file`} controls playsInline preload="metadata"/><div><strong>{source.name}</strong><span>{formatDuration(source.duration)} · {source.width} × {source.height} · {formatBytes(source.size_bytes)}</span><small><CheckCircle2 size={13}/> File lokal valid · timestamp dicek terhadap durasi file</small></div></div>}
            {source && localRange && <div className={`timestamp-validation ${localRange.valid ? "valid" : ""}`}>{rangeMessage(localRange, source.duration, true)}</div>}
            <div className="youtube-boundary-note"><LockKeyhole size={14}/><span>File lokal tidak dicocokkan otomatis dengan preview. Periksa identitas file dan timestamp sendiri.</span></div>
            {!sourcesLoading && sourceMode === "library" && sources.length === 0 && <div className="youtube-metadata-note"><Video size={14}/><span>Source Library kosong. Upload atau impor file melalui workflow Buat Video existing.</span></div>}
            {error && <div className="notice notice-error"><AlertCircle size={16}/><span>{error}</span></div>}
            <div className="youtube-step-actions"><span>Alternatif manual</span><button type="button" className="button button-outline" disabled={!source || !localRange?.valid || uploadBusy || importRunning || running || autoImportedSourceId === source?.id} onClick={() => { setError(""); setStep(4); }}>Lanjut dengan File Lokal <ArrowRight size={14}/></button></div>
          </section>
        </section>}

        {step === 4 && info && source && localRange && <section className="panel form-panel youtube-clip-panel">
          <div className="step-heading"><span className="step-number">04</span><div><h2>Buat Quick Clip</h2><p>Parameter diteruskan ke endpoint Quick Clip existing dan antrean render lokal.</p></div><Scissors size={18} className="youtube-step-icon"/></div>
          <div className="youtube-confirm-card"><div><span>REFERENSI YOUTUBE</span><strong>{info.metadata?.title || info.video_id}</strong><small>{info.metadata?.channel || info.canonical_url}</small></div><div><span>RENTANG</span><strong>{startText} – {endText}</strong><small>{formatTimestamp(parsedEnd! - parsedStart!)} dipilih · durasi sumber {formatTimestamp(source.duration)}</small></div><div><span>FILE YANG DIRENDER</span><strong>{source.name}</strong><small>{formatBytes(source.size_bytes)} · {source.width} × {source.height} · bukan unduhan YouTube</small></div></div>
          <label className="field"><span>Judul klip</span><input maxLength={120} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Masukkan judul klip"/></label>
          <label className="field"><span>Resolusi output</span><select value={resolution} onChange={(event) => setResolution(event.target.value as "720" | "1080")}><option value="720">720 × 1280 · Default</option><option value="1080">1080 × 1920</option></select></label>
          {info.metadata_status === "route_not_found" ? <div className="youtube-player-error"><AlertCircle size={15}/><span>Mode fallback memakai Quick Clip lokal. Referensi YouTube sengaja tidak dikirim agar endpoint lama tetap kompatibel; provenance dan re-probe durasi V2.5 tidak tersedia. Periksa durasi serta identitas file sendiri. Metadata dan availability video belum diverifikasi.</span></div> : <div className="youtube-boundary-note"><LockKeyhole size={14}/><span>FFmpeg membaca file lokal terpilih. YouTube reference disimpan terpisah dan dapat dihapus dari Clip Editor. Identitas video lokal tidak diverifikasi terhadap preview.</span></div>}
          {error && <div className="notice notice-error"><AlertCircle size={16}/><span>{error}</span></div>}
          <div className="youtube-step-actions"><button type="button" className="button button-outline" onClick={() => setStep(3)} disabled={busy}><ArrowLeft size={14}/> Ubah File Sumber</button><button type="button" className="button button-primary" onClick={() => void createQuickClip()} disabled={busy || running || !title.trim() || !localRange.valid}>{busy ? <LoaderCircle size={15} className="spin"/> : <Scissors size={15}/>} Buat Quick Clip <ArrowRight size={14}/></button></div>
        </section>}

        {step === 4 && job && <section className={`job-progress ${job.status === "failed" ? "job-failed" : ""}`}><div className="job-progress-top"><span className="job-progress-icon">{job.status === "failed" ? <AlertCircle size={17}/> : running ? <LoaderCircle size={17} className="spin"/> : <CheckCircle2 size={17}/>}</span><div><strong>{job.status === "queued" ? "Menunggu render lokal" : job.status === "rendering" ? "Quick Clip sedang dirender" : job.status}</strong><span>{job.message}</span></div>{running && <button type="button" className="button button-quiet" onClick={() => void cancelJob()}>Batalkan</button>}{["failed", "cancelled"].includes(job.status) && <button type="button" className="button button-quiet" onClick={() => void retryJob()} disabled={busy}>Coba lagi</button>}</div>{job.progress !== null && running && <div className="progress-track"><span style={{ width: `${Math.round(job.progress * 100)}%` }}/></div>}</section>}
      </div>

      <aside className="youtube-clip-aside">
        <section className="panel notes-card"><div className="notes-title"><span><LockKeyhole size={15}/></span><div><strong>Batas pemrosesan</strong><small>Preview ≠ file sumber</small></div></div><ul className="notes-list"><li><i className="note-dot green"/><span>YouTube IFrame API preview; impor yt-dlp opsional dan harus diaktifkan admin.</span></li><li><i className="note-dot blue"/><span>Tidak ada cookies/session, DRM bypass, atau workaround proteksi akses.</span></li><li><i className="note-dot blue"/><span>Metadata Data API opsional dan tidak disimpan.</span></li><li><i className="note-dot amber"/><span>Quick Clip, FFmpeg, editor, review, dan publishing memakai pipeline existing.</span></li></ul></section>
        {info && <section className="panel notes-card youtube-reference-card"><div className="eyebrow">REFERENSI SEMENTARA</div><strong>{info.metadata?.title || info.video_id}</strong><small>{info.metadata?.channel || "Metadata tidak tersedia"}</small><a href={info.canonical_url} target="_blank" rel="noreferrer">Canonical URL <ExternalLink size={12}/></a></section>}
      </aside>
    </div>
  </>;
}

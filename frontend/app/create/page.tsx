"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertCircle, ArrowLeft, ArrowRight, Check, CheckCircle2, ChevronDown, Clock3, Cloud, Cpu, Heart, Info, LoaderCircle, LockKeyhole, MonitorPlay, Music2, Scissors, Sparkles, Upload, Video, X, Youtube } from "lucide-react";
import { ChangeEvent, DragEvent, useEffect, useRef, useState } from "react";
import { API, formatBytes, formatDuration, request } from "@/lib/api";

type Source = { id: string; name: string; duration: number; width: number; height: number; size_bytes: number; video_codec: string; audio_codec: string | null };
type SavedSource = Source & { clip_count?: number; latest_status?: string | null };
type Job = { id: string; status: string; phase: string; progress: number | null; message: string };
type Settings = { capabilities: { ffmpeg_available: boolean; ffprobe_available: boolean; ollama_connected: boolean; whisper_cpp_available: boolean; whisper_model_configured: boolean; cpu: string; ram_bytes: number | null; gpus: string[] }; providers: { openai: { key_configured: boolean }; gemini: { model: string; key_configured: boolean } } };

const defaults = { count: 5, duration: "30-60", style: "Clean", subtitle_enabled: true, resolution: "720", focus: "center", provider: "local", language: "auto", consent: false };
const phases: Record<string, string> = { queued: "Menunggu giliran", preparing: "Menyiapkan audio", transcribing: "Transkripsi lokal", analyzing: "Analisis highlight", ready_for_review: "Kandidat siap ditinjau", rendering: "Merender MP4", completed: "Selesai", failed: "Gagal", cancelled: "Dibatalkan" };

function parseTimestamp(value: string): number | null {
  const parts = value.trim().split(":");
  if (parts.length < 2 || parts.length > 3 || parts.some((part) => !/^\d+$/.test(part))) return null;
  const numbers = parts.map(Number);
  const seconds = numbers[numbers.length - 1];
  if (seconds >= 60) return null;
  if (numbers.length === 2) return numbers[0] * 60 + seconds;
  if (numbers[1] >= 60) return null;
  return numbers[0] * 3600 + numbers[1] * 60 + seconds;
}

function formatTimestamp(value: number): string {
  const total = Math.max(0, Math.floor(value));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}` : `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export default function CreatePage() {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const previewVideo = useRef<HTMLVideoElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [workflow, setWorkflow] = useState<"quick" | "ai">("quick");
  const [entrySelected, setEntrySelected] = useState(false);
  const [sourceMode, setSourceMode] = useState<"upload" | "url" | "library">("upload");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [source, setSource] = useState<Source | null>(null);
  const [savedSources, setSavedSources] = useState<SavedSource[]>([]);
  const [options, setOptions] = useState(defaults);
  const [quickTitle, setQuickTitle] = useState("");
  const [quickResolution, setQuickResolution] = useState<"720" | "1080">("720");
  const [startTimestamp, setStartTimestamp] = useState("00:00");
  const [endTimestamp, setEndTimestamp] = useState("01:00");
  const [playhead, setPlayhead] = useState(0);
  const [quickClipId, setQuickClipId] = useState("");
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [settings, setSettings] = useState<Settings | null>(null);

  useEffect(() => { request<SavedSource[]>("/sources").then(setSavedSources).catch((reason) => setError(reason.message)); }, []);
  useEffect(() => {
    if (workflow === "ai") request<Settings>("/settings").then(setSettings).catch((reason) => setError(reason.message));
  }, [workflow]);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const id = new URLSearchParams(window.location.search).get("source");
    const mode = params.get("mode");
    if (mode === "quick" || mode === "ai") { setWorkflow(mode); setEntrySelected(true); }
    else if (id) setEntrySelected(true);
    if (id) request<{ source: Source }>(`/sources/${id}`).then((data) => setSource(data.source)).catch((reason) => setError(reason.message));
  }, []);
  useEffect(() => {
    if (!job || !["queued", "preparing", "transcribing", "analyzing", "rendering"].includes(job.status)) return;
    let alive = true;
    const poll = async () => {
      try {
        const next = await request<Job>(`/jobs/${job.id}`);
        if (!alive) return;
        setJob(next);
        if (next.status === "ready_for_review" && source) { router.push(`/sources/${source.id}`); return; }
        if (next.status === "completed" && quickClipId) { router.push(`/clips/${quickClipId}`); return; }
        if (["failed", "cancelled", "completed"].includes(next.status)) return;
        timer.current = setTimeout(poll, 1000);
      } catch (reason) { if (alive) setError((reason as Error).message); }
    };
    timer.current = setTimeout(poll, 650);
    return () => { alive = false; if (timer.current) clearTimeout(timer.current); };
  }, [job?.id, job?.status, source, quickClipId, router]);

  useEffect(() => {
    if (!source) return;
    setQuickTitle(source.name.replace(/\.[^.]+$/, ""));
    setStartTimestamp("00:00");
    setEndTimestamp(formatTimestamp(Math.min(60, Math.floor(source.duration))));
    setPlayhead(0);
  }, [source?.id]);

  const set = <K extends keyof typeof defaults>(key: K, value: (typeof defaults)[K]) => setOptions((current) => ({ ...current, [key]: value }));
  const chooseSavedSource = (sourceId: string) => {
    setSource(savedSources.find((item) => item.id === sourceId) || null);
    setFile(null);
    setQuickClipId("");
    setError("");
  };
  const importFile = async (selected: File) => {
    if (!/\.(mp4|mov)$/i.test(selected.name)) { setError("Pilih video MP4 atau MOV."); return; }
    setError(""); setBusy(true); setFile(selected);
    try {
      const data = new FormData(); data.append("file", selected);
      const created = await request<Source>("/sources/upload", { method: "POST", body: data });
      setSource(created);
      setQuickClipId("");
      setSavedSources((items) => [created, ...items]);
    } catch (reason) { setError((reason as Error).message); setFile(null); }
    finally { setBusy(false); }
  };
  const importUrl = async () => {
    setError(""); setBusy(true);
    try {
      const created = await request<Source>("/sources/url", { method: "POST", body: JSON.stringify({ url }) });
      setSource(created); setQuickClipId(""); setSavedSources((items) => [created, ...items]);
    }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };
  const onFile = (event: ChangeEvent<HTMLInputElement>) => { const selected = event.target.files?.[0]; if (selected) void importFile(selected); };
  const dropFile = (event: DragEvent<HTMLDivElement>) => { event.preventDefault(); const selected = event.dataTransfer.files[0]; if (selected) void importFile(selected); };
  const generate = async () => {
    if (!source) return;
    setError(""); setBusy(true); setQuickClipId("");
    try {
      const data = await request<{ id: string; status: string }>(`/sources/${source.id}/generate`, { method: "POST", body: JSON.stringify(options) });
      setJob({ id: data.id, status: data.status, phase: data.status, progress: null, message: "Job masuk antrean lokal" });
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };
  const createQuickClip = async () => {
    if (!source) return;
    const start = parseTimestamp(startTimestamp), end = parseTimestamp(endTimestamp);
    if (!quickTitle.trim()) { setError("Judul klip wajib diisi."); return; }
    if (start === null || end === null) { setError("Gunakan format MM:SS atau HH:MM:SS."); return; }
    if (end <= start) { setError("End Time harus lebih besar dari Start Time."); return; }
    if (end > source.duration) { setError("End Time tidak boleh melebihi durasi sumber."); return; }
    setError(""); setBusy(true); setQuickClipId("");
    try {
      const result = await request<{ id: string; clip_id: string; status: string }>(`/sources/${source.id}/quick-clips`, {
        method: "POST", body: JSON.stringify({ title: quickTitle.trim(), start, end, resolution: quickResolution }),
      });
      setQuickClipId(result.clip_id);
      setJob({ id: result.id, status: result.status, phase: result.status, progress: null, message: "Quick Clip masuk antrean render" });
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };
  const retryJob = async () => {
    if (!job) return;
    if (!quickClipId) { await generate(); return; }
    setError(""); setBusy(true);
    try {
      const retried = await request<{ id: string; status: string }>(`/jobs/${job.id}/retry`, { method: "POST", body: "{}" });
      setJob({ id: retried.id, status: retried.status, phase: retried.status, progress: null, message: "Quick Clip masuk antrean retry" });
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };
  const cancel = async () => { if (!job) return; try { await request(`/jobs/${job.id}/cancel`, { method: "POST" }); setJob({ ...job, status: "cancelled", phase: "cancelled", message: "Dibatalkan pengguna" }); } catch (reason) { setError((reason as Error).message); } };

  const loadScore = (Number(options.count === 10) * 2) + (Number(options.resolution === "1080") * 2) + Number(options.duration === "60-90") + Number(options.style === "Highlight");
  const load = loadScore >= 4 ? "Berat" : loadScore >= 2 ? "Sedang" : "Relatif ringan";
  const running = Boolean(job && ["queued", "preparing", "transcribing", "analyzing", "rendering"].includes(job.status));
  const parsedStart = parseTimestamp(startTimestamp), parsedEnd = parseTimestamp(endTimestamp);
  const openClipMode = (mode: "quick" | "ai") => {
    setWorkflow(mode);
    setEntrySelected(true);
    router.replace(`/create?mode=${mode}`, { scroll: false });
  };

  if (!entrySelected) return <>
    <div className="page-intro"><div className="eyebrow">KLIPNARA STUDIO 2.1</div><h1>Buat Video</h1><p>Pilih alur video yang ingin kamu buat. File tetap diproses secara lokal.</p></div>
    <section className="mode-card-grid" aria-label="Pilih mode pembuatan video">
      <button type="button" className="mode-card" onClick={() => openClipMode("quick")}><span className="mode-card-icon"><Scissors size={20}/></span><span className="mode-card-copy"><strong>Quick Clip</strong><small>Potong video sendiri dengan timestamp. Tanpa AI.</small><em>Siap digunakan</em></span><ArrowRight size={17}/></button>
      <button type="button" className="mode-card" onClick={() => openClipMode("ai")}><span className="mode-card-icon"><Sparkles size={20}/></span><span className="mode-card-copy"><strong>AI Smart Clip</strong><small>Temukan highlight dari video dengan transkripsi dan AI.</small><em>Perlu runtime AI atau provider cloud</em></span><ArrowRight size={17}/></button>
      <Link href="/mood" className="mode-card mode-card-featured"><span className="mode-card-icon"><Heart size={20}/></span><span className="mode-card-copy"><strong>AI Mood Quotes</strong><small>Buat quote dan video aesthetic dengan background, musik, dan tipografi.</small><em>Workspace kreator</em></span><ArrowRight size={17}/></Link>
      <article className="mode-card mode-card-disabled" aria-disabled="true"><span className="mode-card-icon"><Youtube size={20}/></span><span className="mode-card-copy"><strong>YouTube Clip</strong><small>Impor berdasarkan URL YouTube belum tersedia.</small><em>Segera Hadir</em></span></article>
    </section>
  </>;

  return <>
    <div className="page-intro"><button type="button" className="back-link mode-back" onClick={() => { setEntrySelected(false); router.replace("/create", { scroll: false }); }}><ArrowLeft size={14}/> Semua mode</button><div className="eyebrow">VIDEO CLIPPER</div><h1>{workflow === "quick" ? "Quick Clip" : "AI Smart Clip"}</h1><p>{workflow === "quick" ? "Masukkan timestamp untuk memotong video langsung tanpa Whisper, Ollama, atau Cloud AI." : "Generate kandidat highlight dengan transkripsi dan AI; mode ini tetap opsional."}</p></div>
    <div className="workflow-tabs" role="tablist" aria-label="Mode pembuatan klip">
      <button role="tab" aria-selected={workflow === "quick"} className={workflow === "quick" ? "selected" : ""} disabled={busy || running} onClick={() => { setWorkflow("quick"); setError(""); }}><Scissors size={15}/> Quick Clip <span>DEFAULT</span></button>
      <button role="tab" aria-selected={workflow === "ai"} className={workflow === "ai" ? "selected" : ""} disabled={busy || running} onClick={() => { setWorkflow("ai"); setQuickClipId(""); setError(""); }}><Sparkles size={15}/> AI Smart Clip <small>Optional</small></button>
    </div>
    <div className="create-layout">
      <div className="create-main">
        <section className="panel form-panel source-panel"><div className="step-heading"><span className="step-number">01</span><div><h2>Sumber video</h2><p>Gunakan video yang kamu miliki atau berhak proses.</p></div><span className="required-label">WAJIB</span></div>
          <div className="source-tabs"><button type="button" onClick={() => { setSourceMode("upload"); setSource(null); setFile(null); setQuickClipId(""); setError(""); }} className={sourceMode === "upload" ? "selected" : ""}><Upload size={15}/> Upload file</button><button type="button" onClick={() => { setSourceMode("url"); setSource(null); setFile(null); setQuickClipId(""); setError(""); }} className={sourceMode === "url" ? "selected" : ""}><MonitorPlay size={15}/> URL video</button><button type="button" onClick={() => { setSourceMode("library"); setSource(null); setFile(null); setQuickClipId(""); setError(""); }} className={sourceMode === "library" ? "selected" : ""}><Video size={15}/> Library</button></div>
          {sourceMode === "upload" ? <div className={`dropzone ${file ? "has-file" : ""}`} onDragOver={(event) => event.preventDefault()} onDrop={dropFile} onClick={() => !busy && !source && input.current?.click()} role="button" tabIndex={0} onKeyDown={(event) => event.key === "Enter" && input.current?.click()}>
            <input ref={input} type="file" accept="video/mp4,video/quicktime,.mp4,.mov" onChange={onFile} hidden/>
            {busy && !source ? <span className="drop-icon spinning"><LoaderCircle size={21}/></span> : <span className="drop-icon"><Upload size={21}/></span>}
            {source ? <><strong>{source.name}</strong><span>{formatBytes(source.size_bytes)} · {formatDuration(source.duration)} · {source.width} × {source.height}</span><span className="source-valid"><CheckCircle2 size={14}/> Validasi ffprobe berhasil</span></> : <><strong>{file?.name || "Tarik video ke sini"}</strong><span>{file ? `${formatBytes(file.size)} · Mengunggah dan memvalidasi…` : "atau klik untuk memilih file dari perangkat"}</span><small>MP4 atau MOV · Maks. 2 GB · Durasi maks. 4 jam</small></>}
            {source && <button type="button" className="source-remove" title="Hapus pilihan" onClick={(event) => { event.stopPropagation(); setSource(null); setFile(null); }}><X size={15}/></button>}
          </div> : sourceMode === "url" ? <div className="url-entry"><label htmlFor="video-url">URL langsung file video</label><div className="url-input-row"><input id="video-url" type="url" placeholder="https://contoh.com/video.mp4" value={url} onChange={(event) => setUrl(event.target.value)} disabled={busy || Boolean(source)}/><button className="button button-dark" onClick={importUrl} disabled={busy || !url || Boolean(source)}>{busy ? <LoaderCircle className="spin" size={15}/> : <Upload size={15}/>} Impor</button></div><div className="url-help"><LockKeyhole size={13}/> HTTPS langsung ke file media. Akses lokal/private, redirect berbahaya, dan URL halaman YouTube ditolak.</div>{source && <div className="url-success"><CheckCircle2 size={15}/><span><strong>{source.name}</strong> · {formatDuration(source.duration)} · {formatBytes(source.size_bytes)}</span><button className="icon-button" onClick={() => setSource(null)}><X size={15}/></button></div>}</div> : <div className="library-source-select"><label className="field"><span>Pilih video tersimpan</span><select value={source?.id || ""} onChange={(event) => chooseSavedSource(event.target.value)}><option value="">Pilih dari Source Library…</option>{savedSources.map((item) => <option key={item.id} value={item.id}>{item.name} · {formatDuration(item.duration)}</option>)}</select></label>{source && <div className="url-success"><CheckCircle2 size={15}/><span><strong>{source.name}</strong> · {formatDuration(source.duration)} · {source.width} × {source.height} · {formatBytes(source.size_bytes)}</span></div>}</div>}
          <div className="source-security"><LockKeyhole size={14}/><span>File asli disimpan lokal. Cloud AI hanya menerima transkrip jika kamu memilihnya.</span></div>
        </section>

        {workflow === "quick" ? <section className="panel form-panel quick-clip-panel"><div className="step-heading"><span className="step-number">02</span><div><h2>Quick Clip</h2><p>Tentukan rentang waktu; hanya potongan terpilih yang dirender.</p></div><span className="required-label">TANPA AI</span></div>
          {source && <div className="quick-preview"><video ref={previewVideo} src={`${API}/api/sources/${source.id}/file`} controls playsInline preload="metadata" onTimeUpdate={(event) => setPlayhead(event.currentTarget.currentTime)}/><div><Video size={13}/> Preview sumber · posisi {formatTimestamp(playhead)}</div></div>}
          <label className="field quick-title-field"><span>Judul klip</span><input maxLength={120} value={quickTitle} onChange={(event) => setQuickTitle(event.target.value)} placeholder="Judul klip"/></label>
          <div className="timestamp-grid">
            <label className="field"><span>Start Time</span><input type="text" inputMode="numeric" aria-label="Start Time" aria-invalid={parsedStart === null} value={startTimestamp} onChange={(event) => setStartTimestamp(event.target.value)} placeholder="MM:SS atau HH:MM:SS"/><small>Contoh: 14:00</small></label>
            <button type="button" className="button button-outline playhead-button" disabled={!source} onClick={() => setStartTimestamp(formatTimestamp(playhead))}>Ambil playhead → Start</button>
            <label className="field"><span>End Time</span><input type="text" inputMode="numeric" aria-label="End Time" aria-invalid={parsedEnd === null} value={endTimestamp} onChange={(event) => setEndTimestamp(event.target.value)} placeholder="MM:SS atau HH:MM:SS"/><small>{parsedStart !== null && parsedEnd !== null && parsedEnd > parsedStart ? `Durasi klip: ${formatTimestamp(parsedEnd - parsedStart)}` : "End harus setelah Start"}</small></label>
            <button type="button" className="button button-outline playhead-button" disabled={!source} onClick={() => setEndTimestamp(formatTimestamp(playhead))}>Ambil playhead → End</button>
          </div>
          {source && <div className={`timestamp-validation ${parsedStart !== null && parsedEnd !== null && parsedEnd > parsedStart && parsedEnd <= source.duration ? "valid" : "invalid"}`}>
            {parsedStart === null || parsedEnd === null ? "Gunakan format MM:SS atau HH:MM:SS." : parsedEnd <= parsedStart ? "End Time harus lebih besar dari Start Time." : parsedEnd > source.duration ? `End Time melebihi durasi ${formatTimestamp(source.duration)}.` : `Rentang valid · ${formatTimestamp(parsedEnd - parsedStart)} klip · sumber ${formatTimestamp(source.duration)}`}
          </div>}
          <div className="quick-output-grid"><label className="field"><span>Resolusi</span><select value={quickResolution} onChange={(event) => setQuickResolution(event.target.value as "720" | "1080")}><option value="720">720 × 1280 · Default</option><option value="1080">1080 × 1920</option></select></label><div className="field"><span>Rasio output</span><strong className="quick-ratio">9:16 · portrait</strong></div></div>
          <div className="quick-no-ai-note"><LockKeyhole size={14}/> Subtitle OFF. Quick Clip tidak menjalankan Whisper, Ollama, OpenAI, atau Gemini.</div>
        </section> : <>
        <section className="panel form-panel options-panel"><div className="step-heading"><span className="step-number">02</span><div><h2>Pengaturan klip</h2><p>Ubah opsi; catatan performa diperbarui langsung.</p></div></div>
          <div className="form-grid">
            <label className="field"><span>Jumlah kandidat</span><select value={options.count} onChange={(event) => set("count", Number(event.target.value) as 3 | 5 | 10)}><option value={3}>3 kandidat</option><option value={5}>5 kandidat · Disarankan</option><option value={10}>10 kandidat</option></select><small>Jumlah aktual bergantung materi.</small></label>
            <label className="field"><span>Durasi target</span><select value={options.duration} onChange={(event) => set("duration", event.target.value as typeof options.duration)}><option value="15-30">15–30 detik</option><option value="30-60">30–60 detik · Default</option><option value="60-90">60–90 detik</option></select></label>
            <label className="field"><span>Gaya subtitle</span><select value={options.style} onChange={(event) => set("style", event.target.value as typeof options.style)}><option>Clean</option><option>Bold</option><option>Highlight</option></select><small>{options.style === "Highlight" ? "Timestamp kata belum tersedia; gunakan highlight per frasa." : "Gaya dapat diubah di editor."}</small></label>
            <label className="field"><span>Resolusi ekspor</span><select value={options.resolution} onChange={(event) => set("resolution", event.target.value as "720" | "1080")}><option value="720">720 × 1280 · Default</option><option value="1080">1080 × 1920</option></select></label>
            <label className="field"><span>Fokus video</span><select value={options.focus} onChange={(event) => set("focus", event.target.value as "center" | "manual")}><option value="center">Center crop · Default</option><option value="manual">Atur posisi manual</option></select></label>
            <label className="field"><span>Bahasa transkripsi</span><select value={options.language} onChange={(event) => set("language", event.target.value as typeof options.language)}><option value="auto">Otomatis</option><option value="indonesia">Indonesia</option><option value="english">Inggris</option></select></label>
          </div>
          <label className="toggle-row"><span className="toggle-copy"><strong>Tambahkan subtitle</strong><small>Subtitle dibakar ke video saat render. Teks tetap bisa dikoreksi.</small></span><input type="checkbox" className="toggle-input" checked={options.subtitle_enabled} onChange={(event) => set("subtitle_enabled", event.target.checked)}/><span className="toggle-switch"/></label>
        </section>

        <section className="panel form-panel engine-panel"><div className="step-heading"><span className="step-number">03</span><div><h2>Mesin AI highlight</h2><p>Pilih lokal atau cloud. Cloud tidak pernah menerima file video.</p></div></div>
          <div className="engine-options">
            <button type="button" onClick={() => { set("provider", "local"); set("consent", false); }} className={`engine-card ${options.provider === "local" ? "active" : ""}`}><span className="engine-icon local"><Cpu size={19}/></span><span className="engine-copy"><strong>Local AI <i className="default-chip">DEFAULT</i></strong><small>Ollama di perangkat ini · Tanpa biaya token</small><span className={`connection-state ${settings?.capabilities.ollama_connected ? "connected" : "disconnected"}`}><i/> {settings ? settings.capabilities.ollama_connected ? "Ollama terhubung" : "Ollama belum terdeteksi" : "Memeriksa Ollama…"}</span></span><span className={`radio-mark ${options.provider === "local" ? "checked" : ""}`}/></button>
            <button type="button" onClick={() => set("provider", "openai")} className={`engine-card ${options.provider === "openai" ? "active" : ""}`}><span className="engine-icon openai"><Sparkles size={18}/></span><span className="engine-copy"><strong>OpenAI Cloud</strong><small>Transkrip dikirim ke provider · Biaya mungkin berlaku</small><span className="connection-state">{settings?.providers?.openai?.key_configured ? "API key tersedia" : "Butuh OPENAI_API_KEY di backend"}</span></span><span className={`radio-mark ${options.provider === "openai" ? "checked" : ""}`}/></button>
            <button type="button" onClick={() => set("provider", "gemini")} className={`engine-card ${options.provider === "gemini" ? "active" : ""}`}><span className="engine-icon gemini"><Sparkles size={18}/></span><span className="engine-copy"><strong>Gemini Free Tier</strong><small>{settings?.providers?.gemini?.model || "gemini-3.5-flash-lite"} · Kuota gratis; transkrip saja</small><span className="connection-state">{settings?.providers?.gemini?.key_configured ? "API key tersedia" : "Butuh GEMINI_API_KEY di backend"}</span></span><span className={`radio-mark ${options.provider === "gemini" ? "checked" : ""}`}/></button>
          </div>
          {options.provider !== "local" && <div className="consent-box"><div className="consent-icon"><Cloud size={17}/></div><div><strong>Persetujuan cloud per job</strong><p>Hanya transkrip bertimestamp, bahasa, durasi, dan instruksi analisis yang dikirim. Video dan audio mentah tetap lokal. {options.provider === "gemini" ? "Gunakan project Gemini Free Tier; quota 429 menghentikan job, tanpa fallback berbayar." : "Biaya mengikuti akun provider; tidak ada estimasi harga."}</p><label className="consent-check"><input type="checkbox" checked={options.consent} onChange={(event) => set("consent", event.target.checked)}/><span>Saya setuju mengirim transkrip ke {options.provider === "openai" ? "OpenAI" : "Gemini"} untuk job ini.</span></label></div></div>}
        </section>
        </>}
        {error && <div className="notice notice-error"><AlertCircle size={17}/><span>{error}</span><button className="icon-button" onClick={() => setError("")}><X size={15}/></button></div>}
        {job && <section className={`job-progress ${job.status === "failed" ? "job-failed" : ""}`}><div className="job-progress-top"><span className="job-progress-icon">{job.status === "failed" ? <AlertCircle size={17}/> : running ? <LoaderCircle className="spin" size={17}/> : <CheckCircle2 size={17}/>}</span><div><strong>{quickClipId && job.status === "preparing" ? "Menyiapkan Quick Clip" : phases[job.status] || job.status}</strong><span>{job.message}</span></div>{running && <button className="button button-quiet" onClick={cancel}>Batalkan</button>}{["failed", "cancelled"].includes(job.status) && <button className="button button-quiet" onClick={() => void retryJob()}>Coba lagi</button>}</div>{job.progress !== null && running ? <div className="progress-track"><span style={{ width: `${Math.round(job.progress * 100)}%` }}/></div> : running ? <div className="progress-indeterminate"><i/></div> : null}</section>}
        <div className="form-actions"><span><LockKeyhole size={13}/>{workflow === "quick" ? "Quick Clip · timestamp ke FFmpeg · tanpa AI" : "AI Smart Clip · pemrosesan serial"}</span><button className="button button-primary button-generate" disabled={!source || busy || running || (workflow === "ai" && options.provider !== "local" && !options.consent)} onClick={() => void (workflow === "quick" ? createQuickClip() : generate())}>{busy ? <LoaderCircle size={16} className="spin"/> : workflow === "quick" ? <Scissors size={16}/> : <Sparkles size={16}/>} {workflow === "quick" ? "Buat Quick Clip" : "Generate kandidat"} <ArrowRight size={16}/></button></div>
      </div>
      <aside className="create-aside">
        {workflow === "quick" ? <section className="panel notes-card quick-mode-aside"><div className="notes-title"><span><Scissors size={16}/></span><div><strong>Quick Clip · ringan</strong><small>Workflow default</small></div></div><ul className="notes-list"><li><i className="note-dot green"/><span>FFmpeg merender hanya rentang timestamp pilihan.</span></li><li><i className="note-dot green"/><span>Tidak menjalankan Whisper, Ollama, atau Cloud AI.</span></li><li><i className="note-dot blue"/><span>Output portrait 9:16, 720p default, subtitle OFF.</span></li><li><i className="note-dot blue"/><span>Video tanpa audio didukung; renderer menambahkan audio AAC senyap untuk kontrak review/publishing.</span></li></ul><div className="no-estimate"><Clock3 size={13}/> 1 job render pada satu waktu</div></section> : <>
        <section className="panel notes-card"><div className="notes-title"><span><Info size={16}/></span><div><strong>Catatan performa</strong><small>Berubah sesuai pengaturanmu</small></div></div><div className="load-meter"><span>Beban relatif</span><strong className={`load-${load.toLowerCase().replace(" ", "-")}`}>{load}</strong></div><ul className="notes-list">
          {options.resolution === "1080" && <li><i className="note-dot amber"/><span>1080p butuh render dan storage lebih besar dari 720p.</span></li>}
          {options.count === 10 && <li><i className="note-dot amber"/><span>10 kandidat berarti lebih banyak output untuk ditinjau dan dirender.</span></li>}
          {options.duration === "60-90" && <li><i className="note-dot amber"/><span>Klip 60–90 detik cenderung menghasilkan file lebih besar.</span></li>}
          {options.style === "Highlight" && <li><i className="note-dot blue"/><span>Word-level timestamp tidak aktif; highlight aman per frasa transkrip.</span></li>}
          {options.focus === "manual" && <li><i className="note-dot blue"/><span>Posisi crop manual dapat diatur setelah kandidat siap.</span></li>}
          {options.provider === "local" ? <li><i className="note-dot green"/><span>Local AI tidak memakai token API; resource CPU/RAM bergantung model.</span></li> : options.provider === "gemini" ? <li><i className="note-dot amber"/><span>Gemini memakai model Free Tier `{settings?.providers?.gemini?.model || "gemini-3.5-flash-lite"}`; transkrip saja dikirim. Quota 429 menghentikan job.</span></li> : <li><i className="note-dot amber"/><span>Cloud mengirim transkrip, bukan video. Biaya mengikuti akun provider.</span></li>}
          {!settings?.capabilities?.ffmpeg_available && <li><i className="note-dot red"/><span>FFmpeg belum terdeteksi; pasang sebelum ingest/render.</span></li>}
          {settings?.capabilities?.ffmpeg_available && !settings.capabilities.ollama_connected && options.provider === "local" && <li><i className="note-dot red"/><span>Ollama tidak terjangkau. Local job akan gagal hingga Ollama dan model siap.</span></li>}
        </ul><div className="no-estimate"><Clock3 size={13}/> Tidak ada estimasi waktu palsu</div></section>
        <section className="panel machine-card"><div className="machine-head"><span className="machine-icon"><Cpu size={17}/></span><div><strong>Perangkat terdeteksi</strong><small>Data dari backend lokal</small></div></div>{settings ? <div className="machine-specs"><div><span>CPU</span><strong>{settings.capabilities.cpu}</strong></div><div><span>RAM</span><strong>{settings.capabilities.ram_bytes ? `${(settings.capabilities.ram_bytes / 1024 ** 3).toFixed(1)} GB` : "Tidak diketahui"}</strong></div><div><span>GPU</span><strong>{settings.capabilities.gpus.join(", ")}</strong></div><div><span>Whisper.cpp</span><strong className={settings.capabilities.whisper_cpp_available && settings.capabilities.whisper_model_configured ? "spec-ok" : "spec-missing"}>{settings.capabilities.whisper_cpp_available && settings.capabilities.whisper_model_configured ? "Siap" : "Belum disiapkan"}</strong></div></div> : <div className="machine-loading"><LoaderCircle size={15} className="spin"/> Memuat profil perangkat…</div>}<Link href="/settings" className="machine-link">Lihat diagnostik lengkap <ArrowRight size={13}/></Link></section>
        <div className="aside-tip"><Music2 size={15}/><span>Hasil transkripsi disimpan. Edit subtitle atau crop tidak mengulang analisis AI.</span></div>
        </>}
      </aside>
    </div>
  </>;
}

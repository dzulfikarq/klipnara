"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertCircle, ArrowLeft, ArrowRight, Check, CheckCircle2, ChevronDown, Clock3, Cloud, Cpu, Info, LoaderCircle, LockKeyhole, MonitorPlay, Music2, Scissors, Sparkles, Upload, X } from "lucide-react";
import { ChangeEvent, DragEvent, useEffect, useRef, useState } from "react";
import { API, formatBytes, formatDuration, request } from "@/lib/api";

type Source = { id: string; name: string; duration: number; width: number; height: number; size_bytes: number; video_codec: string; audio_codec: string | null };
type Job = { id: string; status: string; phase: string; progress: number | null; message: string };
type Settings = { capabilities: { ffmpeg_available: boolean; ffprobe_available: boolean; ollama_connected: boolean; whisper_cpp_available: boolean; whisper_model_configured: boolean; cpu: string; ram_bytes: number | null; gpus: string[] }; providers: { openai: { key_configured: boolean }; gemini: { key_configured: boolean } } };

const defaults = { count: 5, duration: "30-60", style: "Clean", subtitle_enabled: true, resolution: "720", focus: "center", provider: "local", language: "auto", consent: false };
const phases: Record<string, string> = { queued: "Menunggu giliran", preparing: "Menyiapkan audio", transcribing: "Transkripsi lokal", analyzing: "Analisis highlight", ready_for_review: "Kandidat siap ditinjau", rendering: "Merender MP4", completed: "Selesai", failed: "Gagal", cancelled: "Dibatalkan" };

export default function CreatePage() {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [mode, setMode] = useState<"upload" | "url">("upload");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [source, setSource] = useState<Source | null>(null);
  const [options, setOptions] = useState(defaults);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [settings, setSettings] = useState<Settings | null>(null);

  useEffect(() => { request<Settings>("/settings").then(setSettings).catch((reason) => setError(reason.message)); }, []);
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("source");
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
        if (["failed", "cancelled", "completed"].includes(next.status)) return;
        timer.current = setTimeout(poll, 1000);
      } catch (reason) { if (alive) setError((reason as Error).message); }
    };
    timer.current = setTimeout(poll, 650);
    return () => { alive = false; if (timer.current) clearTimeout(timer.current); };
  }, [job?.id, job?.status, source, router]);

  const set = <K extends keyof typeof defaults>(key: K, value: (typeof defaults)[K]) => setOptions((current) => ({ ...current, [key]: value }));
  const importFile = async (selected: File) => {
    if (!/\.(mp4|mov)$/i.test(selected.name)) { setError("Pilih video MP4 atau MOV."); return; }
    setError(""); setBusy(true); setFile(selected);
    try {
      const data = new FormData(); data.append("file", selected);
      const created = await request<Source>("/sources/upload", { method: "POST", body: data });
      setSource(created);
    } catch (reason) { setError((reason as Error).message); setFile(null); }
    finally { setBusy(false); }
  };
  const importUrl = async () => {
    setError(""); setBusy(true);
    try { setSource(await request<Source>("/sources/url", { method: "POST", body: JSON.stringify({ url }) })); }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };
  const onFile = (event: ChangeEvent<HTMLInputElement>) => { const selected = event.target.files?.[0]; if (selected) void importFile(selected); };
  const dropFile = (event: DragEvent<HTMLDivElement>) => { event.preventDefault(); const selected = event.dataTransfer.files[0]; if (selected) void importFile(selected); };
  const generate = async () => {
    if (!source) return;
    setError(""); setBusy(true);
    try {
      const data = await request<{ id: string; status: string }>(`/sources/${source.id}/generate`, { method: "POST", body: JSON.stringify(options) });
      setJob({ id: data.id, status: data.status, phase: data.status, progress: null, message: "Job masuk antrean lokal" });
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };
  const cancel = async () => { if (!job) return; try { await request(`/jobs/${job.id}/cancel`, { method: "POST" }); setJob({ ...job, status: "cancelled", phase: "cancelled", message: "Dibatalkan pengguna" }); } catch (reason) { setError((reason as Error).message); } };

  const loadScore = (Number(options.count === 10) * 2) + (Number(options.resolution === "1080") * 2) + Number(options.duration === "60-90") + Number(options.style === "Highlight");
  const load = loadScore >= 4 ? "Berat" : loadScore >= 2 ? "Sedang" : "Relatif ringan";
  const running = Boolean(job && ["queued", "preparing", "transcribing", "analyzing", "rendering"].includes(job.status));

  return <>
    <div className="page-intro"><Link href="/" className="back-link"><ArrowLeft size={14}/> Workspace</Link><div className="eyebrow">AI CLIP GENERATOR</div><h1>Buat Klip AI</h1><p>Unggah video, pilih pengaturan, lalu tinjau kandidat sebelum render.</p></div>
    <div className="create-layout">
      <div className="create-main">
        <section className="panel form-panel source-panel"><div className="step-heading"><span className="step-number">01</span><div><h2>Sumber video</h2><p>Gunakan video yang kamu miliki atau berhak proses.</p></div><span className="required-label">WAJIB</span></div>
          <div className="source-tabs"><button type="button" onClick={() => { setMode("upload"); setSource(null); setError(""); }} className={mode === "upload" ? "selected" : ""}><Upload size={15}/> Upload file</button><button type="button" onClick={() => { setMode("url"); setSource(null); setError(""); }} className={mode === "url" ? "selected" : ""}><MonitorPlay size={15}/> URL video</button></div>
          {mode === "upload" ? <div className={`dropzone ${file ? "has-file" : ""}`} onDragOver={(event) => event.preventDefault()} onDrop={dropFile} onClick={() => !busy && !source && input.current?.click()} role="button" tabIndex={0} onKeyDown={(event) => event.key === "Enter" && input.current?.click()}>
            <input ref={input} type="file" accept="video/mp4,video/quicktime,.mp4,.mov" onChange={onFile} hidden/>
            {busy && !source ? <span className="drop-icon spinning"><LoaderCircle size={21}/></span> : <span className="drop-icon"><Upload size={21}/></span>}
            {source ? <><strong>{source.name}</strong><span>{formatBytes(source.size_bytes)} · {formatDuration(source.duration)} · {source.width} × {source.height}</span><span className="source-valid"><CheckCircle2 size={14}/> Validasi ffprobe berhasil</span></> : <><strong>{file?.name || "Tarik video ke sini"}</strong><span>{file ? `${formatBytes(file.size)} · Mengunggah dan memvalidasi…` : "atau klik untuk memilih file dari perangkat"}</span><small>MP4 atau MOV · Maks. 2 GB · Durasi maks. 4 jam</small></>}
            {source && <button type="button" className="source-remove" title="Hapus pilihan" onClick={(event) => { event.stopPropagation(); setSource(null); setFile(null); }}><X size={15}/></button>}
          </div> : <div className="url-entry"><label htmlFor="video-url">URL langsung file video</label><div className="url-input-row"><input id="video-url" type="url" placeholder="https://contoh.com/video.mp4" value={url} onChange={(event) => setUrl(event.target.value)} disabled={busy || Boolean(source)}/><button className="button button-dark" onClick={importUrl} disabled={busy || !url || Boolean(source)}>{busy ? <LoaderCircle className="spin" size={15}/> : <Upload size={15}/>} Impor</button></div><div className="url-help"><LockKeyhole size={13}/> HTTPS langsung ke file media. Akses lokal/private, redirect berbahaya, dan URL halaman YouTube ditolak.</div>{source && <div className="url-success"><CheckCircle2 size={15}/><span><strong>{source.name}</strong> · {formatDuration(source.duration)} · {formatBytes(source.size_bytes)}</span><button className="icon-button" onClick={() => setSource(null)}><X size={15}/></button></div>}</div>}
          <div className="source-security"><LockKeyhole size={14}/><span>File asli disimpan lokal. Cloud AI hanya menerima transkrip jika kamu memilihnya.</span></div>
        </section>

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
            <button type="button" onClick={() => set("provider", "gemini")} className={`engine-card ${options.provider === "gemini" ? "active" : ""}`}><span className="engine-icon gemini"><Sparkles size={18}/></span><span className="engine-copy"><strong>Gemini Cloud</strong><small>Transkrip dikirim ke provider · Biaya mungkin berlaku</small><span className="connection-state">{settings?.providers?.gemini?.key_configured ? "API key tersedia" : "Butuh GEMINI_API_KEY di backend"}</span></span><span className={`radio-mark ${options.provider === "gemini" ? "checked" : ""}`}/></button>
          </div>
          {options.provider !== "local" && <div className="consent-box"><div className="consent-icon"><Cloud size={17}/></div><div><strong>Persetujuan cloud per job</strong><p>Hanya transkrip bertimestamp, bahasa, durasi, dan instruksi analisis yang dikirim. Video dan audio mentah tetap lokal. Biaya bergantung tarif akun provider; estimasi tidak tersedia.</p><label className="consent-check"><input type="checkbox" checked={options.consent} onChange={(event) => set("consent", event.target.checked)}/><span>Saya setuju mengirim transkrip ke {options.provider === "openai" ? "OpenAI" : "Gemini"} untuk job ini.</span></label></div></div>}
        </section>
        {error && <div className="notice notice-error"><AlertCircle size={17}/><span>{error}</span><button className="icon-button" onClick={() => setError("")}><X size={15}/></button></div>}
        {job && <section className={`job-progress ${job.status === "failed" ? "job-failed" : ""}`}><div className="job-progress-top"><span className="job-progress-icon">{job.status === "failed" ? <AlertCircle size={17}/> : running ? <LoaderCircle className="spin" size={17}/> : <CheckCircle2 size={17}/>}</span><div><strong>{phases[job.status] || job.status}</strong><span>{job.message}</span></div>{running && <button className="button button-quiet" onClick={cancel}>Batalkan</button>}{job.status === "failed" && <button className="button button-quiet" onClick={generate}>Coba lagi</button>}</div>{job.progress !== null && running ? <div className="progress-track"><span style={{ width: `${Math.round(job.progress * 100)}%` }}/></div> : running ? <div className="progress-indeterminate"><i/></div> : null}</section>}
        <div className="form-actions"><span><LockKeyhole size={13}/> Pemrosesan lokal · 1 job berat sekaligus</span><button className="button button-primary button-generate" disabled={!source || busy || running || (options.provider !== "local" && !options.consent)} onClick={generate}>{busy ? <LoaderCircle size={16} className="spin"/> : <Sparkles size={16}/>} Generate kandidat <ArrowRight size={16}/></button></div>
      </div>
      <aside className="create-aside">
        <section className="panel notes-card"><div className="notes-title"><span><Info size={16}/></span><div><strong>Catatan performa</strong><small>Berubah sesuai pengaturanmu</small></div></div><div className="load-meter"><span>Beban relatif</span><strong className={`load-${load.toLowerCase().replace(" ", "-")}`}>{load}</strong></div><ul className="notes-list">
          {options.resolution === "1080" && <li><i className="note-dot amber"/><span>1080p butuh render dan storage lebih besar dari 720p.</span></li>}
          {options.count === 10 && <li><i className="note-dot amber"/><span>10 kandidat berarti lebih banyak output untuk ditinjau dan dirender.</span></li>}
          {options.duration === "60-90" && <li><i className="note-dot amber"/><span>Klip 60–90 detik cenderung menghasilkan file lebih besar.</span></li>}
          {options.style === "Highlight" && <li><i className="note-dot blue"/><span>Word-level timestamp tidak aktif; highlight aman per frasa transkrip.</span></li>}
          {options.focus === "manual" && <li><i className="note-dot blue"/><span>Posisi crop manual dapat diatur setelah kandidat siap.</span></li>}
          {options.provider === "local" ? <li><i className="note-dot green"/><span>Local AI tidak memakai token API; resource CPU/RAM bergantung model.</span></li> : <li><i className="note-dot amber"/><span>Cloud mengirim transkrip, bukan video. Biaya mengikuti akun provider.</span></li>}
          {!settings?.capabilities?.ffmpeg_available && <li><i className="note-dot red"/><span>FFmpeg belum terdeteksi; pasang sebelum ingest/render.</span></li>}
          {settings?.capabilities?.ffmpeg_available && !settings.capabilities.ollama_connected && options.provider === "local" && <li><i className="note-dot red"/><span>Ollama tidak terjangkau. Local job akan gagal hingga Ollama dan model siap.</span></li>}
        </ul><div className="no-estimate"><Clock3 size={13}/> Tidak ada estimasi waktu palsu</div></section>
        <section className="panel machine-card"><div className="machine-head"><span className="machine-icon"><Cpu size={17}/></span><div><strong>Perangkat terdeteksi</strong><small>Data dari backend lokal</small></div></div>{settings ? <div className="machine-specs"><div><span>CPU</span><strong>{settings.capabilities.cpu}</strong></div><div><span>RAM</span><strong>{settings.capabilities.ram_bytes ? `${(settings.capabilities.ram_bytes / 1024 ** 3).toFixed(1)} GB` : "Tidak diketahui"}</strong></div><div><span>GPU</span><strong>{settings.capabilities.gpus.join(", ")}</strong></div><div><span>Whisper.cpp</span><strong className={settings.capabilities.whisper_cpp_available && settings.capabilities.whisper_model_configured ? "spec-ok" : "spec-missing"}>{settings.capabilities.whisper_cpp_available && settings.capabilities.whisper_model_configured ? "Siap" : "Belum disiapkan"}</strong></div></div> : <div className="machine-loading"><LoaderCircle size={15} className="spin"/> Memuat profil perangkat…</div>}<Link href="/settings" className="machine-link">Lihat diagnostik lengkap <ArrowRight size={13}/></Link></section>
        <div className="aside-tip"><Music2 size={15}/><span>Hasil transkripsi disimpan. Edit subtitle atau crop tidak mengulang analisis AI.</span></div>
      </aside>
    </div>
  </>;
}

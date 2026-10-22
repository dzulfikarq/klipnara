"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Check, CheckCircle2, ChevronDown, Clock3, Download, Eye, Film, LoaderCircle, LockKeyhole, RotateCcw, Save, Scissors, Settings2, Sparkles, Type, Video } from "lucide-react";
import { ChangeEvent, useEffect, useMemo, useState } from "react";
import { API, formatDuration, request } from "@/lib/api";

type Edit = { trim_start: number; trim_end: number; subtitle_enabled: boolean; style: "Clean" | "Bold" | "Highlight"; resolution: "720" | "1080"; crop_x: number; crop_y: number; subtitle_size: number; subtitle_position: number; subtitle_color: string; subtitle_overrides: Record<string, string> };
type Segment = { start: number; end: number; text: string };
type Data = { clip: { id: string; source_id: string; title: string; reason: string; start: number; end: number; rank: number; status: string; rendered: boolean; edit: Edit }; source: { name: string; duration: number }; transcript: Segment[]; jobs: { id: string; status: string; message: string }[] };
type Job = { id: string; status: string; phase: string; progress: number | null; message: string };

export default function ClipEditorPage() {
  const params = useParams<{ id: string }>();
  const [data, setData] = useState<Data | null>(null);
  const [edit, setEdit] = useState<Edit | null>(null);
  const [saved, setSaved] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [previewRendered, setPreviewRendered] = useState(false);
  const [previewTime, setPreviewTime] = useState(0);

  const refresh = () => request<Data>(`/clips/${params.id}`).then((next) => { setData(next); setEdit(next.clip.edit); setSaved(JSON.stringify(next.clip.edit)); }).catch((reason) => setError(reason.message));
  useEffect(() => { void refresh(); }, [params.id]);
  useEffect(() => {
    if (!job || !["queued", "preparing", "transcribing", "analyzing", "rendering"].includes(job.status)) return;
    let alive = true;
    const poll = async () => {
      try {
        const next = await request<Job>(`/jobs/${job.id}`);
        if (!alive) return;
        setJob(next);
        if (next.status === "completed") { await refresh(); setPreviewRendered(true); return; }
        if (["failed", "cancelled"].includes(next.status)) return;
        setTimeout(poll, 800);
      } catch (reason) { if (alive) setError((reason as Error).message); }
    };
    const timer = setTimeout(poll, 650);
    return () => { alive = false; clearTimeout(timer); };
  }, [job?.id]);

  const dirty = Boolean(edit && saved && JSON.stringify(edit) !== saved);
  const sourceStart = data?.clip.start || 0;
  const visibleSegments = useMemo(() => data?.transcript.map((segment, index) => ({ ...segment, index })).filter((segment) => segment.end > sourceStart + (edit?.trim_start || 0) && segment.start < sourceStart + (edit?.trim_end ?? (data?.clip.end || 0) - sourceStart)) || [], [data, edit, sourceStart]);
  if (!data || !edit) return <div className="loading-page">{error || "Memuat editor…"}</div>;
  const length = data.clip.end - data.clip.start;
  const update = <K extends keyof Edit>(key: K, value: Edit[K]) => setEdit((current) => current ? { ...current, [key]: value } : current);
  const changeStyle = (style: Edit["style"]) => setEdit((current) => {
    if (!current) return current;
    const color = style === "Highlight" && current.style !== "Highlight" && current.subtitle_color.toLowerCase() === "#ffffff"
      ? "#ffd700"
      : current.style === "Highlight" && style !== "Highlight" && current.subtitle_color.toLowerCase() === "#ffd700"
        ? "#ffffff"
        : current.subtitle_color;
    return { ...current, style, subtitle_color: color };
  });
  const updateOverride = (index: number, text: string) => setEdit((current) => current ? { ...current, subtitle_overrides: { ...current.subtitle_overrides, [String(index)]: text } } : current);
  const save = async () => {
    setError("");
    try { const savedEdit = await request<Edit>(`/clips/${data.clip.id}`, { method: "PATCH", body: JSON.stringify(edit) }); setEdit(savedEdit); setSaved(JSON.stringify(savedEdit)); setPreviewRendered(false); setData((current) => current ? { ...current, clip: { ...current.clip, status: current.clip.rendered ? "needs_render" : current.clip.status } } : current); return true; }
    catch (reason) { setError((reason as Error).message); return false; }
  };
  const render = async () => {
    if (dirty && !(await save())) return;
    try {
      const result = await request<{ id: string; status: string }>(`/clips/${data.clip.id}/render`, { method: "POST" });
      setPreviewRendered(false); setJob({ id: result.id, status: result.status, phase: result.status, progress: null, message: "Job masuk antrean" });
    } catch (reason) { setError((reason as Error).message); }
  };
  const phaseName: Record<string, string> = { queued: "Antrean lokal", preparing: "Menyiapkan render", rendering: "FFmpeg merender", completed: "Render selesai", failed: "Render gagal", cancelled: "Render dibatalkan" };
  const running = Boolean(job && ["queued", "preparing", "rendering"].includes(job.status));
  const videoUrl = previewRendered && data.clip.rendered ? `${API}/api/clips/${data.clip.id}/file` : `${API}/api/sources/${data.clip.source_id}/file`;
  const previewOffset = previewRendered ? sourceStart + edit.trim_start : 0;
  const activeSubtitle = visibleSegments.find((segment) => segment.start <= previewTime + previewOffset && segment.end > previewTime + previewOffset);

  return <>
    <div className="page-intro"><Link href={`/sources/${data.clip.source_id}`} className="back-link"><ArrowLeft size={14}/> Kandidat klip</Link><div className="eyebrow">SIMPLE CLIP EDITOR · #{String(data.clip.rank).padStart(2,"0")}</div><h1>{data.clip.title}</h1><p>{data.source.name} · {formatDuration(data.clip.start)}–{formatDuration(data.clip.end)} · Editor tidak mengulang transkripsi atau analisis AI.</p></div>
    <div className="editor-layout">
        <section className="panel editor-preview-panel"><div className="editor-panel-heading"><div><strong>Preview vertikal</strong><span>{edit.resolution === "720" ? "720 × 1280" : "1080 × 1920"} · 9:16</span></div><div className="preview-actions">{data.clip.rendered && <button type="button" className={`preview-toggle ${previewRendered ? "active" : ""}`} onClick={() => setPreviewRendered((value) => { setPreviewTime(0); return !value; })}><Eye size={13}/>{previewRendered ? data.clip.status === "needs_render" ? "Render lama" : "Hasil render" : "Sumber"}</button>}<span className="local-only-pill"><LockKeyhole size={12}/> LOCAL</span></div></div><div className="portrait-stage"><video key={`${videoUrl}-${edit.trim_start}-${edit.trim_end}`} src={videoUrl} controls playsInline preload="metadata" style={{ objectFit: "cover", objectPosition: `${edit.crop_x}% ${edit.crop_y}%` }} onLoadedMetadata={(event) => { const time = previewRendered ? 0 : sourceStart + edit.trim_start; event.currentTarget.currentTime = time; setPreviewTime(time); }} onTimeUpdate={(event) => { const video = event.currentTarget; const start = sourceStart + edit.trim_start; const end = sourceStart + edit.trim_end; if (!previewRendered && video.currentTime < start) video.currentTime = start; if (!previewRendered && video.currentTime >= end) { video.pause(); video.currentTime = end; } setPreviewTime(video.currentTime); }}/>{edit.subtitle_enabled && !previewRendered && activeSubtitle && <div className={`preview-caption style-${edit.style.toLowerCase()}`} style={{ fontSize: `${Math.max(12, edit.subtitle_size / 3)}px`, color: edit.subtitle_color, bottom: `${Math.max(5, edit.subtitle_position / 4)}%` }}>{edit.subtitle_overrides[String(activeSubtitle.index)] ?? activeSubtitle.text}</div>}<span className="preview-frame-label"><Film size={12}/> 9:16 PREVIEW</span></div><div className="preview-meta"><span><Clock3 size={13}/>{formatDuration(edit.trim_end - edit.trim_start)}</span><span><Video size={13}/>{data.clip.title}</span></div>{data.clip.status === "needs_render" && <div className="stale-render-note">Pengaturan berubah. Preview render lama tidak mencerminkan edit terbaru.</div>}{job && <div className={`editor-job ${job.status === "failed" ? "failed" : ""}`}><span>{running ? <LoaderCircle size={14} className="spin"/> : job.status === "completed" ? <CheckCircle2 size={14}/> : <Film size={14}/>}</span><div><strong>{phaseName[job.status] || job.phase}</strong><small>{job.message}</small></div>{running && job.progress !== null && <b>{Math.round(job.progress * 100)}%</b>}{running && job.progress === null && <i className="mini-indeterminate"/>}{running && <button className="icon-button" onClick={() => request(`/jobs/${job.id}/cancel`, { method: "POST" }).then(() => setJob({ ...job, status: "cancelled", message: "Dibatalkan pengguna" })).catch((reason) => setError((reason as Error).message))}>Batalkan</button>}{job.status === "failed" && <button className="icon-button" title="Retry" onClick={() => request<{id:string;status:string}>(`/jobs/${job.id}/retry`, { method: "POST", body: "{}" }).then((next) => setJob({ ...job, id: next.id, status: next.status, phase: next.status, message: "Job masuk antrean" })).catch((reason) => setError((reason as Error).message))}><RotateCcw size={14}/></button>}</div>}{error && <div className="notice notice-error editor-error">{error}</div>}
        <div className="editor-actions"><button className="button button-outline" onClick={save} disabled={!dirty}><Save size={14}/>{dirty ? "Simpan edit" : "Tersimpan"}{!dirty && <Check size={13}/>}</button><button className="button button-primary" onClick={render} disabled={running}><Sparkles size={14}/>{running ? "Sedang render…" : "Render ulang"}<ArrowLeft className="render-arrow" size={14}/></button></div>{data.clip.rendered && <a href={`${API}/api/clips/${data.clip.id}/download`} className="download-link"><Download size={14}/>{data.clip.status === "needs_render" ? "Download render sebelumnya" : "Download MP4"}</a>}</section>

      <div className={`editor-tools ${running ? "tools-disabled" : ""}`} aria-disabled={running}>
        <section className="panel tool-panel"><div className="tool-heading"><span className="tool-icon"><Scissors size={15}/></span><div><strong>Trim klip</strong><small>Batasi potongan di dalam kandidat</small></div><ChevronDown size={14}/></div><div className="trim-track"><div className="trim-fill"/><i/><i/></div><div className="trim-fields"><label><span>Awal klip</span><div><input type="number" min="0" max={edit.trim_end - 1} step="0.1" value={edit.trim_start} onChange={(event) => update("trim_start", Number(event.target.value))}/><small>detik</small></div></label><span className="trim-separator">—</span><label><span>Akhir klip</span><div><input type="number" min={edit.trim_start + 0.1} max={length} step="0.1" value={edit.trim_end} onChange={(event) => update("trim_end", Number(event.target.value))}/><small>detik</small></div></label></div><div className="trim-boundaries"><span>{formatDuration(data.clip.start + edit.trim_start)} sumber</span><span>{formatDuration(data.clip.start + edit.trim_end)} sumber</span></div></section>

        <section className="panel tool-panel"><div className="tool-heading"><span className="tool-icon purple"><Settings2 size={15}/></span><div><strong>Crop & fokus</strong><small>Posisi sumber dalam frame 9:16</small></div><ChevronDown size={14}/></div><div className="range-control"><div><label>Horizontal</label><span>{edit.crop_x === 50 ? "Center" : `${edit.crop_x}%`}</span></div><input aria-label="Posisi crop horizontal" type="range" min="0" max="100" value={edit.crop_x} onChange={(event) => update("crop_x", Number(event.target.value))}/><div className="range-labels"><span>Kiri</span><span>Tengah</span><span>Kanan</span></div></div><div className="range-control"><div><label>Vertikal</label><span>{edit.crop_y === 50 ? "Center" : `${edit.crop_y}%`}</span></div><input aria-label="Posisi crop vertikal" type="range" min="0" max="100" value={edit.crop_y} onChange={(event) => update("crop_y", Number(event.target.value))}/><div className="range-labels"><span>Atas</span><span>Tengah</span><span>Bawah</span></div></div><div className="field compact-field"><span>Resolusi output</span><select value={edit.resolution} onChange={(event) => update("resolution", event.target.value as Edit["resolution"])}><option value="720">720 × 1280</option><option value="1080">1080 × 1920</option></select></div></section>

        <section className="panel tool-panel subtitle-tool"><div className="tool-heading"><span className="tool-icon amber-tool"><Type size={15}/></span><div><strong>Subtitle</strong><small>{visibleSegments.length} frasa · bisa dikoreksi</small></div><label className="mini-toggle"><input type="checkbox" checked={edit.subtitle_enabled} onChange={(event) => update("subtitle_enabled", event.target.checked)}/><i/></label></div><div className="subtitle-style-row"><label className="field compact-field"><span>Gaya</span><select value={edit.style} onChange={(event) => changeStyle(event.target.value as Edit["style"])}><option>Clean</option><option>Bold</option><option>Highlight</option></select></label><label className="field compact-field"><span>Ukuran teks</span><div className="size-field"><input type="number" min="20" max="120" value={edit.subtitle_size} onChange={(event) => update("subtitle_size", Number(event.target.value))}/><small>px</small></div></label></div><div className="subtitle-color-row"><label>Warna teks</label><div><input type="color" aria-label="Warna teks subtitle" value={edit.subtitle_color} onChange={(event) => update("subtitle_color", event.target.value)}/><span>{edit.subtitle_color.toUpperCase()}</span></div></div><div className="range-control position-control"><div><label>Posisi vertikal</label><span>{edit.subtitle_position}%</span></div><input aria-label="Posisi vertikal subtitle" type="range" min="0" max="100" value={edit.subtitle_position} onChange={(event) => update("subtitle_position", Number(event.target.value))}/><div className="range-labels"><span>Atas</span><span>Bawah</span></div></div><div className="subtitle-edit-list"><div className="subtitle-list-heading"><span>TEKS TRANSKRIP</span><span>EDIT PER FRASA</span></div>{visibleSegments.length ? visibleSegments.map((segment) => <label key={segment.index} className="subtitle-line"><time>{formatDuration(segment.start - data.clip.start)}</time><input value={edit.subtitle_overrides[String(segment.index)] ?? segment.text} onChange={(event) => updateOverride(segment.index, event.target.value)} aria-label={`Subtitle pada ${formatDuration(segment.start)}`}/></label>) : <p className="empty-subtitles">Subtitle belum tersedia.</p>}</div>{edit.style === "Highlight" && <div className="highlight-note"><Sparkles size={13}/> Highlight kuning per frasa; word-level timestamp tidak tersedia dari konfigurasi ini.</div>}</section>
      </div>
    </div>
  </>;
}

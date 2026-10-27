"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowDown, ArrowLeft, ArrowUp, CheckCircle2, Clock3, Download, ExternalLink, Film, LoaderCircle, Pause, Play, RotateCcw, Trash2, XCircle, Youtube } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { API, formatDuration, request, reviewStatusLabel } from "@/lib/api";

type BatchItem = {
  id: string; position: number; name: string; status: string; custom_override: boolean; error: string | null; retry_count: number;
  editor_url?: string; clip_id?: string; mood_project_id?: string; render_id?: string; review_status?: "needs_review" | "approved" | "needs_revision";
  output_url?: string | null; download_url?: string | null; rendered?: boolean; start?: number; end?: number; clip_status?: string;
  project_title?: string; render_status?: string; job: { id: string; status: string; phase: string; progress: number | null; message: string } | null;
};
type Quote = { id: string; title: string; text: string; segments: { text: string; order: number }[]; mood: string; tone: string; visual_keywords: string[]; music_mood: string };
type MoodDetail = { project: { selected_quote: Quote | null }; quotes: Quote[]; generations: { quotes: Quote[] }[]; favorites: { quote: Quote }[] };
type ClipSettings = { resolution: "720" | "1080"; fps: 30 | 60; quality: "smaller" | "balanced" | "high"; subtitle_enabled: boolean };
type Batch = { id: string; name: string; type: "video_clips" | "mood_quotes"; status: string; source_id: string | null; mood_source_project_id: string | null; shared_settings: Partial<ClipSettings>; total: number; completed_count: number; failed_count: number; pending_count: number; progress: number; error: string | null; items: BatchItem[] };

const labels: Record<string, string> = { draft: "Draft", ready: "Siap", queued: "Antrean", running: "Berjalan", pausing: "Menunggu item aktif selesai", paused: "Dijeda", completed: "Selesai", completed_with_errors: "Selesai dengan error", failed: "Gagal", cancelled: "Dibatalkan", rendering: "Merender", completed_item: "Selesai" };

export default function BatchDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [batch, setBatch] = useState<Batch | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [preset, setPreset] = useState("balanced");
  const [moodChoices, setMoodChoices] = useState<Quote[]>([]);
  const [newName, setNewName] = useState("");
  const [newStart, setNewStart] = useState(0);
  const [newEnd, setNewEnd] = useState(30);
  const [newQuoteIndex, setNewQuoteIndex] = useState("");
  const refresh = useCallback(() => request<Batch>(`/batches/${params.id}`).then(setBatch).catch((reason) => setError(reason.message)), [params.id]);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!batch?.mood_source_project_id) return;
    let alive = true;
    request<MoodDetail>(`/mood-projects/${batch.mood_source_project_id}`).then((data) => {
      if (!alive) return;
      const all = [...(data.project.selected_quote ? [data.project.selected_quote] : []), ...data.quotes, ...data.favorites.map((item) => item.quote), ...data.generations.flatMap((row) => row.quotes)];
      const seen = new Set<string>();
      setMoodChoices(all.filter((quote) => { const key = quote.text.toLocaleLowerCase(); if (seen.has(key)) return false; seen.add(key); return true; }));
    }).catch((reason) => setError(reason.message));
    return () => { alive = false; };
  }, [batch?.mood_source_project_id]);
  useEffect(() => {
    const value = batch?.shared_settings;
    if (value) setPreset(value.quality === "smaller" ? "lightweight" : value.resolution === "1080" || value.quality === "high" ? "high" : "balanced");
  }, [batch?.shared_settings]);
  useEffect(() => {
    if (!batch || (!["queued", "running", "pausing"].includes(batch.status) && !batch.items.some((item) => item.job && ["queued", "preparing", "rendering"].includes(item.job.status)))) return;
    const timer = setTimeout(() => void refresh(), 1200);
    return () => clearTimeout(timer);
  }, [batch, refresh]);

  const action = async (path: string, method = "POST", body?: unknown) => {
    setBusy(true); setError("");
    try { await request(path, { method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) }); await refresh(); }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };
  const review = async (item: BatchItem, status: "approved" | "needs_revision") => {
    if (item.clip_id) return action(`/clips/${item.clip_id}/review`, "POST", { status });
    if (item.render_id) return action(`/mood-renders/${item.render_id}/review`, "POST", { status });
  };
  const reorder = (index: number, delta: number) => {
    if (!batch) return;
    const items = [...batch.items]; const target = index + delta;
    if (target < 0 || target >= items.length) return;
    [items[index], items[target]] = [items[target], items[index]];
    void action(`/batches/${batch.id}/items/order`, "PATCH", { item_ids: items.map((item) => item.id) });
  };
  const addItem = () => {
    if (!batch) return;
    const quote = moodChoices[Number(newQuoteIndex)];
    const body = batch.type === "video_clips"
      ? { name: newName.trim() || `Clip ${batch.total + 1}`, start: newStart, end: newEnd }
      : { name: newName.trim() || quote?.title || `Quote ${batch.total + 1}`, quote };
    void action(`/batches/${batch.id}/items`, "POST", body);
  };
  const applySharedSettings = () => {
    if (!batch) return;
    const settings: ClipSettings = preset === "lightweight"
      ? { resolution: "720", fps: 30, quality: "smaller", subtitle_enabled: false }
      : preset === "high"
        ? { resolution: "1080", fps: 30, quality: "high", subtitle_enabled: false }
        : { resolution: "720", fps: 30, quality: "balanced", subtitle_enabled: false };
    void action(`/batches/${batch.id}`, "PATCH", { shared_settings: settings, apply_to_pending: true });
  };
  const removeBatch = async () => {
    if (!batch || !window.confirm("Remove batch queue record? Clip/Mood drafts and rendered MP4 outputs remain available as individual projects.")) return;
    setBusy(true); setError("");
    try { await request(`/batches/${batch.id}`, { method: "DELETE" }); router.push("/batches"); }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };

  if (!batch) return <><div className="page-intro"><Link href="/batches" className="back-link"><ArrowLeft size={14}/> Batch Creator</Link><h1>Batch</h1></div>{error && <div className="notice notice-error">{error}</div>}</>;
  const active = ["queued", "running", "pausing"].includes(batch.status);
  const jobsActive = batch.items.some((item) => item.job && ["queued", "preparing", "rendering"].includes(item.job.status));
  const stateText = labels[batch.status] || batch.status;

  return <>
    <div className="page-intro"><Link href="/batches" className="back-link"><ArrowLeft size={14}/> Semua batch</Link><div className="eyebrow">{batch.type === "video_clips" ? "VIDEO CLIPS" : "MOOD QUOTES"} · BATCH</div><h1>{batch.name}</h1><p>{batch.completed_count}/{batch.total} item selesai · {batch.failed_count} gagal · {batch.pending_count} menunggu · {stateText}</p></div>
    <section className="panel batch-control-panel"><div className="batch-overview"><div><strong>{stateText}</strong><span>Progress penyelesaian item · {batch.completed_count}/{batch.total}</span></div><div className="batch-progress-track"><i style={{ width: `${Math.round(batch.progress * 100)}%` }}/></div></div><div className="batch-controls">
      {batch.status === "draft" || batch.status === "ready" ? <button className="button button-primary" disabled={busy} onClick={() => void action(`/batches/${batch.id}/start`)}><Play size={15}/> Start Batch</button> : null}
      {active && batch.status !== "pausing" && <button className="button button-outline" disabled={busy} onClick={() => void action(`/batches/${batch.id}/pause`)}><Pause size={15}/> Pause setelah item aktif</button>}
      {batch.status === "paused" && <button className="button button-primary" disabled={busy} onClick={() => void action(`/batches/${batch.id}/resume`)}><Play size={15}/> Resume</button>}
      {batch.failed_count > 0 && !active && <button className="button button-outline" disabled={busy} onClick={() => void action(`/batches/${batch.id}/retry-failed`)}><RotateCcw size={15}/> Retry failed items</button>}
      {! ["completed", "completed_with_errors", "failed", "cancelled"].includes(batch.status) && <button className="button button-danger" disabled={busy} onClick={() => { if (window.confirm("Batalkan batch dan tandai item menunggu sebagai dibatalkan? Render aktif berhenti lewat jalur cancel aman; output selesai tetap disimpan.")) void action(`/batches/${batch.id}/cancel`); }}><XCircle size={15}/> Cancel Batch</button>}
      <button className="button button-outline" disabled={busy} onClick={() => void refresh()}><RotateCcw size={14}/> Refresh</button>
      {!active && !jobsActive && <button className="button button-quiet" disabled={busy} onClick={() => void removeBatch()}><Trash2 size={14}/> Hapus batch record</button>}
     </div>{batch.error && <p className="batch-inline-error">{batch.error}</p>}{error && <div className="notice notice-error">{error}</div>}<p className="batch-muted"><Clock3 size={13}/> Satu render aktif. Pause menunggu item aktif selesai; progress persen hanya tampil untuk job yang memberi angka nyata.</p>{batch.type === "video_clips" && ["draft", "ready", "paused"].includes(batch.status) && <div className="batch-shared-settings"><label className="field"><span>Preset bersama</span><select value={preset} onChange={(event) => setPreset(event.target.value)}><option value="balanced">Balanced · 720p</option><option value="lightweight">Lightweight · 720p smaller</option><option value="high">High Quality · 1080p</option></select></label><button className="button button-outline" disabled={busy} onClick={applySharedSettings}>Terapkan ke item pending non-custom</button><small>Custom Override tetap dipertahankan. Item completed tidak dirender ulang otomatis.</small></div>}</section>

    {["draft", "ready", "paused"].includes(batch.status) && <section className="panel batch-add-item"><div className="panel-heading"><div><span className="eyebrow">EDIT QUEUE</span><h3>Tambah item</h3></div><span className="required-label">{batch.total}/10</span></div>{batch.type === "video_clips" ? <div className="batch-add-fields"><label className="field"><span>Nama item</span><input value={newName} maxLength={120} onChange={(event) => setNewName(event.target.value)} placeholder={`Clip ${batch.total + 1}`}/></label><label className="field"><span>Start · detik</span><input type="number" min="0" step="0.1" value={newStart} onChange={(event) => setNewStart(Number(event.target.value))}/></label><label className="field"><span>End · detik</span><input type="number" min="0.1" step="0.1" value={newEnd} onChange={(event) => setNewEnd(Number(event.target.value))}/></label></div> : <div className="batch-add-fields"><label className="field"><span>Quote tersimpan</span><select value={newQuoteIndex} onChange={(event) => setNewQuoteIndex(event.target.value)}><option value="">Pilih saran/favorit/riwayat</option>{moodChoices.map((quote, index) => <option key={`${index}-${quote.id}`} value={index}>{quote.title} · {quote.text.slice(0, 65)}</option>)}</select></label><label className="field"><span>Nama item</span><input value={newName} maxLength={120} onChange={(event) => setNewName(event.target.value)} placeholder="Nama quote"/></label></div>}<button className="button button-primary" disabled={busy || batch.total >= 10 || (batch.type === "mood_quotes" && (newQuoteIndex === "" || !moodChoices[Number(newQuoteIndex)]))} onClick={addItem}><Play size={14}/> Tambah item</button></section>}

    <section className="batch-results"><div className="panel-heading"><div><span className="eyebrow">OUTPUT INDIVIDUAL</span><h3>Queue & Results</h3></div><span className="required-label">REVIEW PER VIDEO</span></div>
      {batch.items.map((item, index) => <article className={`panel batch-result-item batch-status-${item.status}`} key={item.id}>
        <div className="batch-result-main"><span className="batch-result-number">{String(index + 1).padStart(2, "0")}</span><div className="batch-result-copy"><strong>{item.name}</strong><small>{item.project_title || (item.start !== undefined && item.end !== undefined ? `${formatDuration(item.start)}–${formatDuration(item.end)}` : "Mood Quotes output")} · {item.custom_override ? "Custom Override" : "Using Batch Default"}{item.retry_count ? ` · retry ${item.retry_count}` : ""}</small>{item.job?.message && <small>{item.job.message}</small>}{item.error && <span className="batch-inline-error">{item.error}</span>}</div><span className={`batch-status-pill status-${item.status}`}>{labels[item.status] || item.status}</span></div>
        {item.status === "rendering" && <div className="batch-item-progress">{item.job?.progress !== null && item.job?.progress !== undefined ? <div className="progress-track"><span style={{ width: `${Math.round(item.job.progress * 100)}%` }}/></div> : <div className="progress-indeterminate"><i/></div>}</div>}
        <div className="batch-result-actions">
          {item.editor_url && <Link className="button button-outline" href={item.editor_url}><ExternalLink size={14}/> Open Editor</Link>}
          {item.output_url && <details className="batch-preview"><summary className="button button-outline"><Film size={14}/> Preview</summary><video src={`${API}${item.output_url}`} controls preload="none" playsInline/> </details>}
          {item.download_url && <a className="button button-outline" href={`${API}${item.download_url}`}><Download size={14}/> Download</a>}
          {item.rendered && item.review_status && <span className={`review-chip review-${item.review_status}`}>{reviewStatusLabel(item.review_status)}</span>}
          {item.review_status === "approved" && (item.clip_id || item.render_id) && <Link className="button button-outline" href={`/publishing?content_type=${item.clip_id ? "clip" : "mood_render"}&content_id=${item.clip_id || item.render_id}`}><Youtube size={14}/> Publish this item</Link>}
          {item.rendered && (item.clip_status === "completed" || item.render_status === "completed") && item.review_status !== "approved" && <button className="button button-primary" disabled={busy || item.status === "rendering"} onClick={() => void review(item, "approved")}><CheckCircle2 size={14}/> Approve output ini</button>}
          {item.rendered && (item.clip_status === "completed" || item.render_status === "completed") && item.review_status !== "needs_revision" && <button className="button button-quiet" disabled={busy || item.status === "rendering"} onClick={() => void review(item, "needs_revision")}>Needs revision</button>}
          {["failed", "cancelled"].includes(item.status) && <button className="button button-outline" disabled={busy || active} onClick={() => void action(`/batches/${batch.id}/items/${item.id}/retry`)}><RotateCcw size={14}/> Retry item</button>}
          {["draft", "ready"].includes(batch.status) && <><button className="icon-button" aria-label="Naikkan item" disabled={!index || busy} onClick={() => reorder(index, -1)}><ArrowUp size={14}/></button><button className="icon-button" aria-label="Turunkan item" disabled={index === batch.items.length - 1 || busy} onClick={() => reorder(index, 1)}><ArrowDown size={14}/></button><button className="button button-quiet" disabled={busy || batch.items.length <= 1 || !["ready", "draft"].includes(item.status)} onClick={() => void action(`/batches/${batch.id}/items/${item.id}`, "DELETE")}><Trash2 size={14}/> Remove</button></>}
        </div>
        {["draft", "ready"].includes(batch.status) && <div className="batch-result-actions"><button className="button button-quiet" disabled={busy || batch.total >= 10 || !["ready", "draft"].includes(item.status)} onClick={() => void action(`/batches/${batch.id}/items/${item.id}/duplicate`)}>Duplikasi item</button></div>}
        {["queued", "running", "paused"].includes(batch.status) && item.status === "queued" && !item.job && <div className="batch-result-actions"><button className="icon-button" aria-label="Naikkan item" disabled={busy || index === 0 || batch.items[index - 1].status !== "queued" || Boolean(batch.items[index - 1].job)} onClick={() => reorder(index, -1)}><ArrowUp size={14}/></button><button className="icon-button" aria-label="Turunkan item" disabled={busy || index === batch.items.length - 1 || batch.items[index + 1].status !== "queued" || Boolean(batch.items[index + 1].job)} onClick={() => reorder(index, 1)}><ArrowDown size={14}/></button><button className="button button-quiet" disabled={busy} onClick={() => void action(`/batches/${batch.id}/items/${item.id}`, "DELETE")}><Trash2 size={14}/> Remove pending item</button></div>}
      </article>)}
    </section>
  </>;
}

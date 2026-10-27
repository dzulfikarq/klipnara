"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Copy, Film, Heart, LoaderCircle, Plus, Scissors, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { formatDuration, request } from "@/lib/api";

type Source = { id: string; name: string; duration: number; size_bytes: number };
type Project = { id: string; title: string; updated_at: string };
type Quote = { id: string; title: string; text: string; segments: { text: string; order: number }[]; mood: string; tone: string; visual_keywords: string[]; music_mood: string };
type MoodDetail = { project: { id: string; title: string; selected_quote: Quote | null }; quotes: Quote[]; generations: { id: string; provider: string; quotes: Quote[] }[]; favorites: { id: string; quote: Quote }[] };
type Batch = { id: string; name: string; type: string; status: string; total: number; completed_count: number; failed_count: number; updated_at: string };
type ClipSpec = { name: string; start: number; end: number };
type Candidate = { key: string; label: string; quote: Quote };

const presets = {
  balanced: { resolution: "720", fps: 30, quality: "balanced", subtitle_enabled: false },
  lightweight: { resolution: "720", fps: 30, quality: "smaller", subtitle_enabled: false },
  high: { resolution: "1080", fps: 30, quality: "high", subtitle_enabled: false },
} as const;

export default function BatchesPage() {
  const router = useRouter();
  const [batches, setBatches] = useState<Batch[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [mood, setMood] = useState<MoodDetail | null>(null);
  const [sourceId, setSourceId] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState<"video_clips" | "mood_quotes">("video_clips");
  const [clipPreset, setClipPreset] = useState<keyof typeof presets>("balanced");
  const [clips, setClips] = useState<ClipSpec[]>([{ name: "Clip 1", start: 0, end: 30 }]);
  const [selectedQuotes, setSelectedQuotes] = useState<string[]>([]);
  const [manualTitle, setManualTitle] = useState("");
  const [manualText, setManualText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = () => request<Batch[]>("/batches").then(setBatches).catch((reason) => setError(reason.message));
  useEffect(() => {
    void Promise.all([request<Source[]>("/sources"), request<Project[]>("/mood-projects"), request<Batch[]>("/batches")])
      .then(([sourceRows, projectRows, batchRows]) => { setSources(sourceRows); setProjects(projectRows); setBatches(batchRows); if (sourceRows[0]) setSourceId(sourceRows[0].id); if (projectRows[0]) setProjectId(projectRows[0].id); })
      .catch((reason) => setError(reason.message));
  }, []);
  useEffect(() => {
    if (!projectId) { setMood(null); return; }
    let alive = true;
    request<MoodDetail>(`/mood-projects/${projectId}`).then((data) => { if (alive) { setMood(data); setSelectedQuotes([]); } }).catch((reason) => { if (alive) setError(reason.message); });
    return () => { alive = false; };
  }, [projectId]);

  const candidates = useMemo<Candidate[]>(() => {
    if (!mood) return [];
    const rows: Candidate[] = [];
    if (mood.project.selected_quote) rows.push({ key: `selected:${mood.project.selected_quote.id}`, label: "Quote draft", quote: mood.project.selected_quote });
    mood.quotes.forEach((quote, index) => rows.push({ key: `current:${index}:${quote.id}`, label: "Saran terbaru", quote }));
    mood.favorites.forEach((item) => rows.push({ key: `favorite:${item.id}`, label: "Favorit", quote: item.quote }));
    mood.generations.forEach((generation) => generation.quotes.forEach((quote, index) => rows.push({ key: `history:${generation.id}:${index}`, label: `${generation.provider} · riwayat`, quote })));
    const seen = new Set<string>();
    return rows.filter((row) => { const key = row.quote.text.trim().toLocaleLowerCase(); if (seen.has(key)) return false; seen.add(key); return true; });
  }, [mood]);

  const selectedSource = sources.find((source) => source.id === sourceId);
  const toggleQuote = (key: string) => setSelectedQuotes((rows) => rows.includes(key) ? rows.filter((item) => item !== key) : rows.length >= 10 ? rows : [...rows, key]);
  const shiftClip = (index: number, delta: number) => setClips((rows) => { const next = [...rows]; const target = index + delta; if (target < 0 || target >= next.length) return rows; [next[index], next[target]] = [next[target], next[index]]; return next; });
  const duplicateClip = (index: number) => setClips((rows) => rows.length >= 10 ? rows : [...rows.slice(0, index + 1), { ...rows[index], name: `${rows[index].name} copy` }, ...rows.slice(index + 1)]);

  const create = async () => {
    setBusy(true); setError("");
    try {
      let batch: Batch;
      if (type === "video_clips") {
        if (!sourceId) throw new Error("Pilih video sumber.");
        batch = await request<Batch>("/batches/clips", { method: "POST", body: JSON.stringify({ name: name.trim() || "Batch Video Clips", source_id: sourceId, shared_settings: presets[clipPreset], items: clips }) });
      } else {
        if (!projectId || !mood) throw new Error("Pilih draft Mood Quotes.");
        const selected = selectedQuotes.map((key) => candidates.find((item) => item.key === key)).filter((item): item is Candidate => Boolean(item)).map((item) => ({ name: item.quote.title, quote: item.quote }));
        if (manualText.trim()) {
          const template = mood.project.selected_quote || candidates[0]?.quote;
          const manual: Quote = { id: `manual-${Date.now()}`, title: manualTitle.trim() || "Quote manual", text: manualText.trim(), segments: [{ text: manualText.trim(), order: 1 }], mood: template?.mood || "manual", tone: template?.tone || "natural", visual_keywords: template?.visual_keywords || ["calm", "reflection"], music_mood: template?.music_mood || "calm" };
          selected.push({ name: manual.title, quote: manual });
        }
        if (!selected.length) throw new Error("Pilih sedikitnya satu quote atau isi quote manual.");
        if (selected.length > 10) throw new Error("Batch maksimal 10 item.");
        batch = await request<Batch>(`/mood-projects/${projectId}/batches`, { method: "POST", body: JSON.stringify({ name: name.trim() || "Batch Mood Quotes", items: selected }) });
      }
      router.push(`/batches/${batch.id}`);
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };

  return <>
    <div className="page-intro"><Link href="/create" className="back-link"><ArrowLeft size={14}/> Buat Video</Link><div className="eyebrow">KLIPNARA STUDIO · V2.9</div><h1>Batch Creator</h1><p>Siapkan beberapa output, edit per item, lalu render serial lewat worker lokal.</p></div>
    <div className="batch-layout">
      <section className="panel form-panel">
        <div className="step-heading"><span className="step-number">01</span><div><h2>Buat batch</h2><p>Maksimal 10 item. AI quote generation tidak dijalankan otomatis.</p></div></div>
        <div className="workflow-tabs" role="tablist" aria-label="Jenis batch"><button role="tab" aria-selected={type === "video_clips"} className={type === "video_clips" ? "selected" : ""} onClick={() => setType("video_clips")}><Scissors size={15}/> Video Clips</button><button role="tab" aria-selected={type === "mood_quotes"} className={type === "mood_quotes" ? "selected" : ""} onClick={() => setType("mood_quotes")}><Heart size={15}/> Mood Quotes</button></div>
        <label className="field"><span>Nama batch</span><input value={name} maxLength={120} onChange={(event) => setName(event.target.value)} placeholder={type === "video_clips" ? "Podcast highlights" : "Quote pilihan"}/></label>
        {type === "video_clips" ? <>
          <label className="field"><span>Source video</span><select value={sourceId} onChange={(event) => setSourceId(event.target.value)}><option value="">Pilih dari Source Library</option>{sources.map((source) => <option key={source.id} value={source.id}>{source.name} · {formatDuration(source.duration)}</option>)}</select></label>
          {selectedSource && <p className="batch-muted">{selectedSource.name} · {formatDuration(selectedSource.duration)} · source direferensikan, tidak disalin.</p>}
          <label className="field"><span>Preset ekspor bersama</span><select value={clipPreset} onChange={(event) => setClipPreset(event.target.value as keyof typeof presets)}><option value="balanced">Shorts Balanced · 720p · 30 FPS</option><option value="lightweight">Shorts Lightweight · 720p · Smaller</option><option value="high">High Quality · 1080p · 30 FPS</option></select></label>
          <div className="batch-list-heading"><strong>Clip items · {clips.length}/10</strong><button className="button button-outline" disabled={clips.length >= 10} onClick={() => setClips((rows) => [...rows, { name: `Clip ${rows.length + 1}`, start: 0, end: 30 }])}><Plus size={14}/> Tambah clip</button></div>
          <div className="batch-draft-items">{clips.map((clip, index) => <article className="batch-draft-item" key={`${index}-${clip.name}`}><div className="batch-item-toolbar"><strong>{index + 1}. {clip.name || "Clip"}</strong><div><button className="icon-button" aria-label="Naikkan" disabled={!index} onClick={() => shiftClip(index, -1)}><ArrowUp size={14}/></button><button className="icon-button" aria-label="Turunkan" disabled={index === clips.length - 1} onClick={() => shiftClip(index, 1)}><ArrowDown size={14}/></button><button className="icon-button" aria-label="Duplikasi" disabled={clips.length >= 10} onClick={() => duplicateClip(index)}><Copy size={14}/></button><button className="icon-button" aria-label="Hapus" disabled={clips.length <= 1} onClick={() => setClips((rows) => rows.filter((_, item) => item !== index))}><Trash2 size={14}/></button></div></div><div className="batch-clip-fields"><label className="field"><span>Nama output</span><input maxLength={120} value={clip.name} onChange={(event) => setClips((rows) => rows.map((item, i) => i === index ? { ...item, name: event.target.value } : item))}/></label><label className="field"><span>Start · detik</span><input type="number" min="0" step="0.1" value={clip.start} onChange={(event) => setClips((rows) => rows.map((item, i) => i === index ? { ...item, start: Number(event.target.value) } : item))}/></label><label className="field"><span>End · detik</span><input type="number" min="0.1" step="0.1" value={clip.end} onChange={(event) => setClips((rows) => rows.map((item, i) => i === index ? { ...item, end: Number(event.target.value) } : item))}/></label></div><small>Multi-scene, subtitle, audio, dan crop dapat diedit per item setelah dibuat.</small></article>)}</div>
        </> : <>
          <label className="field"><span>Draft Mood Quotes</span><select value={projectId} onChange={(event) => setProjectId(event.target.value)}><option value="">Pilih draft tersimpan</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.title}</option>)}</select></label>
          <p className="batch-muted">Pilih saran terbaru, favorit, atau riwayat. Batch memakai komposisi/background/musik draft sebagai default bersama; tiap item tetap bisa diedit.</p>
          <div className="batch-quote-list">{candidates.map((candidate) => <label key={candidate.key}><input type="checkbox" checked={selectedQuotes.includes(candidate.key)} disabled={!selectedQuotes.includes(candidate.key) && selectedQuotes.length >= 10} onChange={() => toggleQuote(candidate.key)}/><span><strong>{candidate.quote.title}</strong><small>{candidate.quote.text}</small><em>{candidate.label}</em></span></label>)}</div>
          <details className="batch-manual-quote"><summary><Plus size={14}/> Tambah quote manual</summary><label className="field"><span>Judul</span><input value={manualTitle} maxLength={80} onChange={(event) => setManualTitle(event.target.value)}/></label><label className="field"><span>Teks quote</span><textarea rows={3} maxLength={500} value={manualText} onChange={(event) => setManualText(event.target.value)}/></label><small>Quote manual tidak mengirim data ke AI.</small></details>
        </>}
        {error && <div className="notice notice-error">{error}</div>}
        <div className="form-actions"><span>Worker serial · tanpa autopublish</span><button className="button button-primary" disabled={busy || (type === "video_clips" ? !sourceId : !projectId || selectedQuotes.length + Number(Boolean(manualText.trim())) === 0 || selectedQuotes.length + Number(Boolean(manualText.trim())) > 10)} onClick={() => void create()}>{busy ? <LoaderCircle size={15} className="spin"/> : <ArrowRight size={15}/>} Buat batch</button></div>
      </section>
      <aside className="panel batch-aside"><div className="notes-title"><span><Film size={16}/></span><div><strong>Batch lokal</strong><small>Satu render aktif</small></div></div><ul className="notes-list"><li><i className="note-dot green"/><span>Source dan Mood asset direferensikan; media tidak diduplikasi.</span></li><li><i className="note-dot blue"/><span>Render memakai worker dan renderer existing secara berurutan.</span></li><li><i className="note-dot amber"/><span>Pause menunggu render aktif selesai. Progress per item; tidak ada estimasi palsu.</span></li><li><i className="note-dot green"/><span>Setiap output perlu review/approval sendiri.</span></li></ul></aside>
    </div>
    <section className="panel batch-history-panel"><div className="panel-heading"><div><span className="eyebrow">PERSISTENT QUEUE</span><h3>Batch tersimpan</h3></div><button className="button button-outline" onClick={() => void refresh()}>Refresh</button></div>{batches.length ? <div className="batch-history-list">{batches.map((batch) => <Link href={`/batches/${batch.id}`} key={batch.id}><span><strong>{batch.name}</strong><small>{batch.type === "video_clips" ? "Video Clips" : "Mood Quotes"} · {batch.total} item · {batch.completed_count} selesai · {batch.failed_count} gagal</small></span><em>{batch.status.replaceAll("_", " ")}</em><ArrowRight size={15}/></Link>)}</div> : <p className="batch-muted">Belum ada batch.</p>}</section>
  </>;
}

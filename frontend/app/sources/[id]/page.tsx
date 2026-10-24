"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, ArrowRight, Captions, CircleHelp, Clock3, Film, Play, Scissors, Sparkles, Video } from "lucide-react";
import { useEffect, useState } from "react";
import { API, formatBytes, formatDuration, request, reviewStatusLabel } from "@/lib/api";
import type { ReviewStatus } from "@/lib/api";

type Clip = { id: string; start: number; end: number; title: string; reason: string; rank: number; status: string; review_status: ReviewStatus; rendered: boolean };
type Source = { id: string; name: string; duration: number; width: number; height: number; size_bytes: number; video_codec: string; audio_codec: string | null; transcript: { start: number; end: number; text: string }[]; created_at: string };
type Job = { status: string; phase: string; message: string };

export default function SourceDetailPage() {
  const params = useParams<{ id: string }>();
  const [source, setSource] = useState<Source | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    request<{ source: Source; clips: Clip[] }>(`/sources/${params.id}`).then((data) => { setSource(data.source); setClips(data.clips); }).catch((reason) => setError(reason.message));
    request<Job[]>("/jobs").then((rows) => setJob(rows.find((item) => (item as Job & { source_id: string }).source_id === params.id) || null)).catch(() => {});
  }, [params.id]);
  if (!source) return <div className="loading-page">{error || "Memuat video…"}</div>;

  return <>
    <div className="page-intro"><Link href="/library" className="back-link"><ArrowLeft size={14}/> Video Library</Link><div className="eyebrow">VIDEO PROJECT</div><h1>{source.name}</h1><p>{formatDuration(source.duration)} · {source.width} × {source.height} · {formatBytes(source.size_bytes)} · {source.video_codec.toUpperCase()}</p></div>
    <section className="source-summary panel"><div className="source-preview"><video src={`${API}/api/sources/${source.id}/file`} controls preload="metadata"/></div><div className="source-meta"><div className="eyebrow">SOURCE VIDEO</div><h2>Analisis konten</h2><p>Transkrip sumber disimpan lokal dan digunakan ulang saat kamu mengubah subtitle atau merender klip.</p><div className="source-meta-stats"><span><Clock3 size={14}/>{formatDuration(source.duration)}</span><span><Video size={14}/>{source.width} × {source.height}</span><span><Captions size={14}/>{source.transcript.length ? `${source.transcript.length} segmen` : "Belum ditranskripsi"}</span></div>{job && <div className={`job-inline ${job.status === "failed" ? "failed" : ""}`}><i/>{job.message || job.phase.replaceAll("_", " ")}</div>}<Link className="button button-primary" href={`/create?source=${source.id}`}><Scissors size={15}/> Analisis ulang <ArrowRight size={15}/></Link></div></section>
    <div className="review-heading"><div><div className="eyebrow">AI SELECTION</div><h2>Kandidat highlight <span>{clips.length}</span></h2><p>Tinjau alasan AI, edit trim dan subtitle, lalu render klip pilihan.</p></div></div>
    {clips.length ? <div className="candidate-grid">{clips.map((clip) => <article key={clip.id} className="candidate-card"><div className="candidate-cover"><div className="candidate-number">{String(clip.rank).padStart(2,"0")}</div><span className="candidate-play"><Play size={17} fill="currentColor"/></span><span className="candidate-duration">{formatDuration(clip.end - clip.start)}</span><div className="candidate-cover-caption">{clip.title}</div></div><div className="candidate-body"><div className="candidate-label"><Sparkles size={12}/> HIGHLIGHT #{clip.rank} · <span className={`review-status-chip review-${clip.review_status.replace("_","-")}`}>{reviewStatusLabel(clip.review_status)}</span>{clip.rendered && <span className="rendered-chip">{clip.status === "needs_render" ? "RERENDER" : "RENDERED"}</span>}</div><h3>{clip.title}</h3><p>{clip.reason}</p><div className="candidate-time"><Clock3 size={12}/>{formatDuration(clip.start)} – {formatDuration(clip.end)}</div><Link href={`/clips/${clip.id}`} className="button button-outline"><Scissors size={14}/>{clip.rendered ? "Buka editor" : "Edit & render"}<ArrowRight size={14}/></Link></div></article>)}</div> : <div className="empty-review panel"><div className="empty-icon"><CircleHelp size={20}/></div><strong>{source.transcript.length ? "Belum ada kandidat" : "Analisis belum dijalankan"}</strong><span>{source.transcript.length ? "Buat analisis baru untuk memilih momen dari transkrip ini." : "Mulai dari Buat Klip AI untuk transkripsi lokal dan analisis highlight."}</span><Link className="button button-primary" href={`/create?source=${source.id}`}><Sparkles size={15}/> Analisis sumber ini</Link></div>}
    {source.transcript.length > 0 && <details className="transcript-panel panel"><summary><div><Captions size={16}/><strong>Transkrip</strong><span>{source.transcript.length} segmen · bisa dikoreksi di editor klip</span></div><span className="transcript-chevron">⌄</span></summary><div className="transcript-list">{source.transcript.map((segment, index) => <div key={index}><time>{formatDuration(segment.start)}</time><span>{segment.text}</span></div>)}</div></details>}
  </>;
}

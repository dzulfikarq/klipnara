"use client";

import Link from "next/link";
import { ArrowRight, Captions, Clock3, Download, Film, Scissors, Trash2, Video, X } from "lucide-react";
import { useEffect, useState } from "react";
import { API, formatDuration, request, reviewStatusLabel } from "@/lib/api";
import type { ReviewStatus } from "@/lib/api";

type Clip = { id: string; source_id: string; title: string; status: string; origin: string; review_status: ReviewStatus; source_name: string; start: number; end: number; rendered: boolean; reason: string; rank: number };

export default function ClipLibraryPage() {
  const [clips, setClips] = useState<Clip[]>([]);
  const [remove, setRemove] = useState<Clip | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { request<Clip[]>("/clips").then(setClips).catch((reason) => setError(reason.message)); }, []);
  const rendered = clips.filter((clip) => clip.rendered);
  const deleteClip = async () => {
    if (!remove) return;
    setBusy(true);
    try { await request(`/clips/${remove.id}`, { method: "DELETE" }); setClips((items) => items.filter((item) => item.id !== remove.id)); setRemove(null); }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };
  return <>
    <div className="page-intro"><div className="eyebrow">YOUR OUTPUTS</div><h1>Clip Library</h1><p>Kandidat pilihan dan video yang sudah dirender.</p></div>
    {error && <div className="notice notice-error">{error}</div>}
    <div className="library-summary"><div className="library-count"><span className="library-count-icon"><Film size={18}/></span><div><strong>{clips.length} klip</strong><span>{rendered.length} MP4 selesai dirender</span></div></div><span className="library-note"><Captions size={14}/> H.264 · AAC · rasio 9:16</span></div>
    {clips.length ? <div className="clip-library-grid">{clips.map((clip) => <article className="clip-library-card" key={clip.id}><Link href={`/clips/${clip.id}`} className="clip-library-preview">{clip.rendered ? <video src={`${API}/api/clips/${clip.id}/file`} preload="metadata" muted/> : <span><Video size={26}/></span>}<em>{formatDuration(clip.end - clip.start)}</em><div className="preview-badge">{clip.rendered ? "MP4" : "KANDIDAT"}</div></Link><div className="clip-library-info"><div className="clip-library-meta"><span>#{String(clip.rank).padStart(2,"0")} · {clip.source_name}</span><span className={`review-status-chip review-${clip.review_status.replace("_","-")}`} title={clip.status === "needs_render" ? "Edit berubah; render ulang sebelum approval" : undefined}>{clip.status === "needs_render" ? `Edit berubah · ${reviewStatusLabel(clip.review_status)}` : reviewStatusLabel(clip.review_status)}</span></div><h3>{clip.title}</h3><div className="clip-library-footer"><span><Clock3 size={12}/>{formatDuration(clip.start)} – {formatDuration(clip.end)}</span><div><Link href={`/clips/${clip.id}`} className="icon-button" title="Edit"><Scissors size={15}/></Link>{clip.rendered && <a href={`${API}/api/clips/${clip.id}/download`} className="icon-button" title="Download"><Download size={15}/></a>}<button className="icon-button delete-source" title="Hapus klip" onClick={() => setRemove(clip)}><Trash2 size={14}/></button></div></div></div></article>)}</div> : <div className="empty-library panel"><span className="empty-icon"><Film size={21}/></span><h2>Belum ada klip</h2><p>Analisis video untuk menghasilkan kandidat highlight.</p><Link href="/create" className="button button-primary"><Scissors size={15}/> Buat Klip AI <ArrowRight size={15}/></Link></div>}
    {remove && <div className="modal-backdrop" onClick={(event) => { if (event.target === event.currentTarget) setRemove(null); }}><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="delete-clip-title"><span className="confirm-icon"><Trash2 size={18}/></span><h2 id="delete-clip-title">Hapus klip ini?</h2><p><strong>{remove.title}</strong> dan hasil render akan dihapus. Video sumber tetap tersimpan.</p><div><button className="button button-outline" onClick={() => setRemove(null)} disabled={busy}>Batal</button><button className="button button-danger" onClick={deleteClip} disabled={busy}>{busy ? "Menghapus…" : "Hapus klip"}</button></div><button className="modal-close icon-button" aria-label="Tutup" onClick={() => setRemove(null)}><X size={15}/></button></section></div>}
  </>;
}

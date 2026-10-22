"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, Check, Clock3, Film, Search, Trash2, Video, X } from "lucide-react";
import { formatBytes, formatDuration, request } from "@/lib/api";

type Source = { id: string; name: string; duration: number; width: number; height: number; size_bytes: number; created_at: string; clip_count: number; latest_status: string | null };

export default function VideoLibraryPage() {
  const [sources, setSources] = useState<Source[]>([]);
  const [query, setQuery] = useState("");
  const [remove, setRemove] = useState<Source | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = () => request<Source[]>("/sources").then(setSources).catch((reason) => setError(reason.message));
  useEffect(() => { void refresh(); }, []);
  const rows = useMemo(() => sources.filter((source) => source.name.toLowerCase().includes(query.toLowerCase())), [sources, query]);
  const deleteSource = async () => {
    if (!remove) return;
    setBusy(true);
    try { await request(`/sources/${remove.id}`, { method: "DELETE" }); setRemove(null); await refresh(); }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };

  return <>
    <div className="page-intro"><div className="eyebrow">SOURCE COLLECTION</div><h1>Video Library</h1><p>Sumber video original disimpan terpisah dari klip hasil render.</p></div>
    {error && <div className="notice notice-error">{error}<button className="icon-button" onClick={() => setError("")}><X size={14}/></button></div>}
    <div className="library-toolbar"><div className="library-total"><strong>{sources.length}</strong> video tersimpan</div><label className="search-box"><Search size={15}/><input placeholder="Cari video…" value={query} onChange={(event) => setQuery(event.target.value)}/></label></div>
    {rows.length ? <section className="source-list">{rows.map((source) => <article className="source-row-card" key={source.id}><Link href={`/sources/${source.id}`} className="source-thumb"><Video size={23}/><span>{formatDuration(source.duration)}</span></Link><Link href={`/sources/${source.id}`} className="source-row-info"><strong>{source.name}</strong><span>{source.width} × {source.height} · {formatBytes(source.size_bytes)} · {source.clip_count} kandidat</span><small><Clock3 size={12}/>{new Date(source.created_at).toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" })}</small></Link><span className={`source-status ${source.latest_status === "completed" || source.latest_status === "ready_for_review" ? "good" : ""}`}><i/>{source.latest_status?.replaceAll("_", " ") || "Tersimpan"}</span><Link href={`/sources/${source.id}`} className="button button-outline source-open">Buka project <ArrowRight size={14}/></Link><button className="icon-button delete-source" onClick={() => setRemove(source)} aria-label={`Hapus ${source.name}`}><Trash2 size={15}/></button></article>)}</section> : <div className="empty-library panel"><span className="empty-icon"><Video size={21}/></span><h2>{query ? "Video tidak ditemukan" : "Library masih kosong"}</h2><p>{query ? "Coba kata pencarian lain." : "Unggah video MP4/MOV untuk menyimpan sumber pertama."}</p>{!query && <Link href="/create" className="button button-primary">Tambah video <ArrowRight size={15}/></Link>}</div>}
    {remove && <div className="modal-backdrop" role="presentation" onClick={(event) => { if (event.target === event.currentTarget) setRemove(null); }}><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title"><span className="confirm-icon"><Trash2 size={18}/></span><h2 id="confirm-title">Hapus video ini?</h2><p><strong>{remove.name}</strong>, transkrip, kandidat, dan file render terkait akan dihapus. Tindakan ini tidak dapat dibatalkan.</p><div><button className="button button-outline" onClick={() => setRemove(null)} disabled={busy}>Batal</button><button className="button button-danger" onClick={deleteSource} disabled={busy}>{busy ? "Menghapus…" : "Hapus video"}</button></div></section></div>}
  </>;
}

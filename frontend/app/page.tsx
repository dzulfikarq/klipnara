"use client";

import Link from "next/link";
import { ArrowDownRight, ArrowRight, ArrowUpRight, Clock3, Film, FolderOpen, Plus, Scissors, Sparkles, Video } from "lucide-react";
import { useEffect, useState } from "react";
import { API, formatBytes, formatDuration, request } from "@/lib/api";

type Source = { id: string; name: string; duration: number; width: number; height: number; created_at: string; clip_count: number; latest_status: string | null };
type Clip = { id: string; title: string; status: string; source_name: string; start: number; end: number };
type Job = { id: string; status: string; phase: string; message: string; source_name: string };

export default function Dashboard() {
  const [sources, setSources] = useState<Source[]>([]);
  const [clips, setClips] = useState<Clip[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState("");
  const [free, setFree] = useState<number | null>(null);
  useEffect(() => {
    Promise.all([request<Source[]>("/sources"), request<Clip[]>("/clips"), request<Job[]>("/jobs"), request<{ free_bytes: number }>("/settings")])
      .then(([videoRows, clipRows, jobRows, settings]) => { setSources(videoRows); setClips(clipRows); setJobs(jobRows); setFree(settings.free_bytes); })
      .catch((reason) => setError(reason.message));
  }, []);
  const activeJob = jobs.find((job) => ["queued", "preparing", "transcribing", "analyzing", "rendering"].includes(job.status));
  const readyClips = clips.filter((clip) => clip.status === "completed").length;

  return <>
    <section className="welcome-banner"><div className="welcome-copy"><div className="eyebrow light"><Sparkles size={13} /> AI VIDEO CLIPPER &amp; PUBLISHER</div><h1>Dari Video Panjang,<br /><em>Jadi Konten Menarik.</em></h1><p>Temukan highlight, tambahkan subtitle, lalu ekspor klip vertikal — semua diproses lokal.</p><Link href="/create" className="button button-white"><Scissors size={16} /> Buat klip pertama <ArrowRight size={16} /></Link></div><div className="banner-art" aria-hidden="true"><div className="art-glow"/><div className="art-play"><div className="art-frame"><span className="art-spark">✳</span><span className="art-caption">MOMEN<br /><b>TERBAIK.</b></span><span className="art-time">00:24 — 00:57</span></div><span className="play-circle">▶</span></div><div className="art-pill"><Sparkles size={13}/> AI highlight</div></div><div className="banner-orb orb-one"/><div className="banner-orb orb-two"/></section>
    {error && <div className="notice notice-error"><strong>Backend belum terhubung.</strong> {error} <span>Jalankan server backend, lalu muat ulang.</span></div>}
    <div className="section-heading dashboard-heading"><div><div className="eyebrow">OVERVIEW</div><h2>Workspace kamu</h2></div><span className="muted">Semua data tersimpan di perangkat ini</span></div>
    <section className="stats-grid">
      <article className="stat-card"><div className="stat-top"><span>Video sumber</span><FolderOpen size={17}/></div><div className="stat-value">{sources.length}<small> video</small></div><div className="stat-foot"><span className="stat-chip"><Video size={12}/> Library</span><span>Siap dianalisis</span></div></article>
      <article className="stat-card"><div className="stat-top"><span>Kandidat klip</span><Scissors size={17}/></div><div className="stat-value">{clips.length}<small> klip</small></div><div className="stat-foot"><span className="stat-chip mint"><Sparkles size={12}/> AI selected</span><span>{readyClips} sudah dirender</span></div></article>
      <article className="stat-card"><div className="stat-top"><span>Job aktif</span><Clock3 size={17}/></div><div className="stat-value stat-job">{activeJob ? <><i className="pulse-dot"/>{activeJob.phase.replaceAll("_", " ")}</> : "—"}</div><div className="stat-foot"><span className="stat-chip neutral">Concurrency 1</span><span>{activeJob?.source_name || "Tidak ada proses berjalan"}</span></div></article>
    </section>
    <div className="dashboard-lower">
      <section className="panel recent-panel"><div className="panel-heading"><div><div className="eyebrow">LIBRARY</div><h3>Video terbaru</h3></div><Link href="/library" className="text-link">Lihat semua <ArrowUpRight size={14}/></Link></div>
        {sources.length ? <div className="recent-list">{sources.slice(0, 4).map((source) => <Link href={`/sources/${source.id}`} className="recent-row" key={source.id}><div className="video-thumb"><Video size={18}/><span>{formatDuration(source.duration)}</span></div><div className="recent-info"><strong>{source.name}</strong><span>{source.width} × {source.height} · {source.clip_count} kandidat</span></div><span className={`status-tag ${source.latest_status === "completed" || source.latest_status === "ready_for_review" ? "status-ready" : ""}`}>{source.latest_status?.replaceAll("_", " ") || "Tersimpan"}</span><ArrowRight size={15} className="row-arrow"/></Link>)}</div> : <div className="empty-mini"><div className="empty-icon"><Film size={20}/></div><strong>Belum ada video</strong><span>Unggah video MP4/MOV untuk mulai menemukan highlight.</span><Link href="/create" className="text-link">Tambah video <ArrowRight size={14}/></Link></div>}
      </section>
      <section className="panel activity-panel"><div className="panel-heading"><div><div className="eyebrow">PROCESSING</div><h3>Aktivitas terbaru</h3></div><span className="activity-count">{jobs.length}</span></div>
        {jobs.length ? <div className="activity-list">{jobs.slice(0, 4).map((job) => <div key={job.id} className="activity-row"><span className={`activity-icon ${job.status === "failed" ? "failed" : job.status === "completed" ? "done" : "working"}`}>{job.status === "failed" ? <ArrowDownRight size={15}/> : job.status === "completed" ? <Film size={15}/> : <Clock3 size={15}/>}</span><div><strong>{job.message || job.phase}</strong><span>{job.source_name} · {job.status.replaceAll("_", " ")}</span></div></div>)}</div> : <div className="empty-activity"><span className="activity-icon muted-icon"><Clock3 size={15}/></span><p>Belum ada aktivitas.<br/><span>Job baru muncul setelah video diproses.</span></p></div>}
        <div className="storage-box"><div className="storage-icon"><FolderOpen size={15}/></div><div><strong>{free ? `${formatBytes(free)} tersedia` : "Penyimpanan lokal"}</strong><span>Ruang kosong perangkat</span></div><div className="storage-dots"><i/><i/><i/><i/><i/></div></div>
      </section>
    </div>
    <section className="bottom-cta"><span className="cta-icon"><Plus size={18}/></span><div><strong>Punya video yang siap dipotong?</strong><span>Atur jumlah kandidat dan gaya subtitle sebelum mulai.</span></div><Link className="text-link" href="/create">Mulai sekarang <ArrowRight size={14}/></Link></section>
  </>;
}

"use client";

import Link from "next/link";
import { ChangeEvent, useEffect, useMemo, useState } from "react";
import { AudioLines, Check, ChevronLeft, ChevronRight, Download, ExternalLink, Film, Heart, Image, LoaderCircle, Music2, Play, Search, Trash2, Upload, Video, X } from "lucide-react";
import { API, formatBytes, formatDuration, request } from "@/lib/api";

type Tab = "stock" | "video" | "image" | "audio" | "favorites";
type Asset = {
  id: string; kind: "video" | "image" | "audio"; source: string; source_id: string | null; title: string;
  source_url: string | null; preview_url: string | null; creator_name: string | null; creator_url: string | null;
  license_reference: string | null; license_type: string | null; license_notes: string | null; attribution_text: string | null;
  artist: string | null; mood_tags: string[]; favorite: boolean; imported_at: string; last_used_at: string | null;
  duration: number | null; width: number | null; height: number | null; size_bytes: number; mime_type: string;
  url: string; usage_count: number; drafts: { id: string; title: string }[];
};
type PexelsFile = { id: number; quality: "hd" | "sd"; width: number; height: number; fps: number | null; link: string };
type StockVideo = {
  id: string; title: string; duration: number; width: number; height: number; orientation: string;
  page_url: string; preview_url: string | null; creator_name: string | null; creator_url: string | null;
  video_files: PexelsFile[]; favorite?: boolean; imported?: boolean;
  asset_id?: string | null;
};
type ImportJob = { id: string; status: string; phase: string; progress: number | null; bytes_downloaded: number; total_bytes: number | null; message: string; asset?: Asset };
type StockFavorites = { provider_asset_id: string; source_url: string; preview_url: string | null; creator_name: string | null; creator_url: string | null; duration: number; width: number; height: number };
type Storage = { count: number; bytes: number; free_bytes: number; by_kind: Record<string, { count: number; bytes: number }> };

const tabs: { id: Tab; label: string; icon: typeof Video }[] = [
  { id: "stock", label: "Stock Footage", icon: Film },
  { id: "video", label: "My Videos", icon: Video },
  { id: "image", label: "My Images", icon: Image },
  { id: "audio", label: "My Music", icon: Music2 },
  { id: "favorites", label: "Favorites", icon: Heart },
];
const quickSearches = ["Rain", "Sunset", "Beach", "Mountain", "Forest", "Night City", "Flowers", "Sky", "Nature", "Coffee", "Snow", "Romantic", "Calm"];
const moods = ["Mellow", "Piano", "Lofi", "Sad", "Happy", "Romantic", "Cinematic", "Motivational", "Calm", "Upbeat"];
const activeStatuses = new Set(["queued", "downloading", "probing"]);

export default function AssetLibraryPage() {
  const [tab, setTab] = useState<Tab>("stock");
  const [query, setQuery] = useState("");
  const [musicMoodFilter, setMusicMoodFilter] = useState("");
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<Asset[]>([]);
  const [total, setTotal] = useState(0);
  const [stock, setStock] = useState<StockVideo[]>([]);
  const [stockTotal, setStockTotal] = useState(0);
  const [stockFavorites, setStockFavorites] = useState<StockFavorites[]>([]);
  const [stockPage, setStockPage] = useState(1);
  const [orientation, setOrientation] = useState("");
  const [size, setSize] = useState("");
  const [maxDuration, setMaxDuration] = useState("");
  const [minDuration, setMinDuration] = useState("");
  const [selected, setSelected] = useState<StockVideo | null>(null);
  const [selectedFile, setSelectedFile] = useState("");
  const [job, setJob] = useState<ImportJob | null>(null);
  const [storage, setStorage] = useState<Storage | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [remove, setRemove] = useState<Asset | null>(null);
  const [editing, setEditing] = useState<Asset | null>(null);
  const [editMoodTags, setEditMoodTags] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [useProject, setUseProject] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const requested = params.get("tab") as Tab | null;
    if (tabs.some((item) => item.id === requested)) setTab(requested!);
    setUseProject(params.get("project") || "");
  }, []);

  useEffect(() => {
    request<Storage>("/assets/storage").then(setStorage).catch(() => undefined);
  }, [refresh]);

  useEffect(() => {
    if (tab === "stock") return;
    let alive = true;
    setLoading(true);
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ page: String(page), per_page: "40" });
      if (tab !== "favorites") params.set("kind", tab);
      if (tab === "favorites") params.set("favorite", "true");
      if (tab === "audio" && musicMoodFilter) params.set("mood", musicMoodFilter);
      if (query.trim()) params.set("query", query.trim());
      request<{ items: Asset[]; total: number }>(`/assets?${params}`)
        .then((result) => { if (alive) { setItems(result.items); setTotal(result.total); } })
        .catch((reason) => { if (alive) setError(reason.message); })
        .finally(() => { if (alive) setLoading(false); });
    }, query ? 250 : 0);
    return () => { alive = false; clearTimeout(timer); };
  }, [tab, query, musicMoodFilter, page, refresh]);

  useEffect(() => {
    if (tab !== "stock") return;
    const term = query.trim();
    if (!term) { setStock([]); setLoading(false); return; }
    let alive = true;
    setLoading(true);
    setError("");
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ query: term, page: String(stockPage), per_page: "30" });
      if (orientation) params.set("orientation", orientation);
      if (size) params.set("size", size);
      if (maxDuration) params.set("max_duration", maxDuration);
      if (minDuration) params.set("min_duration", minDuration);
      request<{ videos: StockVideo[]; total_results: number }>(`/assets/stock/search?${params}`)
        .then((result) => { if (alive) { setStock(result.videos); setStockTotal(result.total_results); } })
        .catch((reason) => { if (alive) setError(reason.message); })
        .finally(() => { if (alive) setLoading(false); });
    }, 400);
    return () => { alive = false; clearTimeout(timer); };
  }, [tab, query, stockPage, orientation, size, minDuration, maxDuration]);

  useEffect(() => {
    setSelectedFile(selected?.video_files[0] ? String(selected.video_files[0].id) : "");
  }, [selected?.id]);

  useEffect(() => {
    if (tab !== "favorites") return;
    request<StockFavorites[]>("/assets/stock/favorites").then(setStockFavorites).catch(() => setStockFavorites([]));
  }, [tab, refresh]);

  useEffect(() => {
    if (!job || !activeStatuses.has(job.status)) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await request<ImportJob>(`/assets/stock/imports/${job.id}`);
        if (!alive) return;
        setJob(next);
        if (next.status === "ready") {
          setNotice("Video tersimpan di Asset Library dan Source Library. Tidak ada transkrip atau analisis AI yang dijalankan.");
          setRefresh((value) => value + 1);
          setStock((rows) => rows.map((row) => row.id === selected?.id ? { ...row, imported: true } : row));
          return;
        }
        if (activeStatuses.has(next.status)) timer = setTimeout(poll, 700);
      } catch (reason) {
        if (alive) setError((reason as Error).message);
      }
    };
    timer = setTimeout(poll, 500);
    return () => { alive = false; clearTimeout(timer); };
  }, [job?.id, job?.status]);

  const pageCount = Math.max(1, Math.ceil(total / 40));
  const assetTitle = tab === "video" ? "My Videos" : tab === "image" ? "My Images" : tab === "audio" ? "My Music" : "Favorites";
  const currentProjectLink = (assetId: string) => `/mood?${useProject ? `id=${encodeURIComponent(useProject)}&` : ""}asset_id=${encodeURIComponent(assetId)}`;
  const stockHasMore = stockPage * 30 < stockTotal;

  const upload = async (event: ChangeEvent<HTMLInputElement>, kind: "video" | "image" | "audio") => {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const form = new FormData();
      form.append("file", file);
      if (kind === "video") {
        await request("/sources/upload", { method: "POST", body: form });
      } else {
        form.append("kind", kind);
        form.append("title", file.name.replace(/\.[^.]+$/, ""));
        await request("/assets/upload", { method: "POST", body: form });
      }
      setNotice(`${file.name} tersimpan lokal.`);
      setPage(1); setRefresh((value) => value + 1);
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); event.target.value = ""; }
  };

  const toggleLocalFavorite = async (asset: Asset) => {
    try {
      await request(`/assets/${asset.id}`, { method: "PATCH", body: JSON.stringify({ favorite: !asset.favorite }) });
      setRefresh((value) => value + 1);
    } catch (reason) { setError((reason as Error).message); }
  };

  const toggleStockFavorite = async (videoId: string, favorite: boolean) => {
    try {
      if (favorite) await request(`/assets/stock/favorites/${videoId}`, { method: "DELETE" });
      else await request("/assets/stock/favorites", { method: "POST", body: JSON.stringify({ video_id: videoId }) });
      setStock((rows) => rows.map((row) => row.id === videoId ? { ...row, favorite: !favorite } : row));
      setSelected((current) => current?.id === videoId ? { ...current, favorite: !favorite } : current);
      if (tab === "favorites") setRefresh((value) => value + 1);
    } catch (reason) { setError((reason as Error).message); }
  };

  const openFavoritePreview = async (favorite: StockFavorites) => {
    setBusy(true); setError("");
    try { setSelected({ ...await request<StockVideo>(`/assets/stock/videos/${favorite.provider_asset_id}`), favorite: true }); }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };

  const importSelected = async () => {
    if (!selected || !selectedFile) { setError("Pilih kualitas video terlebih dahulu."); return; }
    const file = selected.video_files.find((item) => String(item.id) === selectedFile);
    if (!file) { setError("Kualitas video pilihan tidak tersedia."); return; }
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await request<ImportJob | { asset: Asset; reused: boolean }>("/assets/stock/imports", {
        method: "POST", body: JSON.stringify({ video_id: selected.id, video_file_id: String(file.id), quality: file.quality }),
      });
      if ("asset" in result) {
        setJob({ id: "", status: "ready", phase: "ready", progress: 1, bytes_downloaded: 0, total_bytes: null, message: "Asset sudah tersedia; tidak diunduh ulang.", asset: result.asset });
        setNotice("Asset sudah tersedia secara lokal."); setRefresh((value) => value + 1);
      } else setJob(result);
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };

  const cancelImport = async () => {
    if (!job) return;
    try { await request(`/assets/stock/imports/${job.id}/cancel`, { method: "POST" }); setNotice("Pembatalan diminta; file sementara akan dibersihkan."); }
    catch (reason) { setError((reason as Error).message); }
  };

  const retryImport = async () => {
    if (!job) return;
    try { setJob(await request<ImportJob>(`/assets/stock/imports/${job.id}/retry`, { method: "POST" })); setError(""); }
    catch (reason) { setError((reason as Error).message); }
  };

  const saveMetadata = async () => {
    if (!editing) return;
    const mood_tags = editMoodTags.split(",").map((tag) => tag.trim()).filter(Boolean);
    try {
      await request(`/assets/${editing.id}`, { method: "PATCH", body: JSON.stringify({
        title: editing.title, artist: editing.artist, mood_tags, license_type: editing.license_type,
        license_notes: editing.license_notes, source_url: editing.source_url, attribution_text: editing.attribution_text,
      }) });
       setEditing(null); setRefresh((value) => value + 1); setNotice("Metadata tersimpan; mood tags bukan bukti lisensi.");
    } catch (reason) { setError((reason as Error).message); }
  };

  const deleteAsset = async () => {
    if (!remove) return;
    setBusy(true);
    try { await request(`/assets/${remove.id}`, { method: "DELETE" }); setRemove(null); setRefresh((value) => value + 1); }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };

  const filteredStockFavorites = useMemo(() => stockFavorites.filter((item) => !query || `${item.provider_asset_id} ${item.creator_name || ""}`.toLowerCase().includes(query.toLowerCase())), [stockFavorites, query]);

  return <>
    <div className="page-intro asset-library-intro"><div className="eyebrow">LOCAL-FIRST MEDIA</div><h1>Asset Library</h1><p>Cari footage pilihan, kelola media lokal, dan gunakan ulang tanpa menyalin file per draft.</p></div>
    {error && <div className="notice notice-error">{error}<button className="icon-button" onClick={() => setError("")} aria-label="Tutup pesan"><X size={14}/></button></div>}
    {notice && <div className="notice notice-success">{notice}<button className="icon-button" onClick={() => setNotice("")} aria-label="Tutup pesan"><X size={14}/></button></div>}
    <section className="asset-storage panel">
      <div className="asset-storage-heading"><span className="asset-storage-icon"><Film size={17}/></span><div><strong>Penyimpanan lokal</strong><small>{storage ? `${formatBytes(storage.bytes)} dipakai library · ${formatBytes(storage.free_bytes)} ruang kosong` : "Memuat penggunaan storage…"}</small></div></div>
      <div className="asset-storage-counts">{storage && <><span>{storage.by_kind.video.count} video</span><span>{storage.by_kind.image.count} gambar</span><span>{storage.by_kind.audio.count} audio</span></>}</div>
    </section>
    <div className="asset-tabs" role="tablist" aria-label="Asset library">
      {tabs.map(({ id, label, icon: Icon }) => <button key={id} type="button" role="tab" aria-selected={tab === id} className={tab === id ? "active" : ""} onClick={() => { setTab(id); setPage(1); setError(""); }}><Icon size={15}/>{label}</button>)}
    </div>
    <div className="asset-library-toolbar">
      <div className="asset-results-count"><strong>{tab === "stock" ? stock.length : total}</strong> {tab === "stock" ? "hasil halaman" : "asset"}</div>
      <label className="search-box"><Search size={15}/><input aria-label={tab === "stock" ? "Cari footage Pexels" : `Cari ${assetTitle.toLowerCase()}`} placeholder={tab === "stock" ? "Cari di Pexels…" : `Cari ${assetTitle.toLowerCase()}…`} value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); setStockPage(1); }}/></label>
      {tab !== "stock" && tab !== "favorites" && <label className="asset-upload-control"><Upload size={14}/>{busy ? "Menyimpan…" : `Upload ${tab === "audio" ? "musik" : tab === "image" ? "gambar" : "video"}`}<input type="file" accept={tab === "audio" ? ".mp3,.wav,.m4a,audio/*" : tab === "image" ? ".jpg,.jpeg,.png,.webp,image/*" : ".mp4,.mov,video/mp4,video/quicktime"} disabled={busy} onChange={(event) => void upload(event, tab === "audio" ? "audio" : tab === "image" ? "image" : "video")}/></label>}
      {tab === "audio" && <label className="asset-mood-filter"><span>Mood</span><select value={musicMoodFilter} onChange={(event) => { setMusicMoodFilter(event.target.value); setPage(1); }}><option value="">Semua mood</option>{moods.map((mood) => <option key={mood}>{mood}</option>)}</select></label>}
    </div>

    {tab === "stock" && <>
      <div className="stock-filters">
        <div className="stock-quick-search" role="group" aria-label="Pencarian cepat">{quickSearches.map((word) => <button type="button" key={word} className={query.toLowerCase() === word.toLowerCase() ? "active" : ""} onClick={() => { setQuery(word); setStockPage(1); }}>{word}</button>)}</div>
        <label><span>Orientasi</span><select value={orientation} onChange={(event) => { setOrientation(event.target.value); setStockPage(1); }}><option value="">Semua orientasi</option><option value="portrait">Portrait</option><option value="landscape">Landscape</option><option value="square">Square</option></select></label>
        <label><span>Resolusi minimum</span><select value={size} onChange={(event) => { setSize(event.target.value); setStockPage(1); }}><option value="">Semua</option><option value="small">HD</option><option value="medium">Full HD</option><option value="large">4K</option></select></label>
        <label><span>Durasi minimum</span><select value={minDuration} onChange={(event) => { setMinDuration(event.target.value); setStockPage(1); }}><option value="">Semua</option><option value="5">5 dtk</option><option value="15">15 dtk</option><option value="30">30 dtk</option><option value="60">60 dtk</option></select></label>
        <label><span>Durasi maksimum</span><select value={maxDuration} onChange={(event) => { setMaxDuration(event.target.value); setStockPage(1); }}><option value="">Semua</option><option value="15">15 dtk</option><option value="30">30 dtk</option><option value="60">60 dtk</option><option value="180">3 menit</option></select></label>
      </div>
      <div className="pexels-credit"><a href="https://www.pexels.com" target="_blank" rel="noreferrer">Videos provided by Pexels <ExternalLink size={12}/></a><span>Preview & metadata dari Pexels. Media lokal hanya diunduh setelah dipilih.</span></div>
      {loading && <div className="asset-loading"><LoaderCircle className="spin" size={19}/> Mencari footage…</div>}
      {!loading && !query.trim() && <div className="empty-library panel"><span className="empty-icon"><Film size={21}/></span><h2>Cari stock footage</h2><p>Gunakan keyword atau pencarian cepat. Pexels API key harus dikonfigurasi backend.</p></div>}
      {!loading && query.trim() && stock.length > 0 && <section className="asset-grid">{stock.map((video) => <article className="asset-card stock-card" key={video.id}>
        <button type="button" className="asset-preview" onClick={() => setSelected(video)} aria-label={`Preview ${video.title}`}>
          {video.preview_url ? <img src={video.preview_url} alt="" loading="lazy"/> : <span><Video size={25}/></span>}
          <i className="asset-duration">{formatDuration(video.duration)}</i><b className="asset-preview-play"><Play size={15} fill="currentColor"/></b>
        </button>
        <div className="asset-card-body"><div className="asset-card-title"><strong>{video.title}</strong><button type="button" className={`icon-button ${video.favorite ? "favorite-active" : ""}`} aria-label={video.favorite ? "Hapus favorit" : "Tambah favorit"} onClick={() => void toggleStockFavorite(video.id, Boolean(video.favorite))}><Heart size={15} fill={video.favorite ? "currentColor" : "none"}/></button></div>
          <span>{video.width} × {video.height} · {video.orientation} · {video.creator_name || "Kreator Pexels"}</span>
          <div className="asset-card-actions"><a href={video.page_url} target="_blank" rel="noreferrer">Pexels <ExternalLink size={11}/></a><button type="button" className="button button-outline" onClick={() => setSelected(video)}>{video.imported ? <Check size={13}/> : <Play size={13}/>} {video.imported ? "Tersimpan" : "Preview / Import"}</button></div>
        </div>
      </article>)}</section>}
      {!loading && query.trim() && stock.length === 0 && !error && <div className="empty-library panel"><span className="empty-icon"><Search size={20}/></span><h2>Footage tidak ditemukan</h2><p>Coba kata pencarian lain atau ubah filter.</p></div>}
      {query.trim() && <div className="asset-pagination"><button className="button button-outline" disabled={stockPage <= 1 || loading} onClick={() => setStockPage((value) => value - 1)}><ChevronLeft size={14}/> Sebelumnya</button><span>Halaman {stockPage}</span><button className="button button-outline" disabled={!stockHasMore || loading} onClick={() => setStockPage((value) => value + 1)}>Berikutnya <ChevronRight size={14}/></button></div>}
    </>}

    {tab !== "stock" && <>
      {loading && <div className="asset-loading"><LoaderCircle className="spin" size={19}/> Memuat asset…</div>}
      {!loading && items.length > 0 && <section className="asset-grid">{items.map((asset) => <article className="asset-card" key={asset.id}>
        <div className="asset-preview">
          {asset.preview_url ? <img src={asset.preview_url} alt="" loading="lazy"/> : asset.kind === "image" ? <img src={`${API}${asset.url}`} alt={asset.title} loading="lazy"/> : asset.kind === "audio" ? <span><AudioLines size={27}/></span> : <video controls preload="none" src={`${API}${asset.url}`} aria-label={`Preview ${asset.title}`}/>}
          {asset.duration && <i className="asset-duration">{formatDuration(asset.duration)}</i>}
          <button type="button" className={`asset-fav ${asset.favorite ? "favorite-active" : ""}`} aria-label={asset.favorite ? "Hapus favorit" : "Tambah favorit"} onClick={() => void toggleLocalFavorite(asset)}><Heart size={15} fill={asset.favorite ? "currentColor" : "none"}/></button>
        </div>
        <div className="asset-card-body"><div className="asset-card-title"><strong title={asset.title}>{asset.title}</strong><small className={`asset-provider ${asset.source === "pexels" ? "pexels" : ""}`}>{asset.source === "pexels" ? "Pexels" : "Lokal"}</small></div>
          <span>{asset.artist ? `${asset.artist} · ` : ""}{asset.width && asset.height ? `${asset.width} × ${asset.height} · ` : ""}{formatBytes(asset.size_bytes)}{asset.usage_count ? ` · ${asset.usage_count} draft` : ""}</span>
          {asset.kind === "audio" && <audio controls preload="none" src={`${API}${asset.url}`} aria-label={`Preview ${asset.title}`}/>}
          {asset.kind === "audio" && <small>{asset.mood_tags.length ? `Tags: ${asset.mood_tags.join(", ")}` : "Mood tags belum diatur"} · Lisensi: {asset.license_type || "Belum dicatat"}</small>}
          {asset.source_url && <a className="asset-source-link" href={asset.source_url} target="_blank" rel="noreferrer">Asal & lisensi <ExternalLink size={11}/></a>}
          {asset.creator_name && <small>Oleh {asset.creator_name}{asset.creator_url ? <a href={asset.creator_url} target="_blank" rel="noreferrer"> · Profil</a> : null}</small>}
          <div className="asset-card-actions">
            {asset.kind === "video" && asset.source_id && <Link href={`/sources/${asset.source_id}`}>Buka editor <ChevronRight size={12}/></Link>}
            <button type="button" className="asset-link-button" onClick={() => { setEditing({ ...asset }); setEditMoodTags(asset.mood_tags.join(", ")); }}>Edit metadata</button>
            <Link className="button button-outline" href={currentProjectLink(asset.id)}>Gunakan di Mood</Link>
            <button type="button" className="icon-button delete-source" aria-label={`Hapus ${asset.title}`} onClick={() => setRemove(asset)}><Trash2 size={14}/></button>
          </div>
        </div>
      </article>)}</section>}
      {!loading && items.length === 0 && <div className="empty-library panel"><span className="empty-icon">{tab === "audio" ? <Music2 size={21}/> : tab === "image" ? <Image size={21}/> : <Video size={21}/>}</span><h2>{query ? "Asset tidak ditemukan" : `${assetTitle} kosong`}</h2><p>{query ? "Ubah kata pencarian." : "Upload media untuk menyimpannya sekali dan gunakan ulang di project."}</p>{tab !== "favorites" && <label className="button button-primary asset-empty-upload"><Upload size={14}/> Upload {tab === "audio" ? "musik" : tab === "image" ? "gambar" : "video"}<input type="file" accept={tab === "audio" ? ".mp3,.wav,.m4a,audio/*" : tab === "image" ? ".jpg,.jpeg,.png,.webp,image/*" : ".mp4,.mov,video/mp4,video/quicktime"} onChange={(event) => void upload(event, tab === "audio" ? "audio" : tab === "image" ? "image" : "video")}/></label>}</div>}
      {tab === "favorites" && filteredStockFavorites.length > 0 && <><h2 className="asset-section-title">Favorit Pexels</h2><section className="asset-grid">{filteredStockFavorites.map((favorite) => <article className="asset-card stock-card" key={favorite.provider_asset_id}>
        <button type="button" className="asset-preview" onClick={() => void openFavoritePreview(favorite)}>{favorite.preview_url ? <img src={favorite.preview_url} alt="" loading="lazy"/> : <span><Video size={25}/></span>}<i className="asset-duration">{formatDuration(favorite.duration)}</i><b className="asset-preview-play"><Play size={15} fill="currentColor"/></b></button>
        <div className="asset-card-body"><div className="asset-card-title"><strong>Pexels video {favorite.provider_asset_id}</strong><button className="icon-button favorite-active" onClick={() => void toggleStockFavorite(favorite.provider_asset_id, true)} aria-label="Hapus favorit"><Heart size={15} fill="currentColor"/></button></div><span>{favorite.width} × {favorite.height} · {favorite.creator_name || "Kreator Pexels"}</span><div className="asset-card-actions"><a href={favorite.source_url} target="_blank" rel="noreferrer">Pexels <ExternalLink size={11}/></a><button type="button" className="button button-outline" onClick={() => void openFavoritePreview(favorite)}>Preview / Import</button></div></div>
      </article>)}</section></>}
      {items.length > 0 && pageCount > 1 && <div className="asset-pagination"><button className="button button-outline" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}><ChevronLeft size={14}/> Sebelumnya</button><span>Halaman {page} / {pageCount}</span><button className="button button-outline" disabled={page >= pageCount} onClick={() => setPage((value) => value + 1)}>Berikutnya <ChevronRight size={14}/></button></div>}
    </>}

    {selected && <div className="modal-backdrop" role="presentation" onClick={(event) => { if (event.target === event.currentTarget) setSelected(null); }}><section className="asset-detail-modal" role="dialog" aria-modal="true" aria-labelledby="stock-detail-title">
      <button type="button" className="icon-button asset-modal-close" onClick={() => { setSelected(null); setJob(null); }} aria-label="Tutup"><X size={17}/></button>
      <div className="asset-detail-preview">{selectedFile && selected.video_files.find((file) => String(file.id) === selectedFile) ? <video controls playsInline preload="metadata" src={selected.video_files.find((file) => String(file.id) === selectedFile)?.link}/> : selected.preview_url ? <img src={selected.preview_url} alt="Preview footage"/> : <span><Video size={30}/></span>}</div>
      <div className="asset-detail-content"><div className="eyebrow">PEXELS STOCK VIDEO</div><h2 id="stock-detail-title">{selected.title}</h2><p>{formatDuration(selected.duration)} · {selected.width} × {selected.height} · {selected.orientation}</p>
        <p>Creator: {selected.creator_name || "Tidak tersedia"}{selected.creator_url ? <> · <a href={selected.creator_url} target="_blank" rel="noreferrer">Profil kreator</a></> : null}</p>
        <p><a href={selected.page_url} target="_blank" rel="noreferrer">Lihat halaman Pexels <ExternalLink size={12}/></a> · <a href="https://www.pexels.com/license/" target="_blank" rel="noreferrer">Lisensi Pexels <ExternalLink size={12}/></a></p>
        <label className="field"><span>Kualitas MP4</span><select value={selectedFile} onChange={(event) => setSelectedFile(event.target.value)}><option value="">Pilih resolusi</option>{selected.video_files.map((file) => <option key={file.id} value={file.id}>{file.quality.toUpperCase()} · {file.width} × {file.height}</option>)}</select></label>
        <small className="license-caution">Lisensi tidak menghapus risiko hak atas orang, logo, merek, atau properti pada footage.</small>
        {job && <div className="import-progress"><div className="import-progress-heading"><strong>{job.message}</strong>{activeStatuses.has(job.status) && <button type="button" className="button button-quiet" onClick={() => void cancelImport()}>Batal</button>}</div><div className="progress-track"><i style={{ width: `${Math.round((job.progress ?? 0) * 100)}%` }}/></div><small>{job.progress === null ? `${formatBytes(job.bytes_downloaded)} diunduh` : `${Math.round((job.progress || 0) * 100)}%`}{job.total_bytes ? ` · ${formatBytes(job.bytes_downloaded)} / ${formatBytes(job.total_bytes)}` : ""}</small>{job.status === "failed" || job.status === "cancelled" ? <button type="button" className="button button-outline" onClick={() => void retryImport()}>Coba lagi</button> : null}</div>}
        <div className="asset-detail-actions"><button type="button" className="button button-outline" onClick={() => void toggleStockFavorite(selected.id, Boolean(selected.favorite))}><Heart size={14} fill={selected.favorite ? "currentColor" : "none"}/>{selected.favorite ? "Favorit" : "Favoritkan"}</button>
          {selected.imported || job?.status === "ready" ? <Link href={currentProjectLink(job?.asset?.id || selected.asset_id || "")} className="button button-primary"><Check size={14}/> Gunakan di Mood</Link> : <button type="button" className="button button-primary" disabled={busy || activeStatuses.has(job?.status || "")} onClick={() => void importSelected()}><Download size={14}/>{busy ? "Menyiapkan…" : "Impor ke Klipnara"}</button>}
        </div>
      </div>
    </section></div>}

    {editing && <div className="modal-backdrop" role="presentation" onClick={(event) => { if (event.target === event.currentTarget) setEditing(null); }}><section className="confirm-modal asset-edit-modal" role="dialog" aria-modal="true" aria-labelledby="asset-edit-title"><h2 id="asset-edit-title">Edit metadata {editing.kind === "video" ? "video" : editing.kind === "image" ? "gambar" : "musik"}</h2>
      <label className="field"><span>Judul</span><input value={editing.title} onChange={(event) => setEditing({ ...editing, title: event.target.value })}/></label><label className="field"><span>Artis</span><input value={editing.artist || ""} onChange={(event) => setEditing({ ...editing, artist: event.target.value })}/></label><label className="field"><span>Mood tags · pisahkan koma</span><input value={editMoodTags} onChange={(event) => setEditMoodTags(event.target.value)} placeholder={moods.join(", ")}/></label><label className="field"><span>Jenis lisensi</span><input value={editing.license_type || ""} onChange={(event) => setEditing({ ...editing, license_type: event.target.value })} placeholder="Contoh: YouTube Audio Library terms"/></label><label className="field"><span>Catatan lisensi</span><textarea value={editing.license_notes || ""} onChange={(event) => setEditing({ ...editing, license_notes: event.target.value })}/></label><label className="field"><span>Source URL HTTPS</span><input value={editing.source_url || ""} onChange={(event) => setEditing({ ...editing, source_url: event.target.value })}/></label><label className="field"><span>Teks atribusi</span><input value={editing.attribution_text || ""} onChange={(event) => setEditing({ ...editing, attribution_text: event.target.value })}/></label><small>Mood tags dan upload tidak membuktikan musik bebas copyright. Catat terms yang berlaku.</small><div><button className="button button-outline" onClick={() => setEditing(null)}>Batal</button><button className="button button-primary" onClick={() => void saveMetadata()}>Simpan metadata</button></div>
    </section></div>}

    {remove && <div className="modal-backdrop" role="presentation" onClick={(event) => { if (event.target === event.currentTarget) setRemove(null); }}><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="confirm-asset-title"><span className="confirm-icon"><Trash2 size={18}/></span><h2 id="confirm-asset-title">Hapus asset lokal?</h2><p><strong>{remove.title}</strong>{remove.usage_count ? ` masih dipakai ${remove.usage_count} draft Mood Quotes. Lepas asset dari seluruh draft dulu.` : " akan dihapus dari storage lokal."}{remove.kind === "video" ? " Clip render source ini juga akan dihapus." : ""}</p><div><button className="button button-outline" onClick={() => setRemove(null)} disabled={busy}>Batal</button><button className="button button-danger" onClick={() => void deleteAsset()} disabled={busy || remove.usage_count > 0}>{busy ? "Menghapus…" : "Hapus asset"}</button></div></section></div>}
  </>;
}

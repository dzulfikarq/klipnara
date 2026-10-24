"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, ExternalLink, LoaderCircle, RefreshCw, RotateCcw, ShieldCheck, Youtube } from "lucide-react";
import { formatBytes, formatDuration, request } from "@/lib/api";

type Account = { id: string; channel_id: string; channel_title: string; status: "connected" | "expired" | "error" | "disconnected"; expires_at: number | null; error_message: string | null };
type Publication = {
  id: string; account_id: string; channel_title: string; clip_id: string; clip_title: string;
  status: "pending" | "uploading" | "processing" | "published" | "failed" | "cancelled";
  title: string; description: string; tags: string[]; privacy_status: string; made_for_kids: boolean;
  contains_synthetic_media: boolean; file_size: number; duration: number; width: number; height: number; uploaded_bytes: number; progress: number;
  video_id: string | null; video_url: string | null; attempts: number; upload_started: boolean; reconciliation_required: boolean;
  last_error: string | null; created_at: string; updated_at: string;
};

const accountLabel: Record<Account["status"], string> = { connected: "Connected", expired: "Expired", error: "Error", disconnected: "Disconnected" };
const publicationLabel: Record<Publication["status"], string> = { pending: "Pending", uploading: "Uploading", processing: "Processing", published: "Published", failed: "Failed", cancelled: "Cancelled" };

export default function AccountsPage() {
  const [configured, setConfigured] = useState(false);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [publications, setPublications] = useState<Publication[]>([]);
  const [busy, setBusy] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refresh = useCallback(async () => {
    const [accountData, history] = await Promise.all([
      request<{ configured: boolean; accounts: Account[] }>("/youtube/accounts"),
      request<Publication[]>("/youtube/publications"),
    ]);
    setConfigured(accountData.configured);
    setAccounts(accountData.accounts);
    setPublications(history);
    setError("");
    return history;
  }, []);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const history = await refresh();
        if (alive && history.some((item) => ["pending", "uploading", "processing"].includes(item.status))) {
          timer = setTimeout(poll, 1500);
        }
      } catch (reason) {
        if (alive) {
          setError((reason as Error).message);
          timer = setTimeout(poll, 5000);
        }
      }
    };
    void poll();
    return () => { alive = false; clearTimeout(timer); };
  }, [refresh]);

  useEffect(() => {
    const result = new URLSearchParams(window.location.search).get("youtube");
    if (result) {
      const messages: Record<string, string> = {
        connected: "Channel YouTube berhasil dihubungkan.",
        cancelled: "Koneksi YouTube dibatalkan.",
        state_error: "OAuth state tidak valid atau kedaluwarsa. Coba hubungkan ulang.",
        oauth_error: "Google menolak koneksi OAuth.",
        error: "Channel gagal dihubungkan. Periksa konfigurasi OAuth dan coba lagi.",
      };
      setNotice(messages[result] || messages.error);
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, []);

  const connect = async () => {
    setConnecting(true); setError("");
    try {
      const config = await request<{ configured: boolean; start_url: string | null; redirect_error: string | null }>("/youtube/config");
      if (!config.configured || !config.start_url) throw new Error(config.redirect_error || "Set YouTube OAuth credentials in backend first.");
      window.location.assign(config.start_url);
    } catch (reason) { setError((reason as Error).message); setConnecting(false); }
  };
  const disconnect = async (account: Account) => {
    if (!window.confirm(`Putuskan koneksi ${account.channel_title}?`)) return;
    setBusy(account.id); setError(""); setNotice("");
    try {
      const result = await request<{ remote_revoked: boolean }>(`/youtube/accounts/${account.id}`, { method: "DELETE" });
      setNotice(result.remote_revoked ? `${account.channel_title} disconnected.` : `${account.channel_title} disconnected locally; Google revocation was not confirmed.`);
      await refresh();
    }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(""); }
  };
  const publicationAction = async (item: Publication, action: "retry" | "cancel") => {
    setBusy(item.id); setError(""); setNotice("");
    try {
      const result = await request<Publication>(`/youtube/publications/${item.id}/${action}`, { method: "POST" });
      setNotice(action === "cancel" ? "Upload dibatalkan sebelum mulai." : result.video_id ? "Status video sedang diperiksa; upload tidak diulang." : "Upload masuk antrean retry aman.");
      await refresh();
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(""); }
  };

  return <>
    <div className="page-intro"><div className="eyebrow">YOUTUBE PUBLISHING</div><h1>Connected Accounts</h1><p>Kelola channel YouTube dan lihat riwayat upload.</p></div>
    {error && <div className="notice notice-error"><AlertCircle size={15}/>{error}</div>}
    {notice && <div className="notice notice-success"><CheckCircle2 size={15}/>{notice}</div>}

    <section className="accounts-panel panel">
      <div className="accounts-heading"><div><div className="eyebrow">CHANNELS</div><h2>Connected Accounts</h2></div><button className="button button-primary" onClick={() => void connect()} disabled={!configured || connecting}>{connecting ? <LoaderCircle size={14} className="spin"/> : <Youtube size={15}/>} {accounts.some((item) => ["expired", "error"].includes(item.status)) ? "Hubungkan ulang YouTube" : "Hubungkan YouTube"}</button></div>
      {!configured && <div className="accounts-config-note"><ShieldCheck size={15}/><span>OAuth belum dikonfigurasi. Isi <code>YOUTUBE_CLIENT_ID</code> dan <code>YOUTUBE_CLIENT_SECRET</code> di environment backend, lalu restart backend.</span></div>}
      {accounts.length ? <div className="connected-account-list">{accounts.map((account) => <article className="connected-account" key={account.id}>
        <span className="youtube-account-icon"><Youtube size={19}/></span>
        <div className="connected-account-info"><strong>{account.channel_title}</strong><span>Channel ID · {account.channel_id}</span>{account.error_message && <small>{account.error_message}</small>}</div>
        <span className={`account-status-pill account-${account.status}`}>{accountLabel[account.status]}</span>
        <button className="button button-outline small-button" onClick={() => void disconnect(account)} disabled={busy === account.id || account.status === "disconnected"}>{busy === account.id ? <LoaderCircle size={13} className="spin"/> : "Disconnect"}</button>
      </article>)}</div> : <div className="accounts-empty">Belum ada channel terhubung. OAuth meminta scope minimum <code>youtube.upload</code>; password Google tidak pernah diterima Klipnara.</div>}
    </section>

    <section className="publishing-history-section">
      <div className="publishing-history-heading"><div><div className="eyebrow">UPLOAD HISTORY</div><h2>Publishing History <span>{publications.length}</span></h2></div><button className="icon-button" title="Refresh" onClick={() => void refresh().catch((reason) => setError((reason as Error).message))}><RefreshCw size={14}/></button></div>
      {publications.length ? <div className="publishing-history-list">{publications.map((item) => <article className="publication-card panel" key={item.id}>
        <div className="publication-card-top"><div><span className={`publication-status publication-${item.status}`}>{publicationLabel[item.status]}</span><strong>{item.title}</strong><small>{item.channel_title} · {new Date(item.created_at).toLocaleString()}</small></div><span className="publication-privacy">{item.privacy_status}</span></div>
        <div className="publication-context"><span>Klip: {item.clip_title}</span><span>{formatDuration(item.duration)} · {item.width} × {item.height} · {formatBytes(item.file_size)}</span><span>{item.made_for_kids ? "Made for Kids" : "Not Made for Kids"}</span>{item.contains_synthetic_media && <span>Synthetic disclosure: Yes</span>}</div>
        {(item.status === "uploading" || item.status === "pending") && <div className="publication-progress"><div className="publication-progress-track"><i style={{ width: `${Math.round(item.progress * 100)}%` }}/></div><small>{item.status === "pending" && !item.upload_started ? "Menunggu worker…" : `${formatBytes(item.uploaded_bytes)} / ${formatBytes(item.file_size)} terkirim · ${Math.round(item.progress * 100)}%`}</small></div>}
        {item.status === "processing" && <div className="publication-processing"><LoaderCircle size={14} className="spin"/> YouTube sedang memproses video. Upload tidak akan diulang.</div>}
        {item.last_error && <p className="publication-error">{item.last_error}</p>}
        {item.reconciliation_required && <p className="publication-reconcile">Hasil upload belum pasti. Periksa YouTube Studio sebelum upload baru; retry otomatis diblokir.</p>}
        <div className="publication-actions">
          {item.status === "published" && item.video_url && <a className="button button-primary small-button" href={item.video_url} target="_blank" rel="noreferrer">Lihat di YouTube <ExternalLink size={13}/></a>}
          {item.status === "pending" && !item.upload_started && <button className="button button-outline small-button" onClick={() => void publicationAction(item, "cancel")} disabled={busy === item.id}>Batalkan sebelum upload</button>}
          {item.status === "failed" && !item.reconciliation_required && <button className="button button-outline small-button" onClick={() => void publicationAction(item, "retry")} disabled={busy === item.id}>{busy === item.id ? <LoaderCircle size={13} className="spin"/> : <RotateCcw size={13}/>} {item.video_id ? "Cek status lagi" : "Retry aman"}</button>}
        </div>
      </article>)}</div> : <div className="publishing-empty panel">Belum ada upload. Setujui klip dari Clip Editor, lalu pilih <strong>Posting ke YouTube</strong>.</div>}
    </section>
  </>;
}

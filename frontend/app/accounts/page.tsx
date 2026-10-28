"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, ArrowRight, BookOpen, CalendarDays, Check, CheckCircle2, ChevronDown, Copy, ExternalLink, Film, Info, Instagram, LoaderCircle, RefreshCw, RotateCcw, ShieldCheck, Smartphone, Trash2, X, Youtube } from "lucide-react";
import Link from "next/link";
import { formatBytes, formatDuration, request } from "@/lib/api";
import { youtubeOAuthFeedback } from "@/lib/youtube-oauth.mjs";

type Account = { id: string; channel_id: string; channel_title: string; channel_avatar_url?: string | null; verified_at?: string | null; is_default?: boolean; status: "connected" | "expired" | "error" | "disconnected"; expires_at: number | null; error_message: string | null; analytics_ready?: boolean; upload_ready?: boolean | null; scopes_verified?: boolean };
type OAuthConfig = { configured: boolean; scope: string; start_url: string | null; redirect_uri: string | null; redirect_error: string | null };
type SocialPlatform = { id: "tiktok" | "instagram"; name: string; configured: boolean; oauth_ready: boolean; oauth_start_url: string; redirect_uri: string | null; redirect_error: string | null; scopes: string[]; readiness: string; integration_status: string; authorized_account: boolean; manual_export_available: boolean; reason: string; restrictions: string[]; direct_post_eligible?: boolean | null; local_file_upload?: boolean | null; accounts: Array<{ id: string; display_name: string; username?: string | null; status: string; is_default?: boolean; upload_ready?: boolean; updated_at?: string; granted_scopes: string[]; details: Record<string, string> }> };
type Publication = {
  id: string; account_id: string; channel_title: string; clip_id: string; clip_title: string;
  content_type: "clip" | "mood_render"; remote_status: string | null; publish_at: string | null;
  status: "pending" | "uploading" | "processing" | "published" | "failed" | "cancelled";
  title: string; description: string; tags: string[]; privacy_status: string; made_for_kids: boolean;
  contains_synthetic_media: boolean; file_size: number; duration: number; width: number; height: number; uploaded_bytes: number; progress: number;
  video_id: string | null; video_url: string | null; attempts: number; upload_started: boolean; reconciliation_required: boolean;
  last_error: string | null; created_at: string; updated_at: string;
};
type AccountActionTarget =
  | { platform: "youtube"; id: string; name: string; action: "disconnect" | "delete" }
  | { platform: "tiktok" | "instagram"; id: string; name: string; action: "disconnect" };

const accountLabel: Record<Account["status"], string> = { connected: "Connected", expired: "Expired", error: "Error", disconnected: "Disconnected" };
const publicationLabel: Record<Publication["status"], string> = { pending: "Pending", uploading: "Uploading", processing: "Processing", published: "Published", failed: "Failed", cancelled: "Cancelled" };
const oauthGuideSteps = [
  { title: "Buat Google Cloud Project", summary: "Siapkan project khusus untuk Klipnara.", href: "https://console.cloud.google.com/projectcreate", link: "Buat project" },
  { title: "Aktifkan YouTube Data API v3", summary: "Izinkan project mengakses API YouTube resmi.", href: "https://console.cloud.google.com/apis/library/youtube.googleapis.com", link: "Buka YouTube Data API v3" },
  { title: "Konfigurasi OAuth Consent Screen", summary: "Atur identitas aplikasi, audience testing, dan scope.", href: "https://console.cloud.google.com/auth/branding", link: "Buka Google Auth Platform" },
  { title: "Buat OAuth Client", summary: "Buat client Web application dan daftarkan callback Klipnara.", href: "https://console.cloud.google.com/auth/clients", link: "Buka OAuth Clients" },
  { title: "Simpan Client ID & Client Secret", summary: "Tambahkan placeholder konfigurasi ke environment backend.", href: null, link: null },
  { title: "Hubungkan Channel YouTube", summary: "Jalankan OAuth; channel tampil setelah backend memverifikasi identitasnya.", href: null, link: null },
];

function statusLabel(item: Publication) {
  if (item.status === "failed" || item.status === "cancelled") return publicationLabel[item.status];
  if (item.remote_status === "scheduled") return "Scheduled";
  return publicationLabel[item.status];
}

export default function AccountsPage() {
  const [oauthConfig, setOAuthConfig] = useState<OAuthConfig | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [socialPlatforms, setSocialPlatforms] = useState<SocialPlatform[]>([]);
  const [accountsLoaded, setAccountsLoaded] = useState(false);
  const [publications, setPublications] = useState<Publication[]>([]);
  const [busy, setBusy] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [loading, setLoading] = useState(true);
  const [guideOpen, setGuideOpen] = useState(false);
  const [openGuideStep, setOpenGuideStep] = useState<number | null>(null);
  const [setupGuidePlatform, setSetupGuidePlatform] = useState<SocialPlatform | null>(null);
  const setupGuideDialog = useRef<HTMLDialogElement>(null);
  const [copyNotice, setCopyNotice] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [accountActionTarget, setAccountActionTarget] = useState<AccountActionTarget | null>(null);
  const [oauthFeedback, setOAuthFeedback] = useState<{ kind: "success" | "error" | "info"; className: string; role: "alert" | "status"; message: string; guideStep?: number } | null>(null);

  const refresh = useCallback(async () => {
    const [configData, platformData] = await Promise.all([
      request<OAuthConfig>("/youtube/config"), request<{ platforms: Array<SocialPlatform | { id: "youtube" }> }>("/publishing/platforms"),
    ]);
    setOAuthConfig(configData);
    setSocialPlatforms(platformData.platforms.filter((item): item is SocialPlatform => item.id === "tiktok" || item.id === "instagram"));
    const accountData = await request<{ accounts: Account[] }>("/youtube/accounts");
    setAccounts(accountData.accounts);
    setAccountsLoaded(true);
    const history = await request<Publication[]>("/youtube/publications");
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
        if (alive) setLoading(false);
        const activeUpload = history.some((item) => ["pending", "uploading"].includes(item.status) || item.status === "processing" && item.remote_status !== "scheduled");
        const scheduled = history.some((item) => item.status === "processing" && item.remote_status === "scheduled");
        if (alive && (activeUpload || scheduled)) {
          timer = setTimeout(poll, activeUpload ? 5000 : 60000);
        }
      } catch (reason) {
        if (alive) {
          setLoading(false);
          setError((reason as Error).message);
          timer = setTimeout(poll, 5000);
        }
      }
    };
    void poll();
    return () => { alive = false; clearTimeout(timer); };
  }, [refresh]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const result = params.get("youtube");
    const platformResult = params.has("tiktok") ? "tiktok" : "instagram";
    const socialResult = params.get("tiktok") || params.get("instagram");
    if (result) {
      const feedback = youtubeOAuthFeedback(result);
      setError("");
      setNotice("");
      setOAuthFeedback(feedback);
      if (feedback.kind === "error") {
        setGuideOpen(true);
        setOpenGuideStep(feedback.guideStep ?? 4);
      }
      window.history.replaceState(null, "", window.location.pathname);
    } else if (socialResult) {
      setOAuthFeedback(null);
      setError(socialResult === "connected" ? "" : `${platformResult} connection did not complete (${socialResult}).`);
       setNotice(socialResult === "connected" ? `${platformResult} identity verified. API actions require verified scopes and provider eligibility; manual export remains available.` : "No provider token or authorization code was forwarded to this page.");
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, []);

  useEffect(() => {
    const dialog = setupGuideDialog.current;
    if (!dialog) return;
    if (setupGuidePlatform && !dialog.open) dialog.showModal();
    else if (!setupGuidePlatform && dialog.open) dialog.close();
  }, [setupGuidePlatform]);

  const connectSocial = (platform: SocialPlatform) => {
    setError("");
    if (!platform.oauth_ready || !platform.oauth_start_url) {
      setError(platform.redirect_error || `${platform.name} OAuth credentials/configuration are missing in backend environment.`);
      return;
    }
    window.location.assign(platform.oauth_start_url);
  };

  const disconnectSocial = (platform: SocialPlatform, account: SocialPlatform["accounts"][number]) => {
    setAccountActionTarget({ platform: platform.id, id: account.id, name: account.display_name, action: "disconnect" });
  };

  const deleteDisconnectedAccount = (account: Account) => {
    if (account.status !== "disconnected") return;
    setAccountActionTarget({ platform: "youtube", id: account.id, name: account.channel_title, action: "delete" });
  };

  const confirmAccountAction = async () => {
    if (!accountActionTarget) return;
    const target = accountActionTarget;
    setBusy(target.id); setError(""); setNotice("");
    try {
      if (target.action === "delete") {
        await request(`/youtube/accounts/${target.id}/record`, { method: "DELETE" });
        setNotice(`${target.name} removed from Klipnara.`);
      } else if (target.platform === "youtube") {
        const result = await request<{ remote_revoked: boolean }>(`/youtube/accounts/${target.id}`, { method: "DELETE" });
        setNotice(result.remote_revoked ? `${target.name} disconnected.` : `${target.name} disconnected locally; Google revocation was not confirmed.`);
      } else {
        const result = await request<{ shared_authorization_preserved?: boolean }>(`/platforms/${target.platform}/accounts/${target.id}`, { method: "DELETE" });
        setNotice(`${target.name} disconnected locally.${result.shared_authorization_preserved ? " Shared authorization kept for remaining accounts." : " Provider revocation may need confirmation in provider settings."}`);
      }
      setAccountActionTarget(null);
      await refresh();
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(""); }
  };

  const defaultSocial = async (platform: SocialPlatform, account: SocialPlatform["accounts"][number]) => {
    setBusy(account.id); setError(""); setNotice("");
    try { await request(`/platforms/${platform.id}/accounts/${account.id}/default`, { method: "POST" }); setNotice(`${account.display_name} is default ${platform.name} destination.`); await refresh(); }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(""); }
  };

  const connect = async () => {
    setConnecting(true); setError("");
    try {
      const config = await request<OAuthConfig>("/youtube/config");
      setOAuthConfig(config);
      if (!config.configured) throw new Error("Isi YOUTUBE_CLIENT_ID dan YOUTUBE_CLIENT_SECRET di environment backend, lalu muat ulang backend.");
      if (config.redirect_error || !config.start_url) throw new Error(config.redirect_error || "Callback OAuth belum valid. Periksa YOUTUBE_REDIRECT_URI di environment backend.");
      window.location.assign(config.start_url);
    } catch (reason) { setError((reason as Error).message); setConnecting(false); }
  };

  const enableAnalytics = async (account: Account) => {
    setBusy(account.id); setError("");
    try {
      const config = await request<OAuthConfig>("/youtube/config");
      setOAuthConfig(config);
      if (!config.configured || !config.start_url) throw new Error(config.redirect_error || "Konfigurasi OAuth belum siap.");
      const target = new URL(config.start_url);
      target.searchParams.set("account_id", account.id);
      window.location.assign(target.toString());
    } catch (reason) { setError((reason as Error).message); setBusy(""); }
  };

  const oauthReady = Boolean(oauthConfig?.configured && oauthConfig.start_url && !oauthConfig.redirect_error);
  const showHeaderGuide = !oauthConfig || Boolean(oauthConfig.configured && !oauthConfig.redirect_error && oauthConfig.start_url);
  const callbackUrl = oauthConfig?.redirect_uri && !oauthConfig.redirect_error && oauthConfig.start_url ? oauthConfig.redirect_uri : "";
  const connectReason = !oauthConfig
    ? loading ? "Memuat status OAuth dari backend." : "Status OAuth belum tersedia. Periksa koneksi API, lalu coba lagi."
    : !oauthConfig.configured
      ? "Isi YOUTUBE_CLIENT_ID dan YOUTUBE_CLIENT_SECRET pada environment backend."
      : oauthConfig.redirect_error || (!oauthConfig.start_url ? "Periksa YOUTUBE_REDIRECT_URI pada environment backend." : "");
  const configExample = [
    "YOUTUBE_CLIENT_ID=your-client-id.apps.googleusercontent.com",
    "YOUTUBE_CLIENT_SECRET=your-client-secret",
    ...(callbackUrl ? [`YOUTUBE_REDIRECT_URI=${callbackUrl}`] : []),
  ].join("\n");

  const toggleGuide = () => {
    setGuideOpen((open) => !open);
    if (!guideOpen && openGuideStep === null) setOpenGuideStep(0);
  };
  const copyText = async (value: string, label: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopyNotice(`${label} disalin.`);
    } catch {
      setCopyNotice("Clipboard tidak tersedia. Pilih teks lalu salin manual.");
    }
  };
  const disconnect = async (account: Account) => {
    setAccountActionTarget({ platform: "youtube", id: account.id, name: account.channel_title, action: "disconnect" });
  };
  const defaultYoutube = async (account: Account) => {
    setBusy(account.id); setError(""); setNotice("");
    try { await request(`/youtube/accounts/${account.id}/default`, { method: "POST" }); setNotice(`${account.channel_title} is default YouTube destination.`); await refresh(); }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(""); }
  };
  const verify = async (account: Account) => {
    setBusy(account.id); setError(""); setNotice("");
    try { await request<Account>(`/youtube/accounts/${account.id}/verify`, { method: "POST" }); setNotice(`${account.channel_title} channel identity verified.`); await refresh(); }
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
    <div className="page-intro accounts-intro">
      <div className="accounts-intro-copy"><span className="eyebrow">PUBLISHING DESTINATIONS</span><h1>Connected Accounts</h1><p>Kelola YouTube, TikTok, dan Instagram. Social API publishing tetap bersyarat; manual export selalu tersedia.</p></div>
      <div className="accounts-intro-actions"><div className="accounts-security-badge"><ShieldCheck size={16}/><span>OAuth terenkripsi<small>Token tetap di backend lokal</small></span></div><Link className="button button-primary" href="/publishing"><Youtube size={15}/> Publishing Studio <ArrowRight size={14}/></Link></div>
    </div>
    {error && <div className="notice notice-error"><AlertCircle size={15}/>{error}</div>}
    {notice && <div className="notice notice-success"><CheckCircle2 size={15}/>{notice}</div>}
    {oauthFeedback && <div className={oauthFeedback.className} role={oauthFeedback.role}>
      {oauthFeedback.kind === "error" ? <AlertCircle size={15}/> : oauthFeedback.kind === "success" ? <CheckCircle2 size={15}/> : <Info size={15}/>}
      {oauthFeedback.message}
    </div>}

    <section className="accounts-panel panel">
      <div className="accounts-heading">
        <div className="accounts-heading-copy"><span className="eyebrow">CHANNELS</span><h2>Connected channels <span>{accounts.filter((account) => account.status === "connected").length}</span></h2><p>Hubungkan channel untuk mengunggah Clip dan Mood yang sudah disetujui.</p></div>
        <div className="accounts-heading-actions">
          <button className="button button-primary accounts-connect-button" onClick={() => void connect()} disabled={!oauthReady || connecting} title={connecting ? "OAuth sedang dimulai." : connectReason || "Hubungkan channel lain tanpa mengganti channel yang sudah tersimpan."}>{connecting ? <LoaderCircle size={15} className="spin"/> : <Youtube size={16}/>} + Hubungkan Channel Lain</button>
          {showHeaderGuide && <button className="button button-outline accounts-guide-toggle" onClick={toggleGuide} aria-expanded={guideOpen}><BookOpen size={14}/>{guideOpen ? "Tutup Panduan" : "Lihat Panduan Setup"}</button>}
          {!oauthReady && <small className="accounts-connect-help">{connectReason}</small>}
        </div>
      </div>

      {loading && !oauthConfig && <div className="accounts-empty accounts-loading"><LoaderCircle size={18} className="spin"/><span>Memeriksa konfigurasi OAuth dan channel…</span></div>}
      {oauthConfig && !oauthConfig.configured && <div className="accounts-config-note accounts-oauth-alert" role="status">
        <span className="accounts-config-icon"><ShieldCheck size={17}/></span>
        <div><strong>Konfigurasi OAuth diperlukan</strong><p>Tambahkan Client ID dan Client Secret di environment backend. Klipnara tidak meminta atau menerima password Google.</p><div className="accounts-config-fields"><code>YOUTUBE_CLIENT_ID</code><code>YOUTUBE_CLIENT_SECRET</code></div>{oauthConfig.redirect_error && <small className="accounts-config-error">Callback belum valid: {oauthConfig.redirect_error}</small>}</div>
        <button className="button button-outline accounts-status-refresh" onClick={() => void refresh().catch((reason) => setError((reason as Error).message))}><RefreshCw size={13}/> Cek ulang status</button>
        <button className="button button-outline accounts-guide-toggle" onClick={toggleGuide} aria-expanded={guideOpen}><BookOpen size={14}/>{guideOpen ? "Tutup Panduan" : "Lihat Panduan Setup"}</button>
      </div>}
      {oauthConfig?.configured && (!oauthConfig.start_url || oauthConfig.redirect_error) && <div className="accounts-oauth-error" role="alert"><AlertCircle size={17}/><div><strong>Callback OAuth perlu diperbaiki</strong><p>{oauthConfig.redirect_error || "Backend belum menyediakan URL mulai OAuth yang valid."} Periksa YOUTUBE_REDIRECT_URI; gunakan URL callback aktual dari backend, lalu muat ulang backend.</p></div><button className="button button-outline accounts-guide-toggle" onClick={() => { setGuideOpen(true); setOpenGuideStep(3); }} aria-expanded={guideOpen}><BookOpen size={14}/>Lihat Panduan Setup</button></div>}
      {!loading && !oauthConfig && <div className="accounts-oauth-error" role="alert"><AlertCircle size={17}/><div><strong>Status OAuth belum dapat dibaca</strong><p>Backend belum mengembalikan status konfigurasi. Periksa koneksi API, lalu coba muat ulang; Klipnara belum bisa memastikan apakah OAuth sudah disetel.</p></div><button className="button button-outline" onClick={() => void refresh().catch((reason) => setError((reason as Error).message))}><RefreshCw size={14}/> Coba lagi</button></div>}

      {guideOpen && <section className="accounts-oauth-guide" aria-label="Panduan setup OAuth YouTube">
        <div className="accounts-guide-heading"><div><span className="eyebrow">PANDUAN INTERAKTIF</span><h3>Setup OAuth YouTube</h3><p>Ikuti langkah Google Cloud, lalu simpan konfigurasi hanya di backend. Tidak ada langkah yang ditandai selesai otomatis.</p></div><button className="icon-button" type="button" aria-label="Tutup panduan OAuth" onClick={() => setGuideOpen(false)}><X size={14}/></button></div>
        <div className="accounts-guide-steps">{oauthGuideSteps.map((step, index) => {
          const isOpen = openGuideStep === index;
          return <details className={`accounts-guide-step ${isOpen ? "open" : ""}`} key={step.title} open={isOpen}>
            <summary className="accounts-guide-step-trigger" onClick={(event) => { event.preventDefault(); setOpenGuideStep(isOpen ? null : index); }}><span className="accounts-guide-number">{index + 1}</span><span className="accounts-guide-step-title"><strong>{step.title}</strong><small>{step.summary}</small></span><ChevronDown size={16}/></summary>
            <div className="accounts-guide-step-body">
              {index === 0 && <><p>Buka Google Cloud Console dan buat project baru, misalnya <strong>Klipnara</strong>. Pilih project ini sebelum mengubah API atau OAuth.</p><a className="button button-outline" href={step.href!} target="_blank" rel="noreferrer">{step.link} <ExternalLink size={13}/></a></>}
               {index === 1 && <><p>Pilih project Klipnara, buka API Library, lalu aktifkan <strong>YouTube Data API v3</strong> dan <strong>YouTube Analytics API</strong>. Data API memverifikasi channel dan mengunggah video; Analytics API memasok metrik resmi.</p><div className="accounts-guide-links"><a className="button button-outline" href={step.href!} target="_blank" rel="noreferrer">YouTube Data API v3 <ExternalLink size={13}/></a><a className="button button-outline" href="https://console.cloud.google.com/apis/library/youtubeanalytics.googleapis.com" target="_blank" rel="noreferrer">YouTube Analytics API <ExternalLink size={13}/></a></div></>}
              {index === 2 && <><ol><li>Buka Branding dan isi nama aplikasi <strong>Klipnara</strong>, support email, serta developer email.</li><li>Untuk penggunaan pribadi, pilih audience <strong>External</strong> dan status <strong>Testing</strong>.</li><li>Tambahkan akun Google yang akan digunakan pada bagian <strong>Test users</strong>.</li><li>Di Data Access, gunakan scope yang diminta backend—jangan menambah scope lain tanpa kebutuhan.</li></ol>{oauthConfig?.scope ? <p className="accounts-guide-scope">Scope backend saat ini: <code>{oauthConfig.scope}</code></p> : <p className="accounts-guide-warning">Scope belum dapat dibaca dari backend. Muat ulang status sebelum mengatur Data Access.</p>}<div className="accounts-guide-links"><a className="button button-outline" href={step.href!} target="_blank" rel="noreferrer">Branding <ExternalLink size={13}/></a><a className="button button-outline" href="https://console.cloud.google.com/auth/audience" target="_blank" rel="noreferrer">Audience & Test Users <ExternalLink size={13}/></a><a className="button button-outline" href="https://console.cloud.google.com/auth/scopes" target="_blank" rel="noreferrer">Data Access <ExternalLink size={13}/></a></div></>}
              {index === 3 && <><p>Buka <strong>Google Auth Platform → Clients</strong>, pilih <strong>Create Client</strong>, lalu gunakan tipe <strong>Web application</strong> untuk callback backend Klipnara.</p>{callbackUrl ? <label className="accounts-callback-field"><span>Callback URL Klipnara</span><div><input readOnly aria-label="Callback URL Klipnara" value={callbackUrl} onFocus={(event) => event.currentTarget.select()}/><button className="button button-outline" type="button" onClick={() => void copyText(callbackUrl, "Callback URL")}><Copy size={13}/> Salin URL</button></div></label> : <p className="accounts-guide-warning"><AlertCircle size={14}/> Backend belum memberikan callback URL yang valid. Periksa YOUTUBE_REDIRECT_URI di environment backend dan muat ulang backend; jangan gunakan URL contoh atau menebak port/path.</p>}<p>Tempel URL yang ditampilkan sebagai <strong>Authorized redirect URI</strong>. Nilai harus sama persis.</p><a className="button button-outline" href={step.href!} target="_blank" rel="noreferrer">{step.link} <ExternalLink size={13}/></a></>}
              {index === 4 && <><p>Setelah client dibuat, Google menampilkan Client ID dan Client Secret. Simpan keduanya di <code>backend/.env</code> menggunakan nama variabel source Klipnara di bawah.</p><pre className="accounts-env-example"><code>{configExample}</code></pre><button className="button button-outline" type="button" onClick={() => void copyText(configExample, "Contoh konfigurasi")}><Copy size={13}/> Salin Contoh Konfigurasi</button><p className="accounts-guide-warning"><ShieldCheck size={14}/> Ganti placeholder hanya di environment backend. Jangan masukkan credential ke halaman ini, frontend, screenshot, atau chat. Setelah perubahan, muat ulang backend lalu cek ulang status di halaman ini.</p>{!callbackUrl && <p className="accounts-guide-muted">Callback belum tersedia, jadi contoh tidak menyertakan YOUTUBE_REDIRECT_URI. Jangan isi dengan URL tebakan.</p>}</>}
              {index === 5 && <><p>Setelah backend mendeteksi Client ID dan Client Secret serta callback valid, klik Hubungkan YouTube. Google akan meminta izin; Klipnara tidak meminta password Google.</p><p>Channel baru tampil setelah backend menyelesaikan OAuth dan menerima identitas channel dari YouTube. Kredensial tersedia saja tidak berarti channel sudah terhubung.</p><button className="button button-primary" type="button" onClick={() => void connect()} disabled={!oauthReady || connecting} title={connecting ? "OAuth sedang dimulai." : connectReason || "Mulai koneksi OAuth YouTube."}>{connecting ? <LoaderCircle size={14} className="spin"/> : <Youtube size={14}/>} Hubungkan YouTube</button>{!oauthReady && <small className="accounts-connect-help">{connectReason}</small>}{accounts.some((account) => account.status === "connected") && <Link className="text-link" href="/publishing">Buka Publishing Studio <ArrowRight size={13}/></Link>}</>}
            </div>
          </details>;
        })}</div>
        {copyNotice && <p className="accounts-copy-notice" role="status"><Check size={13}/>{copyNotice}</p>}
      </section>}

      {loading ? <div className="accounts-empty accounts-loading"><LoaderCircle size={18} className="spin"/><span>Memuat akun dan riwayat…</span></div> : !oauthConfig || !accountsLoaded ? <div className="accounts-empty accounts-load-error"><AlertCircle size={18}/><div><strong>Status channel belum tersedia</strong><p>Backend belum mengembalikan daftar akun. Coba muat ulang sebelum menyimpulkan bahwa belum ada channel.</p></div><button className="button button-outline small-button" onClick={() => void refresh().catch((reason) => setError((reason as Error).message))}><RefreshCw size={13}/> Coba lagi</button></div> : accounts.length ? <div className="connected-account-list">{accounts.map((account) => <article className="connected-account" key={account.id}>
        <span className="youtube-account-icon">{account.channel_avatar_url ? <img src={account.channel_avatar_url} alt=""/> : <Youtube size={20}/>}</span>
        <div className="connected-account-info"><strong>{account.channel_title} {account.is_default && <span className="account-default-badge">Default</span>}</strong><span>Channel ID <code>{account.channel_id}</code></span><small className={account.error_message || !account.scopes_verified ? "account-error-message" : ""}>{account.error_message || (!account.scopes_verified ? "Izin lama belum dapat diverifikasi. Hubungkan ulang sebelum Analytics atau upload." : account.analytics_ready ? "Channel verified · Analytics active" : account.verified_at ? "Channel verified · Analytics not enabled" : "Identitas channel belum diverifikasi")}</small></div>
        <span className={`account-status-pill account-${account.status}`}>{accountLabel[account.status]}</span>
        <div className="account-actions">
          {account.status === "connected" && !account.is_default && <button className="button button-outline small-button" onClick={() => void defaultYoutube(account)} disabled={busy === account.id}>Set default</button>}
          {account.status === "connected" && account.scopes_verified && !account.analytics_ready && <button className="button button-outline small-button" onClick={() => void enableAnalytics(account)} disabled={busy === account.id || !oauthReady} title={!oauthReady ? connectReason : "Minta izin YouTube Analytics untuk channel ini tanpa mengubah identitas channel."}>{busy === account.id ? <LoaderCircle size={13} className="spin"/> : <ShieldCheck size={13}/>} Aktifkan Analytics</button>}
          {account.status === "connected" && !account.scopes_verified && <button className="button button-outline small-button" onClick={() => void connect()} disabled={connecting || !oauthReady} title="Hubungkan ulang agar izin aktual dapat diverifikasi.">{connecting ? <LoaderCircle size={13} className="spin"/> : <Youtube size={13}/>} Hubungkan ulang</button>}
          {account.status === "disconnected" ? <button className="button button-outline button-danger small-button" onClick={() => deleteDisconnectedAccount(account)} disabled={busy === account.id} title="Hapus akun disconnect dari Klipnara. Akun dengan riwayat publikasi tidak dapat dihapus.">{busy === account.id ? <LoaderCircle size={13} className="spin"/> : <Trash2 size={13}/>} Delete</button> : <><button className="button button-outline small-button" onClick={() => void verify(account)} disabled={busy === account.id || account.status !== "connected"} title={busy === account.id ? "Tindakan sedang diproses." : account.status !== "connected" ? "Hubungkan ulang akun sebelum memverifikasi channel." : "Verifikasi identitas channel."}>{busy === account.id ? <LoaderCircle size={13} className="spin"/> : <ShieldCheck size={13}/>} Verify</button><button className="button button-outline small-button" onClick={() => void disconnect(account)} disabled={busy === account.id} title={busy === account.id ? "Tindakan sedang diproses." : "Putuskan akun YouTube ini."}>Disconnect</button></>}</div>
      </article>)}</div> : <div className="accounts-empty"><span className="accounts-empty-icon"><Youtube size={22}/></span><div><strong>Belum ada channel terhubung</strong><p>Backend belum memiliki channel OAuth terverifikasi. Klik Hubungkan YouTube setelah konfigurasi siap. Password Google tidak pernah diminta atau disimpan.</p></div></div>}
    </section>

    <section className="accounts-panel panel social-accounts-panel"><div className="accounts-heading"><div className="accounts-heading-copy"><span className="eyebrow">CONDITIONAL PROVIDERS</span><h2>TikTok & Instagram</h2><p>OAuth verifies account identity. OAuth approval alone does not enable media publishing.</p></div></div><div className="social-account-grid">{socialPlatforms.map((platform) => <article className="social-account-card" key={platform.id}>
      <div className="social-account-card-heading"><span className={`social-account-icon social-${platform.id}`}>{platform.id === "tiktok" ? <Smartphone size={19}/> : <Instagram size={19}/>}</span><div><strong>{platform.name}</strong><small>{platform.readiness === "conditional" ? "API method conditionally available" : "Manual export available · API not ready"}</small></div><span className="account-status-pill account-disconnected">{platform.accounts.some((account) => account.status === "connected") ? "Account connected" : "Not connected"}</span></div>
      <p className="social-account-reason">{platform.reason}</p>
       {platform.id === "tiktok" && <p className="social-account-warning">Direct Post stays disabled; Klipnara never requests <code>video.publish</code>. When <code>video.upload</code> is verified, Inbox transfer can be used, but creator must finish post in TikTok. Inbox delivery is not Published.</p>}
       {platform.id === "instagram" && <p className="social-account-warning">API publish requires linked Instagram Professional account, verified permissions, Page authorization, and provider eligibility. Local resumable upload is conditional on Facebook Login for Business; Instagram Login <code>video_url</code> flow is not assumed.</p>}
       <div className="social-account-actions"><button className="button button-outline small-button" onClick={() => connectSocial(platform)} disabled={!platform.oauth_ready || Boolean(busy)} title={!platform.oauth_ready ? platform.redirect_error || "Configure OAuth credentials and callback in backend." : "Connect another account; existing destinations remain saved."}>+ Hubungkan Akun Lain</button><Link className="button button-outline small-button" href="/publishing">Manual export <ArrowRight size={12}/></Link></div>
         {platform.accounts.filter((account) => account.status !== "disconnected").map((account) => <div className="social-connected-account" key={account.id}><span className="social-connected-identity"><i className="social-destination-avatar">{account.details.avatar_url ? <img src={account.details.avatar_url} alt=""/> : platform.id === "tiktok" ? <Smartphone size={15}/> : <Instagram size={15}/>}</i><span><strong>{account.display_name} {account.is_default && <span className="account-default-badge">Default</span>}</strong>{account.username && <small>@{account.username}</small>}<small>{account.status} · {account.upload_ready ? "API scopes verified" : "API scopes/method not ready"}</small><small>{account.granted_scopes.join(", ") || "No scopes verified"}{account.updated_at ? ` · verified ${new Date(account.updated_at).toLocaleDateString()}` : ""}</small></span></span><div className="account-actions">{account.status === "connected" && !account.is_default && <button className="button button-outline small-button" onClick={() => void defaultSocial(platform, account)} disabled={Boolean(busy)}>Set default</button>}<button className="button button-outline small-button" onClick={() => void disconnectSocial(platform, account)} disabled={Boolean(busy)}>{busy === account.id ? "Working…" : "Disconnect"}</button></div></div>)}
      <div className="social-setup-footer"><span>Panduan setup OAuth dan callback</span><button className="button button-outline social-setup-trigger" type="button" onClick={() => setSetupGuidePlatform(platform)} aria-haspopup="dialog" aria-controls="social-guide-modal"><BookOpen size={15}/> Lihat panduan <ArrowRight size={14}/></button></div>
    </article>)}</div></section>

    <dialog id="social-guide-modal" ref={setupGuideDialog} className="social-guide-modal" aria-labelledby="social-guide-title" onClose={() => setSetupGuidePlatform(null)} onClick={(event) => { if (event.target === event.currentTarget) event.currentTarget.close(); }}>
      {setupGuidePlatform && <>
        <header className="social-guide-modal-header"><span className={`social-account-icon social-${setupGuidePlatform.id}`}>{setupGuidePlatform.id === "tiktok" ? <Smartphone size={20}/> : <Instagram size={20}/>}</span><div><span className="eyebrow">PANDUAN SETUP</span><h2 id="social-guide-title">{setupGuidePlatform.name}</h2><p>Callback OAuth, izin yang diperlukan, dan batasan publishing. Tutorial lebih rinci menyusul.</p></div><button className="icon-button" type="button" aria-label="Tutup panduan" onClick={() => setupGuideDialog.current?.close()}><X size={17}/></button></header>
        <div className="social-guide-modal-content">
          <section className="social-guide-callback"><div><ShieldCheck size={17}/><span><strong>Callback backend</strong><small>Daftarkan URL persis seperti nilai dari backend.</small></span></div>{setupGuidePlatform.redirect_uri && !setupGuidePlatform.redirect_error ? <label className="accounts-callback-field"><span>Callback URI</span><input readOnly aria-label={`${setupGuidePlatform.name} callback URI`} value={setupGuidePlatform.redirect_uri} onFocus={(event) => event.currentTarget.select()}/></label> : <p className="accounts-guide-warning">{setupGuidePlatform.redirect_error || "Callback URI belum tersedia. Konfigurasikan backend; jangan menebak URL."}</p>}</section>
          <section className="social-guide-instructions"><h3>Yang perlu disiapkan</h3>{setupGuidePlatform.id === "tiktok" ? <><ol><li>Buat aplikasi TikTok for Developers; tambahkan Login Kit dan Content Posting API.</li><li>Daftarkan callback HTTPS di atas. Klipnara lokal tidak membuat public tunnel.</li><li>Minta scope <code>user.info.basic</code> dan <code>video.upload</code> untuk alur Inbox.</li><li>Tinjau Content Sharing Guidelines. Aplikasi utilitas pribadi/internal dan penyalinan lintas platform belum tentu memenuhi syarat.</li><li>Direct Post perlu persetujuan <code>video.publish</code> dan audit terpisah. Klipnara tidak meminta izin itu atau melewati review.</li></ol><p className="social-guide-env">Nama env backend: <code>TIKTOK_CLIENT_KEY</code>, <code>TIKTOK_CLIENT_SECRET</code>, <code>TIKTOK_REDIRECT_URI</code>.</p><a className="text-link" href="https://developers.tiktok.com/doc/content-posting-api-get-started" target="_blank" rel="noreferrer">Panduan resmi Content Posting <ExternalLink size={14}/></a></> : <><ol><li>Ubah akun Instagram menjadi Professional dan hubungkan ke Facebook Page.</li><li>Buat Meta app dan konfigurasi Facebook Login for Business.</li><li>Ajukan hanya izin publishing dan baca page/account yang disetujui untuk aplikasi.</li><li>Daftarkan callback backend di atas, lalu hubungkan akun dan verifikasi identitas.</li><li>Resumable upload lokal memerlukan Facebook Login for Business. Klipnara tidak membuat public media URL atau tunnel.</li></ol><p className="social-guide-env">Nama env backend: <code>META_APP_ID</code>, <code>META_APP_SECRET</code>, <code>META_LOGIN_CONFIG_ID</code>, <code>META_REDIRECT_URI</code>.</p><a className="text-link" href="https://developers.facebook.com/docs/instagram-platform/content-publishing/resumable-uploads" target="_blank" rel="noreferrer">Panduan resmi resumable upload <ExternalLink size={14}/></a></>}</section>
        </div>
        <footer className="social-guide-modal-footer"><span>Jangan masukkan Client Secret ke halaman ini.</span><button className="button button-outline" type="button" onClick={() => setupGuideDialog.current?.close()}>Tutup</button></footer>
      </>}
    </dialog>

    <section className="publishing-history-section accounts-history-section">
      <div className="publishing-history-heading accounts-history-heading"><div><span className="eyebrow">RIWAYAT UPLOAD</span><h2>Riwayat Publikasi <span>{publications.length}</span></h2><p>Status upload Clip dan Mood, termasuk jadwal native YouTube.</p></div><button className="button button-outline small-button" title="Muat ulang riwayat" onClick={() => void refresh().catch((reason) => setError((reason as Error).message))}><RefreshCw size={14}/> Muat ulang</button></div>
      {publications.length ? <div className="publishing-history-list">{publications.map((item) => <article className="publication-card panel" key={item.id}>
        <div className="publication-card-top"><div className="publication-card-main"><div className="publication-card-title-row"><span className={`publication-status publication-${item.status}`}>{statusLabel(item)}</span><strong title={item.title}>{item.title}</strong></div><small className="publication-card-byline"><span>{item.channel_title}</span><i aria-hidden="true">·</i><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" })}</time></small></div><div className="publication-card-side"><span className="publication-privacy">{item.privacy_status}</span>{item.publish_at && <small className="publication-card-scheduled"><CalendarDays size={12}/> Jadwal · {new Date(item.publish_at).toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" })}</small>}</div></div>
        <div className="publication-context"><span className="publication-context-type"><Film size={13}/>{item.content_type === "mood_render" ? "Mood Quotes" : "Clip"} · {item.clip_title}</span><span>{formatDuration(item.duration)} · {item.width} × {item.height} · {formatBytes(item.file_size)}</span><span><ShieldCheck size={12}/>{item.made_for_kids ? "Made for Kids" : "Not Made for Kids"}</span>{item.contains_synthetic_media && <span><ShieldCheck size={12}/>Synthetic disclosure</span>}</div>
        {(item.status === "uploading" || item.status === "pending") && <div className="publication-progress"><div className="publication-progress-track"><i style={{ width: `${Math.round(item.progress * 100)}%` }}/></div><small>{item.status === "pending" && !item.upload_started ? "Menunggu worker…" : `${formatBytes(item.uploaded_bytes)} / ${formatBytes(item.file_size)} terkirim · ${Math.round(item.progress * 100)}%`}</small></div>}
        {item.status === "processing" && <div className="publication-processing">{item.remote_status === "scheduled" ? "YouTube mengelola jadwal penayangan native." : <><LoaderCircle size={14} className="spin"/> YouTube sedang memproses video. Upload tidak akan diulang.</>}</div>}
        {item.last_error && <p className="publication-error">{item.last_error}</p>}
        {item.reconciliation_required && <p className="publication-reconcile">Hasil upload belum pasti. Periksa YouTube Studio sebelum upload baru; retry otomatis diblokir.</p>}
        <div className="publication-actions">
          {item.status === "published" && item.video_url && <a className="button button-primary small-button" href={item.video_url} target="_blank" rel="noreferrer">Lihat di YouTube <ExternalLink size={13}/></a>}
          {item.status === "pending" && !item.upload_started && <button className="button button-outline small-button" onClick={() => void publicationAction(item, "cancel")} disabled={busy === item.id}>Batalkan sebelum upload</button>}
          {item.status === "failed" && !item.reconciliation_required && <button className="button button-outline small-button" onClick={() => void publicationAction(item, "retry")} disabled={busy === item.id}>{busy === item.id ? <LoaderCircle size={13} className="spin"/> : <RotateCcw size={13}/>} {item.video_id ? "Cek status lagi" : "Retry aman"}</button>}
        </div>
      </article>)}</div> : <div className="publishing-empty accounts-history-empty panel"><span className="accounts-history-icon"><Youtube size={20}/></span><div><strong>Belum ada riwayat upload</strong><p>Setujui output Clip atau Mood, lalu atur publikasi dari Studio.</p></div><Link className="text-link" href="/publishing">Buka Publishing Studio <ArrowRight size={14}/></Link></div>}
    </section>
    {accountActionTarget && <div className="modal-backdrop" onClick={(event) => { if (event.target === event.currentTarget && !busy) setAccountActionTarget(null); }}>
      <section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="account-action-title" aria-describedby="account-action-description">
        <div className="publishing-modal-heading"><div><span className="eyebrow">ACCOUNT MANAGEMENT</span><h2 id="account-action-title">{accountActionTarget.action === "delete" ? `Delete ${accountActionTarget.name}?` : `Disconnect ${accountActionTarget.name}?`}</h2></div><button className="publishing-modal-close" aria-label="Close confirmation" onClick={() => setAccountActionTarget(null)} disabled={Boolean(busy)}><X size={17}/></button></div>
        <div id="account-action-description" className="accounts-config-note">{accountActionTarget.action === "delete" ? <><Trash2 size={16}/><span>This removes the disconnected account from Klipnara. YouTube videos and publishing history stay untouched; accounts with publication history cannot be deleted.</span></> : <><ShieldCheck size={16}/><span>Queued uploads for this destination will be canceled. A transfer already in progress may finish or require provider reconciliation. Publishing history and local media stay untouched; authorization shared by another destination remains active.</span></>}</div>
        {error && <p className="publishing-error" role="alert">{error}</p>}
        <div className="publishing-form-actions"><button className="button button-outline" onClick={() => setAccountActionTarget(null)} disabled={Boolean(busy)}>{accountActionTarget.action === "delete" ? "Keep account" : "Keep connected"}</button><button className="button button-danger" onClick={() => void confirmAccountAction()} disabled={Boolean(busy)}>{busy === accountActionTarget.id ? <LoaderCircle size={14} className="spin"/> : accountActionTarget.action === "delete" ? <Trash2 size={14}/> : <X size={14}/>} {accountActionTarget.action === "delete" ? "Delete account" : "Disconnect account"}</button></div>
      </section>
    </div>}
  </>;
}

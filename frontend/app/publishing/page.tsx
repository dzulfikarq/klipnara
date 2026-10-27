"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, ArrowRight, BarChart3, CalendarDays, CheckCircle2, Clock3, Copy, Download, ExternalLink, FileImage, Film, Instagram, LoaderCircle, RefreshCw, Save, Search, Send, ShieldCheck, Trash2, TrendingUp, Upload, X, Youtube } from "lucide-react";
import { API, formatBytes, formatDuration, request, reviewStatusLabel } from "@/lib/api";

type ContentType = "clip" | "mood_render";
type Privacy = "private" | "unlisted" | "public";
type Metadata = {
  account_id?: string | null; title?: string; description?: string; tags?: string[]; hashtags?: string[];
  privacy_status?: Privacy; publish_at?: string | null; category_id?: string; video_language?: string | null;
  made_for_kids?: boolean | null; contains_synthetic_media?: boolean | null;
};
type Content = {
  content_type: ContentType; content_id: string; title: string; status: string; review_status: string;
  source_name: string | null; project_id: string | null; project_title: string | null; start: number | null; end: number | null;
  file_size: number | null; eligible: boolean; editor_url: string; output_url: string; thumbnail_url: string | null;
  thumbnail_remote_status: string | null; thumbnail_error: string | null; metadata: Metadata;
};
type Account = { id: string; channel_id: string; channel_title: string; status: string; is_default?: boolean; analytics_ready?: boolean; upload_ready?: boolean | null; scopes_verified?: boolean };
type Publication = {
  id: string; content_id: string; content_type: ContentType; account_id: string; channel_title: string; clip_title: string;
  status: string; remote_status: string | null; title: string; privacy_status: Privacy; publish_at: string | null;
  video_id: string | null; video_url: string | null; file_size: number; duration: number; width: number; height: number;
  uploaded_bytes: number; progress: number; made_for_kids: boolean; contains_synthetic_media: boolean;
  upload_started: boolean; reconciliation_required: boolean; last_error: string | null; created_at: string; updated_at: string;
};
type Template = { id: string; name: string; metadata: Metadata };
type PublishingEvent = { id: string; publication_id: string | null; content_id: string; event_type: string; message: string; details: Record<string, unknown>; occurred_at: string };
type PlatformId = "youtube" | "tiktok" | "instagram";
type Platform = { id: PlatformId; name: string; readiness: string; reason: string | null; manual_export_available: boolean; oauth_ready?: boolean; upload_methods?: string[]; accounts: Array<{ id: string; platform_account_id?: string; username?: string | null; display_name?: string; channel_title?: string; status: string; is_default?: boolean; upload_ready?: boolean }> };
type PlatformMetadata = { caption: string; hashtags: string[]; privacy_level?: string; disable_comment?: boolean; disable_duet?: boolean; disable_stitch?: boolean; share_to_feed?: boolean; ai_generated?: boolean | null };
type PlatformJob = { id: string; platform: "tiktok" | "instagram"; content_type: ContentType; content_id: string; status: string; phase?: string; upload_method: string; media_sha256: string; metadata: PlatformMetadata; created_at: string; updated_at?: string; download_url?: string; account_name?: string | null; last_error?: string | null; remote_id?: string | null; upload_started?: boolean; uploaded_bytes?: number; file_size?: number; progress?: number; provider_status?: string | null; events?: Array<{ id: string; event_type: string; message: string; occurred_at: string; details: Record<string, unknown> }> };
type PlatformAction = "manual_export" | "tiktok_inbox" | "instagram_resumable";
type View = "queue" | "calendar" | "history" | "analytics";
type AnalyticsScope = "channel" | "klipnara";
type AnalyticsMetrics = {
  views: number | null; engaged_views: number | null; estimated_minutes_watched: number | null;
  average_view_duration: number | null; average_view_percentage: number | null;
  likes: number | null; comments: number | null; shares: number | null;
  subscribers_gained: number | null; subscribers_lost: number | null; net_subscribers: number | null;
};
type AnalyticsRow = { day?: string; video?: string; elapsedVideoTimeRatio?: number; views?: number | null; engagedViews?: number | null; [key: string]: string | number | null | undefined };
type AnalyticsVideo = AnalyticsRow & {
  video_id: string; publication_id: string | null; title: string | null; content_title: string | null;
  video_url: string; published_date: string | null; attribution: Record<string, unknown> | null; attribution_available: boolean;
};
type AnalyticsDashboard = {
  channel: { id: string; title: string }; scope: AnalyticsScope;
  requested: { start_date: string; end_date: string };
  coverage: { start_date: string | null; end_date: string | null };
  metrics: AnalyticsMetrics; trend: AnalyticsRow[]; videos: AnalyticsVideo[];
  comparison: { previous_period: { start_date: string; end_date: string }; metrics: AnalyticsMetrics | null; changes: Record<string, { absolute: number | null; percent: number | null }> | null };
  insights: { minimum_sample: number; sample_count: number; items: Array<{ kind: string; sample_count: number; timeframe: string; metric?: string; message: string }>; message: string | null } | null;
  last_synced_at: string | null; cached: boolean; errors: Record<string, { code: string; message: string }>;
  channel_video_limit_reached: boolean;
  attribution: { published_video_count: number; reported_video_count: number; limit_reached: boolean };
};
type VideoAnalyticsDetail = { publication_id: string; video_id: string; title: string; content_title: string; video_url: string; published_at: string | null; duration: number; attribution: Record<string, unknown> | null; coverage: { start_date: string | null; end_date: string | null }; metrics: AnalyticsMetrics; trend: AnalyticsRow[] };
type RetentionReport = { duration: number; points: Array<{ ratio: number; timestamp_seconds: number; audience_watch_ratio: number | null; relative_retention_performance: number | null }>; message: string | null };

function dateInputValue(date: Date) {
  return date.toISOString().slice(0, 10);
}

function AnalyticsLineChart({ rows, metric, title, color }: { rows: AnalyticsRow[]; metric: string; title: string; color: string }) {
  const values = rows.map((row) => row[metric]).filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  if (values.length < 2) return <div className="analytics-chart-empty">Belum ada titik data harian untuk grafik ini.</div>;
  const width = 720, height = 190, pad = 18, maximum = Math.max(...values, 1);
  const timestamps = rows.map((row) => row.day ? Date.parse(`${row.day}T00:00:00Z`) : Number.NaN);
  const dated = timestamps.filter(Number.isFinite);
  const firstDate = Math.min(...dated), lastDate = Math.max(...dated);
  const points = rows.flatMap((row, index) => {
    const value = row[metric];
    if (typeof value !== "number" || !Number.isFinite(value)) return [];
    const x = Number.isFinite(timestamps[index]) && firstDate !== lastDate
      ? pad + (timestamps[index] - firstDate) * (width - 2 * pad) / (lastDate - firstDate)
      : pad + index * (width - 2 * pad) / Math.max(1, rows.length - 1);
    const y = height - pad - value / maximum * (height - 2 * pad);
    return [`${x},${y}`];
  });
  return <div className="analytics-chart"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${title} harian`}><title>{title} harian</title><line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} stroke="#dfe8e2"/><polyline points={points.join(" ")} fill="none" stroke={color} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/></svg><div><span>{rows.find((row) => row.day)?.day || ""}</span><strong>{title}</strong><span>{[...rows].reverse().find((row) => row.day)?.day || ""}</span></div></div>;
}

function downloadAnalyticsCsv(data: AnalyticsDashboard) {
  const cell = (value: unknown) => {
    const text = value == null ? "" : String(value);
    const safe = /^[\s]*[=+\-@\t\r]/.test(text) ? `'${text}` : text;
    return `"${safe.replaceAll('"', '""')}"`;
  };
  const headers = ["record_type", "date", "video_id", "title", "views", "engaged_views", "estimated_minutes_watched", "average_view_duration", "average_view_percentage", "likes", "comments", "shares", "subscribers_gained", "subscribers_lost", "net_subscribers", "source_workflow", "subtitle_type"];
  const rows: unknown[][] = [headers];
  rows.push(["summary", `${data.requested.start_date}–${data.requested.end_date}`, "", data.channel.title,
    data.metrics.views, data.metrics.engaged_views, data.metrics.estimated_minutes_watched,
    data.metrics.average_view_duration, data.metrics.average_view_percentage, data.metrics.likes,
    data.metrics.comments, data.metrics.shares, data.metrics.subscribers_gained,
    data.metrics.subscribers_lost, data.metrics.net_subscribers, "", ""]);
  for (const row of data.trend) rows.push(["daily", row.day || "", "", "", row.views, row.engagedViews,
    row.estimatedMinutesWatched, row.averageViewDuration, row.averageViewPercentage, row.likes, row.comments, row.shares,
    row.subscribersGained, row.subscribersLost, "", "", ""]);
  for (const video of data.videos) rows.push(["video", video.published_date || "", video.video_id,
    video.title || video.content_title || "", video.views, video.engagedViews, video.estimatedMinutesWatched,
    video.averageViewDuration, video.averageViewPercentage, video.likes, video.comments, video.shares,
    "", "", "", video.attribution?.source_workflow || "", video.attribution?.subtitle_type || ""]);
  const blob = new Blob([`\uFEFF${rows.map((row) => row.map(cell).join(",")).join("\r\n")}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `klipnara-youtube-${data.scope}-${data.requested.start_date}-${data.requested.end_date}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

function formatMetric(value: number | null | undefined, digits = 0) {
  return typeof value === "number" && Number.isFinite(value)
    ? new Intl.NumberFormat("id-ID", { maximumFractionDigits: digits }).format(value)
    : "—";
}

function metricChange(data: AnalyticsDashboard, key: string) {
  const change = data.comparison.changes?.[key];
  if (change?.absolute == null) return "Perbandingan tidak tersedia";
  const direction = change.absolute > 0 ? "+" : "";
  const percent = change.percent == null ? "· periode sebelumnya 0" : ` (${direction}${formatMetric(change.percent, 1)}%)`;
  return `${direction}${formatMetric(change.absolute, 1)}${percent} vs periode sebelumnya`;
}

const freshMetadata = (title = "", accountId = ""): Metadata => ({
  account_id: accountId,
  title,
  description: "",
  tags: [],
  hashtags: [],
  privacy_status: "private",
  publish_at: null,
  category_id: "22",
  video_language: "",
  made_for_kids: null,
  contains_synthetic_media: null,
});

const freshPlatformMetadata = (platform: "tiktok" | "instagram"): PlatformMetadata => platform === "tiktok"
  ? { caption: "", hashtags: [], privacy_level: "SELF_ONLY", disable_comment: false, disable_duet: false, disable_stitch: false, ai_generated: null }
  : { caption: "", hashtags: [], share_to_feed: true, ai_generated: null };

function localDateValue(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "" : new Date(date.valueOf() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function statusLabel(publication: Publication) {
  if (publication.status === "failed" || publication.status === "cancelled") return publication.status;
  if (publication.remote_status === "scheduled") return "Scheduled";
  if (publication.remote_status === "uploaded") return "Uploaded · processing";
  return publication.status.replaceAll("_", " ");
}

function keepAvailable(current: string[], accounts: Platform["accounts"]) {
  const valid = current.filter((id) => accounts.some((item) => item.id === id && item.upload_ready));
  return valid.length ? valid : accounts.find((item) => item.upload_ready && item.is_default)
    ? [accounts.find((item) => item.upload_ready && item.is_default)!.id] : [];
}

function chooseAvailable(current: string, accounts: Platform["accounts"]) {
  return accounts.some((item) => item.id === current && item.upload_ready) ? current
    : accounts.find((item) => item.upload_ready && item.is_default)?.id || accounts.find((item) => item.upload_ready)?.id || "";
}

export default function PublishingPage() {
  const [content, setContent] = useState<Content[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [publications, setPublications] = useState<Publication[]>([]);
  const [calendar, setCalendar] = useState<Publication[]>([]);
  const [events, setEvents] = useState<PublishingEvent[]>([]);
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [platformJobs, setPlatformJobs] = useState<PlatformJob[]>([]);
  const [platformTargets, setPlatformTargets] = useState<PlatformId[]>(["youtube"]);
  const [metadataTab, setMetadataTab] = useState<PlatformId>("youtube");
  const [platformActions, setPlatformActions] = useState<Record<"tiktok" | "instagram", PlatformAction>>({ tiktok: "manual_export", instagram: "manual_export" });
  const [youtubeAccountIds, setYoutubeAccountIds] = useState<string[]>([]);
  const [activeYoutubeAccountId, setActiveYoutubeAccountId] = useState("");
  const [youtubeMetadataByAccount, setYoutubeMetadataByAccount] = useState<Record<string, Metadata>>({});
  const [platformAccountIds, setPlatformAccountIds] = useState<Record<"tiktok" | "instagram", string[]>>({ tiktok: [], instagram: [] });
  const [activePlatformAccountIds, setActivePlatformAccountIds] = useState<Record<"tiktok" | "instagram", string>>({ tiktok: "", instagram: "" });
  const [platformMetadataByAccount, setPlatformMetadataByAccount] = useState<Record<string, PlatformMetadata>>({});
  const [platformMetadata, setPlatformMetadata] = useState<Record<"tiktok" | "instagram", PlatformMetadata>>({
    tiktok: freshPlatformMetadata("tiktok"), instagram: freshPlatformMetadata("instagram"),
  });
  const [templates, setTemplates] = useState<Template[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [view, setView] = useState<View>("queue");
  const [analyticsScope, setAnalyticsScope] = useState<AnalyticsScope>("channel");
  const [analyticsAccountId, setAnalyticsAccountId] = useState("");
  const [analyticsEnd, setAnalyticsEnd] = useState(() => { const date = new Date(); date.setUTCDate(date.getUTCDate() - 1); return dateInputValue(date); });
  const [analyticsStart, setAnalyticsStart] = useState(() => { const date = new Date(); date.setUTCDate(date.getUTCDate() - 28); return dateInputValue(date); });
  const [analyticsData, setAnalyticsData] = useState<AnalyticsDashboard | null>(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const [analyticsError, setAnalyticsError] = useState("");
  const [analyticsVideoId, setAnalyticsVideoId] = useState("");
  const [videoDetail, setVideoDetail] = useState<VideoAnalyticsDetail | null>(null);
  const [retentionData, setRetentionData] = useState<RetentionReport | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [retentionError, setRetentionError] = useState("");
  const analyticsRequest = useRef(0);
  const detailRequest = useRef(0);
  const [metadata, setMetadata] = useState<Metadata>(freshMetadata());
  const [templateName, setTemplateName] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [checkingBackend, setCheckingBackend] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [copyNotice, setCopyNotice] = useState("");

  const selected = content.find((item) => item.content_id === selectedId) || null;
  const selectedType = selected?.content_type;
  const selectedTitle = selected?.title;
  const publishAccounts = useMemo(() => accounts.filter((item) => item.status === "connected" && item.upload_ready === true), [accounts]);
  const currentMetadata = activeYoutubeAccountId ? youtubeMetadataByAccount[activeYoutubeAccountId] || { ...metadata, account_id: activeYoutubeAccountId } : metadata;
  const currentPlatformMetadata = (platform: "tiktok" | "instagram") => {
    const accountId = activePlatformAccountIds[platform];
    return accountId ? platformMetadataByAccount[`${platform}:${accountId}`] || platformMetadata[platform] : platformMetadata[platform];
  };
  const draftsReady = youtubeAccountIds.every((id) => Object.prototype.hasOwnProperty.call(youtubeMetadataByAccount, id))
    && (["tiktok", "instagram"] as const).every((platform) => platformAccountIds[platform]
      .every((id) => Object.prototype.hasOwnProperty.call(platformMetadataByAccount, `${platform}:${id}`)));
  const analyticsAccounts = useMemo(() => accounts.filter((item) => item.status === "connected" && item.analytics_ready), [accounts]);
  const analyticsMetricCards: Array<[string, number | null, string, number]> = analyticsData ? [
    ["Views", analyticsData.metrics.views, "views", 0],
    ["Engaged Views", analyticsData.metrics.engaged_views, "engaged_views", 0],
    ["Watch time · minutes", analyticsData.metrics.estimated_minutes_watched, "estimated_minutes_watched", 1],
    ["Average view duration", analyticsData.metrics.average_view_duration, "average_view_duration", -1],
    ["Average view percentage", analyticsData.metrics.average_view_percentage, "average_view_percentage", 1],
    ...(analyticsData.scope === "channel" ? [["Net subscribers", analyticsData.metrics.net_subscribers, "net_subscribers", 0] as [string, number | null, string, number]] : []),
  ] : [];
  const selectedHistory = useMemo(() => publications.filter((item) => item.content_id === selected?.content_id && item.content_type === selected?.content_type), [publications, selected?.content_id, selected?.content_type]);
  const backendUnavailable = error.startsWith("Frontend tidak bisa mengakses API di ");

  const refresh = useCallback(async () => {
    const [items, accountData, history, scheduled, savedTemplates, eventData, platformData, platformHistory] = await Promise.all([
      request<Content[]>("/publishing/content"),
      request<{ accounts: Account[] }>("/youtube/accounts"),
      request<Publication[]>("/youtube/publications"),
      request<Publication[]>("/publishing/calendar"),
      request<Template[]>("/publishing/metadata-templates"),
      request<PublishingEvent[]>("/publishing/events"),
      request<{ platforms: Platform[] }>("/publishing/platforms"),
      request<PlatformJob[]>("/platform-publications"),
    ]);
    setContent(items);
    setAccounts(accountData.accounts.filter((item) => item.status === "connected"));
    const readyYoutube = accountData.accounts.filter((item) => item.status === "connected" && item.upload_ready === true);
    setYoutubeAccountIds((current) => {
      const valid = current.filter((id) => readyYoutube.some((item) => item.id === id));
      return valid.length ? valid : readyYoutube.filter((item) => item.is_default).slice(0, 1).map((item) => item.id);
    });
    setActiveYoutubeAccountId((current) => readyYoutube.some((item) => item.id === current)
      ? current : readyYoutube.find((item) => item.is_default)?.id || readyYoutube[0]?.id || "");
    setAnalyticsAccountId((current) => current && accountData.accounts.some((item) => item.id === current && item.status === "connected" && item.analytics_ready)
      ? current : accountData.accounts.find((item) => item.status === "connected" && item.analytics_ready)?.id || "");
    setPublications(history);
    setCalendar(scheduled);
    setTemplates(savedTemplates);
    setEvents(eventData);
    setPlatforms(platformData.platforms);
    setPlatformAccountIds((current) => ({
      tiktok: keepAvailable(current.tiktok, platformData.platforms.find((item) => item.id === "tiktok")?.accounts || []),
      instagram: keepAvailable(current.instagram, platformData.platforms.find((item) => item.id === "instagram")?.accounts || []),
    }));
    setActivePlatformAccountIds((current) => ({
      tiktok: chooseAvailable(current.tiktok, platformData.platforms.find((item) => item.id === "tiktok")?.accounts || []),
      instagram: chooseAvailable(current.instagram, platformData.platforms.find((item) => item.id === "instagram")?.accounts || []),
    }));
    setPlatformActions((current) => ({
      tiktok: platformData.platforms.find((item) => item.id === "tiktok")?.upload_methods?.includes("tiktok_inbox") || current.tiktok === "manual_export" ? current.tiktok : "manual_export",
      instagram: platformData.platforms.find((item) => item.id === "instagram")?.upload_methods?.includes("instagram_resumable") || current.instagram === "manual_export" ? current.instagram : "manual_export",
    }));
    setPlatformJobs(platformHistory);
    if (!selectedId && items.length) {
      const params = new URLSearchParams(window.location.search);
      const requestedId = params.get("content_id");
      const requestedType = params.get("content_type");
      const requested = items.find((item) => item.content_id === requestedId && (!requestedType || item.content_type === requestedType));
      setSelectedId(requested?.content_id || items[0].content_id);
    }
    setError("");
  }, [selectedId]);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try { await refresh(); }
      catch (reason) { if (alive) setError((reason as Error).message); }
      finally { if (alive) setLoading(false); }
    };
    void load();
    return () => { alive = false; };
  }, [refresh]);

  const retryBackend = async () => {
    setCheckingBackend(true);
    try { await refresh(); }
    catch (reason) { setError((reason as Error).message); }
    finally { setCheckingBackend(false); }
  };

  useEffect(() => {
    if (!selectedId || !selectedType) return;
    setYoutubeMetadataByAccount({});
    setPlatformMetadataByAccount({});
    setMetadata(freshMetadata(selectedTitle));
    setPlatformMetadata({ tiktok: freshPlatformMetadata("tiktok"), instagram: freshPlatformMetadata("instagram") });
  }, [selectedId, selectedType, selectedTitle]);

  useEffect(() => {
    if (!selectedId || !selectedType) return;
    let alive = true;
    request<{ metadata: Metadata }>(`/publishing/${selectedType}/${selectedId}/metadata`)
      .then((result) => {
        if (alive) setMetadata({ ...freshMetadata(selectedTitle), ...result.metadata, account_id: undefined });
      })
      .catch((reason) => { if (alive) setError((reason as Error).message); });
    return () => { alive = false; };
  }, [selectedId, selectedType, selectedTitle]);

  useEffect(() => {
    if (!selectedId || !selectedType || !youtubeAccountIds.length) return;
    let alive = true;
    Promise.all(youtubeAccountIds.map(async (accountId) => {
      const query = new URLSearchParams({ account_id: accountId });
      const result = await request<{ metadata: Metadata }>(`/publishing/${selectedType}/${selectedId}/metadata?${query}`);
      return [accountId, { ...freshMetadata(selectedTitle), ...result.metadata, account_id: accountId }] as const;
    })).then((entries) => {
      if (alive) setYoutubeMetadataByAccount((current) => ({ ...current, ...Object.fromEntries(entries) }));
    }).catch((reason) => { if (alive) setError((reason as Error).message); });
    return () => { alive = false; };
  }, [selectedId, selectedType, selectedTitle, youtubeAccountIds]);

  useEffect(() => {
    if (!selectedId || !selectedType) return;
    let alive = true;
    for (const platform of ["tiktok", "instagram"] as const) {
      request<{ metadata: PlatformMetadata }>(`/publishing/${selectedType}/${selectedId}/platform-metadata/${platform}`)
        .then((result) => { if (alive && !platformAccountIds[platform].length) setPlatformMetadata((current) => ({ ...current, [platform]: { ...freshPlatformMetadata(platform), ...result.metadata } })); })
        .catch((reason) => { if (alive) setError((reason as Error).message); });
      Promise.all(platformAccountIds[platform].map(async (accountId) => {
        const query = new URLSearchParams({ account_id: accountId });
        const result = await request<{ metadata: PlatformMetadata }>(`/publishing/${selectedType}/${selectedId}/platform-metadata/${platform}?${query}`);
        return [`${platform}:${accountId}`, { ...freshPlatformMetadata(platform), ...result.metadata }] as const;
      })).then((entries) => {
        if (!alive) return;
        const loaded = Object.fromEntries(entries);
        setPlatformMetadataByAccount((current) => ({ ...current, ...loaded }));
        const activeId = activePlatformAccountIds[platform];
        const activeDraft = activeId ? loaded[`${platform}:${activeId}`] : undefined;
        if (activeDraft) setPlatformMetadata((current) => ({ ...current, [platform]: activeDraft }));
      })
        .catch((reason) => { if (alive) setError((reason as Error).message); });
    }
    return () => { alive = false; };
  }, [selectedId, selectedType, platformAccountIds, activePlatformAccountIds]);

  useEffect(() => {
    const activeUpload = publications.some((item) => ["pending", "uploading"].includes(item.status) || item.status === "processing" && item.remote_status !== "scheduled");
    const scheduled = publications.some((item) => item.status === "processing" && item.remote_status === "scheduled");
    if (!activeUpload && !scheduled) return;
    const timer = setTimeout(() => {
      request<Publication[]>("/youtube/publications").then(setPublications).catch((reason) => setError((reason as Error).message));
      request<Publication[]>("/publishing/calendar").then(setCalendar).catch(() => undefined);
      request<PublishingEvent[]>("/publishing/events").then(setEvents).catch(() => undefined);
    }, activeUpload ? 5000 : 60000);
    return () => clearTimeout(timer);
  }, [publications]);

  useEffect(() => {
    if (!platformJobs.some((job) => ["queued", "uploading", "processing", "awaiting_manual_action"].includes(job.status))) return;
    const interval = platformJobs.some((job) => ["queued", "uploading"].includes(job.status)) ? 5000 : 60000;
    const timer = setTimeout(() => {
      request<PlatformJob[]>("/platform-publications").then(setPlatformJobs).catch((reason) => setError((reason as Error).message));
    }, interval);
    return () => clearTimeout(timer);
  }, [platformJobs]);

  const loadAnalytics = useCallback(async (force = false) => {
    const requestId = ++analyticsRequest.current;
    if (!analyticsAccountId) {
      setAnalyticsData(null);
      setAnalyticsError(analyticsAccounts.length ? "Pilih channel dengan izin Analytics." : "Hubungkan channel, lalu aktifkan Analytics dari Connected Accounts.");
      setAnalyticsLoading(false);
      return;
    }
    const query = new URLSearchParams({ account_id: analyticsAccountId, scope: analyticsScope });
    if (analyticsStart) query.set("start_date", analyticsStart);
    if (analyticsEnd) query.set("end_date", analyticsEnd);
    if (force) query.set("force", "true");
    setAnalyticsLoading(true);
    setAnalyticsError("");
    if (!force) setAnalyticsData(null);
    try {
      const result = await request<AnalyticsDashboard>(`/youtube/analytics?${query}`);
      if (requestId === analyticsRequest.current) setAnalyticsData(result);
    } catch (reason) {
      if (requestId === analyticsRequest.current) setAnalyticsError((reason as Error).message);
    } finally {
      if (requestId === analyticsRequest.current) setAnalyticsLoading(false);
    }
  }, [analyticsAccountId, analyticsAccounts.length, analyticsEnd, analyticsScope, analyticsStart]);

  useEffect(() => {
    if (view !== "analytics") return;
    void loadAnalytics();
    return () => { analyticsRequest.current += 1; };
  }, [view, loadAnalytics]);

  useEffect(() => {
    if (!analyticsVideoId || view !== "analytics") {
      setVideoDetail(null); setRetentionData(null); setDetailError(""); setRetentionError("");
      return;
    }
    const requestId = ++detailRequest.current;
    const query = new URLSearchParams();
    if (analyticsStart) query.set("start_date", analyticsStart);
    if (analyticsEnd) query.set("end_date", analyticsEnd);
    const suffix = query.size ? `?${query}` : "";
    setDetailLoading(true); setDetailError(""); setRetentionError("");
    setVideoDetail(null); setRetentionData(null);
    Promise.allSettled([
      request<VideoAnalyticsDetail>(`/youtube/analytics/publications/${encodeURIComponent(analyticsVideoId)}${suffix}`),
      request<RetentionReport>(`/youtube/analytics/publications/${encodeURIComponent(analyticsVideoId)}/retention${suffix}`),
    ]).then(([detail, retention]) => {
      if (requestId !== detailRequest.current) return;
      if (detail.status === "fulfilled") setVideoDetail(detail.value);
      else setDetailError((detail.reason as Error).message);
      if (retention.status === "fulfilled") setRetentionData(retention.value);
      else setRetentionError((retention.reason as Error).message);
    }).finally(() => {
      if (requestId === detailRequest.current) setDetailLoading(false);
    });
    return () => { detailRequest.current += 1; };
  }, [analyticsEnd, analyticsStart, analyticsVideoId, view]);

  const update = <K extends keyof Metadata,>(key: K, value: Metadata[K]) => {
    if (!activeYoutubeAccountId) {
      setMetadata((current) => ({ ...current, [key]: value }));
      return;
    }
    setYoutubeMetadataByAccount((current) => ({
      ...current,
      [activeYoutubeAccountId]: { ...(current[activeYoutubeAccountId] || { ...metadata, account_id: activeYoutubeAccountId }), [key]: value },
    }));
  };
  const toggleTarget = (platform: PlatformId, enabled: boolean) => {
    setPlatformTargets((current) => enabled ? [...current, platform] : current.filter((item) => item !== platform));
    if (enabled) setMetadataTab(platform);
    else if (metadataTab === platform) {
      const fallback = platformTargets.find((item) => item !== platform);
      if (fallback) setMetadataTab(fallback);
    }
  };
  const updatePlatform = <K extends keyof PlatformMetadata,>(platform: "tiktok" | "instagram", key: K, value: PlatformMetadata[K]) => {
    const accountId = activePlatformAccountIds[platform];
    const visible = currentPlatformMetadata(platform);
    setPlatformMetadata((current) => ({ ...current, [platform]: { ...current[platform], [key]: value } }));
    if (accountId) setPlatformMetadataByAccount((current) => {
      const mapKey = `${platform}:${accountId}`;
      return { ...current, [mapKey]: { ...visible, [key]: value } };
    });
  };
  const toggleYoutubeAccount = (accountId: string, enabled: boolean) => {
    setYoutubeAccountIds((current) => enabled ? [...current, accountId] : current.filter((id) => id !== accountId));
    if (enabled) setActiveYoutubeAccountId(accountId);
    else if (activeYoutubeAccountId === accountId) {
      const next = youtubeAccountIds.find((id) => id !== accountId);
      setActiveYoutubeAccountId(next || "");
    }
  };
  const togglePlatformAccount = (platform: "tiktok" | "instagram", accountId: string, enabled: boolean) => {
    const nextActive = enabled ? accountId : activePlatformAccountIds[platform] === accountId
      ? platformAccountIds[platform].find((id) => id !== accountId) || "" : activePlatformAccountIds[platform];
    setPlatformAccountIds((current) => ({
      ...current, [platform]: enabled ? [...current[platform], accountId] : current[platform].filter((id) => id !== accountId),
    }));
    setActivePlatformAccountIds((current) => ({ ...current, [platform]: nextActive }));
    const nextDraft = nextActive ? platformMetadataByAccount[`${platform}:${nextActive}`] : undefined;
    setPlatformMetadata((current) => ({ ...current, [platform]: nextDraft || freshPlatformMetadata(platform) }));
  };
  const selectPlatformMetadataAccount = (platform: "tiktok" | "instagram", accountId: string) => {
    setActivePlatformAccountIds((current) => ({ ...current, [platform]: accountId }));
    const saved = platformMetadataByAccount[`${platform}:${accountId}`];
    setPlatformMetadata((current) => ({ ...current, [platform]: saved || freshPlatformMetadata(platform) }));
  };
  const selectedPath = selected ? `/publishing/${selected.content_type}/${selected.content_id}` : "";

  const saveDraft = async () => {
    if (!selected) return false;
    setBusy("save"); setError(""); setNotice("");
    try {
      const saved = await Promise.allSettled([
        request(`${selectedPath}/metadata`, { method: "PUT", body: JSON.stringify(metadata) }),
        ...youtubeAccountIds.map((accountId) => request(`${selectedPath}/metadata?account_id=${encodeURIComponent(accountId)}`, {
          method: "PUT", body: JSON.stringify(youtubeMetadataByAccount[accountId] || { ...metadata, account_id: accountId }),
        })),
        ...(["tiktok", "instagram"] as const).flatMap((platform) => platformAccountIds[platform].length
          ? platformAccountIds[platform].map((accountId) => request(`${selectedPath}/platform-metadata/${platform}?account_id=${encodeURIComponent(accountId)}`, {
            method: "PUT", body: JSON.stringify(platformMetadataByAccount[`${platform}:${accountId}`] || platformMetadata[platform]),
          }))
          : [request(`${selectedPath}/platform-metadata/${platform}`, {
            method: "PUT", body: JSON.stringify(platformMetadata[platform]),
          })]),
      ]);
      const failed = saved.filter((item) => item.status === "rejected");
      if (failed.length) throw new Error((failed[0] as PromiseRejectedResult).reason?.message || "Some platform drafts could not be saved.");
      setNotice("Shared drafts and selected account overrides saved locally.");
      await refresh();
      return true;
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(""); }
    return false;
  };

  const submitUpload = async () => {
    if (!selected || !platformTargets.length || !confirmed || !rightsConfirmed) { setError("Choose destinations and confirm review plus platform rights before continuing."); return; }
    setBusy("publish"); setError(""); setNotice("");
    try {
      const publishAt = metadata.publish_at ? new Date(metadata.publish_at).toISOString() : null;
      const common = {
        ...metadata,
        title: metadata.title || "",
        description: metadata.description || "",
        tags: metadata.tags || [],
        hashtags: metadata.hashtags || [],
        privacy_status: metadata.privacy_status || "private",
        publish_at: publishAt,
        category_id: metadata.category_id || "22",
        video_language: metadata.video_language || null,
        made_for_kids: metadata.made_for_kids,
        contains_synthetic_media: metadata.contains_synthetic_media,
      };
      const body = {
        ...common,
        account_ids: youtubeAccountIds,
        metadata_by_account: Object.fromEntries(youtubeAccountIds.map((accountId) => {
          const draft = youtubeMetadataByAccount[accountId] || (accountId === activeYoutubeAccountId ? currentMetadata : { ...metadata, account_id: accountId });
          return [accountId, { ...draft, publish_at: draft.publish_at ? new Date(draft.publish_at).toISOString() : null }];
        })),
        confirmed: true,
        rights_confirmed: true,
      };
      const actions: Array<[PlatformId, Promise<unknown>]> = [];
      if (platformTargets.includes("youtube")) actions.push(["youtube", (async () => {
        if (!youtubeAccountIds.length || youtubeAccountIds.some((id) => {
          const draft = youtubeMetadataByAccount[id] || (id === activeYoutubeAccountId ? currentMetadata : metadata);
          return draft.made_for_kids == null || draft.contains_synthetic_media == null;
        })) throw new Error("Choose at least one YouTube channel and complete both required declarations for every channel.");
        return request(`${selectedPath}/youtube`, { method: "POST", body: JSON.stringify(body) });
      })()]);
      for (const platform of ["tiktok", "instagram"] as const) {
        if (platformTargets.includes(platform)) {
          const uploadMethod = platformActions[platform];
          if (uploadMethod === "manual_export") {
            actions.push([platform, request(`${selectedPath}/platforms/${platform}/manual-export`, {
              method: "POST", body: JSON.stringify({ confirmed: true, rights_confirmed: true, metadata: currentPlatformMetadata(platform) }),
            })]);
          } else if (platformAccountIds[platform].length) {
            actions.push([platform, request(`${selectedPath}/platforms/${platform}/upload`, {
              method: "POST", body: JSON.stringify({
                account_ids: platformAccountIds[platform], confirmed: true, rights_confirmed: true,
                metadata_by_account: Object.fromEntries(platformAccountIds[platform].map((accountId) => [accountId, platformMetadataByAccount[`${platform}:${accountId}`] || currentPlatformMetadata(platform)])),
              }),
            })]);
          } else {
            actions.push([platform, Promise.reject(new Error(`Select authorized ${platform} account or choose manual export.`))]);
          }
        }
      }
      const results = await Promise.all(actions.map(async ([platform, promise]) => ({ platform, result: await Promise.allSettled([promise]).then(([item]) => item) })));
      const succeeded = results.filter((item) => item.result.status === "fulfilled").map((item) => item.platform);
      const failed = results.flatMap((item) => {
        if (item.result.status === "rejected") return [`${item.platform}: ${(item.result as PromiseRejectedResult).reason?.message || "failed"}`];
        const value = (item.result as PromiseFulfilledResult<unknown>).value as { destinations?: Array<{ status: string; account_id: string; error?: { message?: string } }> };
        return (value?.destinations || []).filter((destination) => destination.status === "failed")
          .map((destination) => `${item.platform} ${destination.account_id}: ${destination.error?.message || "failed"}`);
      });
      setConfirmOpen(false); setConfirmed(false); setRightsConfirmed(false); setView("history");
      await refresh();
      if (succeeded.length) setNotice(`Completed independently: ${succeeded.map((item) => item === "youtube" ? "YouTube queued" : platformActions[item] === "manual_export" ? `${item} manual export prepared` : item === "tiktok" ? "TikTok Inbox transfer queued · not Published" : "Instagram Reels API publish queued · provider confirmation pending").join("; ")}.`);
      if (failed.length) setError(failed.join(" · "));
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(""); }
  };

  const applySharedCaption = () => {
    const caption = currentMetadata.description || "";
    for (const platform of ["tiktok", "instagram"] as const) {
      if (!platformTargets.includes(platform)) continue;
      const ids = platformAccountIds[platform];
      setPlatformMetadata((current) => ({ ...current, [platform]: { ...current[platform], caption } }));
      if (ids.length) setPlatformMetadataByAccount((current) => {
        const next = { ...current };
        for (const id of ids) {
          const key = `${platform}:${id}`;
          next[key] = { ...(current[key] || platformMetadata[platform]), caption };
        }
        return next;
      });
    }
  };

  const copyPlatformCaption = async (platform: "tiktok" | "instagram") => {
    const draft = currentPlatformMetadata(platform);
    const caption = [draft.caption.trim(), (draft.hashtags || []).map((tag) => `#${tag.replace(/^#/, "")}`).join(" ")].filter(Boolean).join("\n\n");
    try { await navigator.clipboard.writeText(caption); setCopyNotice(`${platform} caption copied.`); }
    catch { setCopyNotice("Clipboard unavailable. Select and copy caption manually."); }
  };

  const saveTemplate = async () => {
    if (!templateName.trim()) { setError("Enter template name."); return; }
    setBusy("template"); setError("");
    try {
      const item = await request<Template>("/publishing/metadata-templates", {
        method: "POST", body: JSON.stringify({ name: templateName.trim(), metadata: { ...currentMetadata, account_id: undefined, publish_at: null } }),
      });
      setTemplates((current) => [...current.filter((row) => row.id !== item.id), item]);
      setTemplateName(""); setNotice("Metadata template saved.");
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(""); }
  };

  const uploadThumbnail = async (file?: File) => {
    if (!selected || !file) return;
    setBusy("thumbnail"); setError(""); setNotice("");
    try {
      const form = new FormData(); form.append("file", file);
      await request(`${selectedPath}/thumbnail`, { method: "POST", body: form });
      setNotice("Thumbnail saved locally. Apply it to a YouTube video from History.");
      await refresh();
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(""); }
  };

  const applyThumbnail = async (publication: Publication) => {
    setBusy(publication.id); setError(""); setNotice("");
    try {
      await request(`/youtube/publications/${publication.id}/thumbnail`, { method: "POST" });
      setNotice("YouTube confirmed thumbnail update.");
      await refresh();
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(""); }
  };

  const reconcilePlatformJob = async (job: PlatformJob) => {
    setBusy(job.id); setError(""); setNotice("");
    try {
      const result = await request<PlatformJob>(`/platform-publications/${job.id}/reconcile`, { method: "POST" });
      setNotice(result.status === "published" ? `${job.platform} provider confirmed Published.` : `Provider status checked: ${result.status.replaceAll("_", " ")}${result.provider_status ? ` · ${result.provider_status}` : ""}.`);
      await refresh();
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(""); }
  };

  const retryPlatformJob = async (job: PlatformJob) => {
    if (!window.confirm(`Retry ${job.platform} transfer? Confirm current media rights and review this platform's status first.`)) return;
    const abandonIncompleteInstagram = job.platform === "instagram" && job.status === "needs_reconciliation"
      && job.phase === "processing_timeout" && job.provider_status === "IN_PROGRESS";
    const duplicateRisk = Boolean(job.upload_started && !job.remote_id) || abandonIncompleteInstagram;
    if (duplicateRisk && !window.confirm(abandonIncompleteInstagram
      ? "Instagram still reports this container in progress. This abandons that incomplete container and creates a new one; check Instagram first. Continue?"
      : "Provider may have accepted prior request without returning an operation ID. Retry can create duplicate content. Continue?")) return;
    setBusy(job.id); setError(""); setNotice("");
    try {
      await request(`/platform-publications/${job.id}/retry`, {
        method: "POST",
        body: JSON.stringify({ confirmed: true, rights_confirmed: true, duplicate_risk_confirmed: duplicateRisk }),
      });
      setNotice(`${job.platform} retry queued. Provider confirmation remains required.`);
      await refresh();
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(""); }
  };

  const cancelPlatformJob = async (job: PlatformJob) => {
    if (!window.confirm(`Cancel ${job.platform} transfer? If provider already received bytes, status must be reconciled.`)) return;
    setBusy(job.id); setError(""); setNotice("");
    try {
      await request(`/platform-publications/${job.id}/cancel`, { method: "POST" });
      setNotice("Cancellation accepted. Transfer with provider activity may require reconciliation.");
      await refresh();
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(""); }
  };

  const deleteTemplate = async (id: string) => {
    setBusy(id); setError("");
    try { await request(`/publishing/metadata-templates/${id}`, { method: "DELETE" }); setTemplates((items) => items.filter((item) => item.id !== id)); }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(""); }
  };

  const startConfirmation = async () => {
    setError("");
    if (!platformTargets.length) { setError("Select at least one target platform."); return; }
    if (!draftsReady) { setError("Wait for selected account metadata to finish loading."); return; }
    if (platformTargets.includes("youtube") && !youtubeAccountIds.length) { setError("Select at least one YouTube channel."); return; }
    if (platformActions.tiktok === "tiktok_inbox" && platformTargets.includes("tiktok") && !platformAccountIds.tiktok.length) { setError("Select at least one eligible TikTok account."); return; }
    if (platformActions.instagram === "instagram_resumable" && platformTargets.includes("instagram") && !platformAccountIds.instagram.length) { setError("Select at least one eligible Instagram account."); return; }
    if (await saveDraft()) {
      setConfirmed(false); setRightsConfirmed(false); setConfirmOpen(true);
    }
  };

  const updateSchedule = (value: string) => {
    if (!value) { update("publish_at", null); return; }
    const timestamp = new Date(value);
    if (!Number.isNaN(timestamp.valueOf())) {
      update("publish_at", timestamp.toISOString());
      update("privacy_status", "private");
    }
  };

  return <>
    <div className="page-intro publishing-intro"><div><div className="eyebrow">MULTI-PLATFORM PREPARATION · YOUTUBE ANALYTICS</div><h1>Publishing Studio</h1><p>Review approved output, then choose independent YouTube, conditional TikTok Inbox, Instagram Reels, or manual-export actions.</p></div><div className="publishing-hero-mark"><Youtube size={24}/><Instagram size={19}/><span>Independent platform actions</span><small>Provider-confirmed status only</small></div></div>
    {loading ? <div className="publishing-loading panel"><LoaderCircle size={18} className="spin"/><span>Connecting to local backend…</span></div> : backendUnavailable ? <section className="publishing-connection panel" role="alert"><div className="publishing-connection-icon"><AlertCircle size={21}/></div><div className="publishing-connection-copy"><span className="eyebrow">CONNECTION ISSUE</span><h2>Frontend gagal mengakses API</h2><p>{error}</p><div className="publishing-connection-steps"><span>1. Restart FastAPI agar aturan CORS terbaru aktif:</span><code>npm run dev:backend</code><span>2. CORS menerima frontend loopback di port dev mana pun. Health API: <code>{API}/api/health</code>.</span></div><div className="publishing-connection-actions"><button className="button button-primary" onClick={() => void retryBackend()} disabled={checkingBackend}>{checkingBackend ? <LoaderCircle size={14} className="spin"/> : <RefreshCw size={14}/>} Coba lagi</button><a className="button button-outline" href={`${API}/api/health`} target="_blank" rel="noreferrer">Tes koneksi <ExternalLink size={13}/></a></div></div></section> : <>
    {error && <div className="notice notice-error"><AlertCircle size={15}/>{error}</div>}
    {notice && <div className="notice notice-success"><CheckCircle2 size={15}/>{notice}</div>}
    <div className="publishing-tabs" role="tablist" aria-label="Publishing views">
      <button role="tab" aria-selected={view === "queue"} className={view === "queue" ? "selected" : ""} onClick={() => setView("queue")}><Send size={15}/> Queue & metadata</button>
      <button role="tab" aria-selected={view === "calendar"} className={view === "calendar" ? "selected" : ""} onClick={() => setView("calendar")}><CalendarDays size={15}/> Calendar <span>{calendar.length}</span></button>
      <button role="tab" aria-selected={view === "history"} className={view === "history" ? "selected" : ""} onClick={() => setView("history")}><Clock3 size={15}/> History <span>{publications.length + platformJobs.length}</span></button>
      <button role="tab" aria-selected={view === "analytics"} className={view === "analytics" ? "selected" : ""} onClick={() => setView("analytics")}><BarChart3 size={15}/> Analytics</button>
    </div>

    {view === "analytics" && <section className="publishing-analytics panel">
      <div className="analytics-heading"><div><span className="eyebrow">OFFICIAL YOUTUBE ANALYTICS API</span><h2>Channel performance</h2><p>Views and Engaged Views stay separate. Klipnara totals include only published videos linked to immutable local publishing records.</p></div><div className="analytics-actions"><button className="button button-outline small-button" onClick={() => void loadAnalytics(true)} disabled={analyticsLoading || !analyticsAccountId} title="Request fresh report from YouTube; cache remains available after errors.">{analyticsLoading ? <LoaderCircle size={13} className="spin"/> : <RefreshCw size={13}/>} Sync now</button><button className="button button-outline small-button" onClick={() => analyticsData && downloadAnalyticsCsv(analyticsData)} disabled={!analyticsData}><Download size={13}/> Export CSV</button></div></div>
      <div className="analytics-toolbar">
        <label className="field"><span>Verified channel</span><select value={analyticsAccountId} onChange={(event) => { setAnalyticsAccountId(event.target.value); setAnalyticsVideoId(""); }}><option value="">Choose Analytics-enabled channel</option>{analyticsAccounts.map((item) => <option key={item.id} value={item.id}>{item.channel_title}</option>)}</select></label>
        <div className="analytics-scope-switch" role="group" aria-label="Analytics scope"><button className={analyticsScope === "channel" ? "selected" : ""} aria-pressed={analyticsScope === "channel"} onClick={() => { setAnalyticsScope("channel"); setAnalyticsVideoId(""); }}>Channel</button><button className={analyticsScope === "klipnara" ? "selected" : ""} aria-pressed={analyticsScope === "klipnara"} onClick={() => { setAnalyticsScope("klipnara"); setAnalyticsVideoId(""); }}>Klipnara</button></div>
        <label className="field"><span>From</span><input type="date" value={analyticsStart} max={analyticsEnd} onChange={(event) => setAnalyticsStart(event.target.value)}/></label>
        <label className="field"><span>Through · complete days</span><input type="date" value={analyticsEnd} max={dateInputValue(new Date(Date.now() - 86400000))} onChange={(event) => setAnalyticsEnd(event.target.value)}/></label>
      </div>
      {analyticsAccounts.length === 0 && <div className="analytics-empty-state"><ShieldCheck size={20}/><div><strong>Analytics consent required</strong><p>Connected channel remains separate from Analytics access. Grant official read-only Analytics scope first.</p></div><Link className="button button-outline small-button" href="/accounts">Open Connected Accounts <ArrowRight size={13}/></Link></div>}
      {analyticsError && <div className="notice notice-error" role="alert"><AlertCircle size={15}/><span>{analyticsError}</span>{analyticsData && <small>Showing last successful response.</small>}</div>}
      {analyticsLoading && !analyticsData && <div className="publishing-loading"><LoaderCircle size={17} className="spin"/> Fetching cached or current YouTube report…</div>}
      {analyticsData && <>
        <div className="analytics-report-meta"><span><strong>{analyticsData.scope === "channel" ? "Channel totals" : "Klipnara-attributed totals"}</strong> · {analyticsData.channel.title}</span><span>{analyticsData.coverage.start_date ? `Data coverage ${analyticsData.coverage.start_date} – ${analyticsData.coverage.end_date}` : "No report rows for selected range"}</span><span>{analyticsData.cached ? "Cached response" : "Fresh response"}{analyticsData.last_synced_at ? ` · synced ${new Date(analyticsData.last_synced_at).toLocaleString()}` : ""}</span></div>
        {analyticsData.scope === "channel" && <p className="analytics-scope-note"><Search size={13}/> Channel scope includes channel-wide YouTube results, not only Klipnara uploads. Use Klipnara scope to isolate videos with matching publication records.</p>}
        {analyticsData.scope === "klipnara" && <p className="analytics-scope-note"><ShieldCheck size={13}/> Attributed videos {analyticsData.attribution.reported_video_count} of {analyticsData.attribution.published_video_count} linked publications. Metrics come from YouTube, never upload estimates.{analyticsData.attribution.limit_reached ? " Local attribution query capped at 500 records." : ""}</p>}
        <div className="analytics-metric-grid">
          {analyticsMetricCards.map(([label, value, key, digits]) => <article className="analytics-metric" key={label}><span>{label}</span><strong>{digits === -1 ? value == null ? "—" : formatDuration(value) : formatMetric(value, digits)}</strong><small>{metricChange(analyticsData, key)}</small></article>)}
        </div>
        {analyticsData.comparison.metrics && <p className="analytics-comparison-note"><TrendingUp size={13}/> Comparing equal-length previous period: {analyticsData.comparison.previous_period.start_date} – {analyticsData.comparison.previous_period.end_date}. Rate metrics use view-weighted averages.</p>}
        {analyticsData.errors.comparison && <div className="analytics-inline-error" role="status">Comparison unavailable: {analyticsData.errors.comparison.message}</div>}
        <div className="analytics-chart-grid"><article className="analytics-chart-card"><h3>Views</h3><AnalyticsLineChart rows={analyticsData.trend} metric="views" title="Views" color="#138565"/></article><article className="analytics-chart-card"><h3>Engaged Views</h3><AnalyticsLineChart rows={analyticsData.trend} metric="engagedViews" title="Engaged Views" color="#6481ba"/></article></div>
        {analyticsData.scope === "klipnara" && analyticsData.insights && <section className="analytics-insights"><div><span className="eyebrow">RULE-BASED INSIGHTS</span><h3>Production patterns</h3><p>Minimum sample: {analyticsData.insights.minimum_sample} attributed videos per group. Descriptive only; not causal.</p></div>{analyticsData.insights.items.length ? analyticsData.insights.items.map((item, index) => <article key={`${item.kind}-${index}`}><small>{item.timeframe} · n={item.sample_count}</small><span>{item.message}</span></article>) : <div className="analytics-chart-empty">{analyticsData.insights.message}</div>}</section>}
        <section className="analytics-video-section"><div className="analytics-video-heading"><div><span className="eyebrow">VIDEO PERFORMANCE</span><h3>{analyticsData.scope === "channel" ? "Top channel videos" : "Klipnara videos"}</h3></div><span>{analyticsData.videos.length} video rows{analyticsData.channel_video_limit_reached ? " · 500-row cap" : ""}</span></div>
          {analyticsData.errors.videos && <div className="analytics-inline-error" role="status">Video detail query unavailable: {analyticsData.errors.videos.message}</div>}
          {analyticsData.videos.length ? <div className="analytics-table-wrap"><table className="analytics-table"><thead><tr><th>Video</th><th>Views</th><th>Engaged Views</th><th>Avg. view %</th><th>Production attribution</th><th></th></tr></thead><tbody>{analyticsData.videos.map((video) => <tr key={video.video_id}><td><a href={video.video_url} target="_blank" rel="noreferrer">{video.title || video.content_title || video.video_id}<ExternalLink size={11}/></a><small>{video.published_date || "Publication date unavailable"} · {video.video_id}</small></td><td>{formatMetric(video.views)}</td><td>{formatMetric(video.engagedViews)}</td><td>{formatMetric(typeof video.averageViewPercentage === "number" ? video.averageViewPercentage : null, 1)}{typeof video.averageViewPercentage === "number" ? "%" : ""}</td><td>{video.attribution_available ? <span className="analytics-attribution-chip">{String(video.attribution?.source_workflow || "Klipnara")}{video.attribution?.subtitle_type ? ` · ${String(video.attribution.subtitle_type)}` : ""}</span> : <span className="analytics-muted">Not attributed</span>}</td><td>{video.publication_id && <button className="button button-outline small-button" onClick={() => setAnalyticsVideoId(video.publication_id!)}><Search size={12}/> Details</button>}</td></tr>)}</tbody></table></div> : <div className="analytics-chart-empty">No video rows for selected channel and date range.</div>}
        </section>
        {analyticsVideoId && <section className="analytics-detail"><div className="analytics-video-heading"><div><span className="eyebrow">PUBLISHED VIDEO DETAIL</span><h3>{videoDetail?.title || "Loading video details…"}</h3></div><button className="button button-outline small-button" onClick={() => setAnalyticsVideoId("")}>Close <X size={12}/></button></div>
          {detailLoading && <div className="publishing-loading"><LoaderCircle size={15} className="spin"/> Loading daily metrics and retention…</div>}
          {detailError && <div className="notice notice-error" role="alert"><AlertCircle size={14}/>{detailError}</div>}
          {videoDetail && <><div className="analytics-detail-metrics"><span>Views <strong>{formatMetric(videoDetail.metrics.views)}</strong></span><span>Engaged Views <strong>{formatMetric(videoDetail.metrics.engaged_views)}</strong></span><span>Avg. duration <strong>{videoDetail.metrics.average_view_duration == null ? "—" : formatDuration(videoDetail.metrics.average_view_duration)}</strong></span><span>Avg. view % <strong>{formatMetric(videoDetail.metrics.average_view_percentage, 1)}{videoDetail.metrics.average_view_percentage == null ? "" : "%"}</strong></span></div><div className="analytics-chart-card"><h3>Daily video views</h3><AnalyticsLineChart rows={videoDetail.trend} metric="views" title="Video views" color="#138565"/></div>
            {videoDetail.attribution && <dl className="analytics-attribution-details"><div><dt>Workflow</dt><dd>{String(videoDetail.attribution.source_workflow || "Unavailable")}</dd></div><div><dt>Subtitle</dt><dd>{String(videoDetail.attribution.subtitle_type || "Unavailable")}</dd></div><div><dt>Caption preset</dt><dd>{String(videoDetail.attribution.caption_preset || "Unavailable")}</dd></div><div><dt>Visual preset</dt><dd>{String(videoDetail.attribution.visual_preset || "Unavailable")}</dd></div><div><dt>Scenes</dt><dd>{String(videoDetail.attribution.number_of_scenes ?? "Unavailable")}</dd></div><div><dt>Rendered</dt><dd>{String(videoDetail.attribution.rendered_at || "Unavailable")}</dd></div></dl>}
            <div className="analytics-chart-card"><h3>Audience retention</h3>{retentionError ? <div className="analytics-inline-error" role="status">{retentionError}</div> : retentionData?.points.length ? <><AnalyticsLineChart rows={retentionData.points.map((point) => ({ elapsedVideoTimeRatio: point.ratio, audienceWatchRatio: point.audience_watch_ratio }))} metric="audienceWatchRatio" title="Audience watch ratio" color="#be8d3f"/><div className="analytics-retention-labels"><span>0:00</span><span>Video timeline · {formatDuration(retentionData.duration)}</span><span>{formatDuration(retentionData.duration)}</span></div></> : <div className="analytics-chart-empty">{retentionData?.message || "Retention report not available yet."}</div>}</div>
          </>}
        </section>}
      </>}
    </section>}

    {view === "queue" && <div className="publishing-workspace">
      <section className="publishing-content-list panel">
        <div className="panel-heading"><div><span className="eyebrow">LOCAL OUTPUTS</span><h2>Ready for review <span>{content.filter((item) => item.eligible).length}</span></h2></div><button className="icon-button" title="Refresh outputs" onClick={() => void retryBackend()} disabled={checkingBackend}><RefreshCw size={14}/></button></div>
        {content.length ? content.map((item) => <button key={`${item.content_type}:${item.content_id}`} aria-pressed={selectedId === item.content_id} className={`publishing-content-row ${selectedId === item.content_id ? "selected" : ""}`} onClick={() => setSelectedId(item.content_id)}>
          <span className="publishing-content-mark">{item.content_type === "clip" ? "CLIP" : "MOOD"}</span><span className="publishing-content-copy"><strong>{item.title}</strong><small>{item.source_name || item.project_title || "Mood Quotes"} · {item.file_size ? formatBytes(item.file_size) : "missing file"}</small></span>
          <span className={`review-chip review-${item.review_status.replace("_", "-")}`}>{reviewStatusLabel(item.review_status as "approved" | "needs_review" | "needs_revision")}</span>
        </button>) : <div className="publishing-empty">No rendered outputs yet. Render and review clip or Mood output first.</div>}
      </section>

      {selected ? <section className="publishing-editor panel">
        <div className="publishing-editor-heading"><div><span className="eyebrow">{selected.content_type === "clip" ? "CLIP OUTPUT" : "MOOD RENDER"}</span><h2>{selected.title}</h2><small>{selected.review_status === "approved" ? "SHA-256 approval gate passed at review." : "Approve current render before publishing."}</small></div><Link className="button button-outline small-button" href={selected.editor_url}><ExternalLink size={13}/> Open editor</Link></div>
         <video className="publishing-output-preview" src={`${API}${selected.output_url}`} controls playsInline preload="metadata"/>
         {!selected.eligible && <div className="accounts-config-note"><ShieldCheck size={15}/><span>Publishing locked until output render completes and current file receives approval. Batch outputs need individual approval.</span></div>}
          <section className="platform-targets" aria-label="Target platforms"><div><span className="eyebrow">TARGET PLATFORMS</span><strong>Select actions independently</strong><small>YouTube keeps existing uploader. Social API actions appear only when account scopes and platform method are available.</small></div><div className="platform-target-options">{(["youtube", "tiktok", "instagram"] as const).map((platform) => {
            const info = platforms.find((item) => item.id === platform);
            const selectedTarget = platformTargets.includes(platform);
            return <label key={platform} className={selectedTarget ? "selected" : ""}><input type="checkbox" checked={selectedTarget} onChange={(event) => toggleTarget(platform, event.target.checked)}/><span><strong>{info?.name || platform}</strong><small>{platform === "youtube" ? info?.readiness === "existing_uploader" ? "Existing uploader · approval required" : "Connect account for upload" : info?.readiness === "conditional" ? "Conditional API + manual export" : "Manual export available"}</small></span></label>;
          })}</div>{platformTargets.some((item) => item !== "youtube") && <small className="platform-capability-note">{platforms.find((item) => item.id === platformTargets.find((item) => item !== "youtube"))?.reason} <Link href="/accounts">Connected Accounts</Link></small>}</section>
          {platformTargets.some((item) => item !== "youtube") && <div className="platform-action-choices">{platformTargets.filter((item): item is "tiktok" | "instagram" => item !== "youtube").map((platform) => {
             const info = platforms.find((item) => item.id === platform);
             const method = platform === "tiktok" ? "tiktok_inbox" : "instagram_resumable";
             const availableAccounts = info?.accounts || [];
             return <div className="platform-action-choice" key={platform}>
               <label className="field"><span>{info?.name || platform} action</span><select value={platformActions[platform]} onChange={(event) => setPlatformActions((current) => ({ ...current, [platform]: event.target.value as PlatformAction }))}><option value="manual_export">Manual export · download MP4</option>{info?.upload_methods?.includes(method) && <option value={method}>{platform === "tiktok" ? "Transfer to TikTok Inbox · creator must post" : "Resumable upload and publish to Instagram"}</option>}</select></label>
               {platformActions[platform] !== "manual_export" && <fieldset className="publishing-destination-list"><legend>Select {info?.name || platform} accounts</legend>{availableAccounts.length ? availableAccounts.map((account) => <label key={account.id} className={!account.upload_ready ? "unavailable" : ""}><input type="checkbox" checked={platformAccountIds[platform].includes(account.id)} disabled={!account.upload_ready} onChange={(event) => togglePlatformAccount(platform, account.id, event.target.checked)}/><span><strong>{account.display_name || account.id} {account.is_default && <em>Default</em>}</strong><small>{account.username ? `@${account.username} · ` : ""}{account.upload_ready ? "Ready for selected API action" : `${account.status} · permissions unavailable`}</small></span></label>) : <small>No connected accounts. <Link href="/accounts">Connect account</Link> or use manual export.</small>}</fieldset>}
               {!availableAccounts.some((account) => account.upload_ready) && platformActions[platform] !== "manual_export" && <small>Required scopes not verified. Use manual export or connect an eligible account.</small>}
             </div>;
           })}</div>}
         <div className="publishing-platform-tabs" role="tablist" aria-label="Platform metadata">{platformTargets.map((platform) => <button type="button" role="tab" aria-selected={metadataTab === platform} className={metadataTab === platform ? "selected" : ""} key={platform} onClick={() => setMetadataTab(platform)}>{platforms.find((item) => item.id === platform)?.name || platform}</button>)}</div>
          {platformTargets.includes("youtube") && metadataTab === "youtube" && <>
          <fieldset className="publishing-destination-list"><legend>YouTube destination channels</legend>{publishAccounts.length ? publishAccounts.map((item) => <label key={item.id}><input type="checkbox" checked={youtubeAccountIds.includes(item.id)} onChange={(event) => toggleYoutubeAccount(item.id, event.target.checked)}/><span><strong>{item.channel_title} {item.is_default && <em>Default</em>}</strong><small>{item.channel_id}</small></span></label>) : <small><Link href="/accounts">Verify upload permission in Connected Accounts</Link> first.</small>}</fieldset>
          {youtubeAccountIds.length > 0 && <label className="field destination-metadata-account"><span>Edit metadata for destination</span><select value={activeYoutubeAccountId} onChange={(event) => setActiveYoutubeAccountId(event.target.value)}>{youtubeAccountIds.map((id) => <option key={id} value={id}>{publishAccounts.find((item) => item.id === id)?.channel_title || id}</option>)}</select></label>}
          <div className="publishing-form-grid">
           <label className="field"><span>Title · max 100</span><input maxLength={100} value={currentMetadata.title || ""} onChange={(event) => update("title", event.target.value)}/></label>
           <label className="field publishing-wide"><span>Description · max 5,000 UTF-8 bytes</span><textarea maxLength={5000} rows={4} value={currentMetadata.description || ""} onChange={(event) => update("description", event.target.value)}/></label>
           <label className="field"><span>Tags · comma separated</span><input value={(currentMetadata.tags || []).join(", ")} onChange={(event) => update("tags", event.target.value.split(",").map((item) => item.trim()).filter(Boolean))}/></label>
           <label className="field"><span>Hashtags · comma separated</span><input value={(currentMetadata.hashtags || []).join(", ")} onChange={(event) => update("hashtags", event.target.value.split(",").map((item) => item.trim().replace(/^#/, "")).filter(Boolean))}/></label>
           <label className="field"><span>Category</span><select value={currentMetadata.category_id || "22"} onChange={(event) => update("category_id", event.target.value)}><option value="1">Film & Animation</option><option value="2">Autos & Vehicles</option><option value="10">Music</option><option value="15">Pets & Animals</option><option value="17">Sports</option><option value="19">Travel & Events</option><option value="20">Gaming</option><option value="22">People & Blogs</option><option value="23">Comedy</option><option value="24">Entertainment</option><option value="25">News & Politics</option><option value="26">Howto & Style</option><option value="27">Education</option><option value="28">Science & Technology</option></select></label>
           <label className="field"><span>Video language · optional</span><input maxLength={35} placeholder="en or id-ID" value={currentMetadata.video_language || ""} onChange={(event) => update("video_language", event.target.value)}/></label>
           <label className="field"><span>Privacy</span><select value={currentMetadata.privacy_status || "private"} onChange={(event) => update("privacy_status", event.target.value as Privacy)}><option value="private">Private</option><option value="unlisted">Unlisted</option><option value="public" disabled={Boolean(currentMetadata.publish_at)}>Public</option></select></label>
           <label className="field"><span>Schedule · browser local timezone</span><input type="datetime-local" value={localDateValue(currentMetadata.publish_at)} onChange={(event) => updateSchedule(event.target.value)}/><small>Native YouTube schedule requires Private and future time.</small></label>
           <fieldset className="publishing-declaration"><legend>Made for Kids? · required</legend><label><input type="radio" name="kids" checked={currentMetadata.made_for_kids === true} onChange={() => update("made_for_kids", true)}/> Yes</label><label><input type="radio" name="kids" checked={currentMetadata.made_for_kids === false} onChange={() => update("made_for_kids", false)}/> No</label></fieldset>
           <fieldset className="publishing-declaration"><legend>Realistic synthetic media? · required</legend><label><input type="radio" name="synthetic" checked={currentMetadata.contains_synthetic_media === true} onChange={() => update("contains_synthetic_media", true)}/> Yes, disclose</label><label><input type="radio" name="synthetic" checked={currentMetadata.contains_synthetic_media === false} onChange={() => update("contains_synthetic_media", false)}/> No</label></fieldset>
        </div>
         <div className="publishing-template-row"><label className="field"><span>Metadata templates</span><select defaultValue="" onChange={(event) => { const template = templates.find((item) => item.id === event.target.value); if (template) { const next = { ...currentMetadata, ...template.metadata, account_id: activeYoutubeAccountId || undefined }; if (next.publish_at) next.privacy_status = "private"; if (activeYoutubeAccountId) setYoutubeMetadataByAccount((current) => ({ ...current, [activeYoutubeAccountId]: next })); else setMetadata(next); } }}><option value="">Apply saved template</option>{templates.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label className="field"><span>Save current metadata as</span><input value={templateName} maxLength={80} onChange={(event) => setTemplateName(event.target.value)} placeholder="Template name"/></label><button className="button button-outline" onClick={() => void saveTemplate()} disabled={busy === "template"}>{busy === "template" ? <LoaderCircle size={13} className="spin"/> : <Save size={13}/>} Save template</button></div>
        {templates.length > 0 && <div className="publishing-template-list">{templates.map((item) => <span key={item.id}>{item.name}<button className="icon-button" title={`Delete ${item.name}`} onClick={() => void deleteTemplate(item.id)} disabled={Boolean(busy)}><Trash2 size={12}/></button></span>)}</div>}
        <div className="publishing-thumbnail-row"><div><strong><FileImage size={14}/> Custom thumbnail</strong><small>{selected.thumbnail_url ? `Local thumbnail · YouTube: ${selected.thumbnail_remote_status || "not applied"}` : "JPEG/PNG · min 640×360 · max 2 MiB · landscape"}{selected.thumbnail_error ? ` · ${selected.thumbnail_error}` : ""}</small></div><label className="button button-outline small-button"><Upload size={13}/> Choose image<input type="file" accept="image/jpeg,image/png" disabled={!selected.eligible || busy === "thumbnail"} onChange={(event) => void uploadThumbnail(event.target.files?.[0])}/></label></div>
          {selected.thumbnail_url && <img className="publishing-thumbnail-preview" src={`${API}${selected.thumbnail_url}`} alt={`Local thumbnail for ${selected.title}`}/>}
          </>}
          {platformTargets.includes("tiktok") && platformAccountIds.tiktok.length > 0 && <label className="field destination-metadata-account"><span>Edit TikTok metadata for account</span><select value={activePlatformAccountIds.tiktok} onChange={(event) => selectPlatformMetadataAccount("tiktok", event.target.value)}>{platformAccountIds.tiktok.map((id) => <option key={id} value={id}>{platforms.find((item) => item.id === "tiktok")?.accounts.find((account) => account.id === id)?.display_name || id}</option>)}</select></label>}
          {platformTargets.includes("instagram") && platformAccountIds.instagram.length > 0 && <label className="field destination-metadata-account"><span>Edit Instagram metadata for account</span><select value={activePlatformAccountIds.instagram} onChange={(event) => selectPlatformMetadataAccount("instagram", event.target.value)}>{platformAccountIds.instagram.map((id) => <option key={id} value={id}>{platforms.find((item) => item.id === "instagram")?.accounts.find((account) => account.id === id)?.display_name || id}</option>)}</select></label>}
           {platformTargets.includes("tiktok") && metadataTab === "tiktok" && <section className="platform-metadata-card"><div className="platform-metadata-heading"><div><span className="eyebrow">TIKTOK · {platformActions.tiktok === "tiktok_inbox" ? "INBOX TRANSFER" : "MANUAL EXPORT"}</span><strong>Caption draft</strong><small>Caption, privacy, and interaction choices stay local; creator reviews and completes post in TikTok.</small></div><button className="button button-outline small-button" onClick={() => void copyPlatformCaption("tiktok")}><Copy size={13}/> Copy caption</button></div><label className="field"><span>Caption · max 2,200</span><textarea maxLength={2200} rows={4} value={platformMetadata.tiktok.caption} onChange={(event) => updatePlatform("tiktok", "caption", event.target.value)}/></label><label className="field"><span>Hashtags · comma separated</span><input value={platformMetadata.tiktok.hashtags.join(", ")} onChange={(event) => updatePlatform("tiktok", "hashtags", event.target.value.split(",").map((item) => item.trim().replace(/^#/, "")).filter(Boolean))}/></label><div className="publishing-form-grid"><label className="field"><span>Suggested privacy · TikTok reminder</span><select value={platformMetadata.tiktok.privacy_level || "SELF_ONLY"} onChange={(event) => updatePlatform("tiktok", "privacy_level", event.target.value)}><option value="SELF_ONLY">Only me</option><option value="MUTUAL_FOLLOW_FRIENDS">Friends</option><option value="FOLLOWER_OF_CREATOR">Followers</option><option value="PUBLIC_TO_EVERYONE">Everyone</option></select></label><label className="field"><span>AI-generated disclosure</span><select value={platformMetadata.tiktok.ai_generated == null ? "" : String(platformMetadata.tiktok.ai_generated)} onChange={(event) => updatePlatform("tiktok", "ai_generated", event.target.value === "" ? null : event.target.value === "true")}><option value="">Not selected</option><option value="true">Yes</option><option value="false">No</option></select></label></div></section>}
          {platformTargets.includes("instagram") && metadataTab === "instagram" && <section className="platform-metadata-card"><div className="platform-metadata-heading"><div><span className="eyebrow">INSTAGRAM REELS · {platformActions.instagram === "instagram_resumable" ? "API PUBLISH" : "MANUAL EXPORT"}</span><strong>Caption draft</strong><small>{platformActions.instagram === "instagram_resumable" ? "Caption and feed choice are sent with the eligible API request." : "Account eligibility is not verified by manual export."}</small></div><button className="button button-outline small-button" onClick={() => void copyPlatformCaption("instagram")}><Copy size={13}/> Copy caption</button></div><label className="field"><span>Caption · max 2,200</span><textarea maxLength={2200} rows={4} value={platformMetadata.instagram.caption} onChange={(event) => updatePlatform("instagram", "caption", event.target.value)}/></label><label className="field"><span>Hashtags · comma separated</span><input value={platformMetadata.instagram.hashtags.join(", ")} onChange={(event) => updatePlatform("instagram", "hashtags", event.target.value.split(",").map((item) => item.trim().replace(/^#/, "")).filter(Boolean))}/></label><div className="publishing-form-grid"><label className="field"><span>Share to Feed</span><select value={String(platformMetadata.instagram.share_to_feed ?? true)} onChange={(event) => updatePlatform("instagram", "share_to_feed", event.target.value === "true")}><option value="true">Yes</option><option value="false">No</option></select></label><label className="field"><span>AI-generated disclosure</span><select value={platformMetadata.instagram.ai_generated == null ? "" : String(platformMetadata.instagram.ai_generated)} onChange={(event) => updatePlatform("instagram", "ai_generated", event.target.value === "" ? null : event.target.value === "true")}><option value="">Not selected</option><option value="true">Yes</option><option value="false">No</option></select></label></div></section>}
          {platformTargets.some((item) => item !== "youtube") && <div className="platform-metadata-actions"><button className="button button-outline small-button" onClick={applySharedCaption} disabled={!draftsReady}>Apply YouTube description to selected social captions</button>{copyNotice && <small role="status">{copyNotice}</small>}</div>}
         <div className="platform-rights-note"><ShieldCheck size={15}/><span>Confirm rights per export. Music licenses are platform-specific; YouTube Audio Library or stock licenses may not cover TikTok/Instagram. Do not repost footage without rights or remove attribution/watermarks.</span></div>
          <div className="publishing-editor-actions"><button className="button button-outline" onClick={() => void saveDraft()} disabled={!draftsReady || Boolean(busy)}>{busy === "save" ? <LoaderCircle size={13} className="spin"/> : <Save size={13}/>} Save platform drafts</button><button className="button button-youtube" onClick={() => void startConfirmation()} disabled={!selected.eligible || !platformTargets.length || !draftsReady || Boolean(busy)}><Send size={14}/> Review selected actions</button></div>
        {selectedHistory.length > 0 && <div className="publishing-related-history"><strong>Output history</strong>{selectedHistory.map((item) => <span key={item.id}>{statusLabel(item)} · {item.channel_title}{item.video_url ? <> · <a href={item.video_url} target="_blank" rel="noreferrer">Open video</a></> : null}{item.video_id && selected.thumbnail_url && <button className="text-link" onClick={() => void applyThumbnail(item)} disabled={Boolean(busy)}>{busy === item.id ? "Applying…" : "Apply thumbnail"}</button>}</span>)}</div>}
      </section> : <section className="publishing-editor panel publishing-empty-detail"><div className="publishing-empty-art"><Film size={23}/><Youtube size={19}/></div><span className="eyebrow">YOUR PUBLISHING WORKSPACE</span><h2>{content.length ? "Pilih output untuk mulai" : "Belum ada output video"}</h2><p>{content.length ? "Pilih Clip atau Mood render dari daftar untuk melihat preview dan menyiapkan metadata." : "Render dan setujui output final terlebih dahulu. Setelah itu, pilih output di sini untuk menyiapkan publikasi."}</p><div className="publishing-empty-actions"><Link className="button button-outline" href="/clips">Buka Clip Library <ArrowRight size={14}/></Link><Link className="button button-outline" href="/mood">Buka Mood Studio <ArrowRight size={14}/></Link></div></section>}
    </div>}

    {view === "calendar" && <section className="publishing-calendar panel"><div className="panel-heading"><div><span className="eyebrow">NATIVE YOUTUBE SCHEDULES</span><h2>Publishing Calendar</h2></div><CalendarDays size={17}/></div>{calendar.length ? calendar.map((item) => <article className="publishing-calendar-row" key={item.id}><time>{item.publish_at ? new Date(item.publish_at).toLocaleString() : "No date"}</time><div><strong>{item.title}</strong><small>{item.channel_title} · {item.clip_title} · {item.privacy_status} · {statusLabel(item)}</small></div>{item.video_url && <a className="button button-outline small-button" href={item.video_url} target="_blank" rel="noreferrer">Open <ExternalLink size={12}/></a>}</article>) : <div className="publishing-empty">No scheduled outputs. Schedule uses YouTube native `publishAt`; this app does not publish later from a local timer.</div>}</section>}

    {view === "history" && <section className="publishing-history-list"><div className="publishing-history-heading"><div><span className="eyebrow">UPLOADS, RETRIES, THUMBNAILS</span><h2>Publishing History <span>{publications.length}</span></h2></div><button className="button button-outline small-button" onClick={() => void refresh()}>Refresh</button></div>{publications.length ? publications.map((item) => <article className="publication-card panel" key={item.id}>
      <div className="publication-card-top"><div><span className={`publication-status publication-${item.status}`}>{statusLabel(item)}</span><strong>{item.title}</strong><small>{item.channel_title} · {new Date(item.created_at).toLocaleString()}</small></div><span className="publication-privacy">{item.privacy_status}{item.publish_at ? ` · ${new Date(item.publish_at).toLocaleString()}` : ""}</span></div>
      <div className="publication-context"><span>{item.content_type === "mood_render" ? "Mood Quotes" : "Clip"}: {item.clip_title}</span><span>{formatDuration(item.duration)} · {item.width} × {item.height} · {formatBytes(item.file_size)}</span><span>{item.made_for_kids ? "Made for Kids" : "Not Made for Kids"}</span>{item.contains_synthetic_media && <span>Synthetic disclosure: Yes</span>}</div>
      {(item.status === "uploading" || item.status === "pending") && <div className="publication-progress"><div className="publication-progress-track"><i style={{ width: `${Math.round(item.progress * 100)}%` }}/></div><small>{item.status === "pending" && !item.upload_started ? "Waiting for worker…" : `${formatBytes(item.uploaded_bytes)} / ${formatBytes(item.file_size)} · ${Math.round(item.progress * 100)}%`}</small></div>}
      {item.last_error && <p className="publication-error">{item.last_error}</p>}{item.reconciliation_required && <p className="publication-reconcile">Check YouTube Studio before retry. Automatic duplicate upload blocked.</p>}
      {events.some((event) => event.publication_id === item.id) && <details className="publishing-event-list"><summary>Activity · {events.filter((event) => event.publication_id === item.id).length}</summary>{events.filter((event) => event.publication_id === item.id).map((event) => <span key={event.id}><time>{new Date(event.occurred_at).toLocaleString()}</time><strong>{event.event_type.replaceAll("_", " ")}</strong>{event.message}</span>)}</details>}
      <div className="publication-actions">{item.video_url && <a className="button button-primary small-button" href={item.video_url} target="_blank" rel="noreferrer">Open YouTube <ExternalLink size={13}/></a>}{item.video_id && content.find((row) => row.content_id === item.content_id)?.thumbnail_url && <button className="button button-outline small-button" disabled={Boolean(busy)} onClick={() => void applyThumbnail(item)}>{busy === item.id ? <LoaderCircle size={13} className="spin"/> : <FileImage size={13}/>} Apply thumbnail</button>}{item.status === "failed" && !item.reconciliation_required && <button className="button button-outline small-button" disabled={Boolean(busy)} onClick={() => void request(`/youtube/publications/${item.id}/retry`, { method: "POST" }).then(refresh).catch((reason) => setError((reason as Error).message))}>Retry / reconcile</button>}</div>
     </article>) : <div className="publishing-empty panel">No uploads yet.</div>}</section>}

    {view === "history" && <section className="publishing-history-list platform-history">
      <div className="publishing-history-heading"><div><span className="eyebrow">SOCIAL PLATFORM JOBS</span><h2>Social history <span>{platformJobs.length}</span></h2><p>Inbox delivery requires creator action. Instagram Published requires provider confirmation. Manual export never uploads.</p></div><button className="button button-outline small-button" onClick={() => void request<PlatformJob[]>("/platform-publications").then(setPlatformJobs).catch((reason) => setError((reason as Error).message))}><RefreshCw size={13}/> Refresh</button></div>
      {platformJobs.length ? platformJobs.map((job) => {
        const manual = job.upload_method === "manual_export";
        const status = job.status === "prepared_manual" ? "Prepared · manual posting"
          : job.status === "awaiting_manual_action" ? "TikTok Inbox delivered · creator action required"
          : job.status === "published" ? "Published · provider confirmed"
          : job.status.replaceAll("_", " ");
        const progress = Math.min(100, Math.max(0, (job.progress || 0) * 100));
        const caption = [job.metadata.caption || "", (job.metadata.hashtags || []).map((tag) => `#${tag}`).join(" ")].filter(Boolean).join("\n\n");
        return <article className="publication-card panel" key={job.id}>
          <div className="publication-card-top"><div><span className={`publication-status publication-${job.status}`}>{status}</span><strong>{job.platform === "tiktok" ? "TikTok" : "Instagram Reels"}</strong><small>{job.content_type === "mood_render" ? "Mood render" : "Clip"} · {manual ? "No account required" : job.account_name || "Unknown account"} · {new Date(job.created_at).toLocaleString()}</small></div><span className="publication-privacy">{job.upload_method}</span></div>
          <p className="platform-history-caption">{caption || "No caption"}</p>
          {!manual && ["queued", "uploading", "processing"].includes(job.status) && <div className="publication-progress"><div className="publication-progress-track"><i style={{ width: `${progress}%` }}/></div><small>{job.status === "queued" ? "Waiting for local worker…" : `${formatBytes(job.uploaded_bytes || 0)} / ${formatBytes(job.file_size || 0)} provider-confirmed · ${Math.round(progress)}% transfer progress`}{job.provider_status ? ` · Provider: ${job.provider_status}` : ""}</small></div>}
          {job.status === "awaiting_manual_action" && <p className="platform-history-caption">Transfer reached TikTok Inbox. Finish caption, privacy, and posting in TikTok; this job is not Published.</p>}
          {job.last_error && <p className="publication-error">{job.last_error}</p>}
          {job.events?.length ? <details className="publishing-event-list"><summary>Activity · {job.events.length}</summary>{job.events.map((event) => <span key={event.id}><time>{new Date(event.occurred_at).toLocaleString()}</time><strong>{event.event_type.replaceAll("_", " ")}</strong>{event.message}</span>)}</details> : null}
          <div className="publication-actions">
            {manual && job.status === "prepared_manual" && <a className="button button-outline small-button" href={`${API}/api/platform-publications/${job.id}/download`}><Download size={13}/> Download MP4</a>}
            <button className="button button-outline small-button" onClick={() => void navigator.clipboard.writeText(caption).then(() => setCopyNotice("Caption copied."), () => setCopyNotice("Clipboard unavailable."))}><Copy size={13}/> Copy caption</button>
            {!manual && ["needs_reconciliation", "awaiting_manual_action", "processing"].includes(job.status) && <button className="button button-outline small-button" onClick={() => void reconcilePlatformJob(job)} disabled={Boolean(busy)}>{busy === job.id ? <LoaderCircle size={13} className="spin"/> : <RefreshCw size={13}/>} Check provider status</button>}
            {!manual && (["failed", "cancelled"].includes(job.status) || job.status === "needs_reconciliation" && (!job.remote_id || job.phase === "publish_reconciled" || job.platform === "instagram" && job.phase === "processing_timeout" && job.provider_status === "IN_PROGRESS")) && <button className="button button-outline small-button" onClick={() => void retryPlatformJob(job)} disabled={Boolean(busy)}>{busy === job.id ? <LoaderCircle size={13} className="spin"/> : <RefreshCw size={13}/>} Retry with confirmation</button>}
            {!manual && ["queued", "uploading"].includes(job.status) && job.phase !== "publishing" && <button className="button button-outline small-button" onClick={() => void cancelPlatformJob(job)} disabled={Boolean(busy)}><X size={13}/> Cancel transfer</button>}
          </div>
        </article>;
      }) : <div className="publishing-empty panel">No social jobs yet. Manual export remains available without API credentials.</div>}
      {copyNotice && <small role="status">{copyNotice}</small>}
    </section>}

    {confirmOpen && selected && <div className="modal-backdrop" onClick={(event) => { if (event.target === event.currentTarget && !busy) setConfirmOpen(false); }}>
      <section className="confirm-modal publishing-modal" role="dialog" aria-modal="true" aria-labelledby="publishing-confirm-title" aria-describedby="publishing-confirm-description">
        <div className="publishing-modal-heading">
          <div className="publishing-modal-brand">
            <span className="publishing-modal-icon"><Send size={19}/></span>
            <div><span className="eyebrow">FINAL REVIEW</span><h2 id="publishing-confirm-title">Confirm selected actions</h2></div>
          </div>
          <button className="publishing-modal-close" type="button" aria-label="Close confirmation" onClick={() => setConfirmOpen(false)} disabled={Boolean(busy)}><X size={17}/></button>
        </div>
        <p id="publishing-confirm-description" className="publishing-modal-intro">YouTube uses existing uploader. TikTok Inbox transfer still needs creator action; Instagram API action publishes only after provider confirmation. Manual export never uploads.</p>
        <div className="publishing-confirm">
          <div className="publishing-confirm-output">
            <span className="publishing-confirm-kicker">SELECTED TARGETS</span>
            <strong>{platformTargets.map((platform) => platforms.find((item) => item.id === platform)?.name || platform).join(" · ")}</strong>
            <small>{selected.content_type === "mood_render" ? "Mood render" : "Clip output"} · {selected.title} · {selected.eligible ? "Approved fingerprint" : "Approval required"}{selected.file_size ? ` · ${formatBytes(selected.file_size)}` : ""}{selected.thumbnail_url ? " · thumbnail attached" : ""}</small>
          </div>
          {platformTargets.includes("youtube") && youtubeAccountIds.map((id) => {
            const account = publishAccounts.find((item) => item.id === id);
            const draft = youtubeMetadataByAccount[id] || (id === activeYoutubeAccountId ? currentMetadata : metadata);
            return <section className="publishing-confirm-copy" key={id}><span>YouTube · {account?.channel_title || id} · {account?.channel_id}</span><dl className="publishing-confirm-grid"><div><dt>Title</dt><dd>{draft.title || "Empty"}</dd></div><div><dt>Privacy</dt><dd>{draft.publish_at ? "Private · scheduled" : draft.privacy_status || "Private"}</dd></div><div><dt>Schedule</dt><dd>{draft.publish_at ? new Date(draft.publish_at).toLocaleString() : "After processing"}</dd></div><div><dt>Category</dt><dd>{draft.category_id || "22"}</dd></div><div><dt>Made for Kids</dt><dd>{draft.made_for_kids === true ? "Yes" : draft.made_for_kids === false ? "No" : "Not selected"}</dd></div><div><dt>Synthetic disclosure</dt><dd>{draft.contains_synthetic_media === true ? "Yes" : draft.contains_synthetic_media === false ? "No" : "Not selected"}</dd></div></dl><p>{draft.description || "Empty description"}</p><small>Tags: {(draft.tags || []).join(", ") || "None"} · Hashtags: {(draft.hashtags || []).map((tag) => `#${tag.replace(/^#/, "")}`).join(" ") || "None"}</small></section>;
          })}
          {(["tiktok", "instagram"] as const).filter((platform) => platformTargets.includes(platform)).map((platform) => {
            const platformName = platform === "tiktok" ? "TikTok" : "Instagram";
            const action = platformActions[platform] === "manual_export" ? "Manual export" : platform === "tiktok" ? "Inbox transfer · creator must post" : "Reels API publish";
            const selectedIds = platformActions[platform] === "manual_export" ? [""] : platformAccountIds[platform];
            return selectedIds.map((id) => {
              const account = platforms.find((item) => item.id === platform)?.accounts.find((item) => item.id === id);
              const draft = id ? platformMetadataByAccount[`${platform}:${id}`] || currentPlatformMetadata(platform) : platformMetadata[platform];
              return <section className="publishing-confirm-copy" key={`${platform}:${id || "manual"}`}><span>{platformName} · {action}{id ? ` · ${account?.display_name || id}${account?.username ? ` (@${account.username})` : ""}` : " · no account target"}</span><p>{[draft.caption, ...(draft.hashtags || []).map((tag) => `#${tag.replace(/^#/, "")}`)].filter(Boolean).join(" ") || "Empty caption"}</p><small>{platform === "tiktok" ? `Privacy: ${draft.privacy_level || "SELF_ONLY"}` : `Share to Feed: ${draft.share_to_feed === false ? "No" : "Yes"}`}</small></section>;
            });
          })}
        </div>
        <label className="publishing-explicit-confirm"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)}/> I reviewed selected platform metadata and this output's approval.</label>
        <label className="publishing-explicit-confirm"><input type="checkbox" checked={rightsConfirmed} onChange={(event) => setRightsConfirmed(event.target.checked)}/> I have rights for this video, footage, and music on each selected platform.</label>
        {error && <p className="publishing-error" role="alert">{error}</p>}
        <div className="publishing-form-actions">
          <button className="button button-outline" onClick={() => setConfirmOpen(false)} disabled={Boolean(busy)}>Back</button>
          <button className="button button-youtube" onClick={() => void submitUpload()} disabled={!confirmed || !rightsConfirmed || Boolean(busy)}>{busy === "publish" ? <LoaderCircle size={14} className="spin"/> : <Send size={14}/>} Confirm selected actions</button>
        </div>
      </section>
    </div>}
    </>}
  </>;
}

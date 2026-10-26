"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertCircle, ArrowLeft, ArrowRight, Check, CheckCircle2, Clock3, Cloud, Copy, Download, Heart, LoaderCircle, LockKeyhole, Music2, Pause, Play, Plus, RotateCcw, Save, Scissors, Sparkles, Trash2, Upload, Video, Volume2, VolumeX, WandSparkles, X, ZoomIn, ZoomOut } from "lucide-react";
import { ChangeEvent, CSSProperties, PointerEvent as ReactPointerEvent, useEffect, useMemo, useRef, useState } from "react";
import { API, formatDuration, request } from "@/lib/api";
import { createSerializedSaveQueue } from "@/lib/mood-draft.mjs";
import { duplicateSegment as duplicateTimelineSegment, mergeSegment, musicPlaybackSpan, resetSegmentTimings, semanticSegments, snapTimelineTime, splitSegment, timeAtPosition, updateSegmentTiming } from "@/lib/mood-timeline.mjs";

type Option = { id: string; name: string; seconds?: number[] };
type Category = { id: string; name: string; description: string; subcategories: Option[] };
type Quote = { id: string; title: string; text: string; segments: { text: string; order: number }[]; mood: string; tone: string; visual_keywords: string[]; music_mood: string };
type Asset = { id: string; project_id: string; kind: "background_image" | "background_video" | "music"; name: string; mime_type: string; size_bytes: number; duration: number | null; width: number | null; height: number | null; has_audio: boolean; url: string };
type Render = { id: string; project_id: string; job_id: string; status: string; review_status: string; url?: string; download_url?: string; created_at: string };
type MoodJob = { id: string; status: string; phase: string; progress: number | null; message: string };
type TextSegment = { id: string; text: string; start: number; end: number; animation: "fade_in" | "fade_out" | "fade_up" | "slide_up" | "gentle_scale" | "none"; animation_duration: number };
type VisualSettings = { schema_version: 1; preset_id: string | null; motion: "none" | "slow_zoom_in" | "slow_zoom_out" | "pan_left" | "pan_right" | "pan_up" | "pan_down" | "ken_burns"; motion_intensity: "subtle" | "normal" | "strong"; brightness: number; contrast: number; saturation: number; temperature: number; vignette: number; grain: number; dark_overlay: number; gradient_top: string; gradient_bottom: string; gradient_overlay_opacity: number; segment_animation: TextSegment["animation"] };
type VisualPreset = { id: string; name: string; description: string; category: string; mood_recommendations: string[]; preview: string[]; version: number; background: { color: string; color2: string }; effects: Omit<VisualSettings, "schema_version" | "preset_id">; typography: Omit<Composition["text"], "text" | "start" | "end" | "animation_in" | "animation_out" | "animation_duration">; animation: { text_in: string; text_out: string; duration: number }; recommended_music_mood: string };
type ProjectSummary = { id: string; title: string; updated_at: string; current_render: Render | null; latest_job: MoodJob | null };
type SourceItem = { id: string; name: string; duration: number; width: number; height: number };
type Composition = {
  resolution: "720" | "1080"; fps: 30; duration: number;
  background: { kind: "solid" | "gradient" | "image" | "video"; asset_id: string | null; color: string; color2: string; video_start: number; loop: boolean; mute_audio: boolean; audio_volume: number };
  music: { asset_id: string | null; offset: number; trim_start: number; trim_end: number; volume: number; fade_in: number; fade_out: number; loop: boolean; muted: boolean };
  text: { text: string; font: string; font_size: number; font_weight: number; color: string; alignment: "left" | "center" | "right"; x: number; y: number; line_spacing: number; shadow: boolean; outline: boolean; opacity: number; start: number; end: number; animation_in: string; animation_out: string; animation_duration: number; gradient_opacity: number; auto_contrast: boolean };
  visual: VisualSettings; text_mode: "single" | "sequential"; segments: TextSegment[]; segments_source: "auto" | "manual" | "legacy";
};
type VisualTextSettings = Pick<Composition["text"], "font" | "font_size" | "font_weight" | "color" | "alignment" | "x" | "y" | "line_spacing" | "shadow" | "outline" | "opacity" | "animation_in" | "animation_out" | "animation_duration" | "gradient_opacity" | "auto_contrast">;
type Draft = { title: string; category_id: string; subcategory_id: string; custom_topic: string; tone: string; perspective: string; length: string; language: string; provider: "gemini" | "openai" };
type Config = { categories: Category[]; styles: Option[]; perspectives: Option[]; lengths: Option[]; languages: Option[]; music_moods: string[]; fonts: string[]; visual_presets: VisualPreset[]; templates: { id: string; name: string; background: Partial<Composition["background"]>; text: Partial<Composition["text"]> }[]; providers: { default: "gemini" | "openai"; gemini: { configured: boolean; model: string }; openai: { configured: boolean; model: string } }; consent_data: string };
type ProjectDetail = { project: Draft & { id: string; selected_quote: Quote | null; composition: Composition; current_render: Render | null; latest_job: MoodJob | null }; assets: Asset[]; quotes: Quote[]; generations: { id: string; provider: string; model: string; created_at: string; quotes: Quote[] }[]; favorites: { id: string; generation_id: string | null; quote: Quote; created_at: string }[]; renders: Render[] };

const emptyDraft: Draft = { title: "Mood Quotes", category_id: "bahagia-positif", subcategory_id: "kebahagiaan-sederhana", custom_topic: "", tone: "natural", perspective: "netral", length: "short", language: "indonesia", provider: "gemini" };
const emptyComposition: Composition = {
  resolution: "720", fps: 30, duration: 10,
  background: { kind: "gradient", asset_id: null, color: "#1b332c", color2: "#568b70", video_start: 0, loop: true, mute_audio: true, audio_volume: 0.2 },
  music: { asset_id: null, offset: 0, trim_start: 0, trim_end: 30, volume: 0.25, fade_in: 1, fade_out: 1, loop: true, muted: false },
  text: { text: "", font: "Georgia", font_size: 50, font_weight: 600, color: "#ffffff", alignment: "center", x: 50, y: 52, line_spacing: 1.25, shadow: true, outline: false, opacity: 100, start: 0, end: 10, animation_in: "fade", animation_out: "fade", animation_duration: 0.8, gradient_opacity: 18, auto_contrast: false },
  visual: { schema_version: 1, preset_id: null, motion: "none", motion_intensity: "subtle", brightness: 0, contrast: 1, saturation: 1, temperature: 0, vignette: 0, grain: 0, dark_overlay: 0, gradient_top: "#26344a", gradient_bottom: "#101820", gradient_overlay_opacity: 0, segment_animation: "fade_up" },
  text_mode: "sequential", segments: [], segments_source: "auto",
};
const animationOptions = [{ id: "fade", name: "Fade" }, { id: "slide_up", name: "Slide Up" }, { id: "slide_down", name: "Slide Down" }, { id: "typewriter", name: "Typewriter" }, { id: "zoom", name: "Zoom lembut" }, { id: "none", name: "Tanpa animasi" }];
const segmentAnimationOptions = [{ id: "fade_in", name: "Fade In" }, { id: "fade_out", name: "Fade Out" }, { id: "fade_up", name: "Fade Up" }, { id: "slide_up", name: "Slide Up" }, { id: "gentle_scale", name: "Gentle Scale" }, { id: "none", name: "Tanpa animasi" }] as const;
const wordCount = (text: string) => (text.match(/[\p{L}\p{N}]+/gu) || []).length;
const newSegmentId = () => globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
const segmentAnimationForLegacy = (animation: string): TextSegment["animation"] => animation === "slide_up" ? "slide_up" : animation === "zoom" ? "gentle_scale" : animation === "none" ? "none" : "fade_up";

function makeTimedSegments(text: string, duration: number, animation: TextSegment["animation"] = "fade_up", preferred: Quote["segments"] = []): TextSegment[] {
  return semanticSegments(text, duration, animation, preferred);
}

function normalizeComposition(value: Composition, quote: Quote | null): Composition {
  const raw = value as Composition & { text_mode?: Composition["text_mode"]; segments?: TextSegment[]; text?: Partial<Composition["text"]> };
  const legacy = !raw.text_mode;
  const text = { ...emptyComposition.text, ...raw.text };
  const music = { ...emptyComposition.music, ...raw.music };
  const visual = { ...emptyComposition.visual, ...raw.visual };
  if (legacy) { text.gradient_opacity = 0; text.auto_contrast = false; }
  if (!raw.visual) visual.segment_animation = segmentAnimationForLegacy(text.animation_in);
  const duration = raw.duration || emptyComposition.duration;
  let textMode: Composition["text_mode"] = legacy ? "single" : raw.text_mode || "single";
  let segments = Array.isArray(raw.segments) ? raw.segments : [];
  let segmentsSource: Composition["segments_source"] = raw.segments_source || (legacy ? "legacy" : "auto");
  if (legacy && text.text.trim()) {
    segments = [{ id: newSegmentId(), text: text.text, start: text.start, end: text.end, animation: segmentAnimationForLegacy(text.animation_in), animation_duration: Math.min(text.animation_duration, Math.max(0.1, (text.end - text.start) / 2)) }];
  } else if (textMode === "sequential" && !segments.length && (quote?.text || text.text)) {
    segments = makeTimedSegments(quote?.text || text.text, duration, visual.segment_animation, quote?.segments || []);
  }
  return { ...emptyComposition, ...raw, music, text, visual, duration, text_mode: textMode, segments, segments_source: segmentsSource };
}

function sequenceWarnings(segments: TextSegment[], duration: number): string[] {
  const warnings: string[] = [];
  if (!segments.length) return ["Pilih quote atau tambah segmen teks."];
  let previousEnd = 0;
  let readTime = 0;
  segments.forEach((segment, index) => {
    const words = wordCount(segment.text);
    const span = Math.max(0, segment.end - segment.start);
    readTime += Math.max(1.2, words / 2.8 + 0.35) + Math.min(segment.animation_duration, span / 2) * 0.35;
    if (segment.start > previousEnd + 0.05) warnings.push(`Ada jeda sebelum segmen ${index + 1}.`);
    if (segment.start < previousEnd - 0.01) warnings.push(`Segmen ${index + 1} overlap dengan segmen sebelumnya.`);
    if (span > 0 && words / span > 3.2) warnings.push(`Segmen ${index + 1} mungkin terlalu cepat dibaca.`);
    if (span > 0 && span < 0.5) warnings.push(`Segmen ${index + 1} terlalu singkat untuk dibaca nyaman; gunakan minimal 0,5 dtk.`);
    if (words > 18) warnings.push(`Segmen ${index + 1} panjang; segmentasi ulang untuk mencegah font terlalu kecil.`);
    if (segment.animation_duration > span / 2) warnings.push(`Animasi segmen ${index + 1} dibatasi setengah durasi agar teks tetap terlihat.`);
    previousEnd = Math.max(previousEnd, segment.end);
  });
  if (previousEnd < duration - 0.05) warnings.push(`Ada jeda ${ (duration - previousEnd).toFixed(1) } dtk setelah segmen terakhir.`);
  if (readTime > duration + 0.05) warnings.push(`Durasi ${duration.toFixed(1)} dtk mungkin terlalu singkat; perkiraan baca/transisi ${readTime.toFixed(1)} dtk.`);
  return [...new Set(warnings)];
}

function previewTextColor(composition: Composition): string {
  const { text, background } = composition;
  if (!text.auto_contrast || !["solid", "gradient"].includes(background.kind)) return text.color;
  const colors = background.kind === "gradient" ? [background.color, background.color2] : [background.color];
  const channels = [0, 1, 2].map((channel) => colors.reduce((sum, color) => sum + parseInt(color.slice(1 + channel * 2, 3 + channel * 2), 16) / 255, 0) / colors.length);
  const linear = channels.map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2] > 0.52 ? "#18211c" : "#ffffff";
}

function fitPreviewFontSize(text: string, settings: Composition["text"]): number {
  const boxWidth = Math.min(82, settings.x * 2, (100 - settings.x) * 2) * 7.2;
  const centerY = settings.y * 12.8;
  const minSize = Math.max(20, Math.round(settings.font_size * 0.72));
  for (let size = settings.font_size; size >= minSize; size -= Math.max(1, Math.round(settings.font_size * 0.035))) {
    const columns = Math.max(1, Math.floor(boxWidth / (size * 0.56)));
    const lines = text.replace(/\r/gu, "").split("\n").flatMap((paragraph) => {
      const wrapped: string[] = [];
      let current = "";
      for (const word of paragraph.split(/\s+/u).filter(Boolean)) {
        if (current && current.length + 1 + word.length > columns) { wrapped.push(current); current = word; }
        else current = current ? `${current} ${word}` : word;
      }
      if (current || !wrapped.length) wrapped.push(current);
      return wrapped;
    });
    const blockHeight = size * settings.line_spacing * lines.length;
    if (lines.length <= 14 && boxWidth >= size && Math.max(...lines.map((line) => line.length), 0) <= columns && centerY - blockHeight / 2 >= 64 && centerY + blockHeight / 2 <= 1216) return size;
  }
  return minSize;
}

function previewMotionStyle(visual: VisualSettings, duration: number, time: number): CSSProperties {
  const delta = { subtle: 0.04, normal: 0.08, strong: 0.12 }[visual.motion_intensity];
  const progress = Math.max(0, Math.min(1, time / Math.max(0.1, duration)));
  const eased = 0.5 - Math.cos(Math.PI * progress) / 2;
  let scale = 1;
  let x = 0;
  let y = 0;
  switch (visual.motion) {
    case "slow_zoom_in": scale = 1 + delta * eased; break;
    case "slow_zoom_out": scale = 1 + delta * (1 - eased); break;
    case "pan_left": scale = 1 + delta; x = -delta * 50 * eased; break;
    case "pan_right": scale = 1 + delta; x = delta * 50 * (1 - eased); break;
    case "pan_up": scale = 1 + delta; y = -delta * 50 * eased; break;
    case "pan_down": scale = 1 + delta; y = delta * 50 * (1 - eased); break;
    case "ken_burns": scale = 1 + delta * (0.35 + 0.65 * eased); x = -delta * 18 * eased; y = delta * 18 * (1 - eased); break;
    default: break;
  }
  return { transform: `translate(${x.toFixed(2)}%, ${y.toFixed(2)}%) scale(${scale.toFixed(4)})`, transformOrigin: "center" };
}

export default function MoodQuotesPage() {
  const router = useRouter();
  const backgroundVideo = useRef<HTMLVideoElement>(null);
  const musicAudio = useRef<HTMLAudioElement>(null);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saveRevisionRef = useRef(0);
  const musicWaitingOffsetRef = useRef(false);
  const musicSyncKeyRef = useRef("");
  const timelineGestureRef = useRef<{ id: string; mode: "move" | "resize-start" | "resize-end"; pointerId: number; originX: number; start: number; end: number; blocked: boolean } | null>(null);
  const musicGestureRef = useRef<{ pointerId: number; originX: number; offset: number } | null>(null);
  const timelineDraggedRef = useRef(false);
  const initialization = useRef<Promise<{ categories: Config; sources: SourceItem[]; projects: ProjectSummary[]; detail: ProjectDetail; id: string | null }> | null>(null);
  const thumbnailRequest = useRef(0);
  const thumbnailUrlRef = useRef("");
  const declinedManualQuoteEdit = useRef<string | null>(null);
  const styleUndoRef = useRef<{ visual: VisualSettings; text: VisualTextSettings; colors: { color: string; color2: string }; segmentStyles: Record<string, Pick<TextSegment, "animation" | "animation_duration">> } | null>(null);
  const [projectId, setProjectId] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [config, setConfig] = useState<Config | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [sourceLibrary, setSourceLibrary] = useState<SourceItem[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [generations, setGenerations] = useState<ProjectDetail["generations"]>([]);
  const [favorites, setFavorites] = useState<ProjectDetail["favorites"]>([]);
  const [renders, setRenders] = useState<Render[]>([]);
  const [activeGeneration, setActiveGeneration] = useState<string | null>(null);
  const [currentRenderId, setCurrentRenderId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [selected, setSelected] = useState<Quote | null>(null);
  const [composition, setComposition] = useState<Composition>(emptyComposition);
  const [step, setStep] = useState(1);
  const [categorySearch, setCategorySearch] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [job, setJob] = useState<MoodJob | null>(null);
  const [playhead, setPlayhead] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [selectedSegmentId, setSelectedSegmentId] = useState<string | null>(null);
  const [timelineZoom, setTimelineZoom] = useState(28);
  const [timelineSnap, setTimelineSnap] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [showSafeArea, setShowSafeArea] = useState(false);
  const [thumbnailUrl, setThumbnailUrl] = useState("");
  const [thumbnailLoading, setThumbnailLoading] = useState(false);
  const [thumbnailError, setThumbnailError] = useState("");

  const saveQueue = useRef<ReturnType<typeof createSerializedSaveQueue> | null>(null);
  if (!saveQueue.current) saveQueue.current = createSerializedSaveQueue();
  const refreshProjects = () => request<ProjectSummary[]>("/mood-projects").then(setProjects).catch(() => undefined);
  const enqueueDraftSave = (payload: Record<string, unknown>) => {
    if (!projectId) return Promise.resolve(null);
    return saveQueue.current!(() => request(`/mood-projects/${projectId}`, { method: "PATCH", body: JSON.stringify(payload) }));
  };
  const applyDetail = (detail: ProjectDetail) => {
    setDraft({ title: detail.project.title, category_id: detail.project.category_id, subcategory_id: detail.project.subcategory_id, custom_topic: detail.project.custom_topic,
      tone: detail.project.tone, perspective: detail.project.perspective, length: detail.project.length, language: detail.project.language, provider: detail.project.provider });
    setSelected(detail.project.selected_quote);
    setActiveGeneration(detail.generations.find((generation) => generation.quotes.some((quote) => quote.id === detail.project.selected_quote?.id))?.id || null);
    setCurrentRenderId(detail.project.current_render?.id || null);
    const normalized = normalizeComposition(detail.project.composition, detail.project.selected_quote);
    setComposition(normalized); setSelectedSegmentId(normalized.segments[0]?.id || null);
    const renderRows = detail.renders || [];
    setAssets(detail.assets); setQuotes(detail.quotes); setGenerations(detail.generations); setFavorites(detail.favorites);
    setRenders(detail.project.current_render && !renderRows.some((render) => render.id === detail.project.current_render?.id) ? [detail.project.current_render, ...renderRows] : renderRows);
    setJob(detail.project.latest_job && ["queued", "preparing", "rendering"].includes(detail.project.latest_job.status) ? detail.project.latest_job : null);
  };

  useEffect(() => {
    let alive = true;
    if (!initialization.current) {
      initialization.current = (async () => {
        const [categories, sources, savedProjects] = await Promise.all([
          request<Config>("/mood-quotes/categories"), request<SourceItem[]>("/sources"), request<ProjectSummary[]>("/mood-projects"),
        ]);
        const id = new URLSearchParams(window.location.search).get("id");
        const detail = id ? await request<ProjectDetail>(`/mood-projects/${id}`) : await request<ProjectDetail>("/mood-projects", { method: "POST", body: JSON.stringify({}) });
        return { categories, sources, projects: savedProjects, detail, id };
      })();
    }
    initialization.current.then(({ categories, sources, projects: savedProjects, detail, id }) => {
      if (!alive) return;
      setConfig(categories); setSourceLibrary(sources); setProjects(savedProjects);
      setProjectId(detail.project.id); applyDetail(detail); setLoaded(true);
      if (!id) router.replace(`/mood?id=${detail.project.id}`, { scroll: false });
      if (!id) void refreshProjects();
    }).catch((reason) => { if (alive) setError((reason as Error).message); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!loaded || !projectId || job && ["queued", "preparing", "rendering"].includes(job.status)) return;
    const revision = ++saveRevisionRef.current;
    const timer = setTimeout(async () => {
      saveTimerRef.current = null;
      setSaving(true);
      try {
        await enqueueDraftSave({ ...draft, selected_quote: selected, composition });
        setError("");
        void refreshProjects();
      } catch (reason) { setError((reason as Error).message); }
      finally { if (revision === saveRevisionRef.current) setSaving(false); }
    }, 500);
    saveTimerRef.current = timer;
    return () => {
      clearTimeout(timer);
      if (saveTimerRef.current === timer) saveTimerRef.current = null;
    };
  }, [loaded, projectId, draft, selected, composition, job]);

  useEffect(() => {
    if (!job) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await request<MoodJob>(`/mood-jobs/${job.id}`);
        if (!alive) return;
        setJob(next);
        if (["completed", "failed", "cancelled"].includes(next.status)) {
          setJob(next);
          const detail = await request<ProjectDetail>(`/mood-projects/${projectId}`);
          if (!alive) return;
          applyDetail(detail); setLoaded(true); setJob(next); setStep(next.status === "completed" ? 5 : 4); void refreshProjects();
          return;
        }
        timer = setTimeout(poll, 900);
      } catch (reason) { if (alive) setError((reason as Error).message); }
    };
    timer = setTimeout(poll, 600);
    return () => { alive = false; clearTimeout(timer); };
  }, [job?.id]);

  useEffect(() => {
    const assetId = composition.background.asset_id;
    if (step !== 3 || composition.background.kind !== "video" || !assetId) {
      thumbnailRequest.current++;
      thumbnailUrlRef.current = "";
      setThumbnailUrl(""); setThumbnailLoading(false); setThumbnailError("");
      return;
    }
    const requestId = ++thumbnailRequest.current;
    setThumbnailUrl(""); setThumbnailLoading(true); setThumbnailError("");
    const timer = setTimeout(() => {
      if (requestId !== thumbnailRequest.current) return;
      const frameTime = Math.max(0, Math.round(composition.background.video_start * 10) / 10);
      const url = `${API}/api/mood-assets/${assetId}/thumbnail?time=${frameTime}`;
      thumbnailUrlRef.current = url;
      setThumbnailUrl(url);
    }, 450);
    return () => { clearTimeout(timer); thumbnailRequest.current++; };
  }, [step, composition.background.kind, composition.background.asset_id, composition.background.video_start]);

  useEffect(() => {
    if (!playing) return;
    let last = performance.now();
    const timer = setInterval(() => {
      const now = performance.now();
      const elapsed = (now - last) / 1000;
      last = now;
      setPlayhead((time) => Math.min(composition.duration, time + elapsed));
    }, 33);
    return () => clearInterval(timer);
  }, [playing, composition.duration]);

  useEffect(() => {
    if (playing && playhead >= composition.duration) {
      setPlaying(false); setPlayhead(0); backgroundVideo.current?.pause(); musicAudio.current?.pause();
    }
  }, [playing, playhead, composition.duration]);

  useEffect(() => {
    if (step === 4 && playing && backgroundVideo.current?.paused) void backgroundVideo.current.play().catch(() => undefined);
  }, [step, playing]);

  useEffect(() => {
    if (!playing) return;
    if (composition.text_mode !== "sequential") return;
    const active = composition.segments.find((segment) => playhead >= segment.start && playhead < segment.end && segment.text.trim());
    if (active) setSelectedSegmentId((current) => current === active.id ? current : active.id);
  }, [playing, playhead, composition.text_mode, composition.segments]);

  useEffect(() => {
    const audio = musicAudio.current;
    const music = composition.music;
    const asset = assets.find((item) => item.id === music.asset_id);
    const span = musicPlaybackSpan(music, composition.duration, asset?.duration ?? null);
    const relativeTime = playhead - music.offset;
    const syncKey = `${asset?.id || ""}:${music.offset}:${music.trim_start}:${music.trim_end}:${music.loop}`;
    if (musicSyncKeyRef.current !== syncKey) {
      musicSyncKeyRef.current = syncKey;
      if (audio && audio.readyState >= 1) {
        const sourceSpan = Math.max(0.05, Math.min(music.trim_end, asset?.duration ?? music.trim_end) - music.trim_start);
        audio.currentTime = music.trim_start + (relativeTime < 0 ? 0 : music.loop ? relativeTime % sourceSpan : Math.min(relativeTime, sourceSpan));
      }
    }
    const audible = Boolean(playing && asset && !music.muted && music.volume > 0 && relativeTime >= 0 && relativeTime < span);
    const waitingForOffset = Boolean(playing && asset && !music.muted && music.volume > 0 && relativeTime < 0);
    let volume = audible ? music.volume : 0;
    if (audible && music.fade_in > 0 && relativeTime < music.fade_in) volume *= relativeTime / music.fade_in;
    if (audible && music.fade_out > 0 && relativeTime > span - music.fade_out) volume *= Math.max(0, (span - relativeTime) / music.fade_out);
    if (audio) {
      audio.volume = Math.max(0, Math.min(1, volume));
      if (waitingForOffset) {
        if (audio.paused) {
          audio.currentTime = music.trim_start;
          void audio.play().catch(() => undefined);
        }
      } else if (!audible) audio.pause();
      else if (musicWaitingOffsetRef.current) {
        audio.currentTime = music.trim_start;
        if (audio.paused) void audio.play().catch(() => undefined);
      }
      else if (audio.paused) {
        const sourceSpan = Math.max(0.05, music.trim_end - music.trim_start);
        audio.currentTime = music.trim_start + (music.loop ? relativeTime % sourceSpan : Math.min(relativeTime, sourceSpan));
        void audio.play().catch(() => undefined);
      }
    }
    musicWaitingOffsetRef.current = waitingForOffset;
    if (backgroundVideo.current) {
      backgroundVideo.current.muted = composition.background.mute_audio;
      backgroundVideo.current.volume = composition.background.audio_volume;
    }
  }, [assets, playing, playhead, composition.duration, composition.music, composition.background]);

  const selectedCategory = config?.categories.find((item) => item.id === draft.category_id);
  const filteredCategories = useMemo(() => config?.categories.filter((category) => `${category.name} ${category.description} ${category.subcategories.map((item) => item.name).join(" ")}`.toLowerCase().includes(categorySearch.toLowerCase())) || [], [config, categorySearch]);
  const activeRender = renders.find((item) => item.id === currentRenderId) || null;
  const selectedAsset = assets.find((item) => item.id === composition.background.asset_id);
  const selectedMusic = assets.find((item) => item.id === composition.music.asset_id);
  const selectedSegment = composition.segments.find((item) => item.id === selectedSegmentId) || null;
  const selectedSegmentIndex = selectedSegment ? composition.segments.findIndex((item) => item.id === selectedSegment.id) : -1;
  const timelinePixelsPerSecond = timelineZoom;
  const timelineWidth = Math.ceil(timelinePixelsPerSecond * composition.duration);
  const timelineTickStep = timelineZoom < 20 ? 5 : timelineZoom < 36 ? 2 : 1;
  const timelineTicks = Array.from({ length: Math.floor(composition.duration / timelineTickStep) + 1 }, (_, index) => index * timelineTickStep);
  const musicTimelineSpan = musicPlaybackSpan(composition.music, composition.duration, selectedMusic?.duration ?? null);
  const timelineRulerStyle = { width: timelineWidth, "--tick": `${timelinePixelsPerSecond}px` } as CSSProperties;
  const providerInfo = config?.providers[draft.provider];
  const moodIds = [draft.category_id, draft.subcategory_id, selected?.mood || ""];
  const visualPresets = config?.visual_presets || [];
  const recommendedVisualPresets = visualPresets.filter((preset) => preset.mood_recommendations.some((mood) => moodIds.includes(mood)));
  const recommendedPresetIds = new Set(recommendedVisualPresets.map((preset) => preset.id));
  const otherVisualPresets = visualPresets.filter((preset) => !recommendedPresetIds.has(preset.id));
  const isRunning = Boolean(job && ["queued", "preparing", "rendering"].includes(job.status));
  const invalidateRender = () => setRenders((items) => items.map((item) => item.id === currentRenderId && item.status === "completed" ? { ...item, status: "needs_render", review_status: "needs_review" } : item));
  const updateComposition = <K extends keyof Composition>(key: K, value: Composition[K]) => { invalidateRender(); setComposition((current) => ({ ...current, [key]: value })); };
  const updateText = <K extends keyof Composition["text"]>(key: K, value: Composition["text"][K]) => {
    invalidateRender();
    setComposition((current) => {
      const text = { ...current.text, [key]: value };
      let segments = current.segments;
      if (current.text_mode === "sequential" && key === "animation_in") segments = segments.map((segment) => ({ ...segment, animation: segmentAnimationForLegacy(String(value)) }));
      if (current.text_mode === "sequential" && key === "animation_duration") segments = segments.map((segment) => ({ ...segment, animation_duration: Math.max(0.1, Math.min(Number(value), (segment.end - segment.start) / 2)) }));
      if (current.text_mode === "sequential" && key === "text") {
        if (current.segments_source === "manual") return current;
        segments = makeTimedSegments(String(value), current.duration, current.visual.segment_animation, selected?.segments || []);
      }
      return { ...current, text, segments, segments_source: current.text_mode === "sequential" && key === "text" ? "auto" : current.segments_source };
    });
  };
  const updateBackground = <K extends keyof Composition["background"]>(key: K, value: Composition["background"][K]) => { invalidateRender(); setComposition((current) => ({ ...current, background: { ...current.background, [key]: value } })); };
  const updateMusic = <K extends keyof Composition["music"]>(key: K, value: Composition["music"][K]) => {
    const asset = assets.find((item) => item.id === composition.music.asset_id);
    const next = { ...composition.music, [key]: value };
    if (key === "offset" && (Number(value) < 0 || Number(value) >= composition.duration)) { setError("Posisi mulai musik harus berada di dalam durasi video."); return; }
    if ((key === "trim_start" || key === "trim_end") && (next.trim_start < 0 || next.trim_end - next.trim_start < 0.05 || Boolean(asset?.duration && next.trim_end > asset.duration))) { setError("Rentang trim harus menyisakan minimal 0,05 detik dan tidak boleh melewati durasi file musik."); return; }
    const available = musicPlaybackSpan(next, composition.duration, asset?.duration ?? null);
    if ((key === "offset" || key === "trim_start" || key === "trim_end" || key === "fade_in" || key === "fade_out" || key === "loop") && next.fade_in + next.fade_out > available + 0.001) {
      setError("Fade-in dan fade-out melebihi durasi musik yang terdengar. Kurangi fade atau ubah trim/offset."); return;
    }
    invalidateRender(); setError("");
    setComposition((current) => ({ ...current, music: { ...current.music, [key]: value } }));
  };
  const updateVisual = <K extends keyof VisualSettings>(key: K, value: VisualSettings[K]) => {
    invalidateRender();
    setComposition((current) => {
      const segments = key === "segment_animation" && current.text_mode === "sequential" && current.segments_source !== "manual"
        ? current.segments.map((segment) => ({ ...segment, animation: value as TextSegment["animation"] }))
        : current.segments;
      return { ...current, visual: { ...current.visual, [key]: value }, segments };
    });
  };
  const updateDuration = (duration: number) => {
    if (composition.text_mode === "sequential" && composition.segments.some((segment) => segment.end > duration)) {
      setError("Durasi baru memotong segmen. Perpanjang durasi atau atur timing segmen terlebih dahulu."); return;
    }
    if (composition.music.offset >= duration) { setError("Durasi baru memotong posisi mulai musik. Atur offset musik lebih awal terlebih dahulu."); return; }
    const musicAsset = assets.find((asset) => asset.id === composition.music.asset_id);
    const musicSpan = musicPlaybackSpan(composition.music, duration, musicAsset?.duration ?? null);
    if (composition.music.asset_id && composition.music.fade_in + composition.music.fade_out > musicSpan + 0.001) {
      setError("Durasi baru terlalu pendek untuk fade musik. Kurangi fade atau atur offset lebih awal."); return;
    }
    invalidateRender();
    setComposition((current) => {
      const start = Math.min(current.text.start, duration - 0.1);
      return { ...current, duration, text: { ...current.text, start, end: Math.max(start + 0.1, Math.min(current.text.end, duration)) } };
    });
  };

  const persist = async (nextDraft = draft, nextQuote = selected, nextComposition = composition) => {
    if (!projectId) return;
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = null;
    const revision = ++saveRevisionRef.current;
    setSaving(true);
    try {
      await enqueueDraftSave({ ...nextDraft, selected_quote: nextQuote, composition: nextComposition });
      void refreshProjects();
    } finally { if (revision === saveRevisionRef.current) setSaving(false); }
  };
  const saveBeforeNavigate = async (target: string) => {
    try { await persist(); window.location.assign(target); }
    catch (reason) { setError((reason as Error).message); }
  };
  const generate = async () => {
    if (!consent) { setError("Setujui pengiriman prompt quote ke provider untuk permintaan ini."); return; }
    setBusy(true); setError(""); setNotice("");
    try {
      await persist();
      const result = await request<{ id: string; provider: string; model: string; quotes: Quote[] }>(`/mood-projects/${projectId}/generate`, { method: "POST", body: JSON.stringify({ provider: draft.provider, consent: true }) });
      setQuotes(result.quotes); setActiveGeneration(result.id); setGenerations((items) => [{ id: result.id, provider: result.provider, model: result.model, created_at: new Date().toISOString(), quotes: result.quotes }, ...items]);
      setNotice(`Lima quote dibuat dengan ${result.provider} · ${result.model}.`); setStep(2); void refreshProjects();
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); setConsent(false); }
  };
  const selectQuote = (quote: Quote, generationId?: string | null) => {
    invalidateRender();
    const chosen = { ...quote, segments: quote.segments?.length ? quote.segments : [{ text: quote.text, order: 1 }] };
    setSelected(chosen);
    const duration = draft.length === "short" ? 8 : draft.length === "medium" ? 18 : 32;
    const segments = makeTimedSegments(chosen.text, duration, composition.visual.segment_animation, chosen.segments);
    setComposition((current) => {
      const offset = Math.min(current.music.offset, duration - 0.1);
      const available = musicPlaybackSpan({ ...current.music, offset }, duration, assets.find((asset) => asset.id === current.music.asset_id)?.duration ?? null);
      const fade_in = Math.min(current.music.fade_in, Math.max(0, available / 2));
      return { ...current, duration, segments, segments_source: "auto", music: { ...current.music, offset, fade_in, fade_out: Math.min(current.music.fade_out, Math.max(0, available - fade_in)) }, text: { ...current.text, text: chosen.text, start: 0, end: duration } };
    });
    setSelectedSegmentId(segments[0]?.id || null);
    declinedManualQuoteEdit.current = null;
    if (generationId) setActiveGeneration(generationId);
    setNotice(composition.music.offset >= duration ? "Quote dipilih. Offset musik disesuaikan agar tetap di dalam durasi baru." : "Quote dipilih. Editor video dapat digunakan tanpa generate ulang.");
  };
  const favorite = async (quote: Quote, generationId: string | null) => {
    try {
      const saved = await request<{ id: string; quote: Quote }>(`/mood-projects/${projectId}/favorites`, { method: "POST", body: JSON.stringify({ quote, generation_id: generationId }) });
      setFavorites((items) => items.some((item) => item.id === saved.id) ? items : [{ id: saved.id, generation_id: generationId, quote: saved.quote, created_at: new Date().toISOString() }, ...items]);
      setNotice("Quote tersimpan di Favorit.");
    } catch (reason) { setError((reason as Error).message); }
  };
  const editQuote = (quote: Quote, field: "title" | "text", value: string) => {
    if (field === "text" && selected?.id === quote.id && composition.text_mode === "sequential" && composition.segments_source === "manual") {
      if (declinedManualQuoteEdit.current === quote.id) return;
      if (!window.confirm("Teks quote berubah. Ganti segmen manual dengan segmentasi otomatis?")) {
        declinedManualQuoteEdit.current = quote.id;
        setNotice("Segmen manual dipertahankan. Reset segmentasi otomatis sebelum mengubah teks quote.");
        return;
      }
    }
    const editedSegments = field === "text" ? makeTimedSegments(value, composition.duration, composition.visual.segment_animation) : [];
    const next = { ...quote, [field]: value, segments: field === "text" ? editedSegments.map((segment, index) => ({ text: segment.text, order: index + 1 })) : quote.segments };
    setQuotes((items) => items.map((item) => item.id === quote.id ? next : item));
    if (selected?.id === quote.id) {
      setSelected(next);
      if (field === "text") {
        invalidateRender();
        setComposition((current) => current.text_mode === "single"
          ? { ...current, text: { ...current.text, text: value } }
          : { ...current, text: { ...current.text, text: value }, segments: editedSegments, segments_source: "auto" });
        declinedManualQuoteEdit.current = null;
      }
    }
  };

  const setTextMode = (mode: Composition["text_mode"]) => {
    if (mode === composition.text_mode) return;
    invalidateRender();
    setComposition((current) => {
      if (mode === "sequential") {
        const text = current.text.text || selected?.text || "";
        const segments = makeTimedSegments(text, current.duration, current.visual.segment_animation, selected?.text === text ? selected.segments : []);
        return { ...current, text_mode: mode, segments, segments_source: "auto", text: { ...current.text, text, start: segments[0]?.start || 0, end: segments[segments.length - 1]?.end || current.duration } };
      }
      const text = current.segments.map((item) => item.text).filter(Boolean).join(" ") || current.text.text;
      const start = current.segments.length ? Math.min(...current.segments.map((item) => item.start)) : current.text.start;
      const end = current.segments.length ? Math.max(...current.segments.map((item) => item.end)) : current.text.end;
      return { ...current, text_mode: mode, text: { ...current.text, text, start, end } };
    });
  };

  const commitTimelineSegments = (segments: TextSegment[], selectedId?: string | null) => {
    invalidateRender();
    setComposition((current) => ({ ...current, segments, segments_source: "manual", text: {
      ...current.text, text: segments.map((item) => item.text).join(" "),
      start: segments.length ? Math.min(...segments.map((item) => item.start)) : 0,
      end: segments.length ? Math.max(...segments.map((item) => item.end)) : current.duration,
    } }));
    if (selectedId !== undefined) setSelectedSegmentId(selectedId);
    setError("");
  };

  const updateSegment = (id: string, key: keyof TextSegment, value: string | number) => {
    if (key === "text") {
      const otherCharacters = composition.segments.filter((item) => item.id !== id).reduce((count, item) => count + item.text.length, 0);
      if (otherCharacters + String(value).length + composition.segments.length - 1 > 500) { setError("Gabungan teks segmen maksimal 500 karakter."); return; }
    }
    const segment = composition.segments.find((item) => item.id === id);
    if (!segment) return;
    if (key === "start" || key === "end") {
      const result = updateSegmentTiming(composition.segments, id, key === "start" ? "resize-start" : "resize-end", Number(value) - segment[key], composition.duration, { start: segment.start, end: segment.end }, false);
      if (result.blocked || result.clamped) { setError("Timing bentrok atau durasi segmen di bawah 0,5 detik. Segmen lain tidak digeser."); return; }
      commitTimelineSegments(result.segments, id);
      return;
    }
    if (key === "animation_duration" && Number(value) > Math.min(2, (segment.end - segment.start) / 2)) {
      setError("Durasi animasi maksimal setengah durasi segmen agar teks tetap terlihat."); return;
    }
    const segments = composition.segments.map((item) => item.id === id ? { ...item, [key]: value } as TextSegment : item);
    commitTimelineSegments(segments, id);
  };

  const reorderSegment = (index: number, direction: -1 | 1) => {
    const nextIndex = index + direction;
    if (nextIndex < 0 || nextIndex >= composition.segments.length) return;
    invalidateRender();
    setComposition((current) => {
      const slots = current.segments.map(({ start, end }) => ({ start, end }));
      const segments = [...current.segments];
      [segments[index], segments[nextIndex]] = [segments[nextIndex], segments[index]];
      const timed = segments.map((segment, slot) => ({ ...segment, ...slots[slot] }));
      return { ...current, segments: timed, segments_source: "manual", text: { ...current.text, text: timed.map((item) => item.text).join(" ") } };
    });
  };

  const addSegment = () => {
    if (composition.segments.length >= 8) { setError("Maksimal 8 segmen per video."); return; }
    const last = composition.segments[composition.segments.length - 1];
    if (last && last.end - last.start < 1) { setError("Butuh sedikitnya 1 detik untuk membagi segmen menjadi dua bagian yang terbaca."); return; }
    const end = last?.end ?? composition.duration;
    const start = last ? (last.start + last.end) / 2 : 0;
    const segments = [...composition.segments];
    if (last) segments[segments.length - 1] = { ...last, end: start, animation_duration: Math.min(last.animation_duration, (start - last.start) / 2) };
    const next = { id: newSegmentId(), text: "", start, end, animation: "fade_up" as const, animation_duration: Math.min(0.35, (end - start) / 2) };
    commitTimelineSegments([...segments, next], next.id);
  };

  const deleteSegment = (id: string) => {
    const segment = composition.segments.find((item) => item.id === id);
    if (!segment || !window.confirm(`Hapus teks segmen “${segment.text.slice(0, 80)}” dari hasil render? Quote asli tetap ada di draft.`)) return;
    const segments = composition.segments.filter((item) => item.id !== id);
    commitTimelineSegments(segments, segments[Math.min(composition.segments.findIndex((item) => item.id === id), segments.length - 1)]?.id || null);
  };

  const splitSelectedSegment = () => {
    if (composition.segments.length >= 8) { setError("Maksimal 8 segmen per video."); return; }
    const next = splitSegment(composition.segments, selectedSegmentId || "", composition.duration);
    if (!next) { setError("Teks perlu minimal empat kata dan durasi segmen minimal 1 detik untuk split aman."); return; }
    const index = next.findIndex((item) => item.id === selectedSegmentId);
    commitTimelineSegments(next, next[index + 1]?.id || selectedSegmentId);
  };

  const mergeSelectedSegment = (direction: -1 | 1) => {
    const next = mergeSegment(composition.segments, selectedSegmentId || "", direction);
    if (!next) { setError(direction < 0 ? "Tidak ada segmen sebelumnya untuk digabung." : "Tidak ada segmen berikutnya untuk digabung."); return; }
    const index = composition.segments.findIndex((item) => item.id === selectedSegmentId);
    commitTimelineSegments(next, next[Math.min(index, index + direction)]?.id || null);
  };

  const duplicateSelectedSegment = () => {
    if (composition.segments.length >= 8) { setError("Maksimal 8 segmen per video."); return; }
    const next = duplicateTimelineSegment(composition.segments, selectedSegmentId || "", composition.duration);
    if (!next) { setError("Tidak ada gap 0,5 detik untuk duplikat. Timing segmen lain tidak digeser."); return; }
    const index = next.findIndex((item) => item.id === selectedSegmentId);
    commitTimelineSegments(next, next[index + 1]?.id || next[index - 1]?.id || null);
  };

  const resetTimelineTiming = () => {
    const next = resetSegmentTimings(composition.segments, composition.duration);
    if (!next) { setError("Durasi komposisi terlalu pendek untuk jumlah segmen ini."); return; }
    commitTimelineSegments(next, selectedSegmentId);
    setNotice("Timing diratakan ulang; teks dan animasi tetap.");
  };

  const resetSegments = () => {
    const message = composition.segments_source === "manual"
      ? "Segmentasi ulang akan mengganti teks dan timing segmen manual. Quote asli draft tetap dipertahankan. Lanjutkan?"
      : "Buat ulang segmen otomatis? Edit timing dan animasi saat ini akan diganti.";
    if (!window.confirm(message)) return;
    const text = composition.text.text || selected?.text || "";
    const segments = makeTimedSegments(text, composition.duration, composition.visual.segment_animation, selected?.text === text ? selected.segments : []);
    invalidateRender();
    setComposition((current) => ({ ...current, text_mode: "sequential", segments, segments_source: "auto", text: { ...current.text, text, start: 0, end: current.duration } }));
    setSelectedSegmentId(segments[0]?.id || null);
    declinedManualQuoteEdit.current = null;
  };

  const goToSegment = (index: number) => {
    const segment = composition.segments[index];
    if (segment) seek(segment.start);
  };
  const uploadAsset = async (event: ChangeEvent<HTMLInputElement>, kind: Asset["kind"]) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const form = new FormData(); form.append("file", file); form.append("kind", kind);
    setBusy(true); setError("");
    try {
      const asset = await request<Asset>(`/mood-projects/${projectId}/assets`, { method: "POST", body: form });
      setAssets((items) => [asset, ...items]);
      if (kind === "music") {
        if (asset.duration !== null && asset.duration < 0.05) setError("File musik harus berdurasi minimal 0,05 detik.");
        else {
          invalidateRender();
          setComposition((current) => {
          const fileDuration = asset.duration || current.music.trim_end;
          const trim_start = Math.min(current.music.trim_start, Math.max(0, fileDuration - 0.05));
          const trim_end = Math.min(fileDuration, Math.max(trim_start + Math.min(0.05, fileDuration - trim_start), Math.min(current.music.trim_end, fileDuration)));
          const available = current.music.loop ? current.duration - current.music.offset : Math.min(current.duration - current.music.offset, trim_end - trim_start);
          const fade_in = Math.min(current.music.fade_in, Math.max(0, available / 2));
          return { ...current, music: { ...current.music, asset_id: asset.id, trim_start, trim_end, fade_in, fade_out: Math.min(current.music.fade_out, Math.max(0, available - fade_in)) } };
          });
        }
      }
      else { updateBackground("kind", kind === "background_image" ? "image" : "video"); updateBackground("asset_id", asset.id); }
      setNotice(`${file.name} tersimpan di aset lokal draft.`);
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); event.target.value = ""; }
  };
  const chooseSourceBackground = async (sourceId: string) => {
    if (!sourceId) return;
    setBusy(true); setError("");
    try {
      const asset = await request<Asset>(`/mood-projects/${projectId}/source-assets`, { method: "POST", body: JSON.stringify({ source_id: sourceId }) });
      setAssets((items) => items.some((item) => item.id === asset.id) ? items : [asset, ...items]);
      updateBackground("kind", "video"); updateBackground("asset_id", asset.id);
      setNotice("Video Source Library dipakai langsung; file asli tidak disalin.");
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };
  const chooseMusic = (assetId: string) => {
    const asset = assets.find((item) => item.id === assetId);
    if (!asset) { updateMusic("asset_id", null); return; }
    const duration = asset.duration || composition.music.trim_end;
    if (duration < 0.05) { setError("File musik harus berdurasi minimal 0,05 detik."); return; }
    setComposition((current) => {
      const start = Math.min(current.music.trim_start, Math.max(0, duration - 0.05));
      const end = Math.min(duration, Math.max(start + Math.min(0.05, duration - start), Math.min(current.music.trim_end, duration)));
      const available = current.music.loop ? current.duration - current.music.offset : Math.min(current.duration - current.music.offset, end - start);
      const fadeIn = Math.min(current.music.fade_in, Math.max(0, available / 2));
      const fadeOut = Math.min(current.music.fade_out, Math.max(0, available - fadeIn));
      return { ...current, music: { ...current.music, asset_id: asset.id, trim_start: start, trim_end: end, fade_in: fadeIn, fade_out: fadeOut } };
    });
    invalidateRender(); setError("");
  };
  const render = async () => {
    if (!selected) { setError("Pilih quote sebelum render."); setStep(2); return; }
    setBusy(true); setError(""); setNotice(""); setPlaying(false);
    try {
      await persist();
      const response = await request<{ id: string; render_id: string; status: string }>(`/mood-projects/${projectId}/render`, { method: "POST", body: JSON.stringify(composition) });
      setJob({ id: response.id, status: response.status, phase: response.status, progress: null, message: "Mood Quotes masuk antrean render" });
      setStep(4);
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };
  const cancel = async () => { if (!job) return; try { await request(`/mood-jobs/${job.id}/cancel`, { method: "POST" }); setNotice("Permintaan pembatalan render dikirim."); } catch (reason) { setError((reason as Error).message); } };
  const retry = async () => { if (!job) return; try { const next = await request<{ id: string; status: string }>(`/mood-jobs/${job.id}/retry`, { method: "POST" }); setJob({ id: next.id, status: next.status, phase: next.status, progress: null, message: "Retry render masuk antrean" }); } catch (reason) { setError((reason as Error).message); } };
  const review = async (status: "approved" | "needs_revision") => {
    if (!activeRender) return;
    try {
      await request(`/mood-renders/${activeRender.id}/review`, { method: "POST", body: JSON.stringify({ status }) });
      const detail = await request<ProjectDetail>(`/mood-projects/${projectId}`); applyDetail(detail); setNotice(status === "approved" ? "Video disetujui; file dapat diunduh." : "Status video: perlu revisi.");
    } catch (reason) { setError((reason as Error).message); }
  };
  const seek = (value: number) => {
    const next = Math.max(0, Math.min(composition.duration, value)); setPlayhead(next);
    if (backgroundVideo.current && selectedAsset && backgroundVideo.current.readyState >= 1) {
      const span = Math.max(0.05, (selectedAsset.duration || composition.background.video_start + 0.1) - composition.background.video_start);
      try { backgroundVideo.current.currentTime = composition.background.video_start + (composition.background.loop ? next % span : Math.min(next, span)); } catch { /* Metadata may still be loading. */ }
    }
    if (musicAudio.current && selectedMusic && musicAudio.current.readyState >= 1) {
      const relative = next - composition.music.offset;
      const span = Math.max(0.05, composition.music.trim_end - composition.music.trim_start);
      const playSpan = musicPlaybackSpan(composition.music, composition.duration, selectedMusic.duration);
      if (relative < 0 || relative >= playSpan && !composition.music.loop) {
        musicAudio.current.pause();
        try { musicAudio.current.currentTime = relative < 0 ? composition.music.trim_start : composition.music.trim_end; } catch { /* Metadata may still be loading. */ }
      } else {
        try { musicAudio.current.currentTime = composition.music.trim_start + (composition.music.loop ? relative % span : Math.min(relative, span)); } catch { /* Metadata may still be loading. */ }
      }
    }
  };
  const beginTimelineGesture = (event: ReactPointerEvent<HTMLElement>, id: string, mode: "move" | "resize-start" | "resize-end") => {
    if (isRunning || composition.text_mode !== "sequential") return;
    event.preventDefault(); event.stopPropagation();
    const segment = composition.segments.find((item) => item.id === id);
    if (!segment) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    timelineGestureRef.current = { id, mode, pointerId: event.pointerId, originX: event.clientX, start: segment.start, end: segment.end, blocked: false };
    setSelectedSegmentId(id);
  };
  const beginMusicGesture = (event: ReactPointerEvent<HTMLElement>) => {
    if (isRunning || !selectedMusic) return;
    event.preventDefault(); event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    musicGestureRef.current = { pointerId: event.pointerId, originX: event.clientX, offset: composition.music.offset };
  };
  const moveTimelineGesture = (event: ReactPointerEvent<HTMLElement>) => {
    const gesture = timelineGestureRef.current;
    if (gesture?.pointerId === event.pointerId) {
      const delta = (event.clientX - gesture.originX) / timelinePixelsPerSecond;
      if (Math.abs(event.clientX - gesture.originX) > 3) timelineDraggedRef.current = true;
      const result = updateSegmentTiming(composition.segments, gesture.id, gesture.mode, delta, composition.duration, { start: gesture.start, end: gesture.end }, timelineSnap);
      gesture.blocked = result.blocked || result.clamped;
      if (!result.blocked && result.changed) commitTimelineSegments(result.segments, gesture.id);
      return;
    }
    const musicGesture = musicGestureRef.current;
    if (musicGesture?.pointerId === event.pointerId) {
      const raw = musicGesture.offset + (event.clientX - musicGesture.originX) / timelinePixelsPerSecond;
      const boundaries = [0, composition.duration, ...composition.segments.flatMap((item) => [item.start, item.end])];
      const offset = Math.max(0, Math.min(Math.max(0, composition.duration - 0.1), timelineSnap ? snapTimelineTime(raw, boundaries) : raw));
      if (Math.abs(event.clientX - musicGesture.originX) > 3) timelineDraggedRef.current = true;
      if (offset !== composition.music.offset) updateMusic("offset", Number(offset.toFixed(3)));
    }
  };
  const endTimelineGesture = (event: ReactPointerEvent<HTMLElement>) => {
    const gesture = timelineGestureRef.current;
    if (gesture?.pointerId === event.pointerId) {
      timelineGestureRef.current = null;
      if (gesture.blocked) setNotice("Gerak dibatasi agar segmen tidak overlap; timing segmen lain tetap.");
    }
    if (musicGestureRef.current?.pointerId === event.pointerId) musicGestureRef.current = null;
    window.setTimeout(() => { timelineDraggedRef.current = false; }, 0);
  };
  const seekTimelinePointer = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    const rect = event.currentTarget.getBoundingClientRect();
    seek(timeAtPosition(event.clientX, rect.left, timelinePixelsPerSecond, composition.duration));
  };
  const selectTimelineSegment = (segment: TextSegment) => {
    if (timelineDraggedRef.current) { timelineDraggedRef.current = false; return; }
    setSelectedSegmentId(segment.id); seek(segment.start);
  };
  const startMusicPreview = (at = playhead) => {
    const audio = musicAudio.current;
    const music = composition.music;
    if (!audio || !selectedMusic || music.muted || music.volume <= 0) return;
    const relative = at - music.offset;
    const span = musicPlaybackSpan(music, composition.duration, selectedMusic.duration);
    if (relative >= span && !music.loop) return;
    const sourceSpan = Math.max(0.05, Math.min(music.trim_end, selectedMusic.duration || music.trim_end) - music.trim_start);
    audio.currentTime = music.trim_start + (relative <= 0 ? 0 : music.loop ? relative % sourceSpan : Math.min(relative, sourceSpan));
    let volume = relative < 0 ? 0 : music.volume;
    if (relative >= 0 && music.fade_in > 0 && relative < music.fade_in) volume *= relative / music.fade_in;
    if (relative >= 0 && music.fade_out > 0 && relative > span - music.fade_out) volume *= Math.max(0, (span - relative) / music.fade_out);
    audio.volume = volume;
    void audio.play().catch(() => setError("Browser memblokir preview audio. Tekan Play lagi untuk memberi izin audio."));
  };
  const togglePreview = async () => {
    if (playing) { setPlaying(false); backgroundVideo.current?.pause(); musicAudio.current?.pause(); return; }
    const startAt = playhead >= composition.duration ? 0 : playhead;
    if (playhead >= composition.duration) seek(0);
    setPlaying(true);
    const videoPlay = backgroundVideo.current?.play();
    startMusicPreview(startAt);
    try { await videoPlay; } catch { /* Image/solid preview uses local clock. */ }
  };
  const openFullPreview = (autoplay: boolean) => {
    void persist().catch((reason) => setError((reason as Error).message));
    setStep(4); setPlayhead(0); setPlaying(autoplay);
    if (autoplay) startMusicPreview(0);
  };
  const applyVisualPreset = (id: string) => {
    const preset = config?.visual_presets.find((item) => item.id === id);
    if (!preset) return;
    invalidateRender();
    styleUndoRef.current = {
      visual: composition.visual,
      text: Object.fromEntries(Object.keys(composition.text).filter((key) => key !== "text" && key !== "start" && key !== "end").map((key) => [key, composition.text[key as keyof Composition["text"]]])) as VisualTextSettings,
      colors: { color: composition.background.color, color2: composition.background.color2 },
      segmentStyles: Object.fromEntries(composition.segments.map((segment) => [segment.id, { animation: segment.animation, animation_duration: segment.animation_duration }])),
    };
    setComposition((current) => {
      const segments = current.text_mode === "sequential" && current.segments_source !== "manual"
        ? current.segments.map((segment) => ({ ...segment, animation: preset.effects.segment_animation, animation_duration: Math.min(preset.animation.duration, Math.max(0.1, (segment.end - segment.start) / 2)) }))
        : current.segments;
      const background = current.background.kind === "solid" || current.background.kind === "gradient"
        ? { ...current.background, ...preset.background }
        : current.background;
      return {
        ...current, background, segments,
        visual: { ...current.visual, ...preset.effects, preset_id: preset.id, schema_version: 1 },
        text: { ...current.text, ...preset.typography, animation_in: preset.animation.text_in, animation_out: preset.animation.text_out, animation_duration: preset.animation.duration },
      };
    });
    setNotice(`${preset.name} diterapkan. Quote, timing manual, aset background, dan musik tetap dipertahankan; palet solid/gradient mengikuti preset.`);
  };
  const undoVisualPreset = () => {
    const snapshot = styleUndoRef.current;
    if (!snapshot) return;
    invalidateRender();
    setComposition((current) => ({
      ...current,
      visual: snapshot.visual,
      text: { ...current.text, ...snapshot.text },
      background: { ...current.background, ...snapshot.colors },
      segments: current.segments.map((segment) => snapshot.segmentStyles[segment.id] ? { ...segment, ...snapshot.segmentStyles[segment.id] } : segment),
    }));
    styleUndoRef.current = null;
    setNotice("Style terakhir dibatalkan; teks, timing, aset, dan musik tetap dipertahankan.");
  };
  const resetVisualEffects = () => {
    invalidateRender();
    setComposition((current) => ({
      ...current,
      visual: { ...emptyComposition.visual },
      segments: current.text_mode === "sequential" && current.segments_source !== "manual"
        ? current.segments.map((segment) => ({ ...segment, animation: emptyComposition.visual.segment_animation }))
        : current.segments,
    }));
    styleUndoRef.current = null;
    setNotice("Efek visual dikembalikan ke default.");
  };
  const resetVisualStyle = () => {
    invalidateRender();
    setComposition((current) => {
      const text = { ...current.text, ...emptyComposition.text, text: current.text.text, start: current.text.start, end: current.text.end };
      const segments = current.text_mode === "sequential" && current.segments_source !== "manual"
        ? current.segments.map((segment) => ({ ...segment, animation: emptyComposition.visual.segment_animation, animation_duration: Math.min(0.45, Math.max(0.1, (segment.end - segment.start) / 2)) }))
        : current.segments;
      const background = current.background.kind === "solid" || current.background.kind === "gradient"
        ? { ...current.background, color: emptyComposition.background.color, color2: emptyComposition.background.color2 }
        : current.background;
      return { ...current, visual: { ...emptyComposition.visual }, text, segments, background };
    });
    styleUndoRef.current = null;
    setNotice("Visual style direset. Quote, timing, aset background, dan musik tidak berubah.");
  };
  const confirmProjectDelete = async () => {
    try { await request(`/mood-projects/${projectId}`, { method: "DELETE" }); setConfirmDelete(false); window.location.assign("/mood"); }
    catch (reason) { setError((reason as Error).message); setConfirmDelete(false); }
  };

  if (!loaded || !config) return <div className="loading-page">{error || "Menyiapkan Mood Quotes workspace…"}</div>;
  const animationStyle = (name: string, direction: "in" | "out") => {
    const keyframe = name === "fade" ? direction === "in" ? "moodFadeIn" : "moodFadeOut" : name === "slide_up" ? "moodSlideUp" : name === "slide_down" ? "moodSlideDown" : name === "zoom" ? "moodZoom" : name === "typewriter" ? "moodTypewriter" : "none";
    if (keyframe === "none") return "none";
    const visibleDuration = composition.text.end - composition.text.start;
    const animationDuration = name === "typewriter" ? Math.min(composition.text.animation_duration, visibleDuration) : Math.min(composition.text.animation_duration, visibleDuration / 2);
    const timing = name === "typewriter" ? `steps(${Math.max(1, composition.text.text.trim().split(/\s+/).length)}, end)` : direction === "in" ? "ease-out" : "ease-in";
    return `${keyframe} ${animationDuration}s ${timing} both`;
  };
  const activeSequenceSegment = composition.text_mode === "sequential" ? composition.segments.find((segment) => playhead >= segment.start && playhead < segment.end && segment.text.trim()) || null : null;
  const activeSegmentIndex = composition.text_mode === "sequential"
    ? activeSequenceSegment ? composition.segments.findIndex((segment) => segment.id === activeSequenceSegment.id) : composition.segments.findIndex((segment) => segment.start > playhead)
    : -1;
  const previousSegmentIndex = composition.text_mode !== "sequential" ? -1 : activeSequenceSegment ? activeSegmentIndex - 1 : activeSegmentIndex < 0 ? composition.segments.length - 1 : activeSegmentIndex - 1;
  const nextSegmentIndex = composition.text_mode !== "sequential" ? -1 : activeSequenceSegment ? activeSegmentIndex + 1 : activeSegmentIndex;
  const activeText = composition.text_mode === "sequential" ? activeSequenceSegment?.text || "" : composition.text.text;
  const activeStart = activeSequenceSegment?.start ?? composition.text.start;
  const activeEnd = activeSequenceSegment?.end ?? composition.text.end;
  const quoteActive = composition.text_mode === "sequential"
    ? Boolean(activeSequenceSegment)
    : playhead >= composition.text.start && playhead <= composition.text.end && Boolean(composition.text.text);
  const fadeDuration = Math.min(composition.text.animation_duration, (composition.text.end - composition.text.start) / 2);
  const segmentAnimationStyle = () => {
    if (!activeSequenceSegment || activeSequenceSegment.animation === "none") return "none";
    const { animation, animation_duration: rawDuration, start, end } = activeSequenceSegment;
    const animationDuration = Math.min(rawDuration, (end - start) / 2);
    const keyframe = animation === "fade_in" ? "moodFadeIn" : animation === "fade_out" ? "moodFadeOut" : animation === "fade_up" ? "moodFadeUp" : animation === "slide_up" ? "moodSlideUp" : "moodGentleScale";
    const animationStart = animation === "fade_out" ? end - animationDuration : start;
    return `${keyframe} ${animationDuration}s ease both|${-(playhead - animationStart)}s`;
  };
  const currentSegmentAnimation = segmentAnimationStyle();
  const splitAnimation = currentSegmentAnimation.split("|");
  const previewColor = previewTextColor(composition);
  const previewFontSize = fitPreviewFontSize(activeText || composition.text.text, composition.text);
  const sequenceWarningsNow = composition.text_mode === "sequential" ? sequenceWarnings(composition.segments, composition.duration) : [];
  const visualOverflowWarning = Boolean(activeText && quoteActive) && previewFontSize < composition.text.font_size * 0.74;
  const singleTextWarning = composition.text_mode === "single" && Boolean(composition.text.text) && (wordCount(composition.text.text) > 18 || visualOverflowWarning);
  const quotePreviewStyle = {
    left: `${composition.text.x}%`, top: `${composition.text.y}%`, width: `${Math.min(82, composition.text.x * 2, (100 - composition.text.x) * 2)}%`,
    color: previewColor, fontFamily: `"${composition.text.font}", Arial, sans-serif`,
    fontSize: `${previewFontSize / 7.2}cqw`, fontWeight: composition.text.font_weight, lineHeight: composition.text.line_spacing,
    opacity: composition.text.opacity / 100, textShadow: composition.text.shadow ? "0 1px 5px rgba(0,0,0,.7)" : undefined,
    "--mood-text-opacity": composition.text.opacity / 100,
    WebkitTextStroke: composition.text.outline ? "1px rgba(0,0,0,.8)" : undefined,
    animation: activeSequenceSegment ? splitAnimation[0] : `${animationStyle(composition.text.animation_in, "in")}, ${animationStyle(composition.text.animation_out, "out")}`,
    animationDelay: activeSequenceSegment ? splitAnimation[1] : `${-(playhead - composition.text.start)}s, ${-(playhead - Math.max(composition.text.start, composition.text.end - fadeDuration))}s`,
  } as CSSProperties;
  const textGradientStyle: CSSProperties = { background: `radial-gradient(ellipse at 50% ${composition.text.y}%, rgba(0,0,0,${composition.text.gradient_opacity / 100}) 0%, rgba(0,0,0,${composition.text.gradient_opacity / 150}) 38%, transparent 72%)` };
  const previewBackgroundStyle: CSSProperties = {
    background: composition.background.kind === "gradient"
      ? `linear-gradient(180deg, ${composition.background.color}, ${composition.background.color2})`
      : composition.background.kind === "solid" ? composition.background.color : undefined,
  };
  const visualFilter = `brightness(${Math.max(0.5, 1 + composition.visual.brightness).toFixed(3)}) contrast(${composition.visual.contrast.toFixed(3)}) saturate(${composition.visual.saturation.toFixed(3)})`;
  const backgroundMotion = ["image", "video"].includes(composition.background.kind) && selectedAsset
    ? previewMotionStyle(composition.visual, composition.duration, playhead)
    : {};
  const temperature = composition.visual.temperature;
  const visualLayers = <>
    {composition.visual.gradient_overlay_opacity > 0 && <div className="mood-atmosphere-gradient" style={{ background: `linear-gradient(180deg, ${composition.visual.gradient_top}, ${composition.visual.gradient_bottom})`, opacity: composition.visual.gradient_overlay_opacity / 100}}/>}
    {composition.visual.dark_overlay > 0 && <div className="mood-dark-overlay" style={{ opacity: composition.visual.dark_overlay}}/>}
    {temperature !== 0 && <div className="mood-temperature-overlay" style={{ background: temperature > 0 ? "#ff9d45" : "#6baeff", opacity: Math.abs(temperature) * 0.2}}/>}
    {composition.visual.vignette > 0 && <div className="mood-vignette" style={{ opacity: composition.visual.vignette}}/>}
    {composition.visual.grain > 0 && <div className="mood-film-grain" style={{ opacity: composition.visual.grain * 0.012}}/>}
  </>;
  const modeName = "AI Mood Quotes";

  return <>
    <div className="page-intro mood-intro"><Link href="/create" className="back-link"><ArrowLeft size={14}/> Semua mode</Link><div className="eyebrow">KLIPNARA STUDIO · {modeName.toUpperCase()}</div><h1>{draft.title || modeName}</h1><p>Pilih mood, susun quote, lalu buat video lokal tanpa memanggil AI saat edit atau render.</p></div>
    <div className="mood-workspace-head"><div className="mood-draft-picker"><label className="field"><span>Draft tersimpan</span><select value={projectId} onChange={(event) => { if (event.target.value && event.target.value !== projectId) void saveBeforeNavigate(`/mood?id=${event.target.value}`); }}><option value={projectId}>{draft.title || "Draft saat ini"}</option>{projects.filter((item) => item.id !== projectId).map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label><button type="button" className="button button-outline" onClick={() => void saveBeforeNavigate("/mood")}><Plus size={14}/> Draft baru</button></div><span className="autosave-state">{saving ? <><LoaderCircle size={13} className="spin"/> Menyimpan…</> : <><Check size={13}/> Autosave lokal</>}</span></div>
    <nav className="mood-steps" aria-label="Tahapan Mood Quotes">{["Pilih Mood", "Generate Quotes", "Customize", "Preview & Render", "Review & Export"].map((label, index) => <button key={label} type="button" className={step === index + 1 ? "active" : step > index + 1 ? "done" : ""} onClick={() => setStep(index + 1)}><i>{step > index + 1 ? <Check size={13}/> : index + 1}</i><span>{label}</span></button>)}</nav>
    {error && <div className="notice notice-error"><AlertCircle size={16}/><span>{error}</span><button className="icon-button" onClick={() => setError("")} aria-label="Tutup pesan"><X size={14}/></button></div>}
    {notice && <div className="notice notice-success"><CheckCircle2 size={16}/><span>{notice}</span><button className="icon-button" onClick={() => setNotice("")} aria-label="Tutup pesan"><X size={14}/></button></div>}
    <audio ref={musicAudio} src={selectedMusic ? `${API}${selectedMusic.url}` : undefined} preload="metadata" onLoadedMetadata={(event) => { if (playing) startMusicPreview(playhead); else event.currentTarget.currentTime = Math.min(composition.music.trim_start, Math.max(0, event.currentTarget.duration - 0.05)); }} onTimeUpdate={(event) => { if (selectedMusic && event.currentTarget.currentTime >= Math.min(composition.music.trim_end, selectedMusic.duration || composition.music.trim_end)) { if (composition.music.loop) event.currentTarget.currentTime = composition.music.trim_start; else event.currentTarget.pause(); } }} onError={() => { if (selectedMusic) setError("Browser tidak dapat memutar file musik. Pilih ulang atau upload file audio valid."); }}/>

    {step === 1 && <section className="panel mood-step-panel"><div className="step-heading"><span className="step-number">01</span><div><h2>Pilih mood dan gaya</h2><p>Kategori terstruktur, topik opsional, dan target komposisi.</p></div></div>
      <div className="mood-form-grid"><label className="field"><span>Nama draft</span><input maxLength={120} value={draft.title} onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))}/></label>
        <label className="field mood-search-field"><span>Cari mood/subkategori</span><input value={categorySearch} onChange={(event) => setCategorySearch(event.target.value)} placeholder="Cari kategori atau subkategori…"/></label>
        <label className="field"><span>Kategori mood</span><select value={draft.category_id} onChange={(event) => { const category = config.categories.find((item) => item.id === event.target.value); setDraft((current) => ({ ...current, category_id: event.target.value, subcategory_id: category?.subcategories[0]?.id || "" })); }}><option value="">Pilih kategori</option>{filteredCategories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select><small>{selectedCategory?.description}</small></label>
        <label className="field"><span>Subkategori</span><select value={draft.subcategory_id} onChange={(event) => setDraft((current) => ({ ...current, subcategory_id: event.target.value }))}>{selectedCategory?.subcategories.filter((item) => !categorySearch || item.name.toLowerCase().includes(categorySearch.toLowerCase()) || selectedCategory.name.toLowerCase().includes(categorySearch.toLowerCase())).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="field"><span>Topik kustom <small>Opsional</small></span><input maxLength={200} value={draft.custom_topic} onChange={(event) => setDraft((current) => ({ ...current, custom_topic: event.target.value }))} placeholder="Contoh: Semangat menghadapi interview kerja"/></label>
        <label className="field"><span>Gaya bahasa</span><select value={draft.tone} onChange={(event) => setDraft((current) => ({ ...current, tone: event.target.value }))}>{config.styles.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="field"><span>Sudut pandang</span><select value={draft.perspective} onChange={(event) => setDraft((current) => ({ ...current, perspective: event.target.value }))}>{config.perspectives.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="field"><span>Panjang konten</span><select value={draft.length} onChange={(event) => setDraft((current) => ({ ...current, length: event.target.value }))}>{config.lengths.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><small>Target komposisi, bukan jaminan jumlah kata.</small></label>
        <label className="field"><span>Bahasa</span><select value={draft.language} onChange={(event) => setDraft((current) => ({ ...current, language: event.target.value }))}>{config.languages.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      </div>
      <div className="mood-step-actions"><span><Save size={14}/> Draft tersimpan otomatis saat berpindah langkah.</span><button className="button button-primary" onClick={async () => { try { await persist(); setStep(2); } catch (reason) { setError((reason as Error).message); } }}>Lanjut ke quotes <ArrowRight size={15}/></button></div>
    </section>}

    {step === 2 && <section className="panel mood-step-panel"><div className="step-heading"><span className="step-number">02</span><div><h2>Lima alternatif quote</h2><p>Pilih, edit, simpan favorit, atau generate batch baru. Riwayat lama tetap tersimpan.</p></div></div>
      <div className="mood-provider-row"><label className="field"><span>Provider AI</span><select value={draft.provider} onChange={(event) => setDraft((current) => ({ ...current, provider: event.target.value as Draft["provider"] }))}><option value="gemini">Gemini · {config.providers.gemini.model}{config.providers.gemini.configured ? " · siap" : " · belum dikonfigurasi"}</option><option value="openai">OpenAI · {config.providers.openai.model}{config.providers.openai.configured ? " · siap" : " · belum dikonfigurasi"}</option></select></label><div className="provider-consent-note"><Cloud size={16}/><span>{config.consent_data}</span></div></div>
      <label className="mood-consent"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)}/><span>Saya setuju mengirim prompt ini ke <strong>{draft.provider}</strong>. Provider dapat memiliki biaya atau batas kuota; tidak ada provider fallback.</span></label>
      <div className="mood-step-actions quote-actions"><span>{quotes.length ? `${quotes.length} quote pada hasil terbaru` : "Belum ada hasil generate"}</span><button className="button button-primary" disabled={busy || !consent || !providerInfo?.configured} onClick={() => void generate()}>{busy ? <LoaderCircle size={15} className="spin"/> : <Sparkles size={15}/>} {quotes.length ? "Regenerate 5 Quotes" : "Generate 5 Quotes"}</button></div>
      {!providerInfo?.configured && <p className="mood-inline-warning">Provider ini belum dikonfigurasi. Isi API key di `backend/.env`; request tidak akan dialihkan ke provider lain.</p>}
      {quotes.length > 0 && <div className="quote-grid">{quotes.map((quote) => {
        const chosen = selected?.id === quote.id;
        const isFav = favorites.some((item) => item.quote.text.toLowerCase() === quote.text.toLowerCase());
        return <article className={`quote-card ${chosen ? "chosen" : ""}`} key={quote.id}><div className="quote-card-top"><span>ALTERNATIF {String(quotes.indexOf(quote) + 1).padStart(2, "0")}</span><button className={`icon-button ${isFav ? "favorite-active" : ""}`} title="Simpan favorit" onClick={() => void favorite(quote, activeGeneration)}><Heart size={15} fill={isFav ? "currentColor" : "none"}/></button></div><strong>{quote.title}</strong><p>{quote.text}</p><div className="quote-keywords">{quote.visual_keywords.map((word) => <i key={word}>{word}</i>)}</div><small>Musik: {quote.music_mood} · gaya: {quote.tone}</small><div className="quote-card-actions"><button type="button" className={`button ${chosen ? "button-primary" : "button-outline"}`} onClick={() => selectQuote(quote, activeGeneration)}>{chosen ? <Check size={14}/> : <ArrowRight size={14}/>} {chosen ? "Terpilih" : "Pilih quote"}</button><button type="button" className="button button-quiet" onClick={() => selectQuote(quote, activeGeneration)}>Edit</button></div>{chosen && <div className="quote-edit-fields"><label className="field"><span>Judul</span><input maxLength={80} value={quote.title} onChange={(event) => editQuote(quote, "title", event.target.value)}/></label><label className="field"><span>Teks final</span><textarea maxLength={360} rows={4} value={quote.text} onChange={(event) => editQuote(quote, "text", event.target.value)}/></label><button className="button button-outline" onClick={() => { setStep(3); setNotice("Quote dan edit tersimpan; lanjutkan video tanpa AI lagi."); }}>Gunakan quote di video <ArrowRight size={14}/></button></div>}</article>;
      })}</div>}
      {favorites.length > 0 && <details className="mood-history"><summary><Heart size={14}/> Favorit tersimpan · {favorites.length}</summary><div className="mood-history-list">{favorites.map((item) => <div key={item.id}><span><strong>{item.quote.title}</strong><small>{item.quote.text}</small></span><button className="button button-outline" onClick={() => selectQuote(item.quote, item.generation_id)}>Pilih</button><button className="icon-button" aria-label="Hapus favorit" onClick={async () => { try { await request(`/mood-projects/${projectId}/favorites/${item.id}`, { method: "DELETE" }); setFavorites((rows) => rows.filter((row) => row.id !== item.id)); } catch (reason) { setError((reason as Error).message); } }}><X size={14}/></button></div>)}</div></details>}
      {generations.length > 0 && <details className="mood-history"><summary><Clock3 size={14}/> Riwayat generate · {generations.length}</summary><div className="mood-history-list">{generations.map((generation) => <div key={generation.id}><span><strong>{generation.provider} · {generation.model}</strong><small>{new Date(generation.created_at).toLocaleString("id-ID")} · {generation.quotes.length} quote</small></span><button className="button button-outline" onClick={() => { setQuotes(generation.quotes); setActiveGeneration(generation.id); }}>Buka hasil</button></div>)}</div></details>}
      <div className="mood-step-actions"><button className="button button-outline" onClick={() => setStep(1)}><ArrowLeft size={14}/> Kembali</button><button className="button button-primary" disabled={!selected} onClick={() => setStep(3)}>Customize video <ArrowRight size={15}/></button></div>
    </section>}

    {step === 3 && <section className={`panel mood-step-panel mood-customize-step ${composition.text_mode === "sequential" ? "sequential-mode" : "single-mode"}`}><div className="step-heading"><span className="step-number">03</span><div><h2>Customize video</h2><p>Text Sequence, visual, timing, dan musik disimpan di draft lokal.</p></div></div>
      <div className="mood-customize-layout"><div className="mood-controls-column">
      <details open className="mood-control-group mood-preset-group"><summary><WandSparkles size={15}/> Smart Visual Presets</summary><p>Mood memberi rekomendasi; Visual Style tetap pilihanmu. Preset tidak mengubah aset atau musik.</p>
        {recommendedVisualPresets.length > 0 && <><h4>Direkomendasikan</h4><div className="mood-preset-grid">{recommendedVisualPresets.map((preset) => <button type="button" className={`mood-preset-card ${composition.visual.preset_id === preset.id ? "active" : ""}`} key={preset.id} onClick={() => applyVisualPreset(preset.id)}><i style={{ background: `linear-gradient(145deg, ${preset.preview.join(", ")})` }}/><span><strong>{preset.name}</strong><small>{preset.description} · Musik: {preset.recommended_music_mood}</small><em>Direkomendasikan</em></span></button>)}</div></>}
        <h4>Preset lainnya</h4><div className="mood-preset-grid">{otherVisualPresets.map((preset) => <button type="button" className={`mood-preset-card ${composition.visual.preset_id === preset.id ? "active" : ""}`} key={preset.id} onClick={() => applyVisualPreset(preset.id)}><i style={{ background: `linear-gradient(145deg, ${preset.preview.join(", ")})` }}/><span><strong>{preset.name}</strong><small>{preset.description} · Musik: {preset.recommended_music_mood}</small></span></button>)}</div>
        <div className="mood-preset-actions"><button type="button" className="button button-outline" disabled={!styleUndoRef.current} onClick={undoVisualPreset}><RotateCcw size={13}/> Undo preset</button><button type="button" className="button button-outline" onClick={resetVisualStyle}>Reset Visual Style</button></div>
      </details>
      <details open className="mood-sequence-editor mood-control-group"><summary><Sparkles size={15}/> Text Sequence</summary><div className="mood-sequence-heading"><label className="field"><span>Mode teks</span><select value={composition.text_mode} onChange={(event) => setTextMode(event.target.value as Composition["text_mode"])}><option value="sequential">Sequential Text</option><option value="single">Single Text</option></select></label></div>
        {composition.text_mode === "sequential" ? <details open className="mood-sequence-details"><summary>{composition.segments.length} segmen · otomatis lokal, bisa diedit</summary>
          {composition.segments.map((segment, index) => <article className="mood-segment-card" key={segment.id}><div className="mood-segment-card-head"><strong>Segment {String(index + 1).padStart(2, "0")} — {index === 0 ? "Hook" : index === composition.segments.length - 1 ? "Closing" : "Main Message"}</strong><div><button type="button" className="icon-button" aria-label="Naikkan urutan" disabled={index === 0} onClick={() => reorderSegment(index, -1)}>↑</button><button type="button" className="icon-button" aria-label="Turunkan urutan" disabled={index === composition.segments.length - 1} onClick={() => reorderSegment(index, 1)}>↓</button><button type="button" className="icon-button" aria-label="Hapus segmen" onClick={() => deleteSegment(segment.id)}><X size={13}/></button></div></div>
            <label className="field"><span>Teks segmen</span><textarea maxLength={500} rows={2} value={segment.text} onChange={(event) => updateSegment(segment.id, "text", event.target.value)}/></label>
            <div className="mood-segment-fields"><label className="field"><span>Mulai · {segment.start.toFixed(1)} dtk</span><input type="number" min="0" max={composition.duration} step="0.1" value={segment.start} onChange={(event) => updateSegment(segment.id, "start", Number(event.target.value))}/></label><label className="field"><span>Selesai · {segment.end.toFixed(1)} dtk</span><input type="number" min="0.1" max={composition.duration} step="0.1" value={segment.end} onChange={(event) => updateSegment(segment.id, "end", Number(event.target.value))}/></label></div>
            <div className="mood-segment-fields"><label className="field"><span>Animasi</span><select value={segment.animation} onChange={(event) => updateSegment(segment.id, "animation", event.target.value)}>{segmentAnimationOptions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label className="field"><span>Durasi transisi · {segment.animation_duration.toFixed(2)} dtk</span><input type="number" min="0.1" max={Math.max(0.1, Math.min(2, segment.end - segment.start))} step="0.05" value={segment.animation_duration} onChange={(event) => updateSegment(segment.id, "animation_duration", Number(event.target.value))}/></label></div>
          </article>)}
          <div className="mood-sequence-actions"><button type="button" className="button button-outline" onClick={addSegment} disabled={composition.segments.length >= 8}><Plus size={13}/> Tambah segmen</button><button type="button" className="button button-outline" onClick={resetSegments}>Segmentasi ulang</button></div>
          {sequenceWarningsNow.map((warning) => <p className="mood-inline-warning" key={warning}>{warning}</p>)}
          {visualOverflowWarning && <p className="mood-inline-warning">Teks preview perlu diperkecil mendekati batas aman; pecah segmen atau pindahkan teks agar tetap terbaca.</p>}
          {composition.segments_source === "manual" && <small>Quote utama berubah? Segment manual tidak akan ditimpa tanpa konfirmasi.</small>}
        </details> : <label className="field mood-single-text"><span>Teks tunggal</span><textarea maxLength={500} rows={4} value={composition.text.text} onChange={(event) => { updateText("text", event.target.value); if (selected) setSelected({ ...selected, text: event.target.value, segments: [{ text: event.target.value, order: 1 }] }); }}/></label>}
        {singleTextWarning && <p className="mood-inline-warning">Teks tunggal panjang atau mendekati batas ukuran aman. Pecah teks atau ubah ukuran/posisi tanpa melewati safe area.</p>}
        <label className="field"><span>Gradient gelap belakang teks · {composition.text.gradient_opacity}%</span><input type="range" min="0" max="80" step="5" value={composition.text.gradient_opacity} onChange={(event) => updateText("gradient_opacity", Number(event.target.value))}/></label>
        <label className="check-field"><input type="checkbox" checked={composition.text.auto_contrast} onChange={(event) => updateText("auto_contrast", event.target.checked)}/> Auto Contrast untuk background warna solid/gradient</label>
      </details>
      <div className="mood-editor-grid">
        <div className="mood-editor-stack">
          <details open className="mood-control-group mood-background-group"><summary><Video size={15}/> Background</summary><label className="field"><span>Jenis background</span><select value={composition.background.kind} onChange={(event) => { const kind = event.target.value as Composition["background"]["kind"]; updateBackground("kind", kind); if (kind === "solid" || kind === "gradient") updateBackground("asset_id", null); }}><option value="solid">Warna solid</option><option value="gradient">Gradient</option><option value="image">Gambar</option><option value="video">Video lokal</option></select></label>
          {(composition.background.kind === "solid" || composition.background.kind === "gradient") && <div className="color-pair"><label className="field"><span>{composition.background.kind === "gradient" ? "Warna awal" : "Warna"}</span><input type="color" value={composition.background.color} onChange={(event) => updateBackground("color", event.target.value)}/></label>{composition.background.kind === "gradient" && <label className="field"><span>Warna akhir</span><input type="color" value={composition.background.color2} onChange={(event) => updateBackground("color2", event.target.value)}/></label>}</div>}
          {composition.background.kind === "image" && <><label className="field"><span>Gambar tersimpan</span><select value={composition.background.asset_id || ""} onChange={(event) => updateBackground("asset_id", event.target.value || null)}><option value="">Pilih gambar</option>{assets.filter((asset) => asset.kind === "background_image").map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}</select></label><label className="asset-upload-button"><Upload size={14}/> Upload JPG, PNG, WebP<input type="file" accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp" onChange={(event) => void uploadAsset(event, "background_image")}/></label></>}
          {composition.background.kind === "video" && <><label className="field"><span>Video tersimpan</span><select value={composition.background.asset_id || ""} onChange={(event) => updateBackground("asset_id", event.target.value || null)}><option value="">Pilih video</option>{assets.filter((asset) => asset.kind === "background_video").map((asset) => <option key={asset.id} value={asset.id}>{asset.name} · {asset.duration ? formatDuration(asset.duration) : ""}</option>)}</select></label><label className="field"><span>Source Library · pakai file tanpa menyalin</span><select value="" onChange={(event) => void chooseSourceBackground(event.target.value)}><option value="">Pilih video tersimpan…</option>{sourceLibrary.map((source) => <option key={source.id} value={source.id}>{source.name} · {formatDuration(source.duration)}</option>)}</select></label><label className="asset-upload-button"><Upload size={14}/> Upload MP4/MOV<input type="file" accept="video/mp4,video/quicktime,.mp4,.mov" onChange={(event) => void uploadAsset(event, "background_video")}/></label><label className="field"><span>Mulai segmen (detik)</span><input type="number" min="0" max={selectedAsset?.duration || 14400} step="0.1" value={composition.background.video_start} onChange={(event) => updateBackground("video_start", Number(event.target.value))}/></label><label className="check-field"><input type="checkbox" checked={composition.background.loop} onChange={(event) => updateBackground("loop", event.target.checked)}/> Loop background video</label><label className="check-field"><input type="checkbox" checked={composition.background.mute_audio} onChange={(event) => updateBackground("mute_audio", event.target.checked)}/> Mute audio video</label>{!composition.background.mute_audio && <label className="field"><span>Volume audio video · {Math.round(composition.background.audio_volume * 100)}%</span><input type="range" min="0" max="1" step="0.05" value={composition.background.audio_volume} onChange={(event) => updateBackground("audio_volume", Number(event.target.value))}/></label>}</>}
        </details>
          <details open className="mood-control-group mood-cinematic-effects"><summary><Sparkles size={15}/> Cinematic Effects</summary>
          <div className="color-pair"><label className="field"><span>Effect Type</span><select value={composition.visual.motion} onChange={(event) => updateVisual("motion", event.target.value as VisualSettings["motion"])}><option value="none">None</option><option value="slow_zoom_in">Slow Zoom In</option><option value="slow_zoom_out">Slow Zoom Out</option><option value="pan_left">Pan Left</option><option value="pan_right">Pan Right</option><option value="pan_up">Pan Up</option><option value="pan_down">Pan Down</option><option value="ken_burns">Ken Burns</option></select></label><label className="field"><span>Motion Intensity</span><select value={composition.visual.motion_intensity} onChange={(event) => updateVisual("motion_intensity", event.target.value as VisualSettings["motion_intensity"])}><option value="subtle">Subtle</option><option value="normal">Normal</option><option value="strong">Strong</option></select></label></div>
          <div className="color-pair"><label className="field"><span>Brightness · {composition.visual.brightness.toFixed(2)}</span><input type="range" min="-0.3" max="0.3" step="0.01" value={composition.visual.brightness} onChange={(event) => updateVisual("brightness", Number(event.target.value))}/></label><label className="field"><span>Contrast · {composition.visual.contrast.toFixed(2)}</span><input type="range" min="0.5" max="1.5" step="0.05" value={composition.visual.contrast} onChange={(event) => updateVisual("contrast", Number(event.target.value))}/></label></div>
          <div className="color-pair"><label className="field"><span>Saturation · {composition.visual.saturation.toFixed(2)}</span><input type="range" min="0" max="2" step="0.05" value={composition.visual.saturation} onChange={(event) => updateVisual("saturation", Number(event.target.value))}/></label><label className="field"><span>Temperature · {composition.visual.temperature.toFixed(2)}</span><input type="range" min="-1" max="1" step="0.05" value={composition.visual.temperature} onChange={(event) => updateVisual("temperature", Number(event.target.value))}/></label></div>
          <div className="color-pair"><label className="field"><span>Vignette · {composition.visual.vignette.toFixed(2)}</span><input type="range" min="0" max="1" step="0.05" value={composition.visual.vignette} onChange={(event) => updateVisual("vignette", Number(event.target.value))}/></label><label className="field"><span>Film Grain · {composition.visual.grain}</span><input type="range" min="0" max="10" step="1" value={composition.visual.grain} onChange={(event) => updateVisual("grain", Number(event.target.value))}/></label></div>
          <div className="color-pair"><label className="field"><span>Dark Overlay · {Math.round(composition.visual.dark_overlay * 100)}%</span><input type="range" min="0" max="0.7" step="0.05" value={composition.visual.dark_overlay} onChange={(event) => updateVisual("dark_overlay", Number(event.target.value))}/></label><label className="field"><span>Gradient Overlay · {composition.visual.gradient_overlay_opacity}%</span><input type="range" min="0" max="60" step="5" value={composition.visual.gradient_overlay_opacity} onChange={(event) => updateVisual("gradient_overlay_opacity", Number(event.target.value))}/></label></div>
          <div className="color-pair"><label className="field"><span>Gradient atas</span><input type="color" value={composition.visual.gradient_top} onChange={(event) => updateVisual("gradient_top", event.target.value)}/></label><label className="field"><span>Gradient bawah</span><input type="color" value={composition.visual.gradient_bottom} onChange={(event) => updateVisual("gradient_bottom", event.target.value)}/></label></div>
          <div className="mood-preset-actions"><button type="button" className="button button-outline" onClick={resetVisualEffects}><RotateCcw size={13}/> Reset Effect</button><small>Preview mensimulasikan motion dengan transform; video background memakai thumbnail statis di editor.</small></div>
        </details>
        </div>
        <div className="mood-editor-stack">
          <details open className="mood-control-group mood-typography-group"><summary><Sparkles size={15}/> Text Sequence & Typography</summary>
          {composition.text_mode === "single" || composition.segments_source !== "manual" ? <label className="field"><span>Teks quote</span><textarea maxLength={500} rows={4} value={composition.text.text} onChange={(event) => { updateText("text", event.target.value); if (selected) setSelected({ ...selected, text: event.target.value, segments: [{ text: event.target.value, order: 1 }] }); }}/></label> : <p className="mood-inline-warning">Teks dirakit dari segmen manual. Edit teks per segmen; Segmentasi ulang meminta konfirmasi.</p>}
          <div className="color-pair"><label className="field"><span>Font sistem</span><select value={composition.text.font} onChange={(event) => updateText("font", event.target.value)}>{config.fonts.map((font) => <option key={font}>{font}</option>)}</select></label><label className="field"><span>Ukuran font ? {composition.text.font_size}px</span><input type="range" min="20" max="120" value={composition.text.font_size} onChange={(event) => updateText("font_size", Number(event.target.value))}/></label></div>
          <div className="color-pair"><label className="field"><span>Font weight ? {composition.text.font_weight}</span><input type="range" min="400" max="800" step="100" value={composition.text.font_weight} onChange={(event) => updateText("font_weight", Number(event.target.value))}/></label><label className="field"><span>Animasi segmen default</span><select value={composition.visual.segment_animation} onChange={(event) => updateVisual("segment_animation", event.target.value as TextSegment["animation"])}>{segmentAnimationOptions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label></div>
          <div className="color-pair"><label className="field"><span>Warna teks</span><input type="color" value={composition.text.color} onChange={(event) => updateText("color", event.target.value)}/></label><label className="field"><span>Perataan</span><select value={composition.text.alignment} onChange={(event) => updateText("alignment", event.target.value as Composition["text"]["alignment"])}><option value="left">Kiri</option><option value="center">Tengah</option><option value="right">Kanan</option></select></label></div>
          <label className="field"><span>Posisi horizontal ? {composition.text.x}%</span><input type="range" min="5" max="95" value={composition.text.x} onChange={(event) => updateText("x", Number(event.target.value))}/></label><label className="field"><span>Posisi vertikal ? {composition.text.y}%</span><input type="range" min="8" max="92" value={composition.text.y} onChange={(event) => updateText("y", Number(event.target.value))}/></label>
          <label className="field"><span>Line spacing ? {composition.text.line_spacing.toFixed(2)}</span><input type="range" min="0.8" max="2.2" step="0.05" value={composition.text.line_spacing} onChange={(event) => updateText("line_spacing", Number(event.target.value))}/></label><label className="field"><span>Opacity ? {composition.text.opacity}%</span><input type="range" min="10" max="100" value={composition.text.opacity} onChange={(event) => updateText("opacity", Number(event.target.value))}/></label>
          <div className="check-row"><label className="check-field"><input type="checkbox" checked={composition.text.shadow} onChange={(event) => updateText("shadow", event.target.checked)}/> Shadow</label><label className="check-field"><input type="checkbox" checked={composition.text.outline} onChange={(event) => updateText("outline", event.target.checked)}/> Outline</label></div>
          <div className="color-pair"><label className="field"><span>Animasi masuk</span><select value={composition.text.animation_in} onChange={(event) => updateText("animation_in", event.target.value)}>{animationOptions.map((option) => <option key={option.id} value={option.id}>{option.name}</option>)}</select></label><label className="field"><span>Animasi keluar</span><select value={composition.text.animation_out} onChange={(event) => updateText("animation_out", event.target.value)}><option value="fade">Fade Out</option><option value="none">Tanpa animasi</option></select></label></div>
          <label className="field"><span>Durasi animasi ? {composition.text.animation_duration.toFixed(1)} dtk</span><input type="range" min="0.1" max="5" step="0.1" value={composition.text.animation_duration} onChange={(event) => updateText("animation_duration", Number(event.target.value))}/></label>
          {composition.text_mode === "single" && <div className="color-pair"><label className="field"><span>Teks muncul (detik)</span><input type="number" min="0" max={composition.duration - 0.1} step="0.1" value={composition.text.start} onChange={(event) => updateText("start", Number(event.target.value))}/></label><label className="field"><span>Teks hilang (detik)</span><input type="number" min={composition.text.start + 0.1} max={composition.duration} step="0.1" value={composition.text.end} onChange={(event) => updateText("end", Number(event.target.value))}/></label></div>}
        </details>
          <details open className="mood-control-group mood-music-group"><summary><Music2 size={15}/> Music</summary><label className="field"><span>Suasana rekomendasi</span><select value={selected?.music_mood || "calm"} onChange={() => undefined} disabled><option>{selected?.music_mood || "calm"}</option></select><small>Label rekomendasi saja; tidak mengunduh musik.</small></label><label className="field"><span>Audio lokal</span><select value={composition.music.asset_id || ""} onChange={(event) => chooseMusic(event.target.value)}><option value="">Tanpa musik</option>{assets.filter((asset) => asset.kind === "music").map((asset) => <option key={asset.id} value={asset.id}>{asset.name} · {asset.duration ? formatDuration(asset.duration) : ""}</option>)}</select></label><label className="asset-upload-button"><Upload size={14}/> Upload MP3, WAV, M4A<input type="file" accept="audio/mpeg,audio/wav,audio/mp4,.mp3,.wav,.m4a" onChange={(event) => void uploadAsset(event, "music")}/></label>{selectedMusic && <><label className="field"><span>Trim awal · {composition.music.trim_start.toFixed(1)} dtk</span><input type="range" min="0" max={Math.max(0, (selectedMusic.duration || 1) - 0.1)} step="0.1" value={Math.min(composition.music.trim_start, Math.max(0, (selectedMusic.duration || 1) - 0.1))} onChange={(event) => updateMusic("trim_start", Number(event.target.value))}/></label><label className="field"><span>Trim akhir (detik)</span><input type="number" min={composition.music.trim_start + 0.1} max={selectedMusic.duration || 1} step="0.1" value={Math.min(composition.music.trim_end, selectedMusic.duration || composition.music.trim_end)} onChange={(event) => updateMusic("trim_end", Number(event.target.value))}/></label><label className="field"><span>Volume musik · {Math.round(composition.music.volume * 100)}%</span><input type="range" min="0" max="1" step="0.05" value={composition.music.volume} onChange={(event) => updateMusic("volume", Number(event.target.value))}/></label><div className="color-pair"><label className="field"><span>Fade in · dtk</span><input type="number" min="0" max="10" step="0.1" value={composition.music.fade_in} onChange={(event) => updateMusic("fade_in", Number(event.target.value))}/></label><label className="field"><span>Fade out · dtk</span><input type="number" min="0" max="10" step="0.1" value={composition.music.fade_out} onChange={(event) => updateMusic("fade_out", Number(event.target.value))}/></label></div><label className="check-field"><input type="checkbox" checked={composition.music.loop} onChange={(event) => updateMusic("loop", event.target.checked)}/> Loop musik jika lebih pendek</label></>}</details>
        </div>
      </div>
        {selectedMusic && <div className="mood-music-timeline-controls"><label className="field"><span>Music start offset · {composition.music.offset.toFixed(2)} dtk</span><input type="number" min="0" max={Math.max(0, composition.duration - 0.1)} step="0.05" value={composition.music.offset} onChange={(event) => updateMusic("offset", Number(event.target.value))}/></label><button type="button" className="button button-outline" onClick={() => updateMusic("muted", !composition.music.muted)}>{composition.music.muted ? <VolumeX size={14}/> : <Volume2 size={14}/>} {composition.music.muted ? "Unmute musik" : "Mute musik"}</button><button type="button" className="button button-outline" onClick={() => void togglePreview()}>{playing ? <Pause size={14}/> : <Play size={14}/>} {playing ? "Pause preview" : "Play preview"}</button></div>}
      <p className="mood-rights-note"><LockKeyhole size={14}/> Pastikan kamu memiliki hak penggunaan footage dan musik yang diunggah. Klipnara tidak menyertakan atau mengunduh media berhak cipta.</p>
      </div>
      <aside className="mood-live-preview panel" aria-label="Live Preview Mood Quotes">
        <div className="mood-live-preview-heading"><div><span className="eyebrow">LIVE COMPOSITION</span><h3>Preview Langsung</h3></div><label className="mood-safe-toggle"><input type="checkbox" checked={showSafeArea} onChange={(event) => setShowSafeArea(event.target.checked)}/> Safe Area</label></div>
        <div className="mood-live-canvas">
          {(composition.background.kind === "solid" || composition.background.kind === "gradient") && <div className="mood-background-base" style={{ ...previewBackgroundStyle, filter: visualFilter }} />}
          {composition.background.kind === "image" && selectedAsset && <img className="mood-live-bg" style={{ ...backgroundMotion, filter: visualFilter }} src={`${API}${selectedAsset.url}`} alt="Background gambar Mood Quotes"/>}
          {composition.background.kind === "video" && thumbnailUrl && <img key={thumbnailUrl} className="mood-live-bg" style={{ ...backgroundMotion, filter: visualFilter }} src={thumbnailUrl} alt={`Frame background pada ${composition.background.video_start.toFixed(1)} detik`} onLoad={(event) => { if (event.currentTarget.currentSrc === thumbnailUrlRef.current) { setThumbnailLoading(false); setThumbnailError(""); } }} onError={(event) => { if (event.currentTarget.currentSrc === thumbnailUrlRef.current) { setThumbnailLoading(false); setThumbnailError("Frame tidak dapat dimuat."); } }} />}
          {(composition.background.kind === "image" || composition.background.kind === "video") && !selectedAsset && <div className="mood-live-placeholder"><Video size={22}/><strong>Pilih background</strong><span>Upload atau pilih media lokal untuk melihat preview.</span></div>}
          {composition.background.kind === "video" && selectedAsset && thumbnailLoading && <div className="mood-thumbnail-skeleton"><LoaderCircle size={18} className="spin"/><span>Mengambil frame preview…</span></div>}
          {composition.background.kind === "video" && selectedAsset && thumbnailError && <div className="mood-live-placeholder"><AlertCircle size={20}/><strong>Preview frame gagal</strong><span>{thumbnailError}</span></div>}
          {visualLayers}
          {composition.text.gradient_opacity > 0 && <div className="mood-text-gradient" style={textGradientStyle}/>}
          {quoteActive && activeText && <div key={activeSequenceSegment?.id || "single-live"} className={`mood-live-quote align-${composition.text.alignment}`} style={quotePreviewStyle}>{activeText}</div>}
          {showSafeArea && <div className="mood-safe-guide" aria-hidden="true"><span>SAFE AREA · PANDUAN</span></div>}
          <span className="mood-live-ratio">9:16 · {composition.resolution === "720" ? "720 × 1280" : "1080 × 1920"}</span>
        </div>
        {showSafeArea && <small className="mood-safe-note">Panduan margin konservatif; area kontrol tiap platform berbeda. Garis panduan tidak masuk ke hasil render.</small>}
        <div className="mood-live-meta"><span><Clock3 size={13}/>{playhead.toFixed(1)} / {composition.duration}s · {activeSequenceSegment ? `segmen ${activeSegmentIndex + 1} · ${activeStart.toFixed(1)}–${activeEnd.toFixed(1)}s` : composition.text_mode === "single" ? `teks ${composition.text.start.toFixed(1)}–${composition.text.end.toFixed(1)}s` : "tanpa teks pada playhead"}</span><span>{composition.background.kind === "video" ? "Preview visual · frame statis" : "Preview visual langsung"}</span></div>
        <div className="mood-live-audio"><Music2 size={14}/><span>{selectedMusic ? `${selectedMusic.name} · musik ${composition.music.volume === 0 ? "0% (mute)" : `${Math.round(composition.music.volume * 100)}%`}${composition.background.kind === "video" && !composition.background.mute_audio && selectedAsset?.has_audio ? ` · background ${Math.round(composition.background.audio_volume * 100)}%` : ""}` : composition.background.kind === "video" && !composition.background.mute_audio && selectedAsset?.has_audio ? `${selectedAsset.name} · audio background ${Math.round(composition.background.audio_volume * 100)}%` : "Belum ada file musik terpilih. Mood hanya rekomendasi; output akan memakai audio background atau silent AAC."}</span></div>
        <div className="mood-live-timeline"><div><button type="button" className="button button-outline" onClick={() => void togglePreview()}>{playing ? <X size={14}/> : <Play size={14}/>} {playing ? "Pause" : "Play"}</button><button type="button" className="button button-outline" disabled={previousSegmentIndex < 0} onClick={() => goToSegment(previousSegmentIndex)}>Segmen sebelumnya</button><button type="button" className="button button-outline" disabled={nextSegmentIndex < 0 || nextSegmentIndex >= composition.segments.length} onClick={() => goToSegment(nextSegmentIndex)}>Segmen berikutnya</button><button type="button" className="button button-outline" onClick={() => { const start = activeSequenceSegment?.start ?? 0; seek(start); setPlaying(true); startMusicPreview(start); }}><RotateCcw size={13}/> Replay</button></div><input aria-label="Timeline preview Customize" type="range" min="0" max={composition.duration} step="0.1" value={playhead} onChange={(event) => seek(Number(event.target.value))}/></div>
        {composition.background.kind === "video" && <small className="mood-thumbnail-note">Frame diambil pada {composition.background.video_start.toFixed(1)}s; motion dan audio diperiksa di preview penuh.</small>}
        <div className="mood-live-actions"><button type="button" className="button button-outline" disabled={!selected} onClick={() => openFullPreview(true)}><Play size={14}/> Preview Penuh</button><button type="button" className="button button-primary" disabled={!selected} onClick={() => openFullPreview(false)}>Lanjut ke Preview &amp; Render <ArrowRight size={14}/></button></div>
      </aside>
      <details className="mood-timeline-panel" open>
        <summary><span><Clock3 size={15}/> Visual Timeline Editor</span><small>{composition.duration.toFixed(1)} dtk · {composition.segments.length} segmen · satu komposisi untuk preview/render</small></summary>
        <div className="mood-timeline-toolbar">
          <div><button type="button" className="button button-outline" onClick={() => void togglePreview()}>{playing ? <Pause size={14}/> : <Play size={14}/>} {playing ? "Pause" : "Play"}</button><button type="button" className="button button-outline" onClick={() => { seek(0); setPlaying(true); startMusicPreview(0); const videoPlay = backgroundVideo.current?.play(); void videoPlay?.catch(() => undefined); }}><RotateCcw size={13}/> Replay</button><span className="mood-timeline-clock">{playhead.toFixed(2)} / {composition.duration.toFixed(2)} dtk</span></div>
          <div><label className="mood-timeline-snap"><input type="checkbox" checked={timelineSnap} onChange={(event) => setTimelineSnap(event.target.checked)}/> Snap</label><button type="button" className="icon-button" aria-label="Perkecil timeline" onClick={() => setTimelineZoom((value) => Math.max(12, value / 1.3))}><ZoomOut size={15}/></button><input className="mood-timeline-zoom" aria-label="Zoom timeline" type="range" min="12" max="120" step="2" value={Math.max(12, Math.min(120, timelineZoom))} onChange={(event) => setTimelineZoom(Number(event.target.value))}/><button type="button" className="icon-button" aria-label="Perbesar timeline" onClick={() => setTimelineZoom((value) => Math.min(120, value * 1.3))}><ZoomIn size={15}/></button></div>
        </div>
        <div className="mood-timeline-scroll" onPointerMove={moveTimelineGesture} onPointerUp={endTimelineGesture} onPointerCancel={endTimelineGesture}>
          <div className="mood-timeline-grid" style={{ gridTemplateColumns: `112px ${timelineWidth}px` }}>
            <div className="mood-timeline-label mood-timeline-ruler-label">WAKTU</div>
            <div className="mood-timeline-ruler mood-timeline-track" style={timelineRulerStyle} onPointerDown={seekTimelinePointer}>
              {timelineTicks.map((tick) => <span className="mood-timeline-tick" key={tick} style={{ left: tick * timelinePixelsPerSecond }}>{tick}s</span>)}
              <i className="mood-timeline-playhead" style={{ left: playhead * timelinePixelsPerSecond }} />
            </div>
            <div className="mood-timeline-label">TEXT TRACK<small>{composition.text_mode === "single" ? "Single Text" : "Sequential Text"}</small></div>
            <div className="mood-timeline-track mood-timeline-text-track" style={{ width: timelineWidth }} onPointerDown={seekTimelinePointer}>
              {timelineTicks.map((tick) => <i className="mood-timeline-gridline" key={tick} style={{ left: tick * timelinePixelsPerSecond }} />)}
              {composition.text_mode === "sequential" ? composition.segments.map((segment, index) => <div className={`mood-timeline-segment ${selectedSegmentId === segment.id ? "selected" : ""} ${activeSequenceSegment?.id === segment.id ? "active" : ""}`} key={segment.id} style={{ left: segment.start * timelinePixelsPerSecond, width: Math.max(12, (segment.end - segment.start) * timelinePixelsPerSecond) }}>
                <button type="button" className="mood-timeline-segment-body" aria-label={`Pilih segmen ${index + 1}: ${segment.text || "kosong"}`} aria-pressed={selectedSegmentId === segment.id} onPointerDown={(event) => beginTimelineGesture(event, segment.id, "move")} onClick={() => selectTimelineSegment(segment)}><strong>{String(index + 1).padStart(2, "0")}</strong><span>{segment.text || "Segmen kosong"}</span></button>
                <button type="button" className="mood-timeline-resize start" aria-label={`Ubah waktu mulai segmen ${index + 1}`} onPointerDown={(event) => beginTimelineGesture(event, segment.id, "resize-start")} />
                <button type="button" className="mood-timeline-resize end" aria-label={`Ubah waktu akhir segmen ${index + 1}`} onPointerDown={(event) => beginTimelineGesture(event, segment.id, "resize-end")} />
              </div>) : <div className={`mood-timeline-single ${playhead >= composition.text.start && playhead < composition.text.end ? "active" : ""}`} style={{ left: composition.text.start * timelinePixelsPerSecond, width: Math.max(12, (composition.text.end - composition.text.start) * timelinePixelsPerSecond) }}><span>{composition.text.text || "Belum ada teks"}</span></div>}
              <i className="mood-timeline-playhead" style={{ left: playhead * timelinePixelsPerSecond }} />
            </div>
            <div className="mood-timeline-label">BACKGROUND<small>{selectedAsset?.name || (composition.background.kind === "gradient" ? "Gradient" : composition.background.kind === "solid" ? "Warna solid" : "Belum dipilih")}</small></div>
            <div className="mood-timeline-track mood-timeline-background-track" style={{ width: timelineWidth }} onPointerDown={seekTimelinePointer}>
              {timelineTicks.map((tick) => <i className="mood-timeline-gridline" key={tick} style={{ left: tick * timelinePixelsPerSecond }} />)}
              <div className="mood-timeline-background-clip"><strong>{composition.background.kind.toUpperCase()} · {composition.visual.motion.replaceAll("_", " ")}</strong><span>{composition.visual.motion_intensity} motion · {composition.visual.preset_id || "custom style"}</span></div>
              <i className="mood-timeline-playhead" style={{ left: playhead * timelinePixelsPerSecond }} />
            </div>
            <div className="mood-timeline-label">MUSIC TRACK<small>{selectedMusic ? selectedMusic.name : "Belum ada musik"}</small></div>
            <div className="mood-timeline-track mood-timeline-music-track" style={{ width: timelineWidth }} onPointerDown={seekTimelinePointer}>
              {timelineTicks.map((tick) => <i className="mood-timeline-gridline" key={tick} style={{ left: tick * timelinePixelsPerSecond }} />)}
              {selectedMusic && musicTimelineSpan > 0 && <div className={`mood-timeline-music-clip ${composition.music.muted ? "muted" : ""}`} style={{ left: composition.music.offset * timelinePixelsPerSecond, width: Math.max(12, musicTimelineSpan * timelinePixelsPerSecond) }} onPointerDown={beginMusicGesture}>
                {composition.music.fade_in > 0 && <i className="mood-timeline-fade-in" style={{ width: `${Math.min(100, composition.music.fade_in / Math.max(0.1, musicTimelineSpan) * 100)}%` }} />}{composition.music.fade_out > 0 && <i className="mood-timeline-fade-out" style={{ width: `${Math.min(100, composition.music.fade_out / Math.max(0.1, musicTimelineSpan) * 100)}%` }} />}
                <span><strong>{selectedMusic.name}</strong> · trim {composition.music.trim_start.toFixed(1)}–{Math.min(composition.music.trim_end, selectedMusic.duration || composition.music.trim_end).toFixed(1)}s · {composition.music.muted ? "mute" : `${Math.round(composition.music.volume * 100)}%`}</span>
              </div>}
              <i className="mood-timeline-playhead" style={{ left: playhead * timelinePixelsPerSecond }} />
            </div>
          </div>
        </div>
        <div className="mood-timeline-bottom-controls">
          <input aria-label="Timeline playhead" type="range" min="0" max={composition.duration} step="0.01" value={playhead} onChange={(event) => seek(Number(event.target.value))}/>
          <span>Background track 9:16 · {composition.duration.toFixed(1)} dtk · preview video memakai frame statis</span>
        </div>
        {selectedSegment && composition.text_mode === "sequential" && <section className="mood-timeline-properties" aria-label="Properti segmen terpilih">
          <div className="mood-timeline-properties-heading"><strong>Properti segmen {selectedSegmentIndex + 1}</strong><span>Style teks global tetap berlaku</span></div>
          <label className="field mood-timeline-property-text"><span>Teks</span><textarea rows={2} maxLength={500} value={selectedSegment.text} onChange={(event) => updateSegment(selectedSegment.id, "text", event.target.value)}/></label>
          <label className="field"><span>Mulai (detik)</span><input type="number" min="0" max={composition.duration} step="0.01" value={selectedSegment.start} onChange={(event) => updateSegment(selectedSegment.id, "start", Number(event.target.value))}/></label>
          <label className="field"><span>Selesai (detik)</span><input type="number" min="0" max={composition.duration} step="0.01" value={selectedSegment.end} onChange={(event) => updateSegment(selectedSegment.id, "end", Number(event.target.value))}/></label>
          <label className="field"><span>Durasi · {(selectedSegment.end - selectedSegment.start).toFixed(2)} dtk</span><input type="number" readOnly value={(selectedSegment.end - selectedSegment.start).toFixed(2)}/></label>
          <label className="field"><span>Animasi</span><select value={selectedSegment.animation} onChange={(event) => updateSegment(selectedSegment.id, "animation", event.target.value)}>{segmentAnimationOptions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label className="field"><span>Durasi animasi</span><input type="number" min="0.1" max={Math.max(0.1, Math.min(2, (selectedSegment.end - selectedSegment.start) / 2))} step="0.05" value={selectedSegment.animation_duration} onChange={(event) => updateSegment(selectedSegment.id, "animation_duration", Number(event.target.value))}/></label>
          <div className="mood-timeline-edit-actions"><button type="button" className="button button-outline" onClick={splitSelectedSegment}><Scissors size={13}/> Split</button><button type="button" className="button button-outline" onClick={() => mergeSelectedSegment(-1)} disabled={selectedSegmentIndex <= 0}>Gabung ←</button><button type="button" className="button button-outline" onClick={() => mergeSelectedSegment(1)} disabled={selectedSegmentIndex < 0 || selectedSegmentIndex >= composition.segments.length - 1}>Gabung →</button><button type="button" className="button button-outline" onClick={duplicateSelectedSegment}><Copy size={13}/> Duplikat</button><button type="button" className="button button-outline" onClick={() => reorderSegment(selectedSegmentIndex, -1)} disabled={selectedSegmentIndex <= 0}>Urut ↑</button><button type="button" className="button button-outline" onClick={() => reorderSegment(selectedSegmentIndex, 1)} disabled={selectedSegmentIndex < 0 || selectedSegmentIndex >= composition.segments.length - 1}>Urut ↓</button><button type="button" className="button button-outline" onClick={resetTimelineTiming}>Reset timing</button><button type="button" className="button button-outline" onClick={resetSegments}>Auto Re-segment</button><button type="button" className="button button-outline" onClick={() => deleteSegment(selectedSegment.id)}>Hapus</button></div>
        </section>}
      </details>
      <div className="mood-step-actions mood-customize-footer"><button className="button button-outline" onClick={() => setStep(2)}><ArrowLeft size={14}/> Kembali ke quote</button><span><Save size={14}/> Autosave aktif · perubahan tidak memanggil AI.</span></div>
      </div>
    </section>}

    {step === 4 && <section className="panel mood-step-panel"><div className="step-heading"><span className="step-number">04</span><div><h2>Preview & render</h2><p>Preview 9:16 menggunakan aset lokal; render memakai konfigurasi tersimpan yang sama.</p></div></div>
      <div className="mood-preview-layout"><div className="mood-preview-frame">
        {(composition.background.kind === "solid" || composition.background.kind === "gradient") && <div className="mood-background-base" style={{ ...previewBackgroundStyle, filter: visualFilter }} />}
        {composition.background.kind === "image" && selectedAsset && <img style={{ ...backgroundMotion, filter: visualFilter }} src={`${API}${selectedAsset.url}`} alt="Mood Quotes background"/>}
        {composition.background.kind === "video" && selectedAsset && <video ref={backgroundVideo} style={{ ...backgroundMotion, filter: visualFilter }} src={`${API}${selectedAsset.url}`} muted={composition.background.mute_audio} playsInline onLoadedMetadata={(event) => { event.currentTarget.currentTime = composition.background.video_start; }} onEnded={(event) => { if (composition.background.loop && playing) { event.currentTarget.currentTime = composition.background.video_start; void event.currentTarget.play(); } }} />}
        {visualLayers}
        {composition.text.gradient_opacity > 0 && <div className="mood-text-gradient" style={textGradientStyle}/>}
        {quoteActive && activeText && <div key={activeSequenceSegment?.id || "single-full-preview"} className={`mood-preview-quote align-${composition.text.alignment}`} style={quotePreviewStyle}>{activeText}</div>}
        <span className="mood-preview-resolution">9:16 · {composition.resolution}p · {composition.duration}s</span>
      </div><div className="mood-preview-controls"><button className="button button-outline" onClick={() => void togglePreview()}>{playing ? <X size={14}/> : <Play size={14}/>} {playing ? "Pause" : "Play"}</button><button className="button button-outline" onClick={() => { seek(0); setPlaying(true); void backgroundVideo.current?.play(); startMusicPreview(0); }}><RotateCcw size={14}/> Replay</button><span>{playhead.toFixed(1)} / {composition.duration}s</span><input aria-label="Timeline playhead" type="range" min="0" max={composition.duration} step="0.1" value={playhead} onChange={(event) => seek(Number(event.target.value))}/></div>
      </div>
      <div className="mood-render-options"><label className="field"><span>Resolusi export</span><select value={composition.resolution} onChange={(event) => updateComposition("resolution", event.target.value as Composition["resolution"])}><option value="720">720 × 1280 · default</option><option value="1080">1080 × 1920</option></select></label><label className="field"><span>Durasi output · {composition.duration}s</span><input type="range" min="5" max="40" step="1" value={composition.duration} onChange={(event) => updateDuration(Number(event.target.value))}/></label><p>30 FPS · H.264/AAC · MP4. Render tidak memanggil AI, Whisper, atau Ollama.</p></div>
      {job && <div className={`job-progress ${job.status === "failed" ? "job-failed" : ""}`}><div className="job-progress-top"><span className="job-progress-icon">{isRunning ? <LoaderCircle size={17} className="spin"/> : job.status === "completed" ? <CheckCircle2 size={17}/> : <AlertCircle size={17}/>}</span><div><strong>{job.status === "completed" ? "Render selesai" : job.status === "failed" ? "Render gagal" : job.status === "cancelled" ? "Render dibatalkan" : job.phase === "rendering" ? "FFmpeg merender video" : "Menunggu render"}</strong><span>{job.message}</span></div>{isRunning && <button className="button button-quiet" onClick={() => void cancel()}>Batalkan</button>}{["failed", "cancelled"].includes(job.status) && <button className="button button-quiet" onClick={() => void retry()}>Coba lagi</button>}</div>{job.progress !== null && isRunning && <div className="progress-track"><span style={{ width: `${Math.round(job.progress * 100)}%` }}/></div>}</div>}
      <div className="mood-step-actions"><button className="button button-outline" onClick={() => setStep(3)}><ArrowLeft size={14}/> Edit komposisi</button><button className="button button-primary" disabled={busy || isRunning || !selected} onClick={() => void render()}>{busy ? <LoaderCircle size={15} className="spin"/> : <Video size={15}/>} Render MP4 <ArrowRight size={14}/></button></div>
    </section>}

    {step === 5 && <section className="panel mood-step-panel"><div className="step-heading"><span className="step-number">05</span><div><h2>Review & export</h2><p>Periksa video final, setujui file berdasarkan fingerprint, lalu unduh MP4.</p></div></div>
      {activeRender?.url ? <div className="mood-final-video"><video src={`${API}${activeRender.url}`} controls playsInline/><div className="mood-final-meta"><span className={`review-status-chip review-${activeRender.review_status.replace("_", "-")}`}>{activeRender.review_status === "approved" ? "Disetujui" : activeRender.review_status === "needs_revision" ? "Perlu Revisi" : "Perlu Review"}</span><span>{activeRender.status === "needs_render" ? "Komposisi berubah; render lama masih tersedia." : "H.264 · AAC · 9:16"}</span></div><div className="mood-step-actions"><button className="button button-outline" onClick={() => void review("needs_revision")}><RotateCcw size={14}/> Perlu revisi</button><button className="button button-primary" onClick={() => void review("approved")}><CheckCircle2 size={14}/> Setujui video</button><a className="button button-outline" href={`${API}${activeRender.download_url}`}><Download size={14}/> Download MP4</a></div></div> : <div className="mood-empty-state"><Video size={22}/><strong>Belum ada render final</strong><span>Atur komposisi lalu render MP4. Draft dan quote sudah tersimpan.</span><button className="button button-primary" onClick={() => setStep(selected ? 4 : 2)}>Lanjutkan</button></div>}
      {renders.length > 1 && <details className="mood-history"><summary><Clock3 size={14}/> Riwayat render · {renders.length}</summary><div className="mood-history-list">{renders.map((item) => <div key={item.id}><span><strong>{item.status} · {item.review_status.replace("_", " ")}</strong><small>{new Date(item.created_at).toLocaleString("id-ID")}</small></span>{item.download_url && <a className="button button-outline" href={`${API}${item.download_url}`}><Download size={13}/> Download</a>}</div>)}</div></details>}
      <div className="mood-step-actions"><button className="button button-outline" onClick={() => setStep(4)}><ArrowLeft size={14}/> Kembali ke preview</button><button className="button button-outline button-danger" onClick={() => setConfirmDelete(true)}><Trash2 size={14}/> Hapus draft</button><button className="button button-outline" onClick={async () => { try { await persist(); setNotice("Draft tersimpan di perangkat."); } catch (reason) { setError((reason as Error).message); } }}><Save size={14}/> Simpan draft</button></div>
    </section>}

    <div className="mood-workspace-footer"><span>{selected ? `Quote dipilih: ${selected.title}` : "Pilih quote untuk membuka editor video"}</span><Link href="/clips" className="text-link">Video Library <ArrowRight size={13}/></Link></div>
    {confirmDelete && <div className="modal-backdrop" onClick={(event) => { if (event.target === event.currentTarget) setConfirmDelete(false); }}><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="delete-mood-title"><span className="confirm-icon"><Trash2 size={18}/></span><h2 id="delete-mood-title">Hapus Mood Quotes draft?</h2><p><strong>{draft.title}</strong>, aset lokal, riwayat quotes, dan render terkait akan dihapus. Tindakan ini tidak dapat dibatalkan.</p><div><button className="button button-outline" onClick={() => setConfirmDelete(false)}>Batal</button><button className="button button-danger" onClick={() => void confirmProjectDelete()}>Hapus draft</button></div><button className="modal-close icon-button" aria-label="Tutup" onClick={() => setConfirmDelete(false)}><X size={14}/></button></section></div>}
  </>;
}

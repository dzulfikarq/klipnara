"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { AlertCircle, ArrowLeft, ArrowRight, Check, CheckCircle2, ChevronDown, Copy, Download, ExternalLink, Eye, Film, GripVertical, LoaderCircle, LockKeyhole, Maximize2, Minimize2, Pause, Play, Plus, Redo2, RotateCcw, Save, Scissors, Settings2, Sparkles, Trash2, Type, Undo2, Volume2, VolumeX, X, Youtube } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { API, formatDuration, request, reviewStatusLabel } from "@/lib/api";
import type { ReviewStatus } from "@/lib/api";
import { clipEditorStatus } from "@/lib/clip-editor-state.mjs";
import { deleteOutputRange, deleteScene, duplicateScene, outputToSource, pushEditHistory, redoEditHistory, reorderScene, sceneTimeline, splitScene, undoEditHistory, updateSceneRange } from "@/lib/clip-timeline.mjs";
import { activeWordIndexAt, joinWordText, validWordAlignment } from "@/lib/word-pop.mjs";

type Word = { id: string; text: string; start: number | null; end: number | null; speaker_id?: string };
type Segment = { id: string; start: number; end: number; text: string; words?: Word[]; word_alignment_reviewed?: boolean | null; speaker_id?: string; source_segment_id?: string; original_text?: string; edited?: boolean };
type SubtitleTrack = { id: string; source_type: "manual" | "generated" | "imported" | "translation"; language: string; provider?: string | null; model?: string | null; timebase: "output" | "source" | "clip"; segments: Segment[]; transcript_text?: string | null; composition_signature?: string | null; composition_fingerprint?: string | null; source_track_id?: string | null; source_fingerprint?: string | null; word_timestamps?: boolean; speaker_identification?: boolean; edited?: boolean };
type Scene = { id: string; source_start: number; source_end: number; order: number; role: "hook" | "body" | "ending"; duration?: number; timeline_start?: number; timeline_end?: number };
type Audio = { volume: number; muted: boolean; fade_in: number; fade_out: number; normalize: boolean; target_lufs: number; limiter: boolean };
type TitleOverlay = { enabled: boolean; text: string; font: "Arial" | "Georgia" | "Segoe UI" | "Tahoma" | "Trebuchet MS" | "Times New Roman"; size: number; color: string; position: number; duration: number; fade_in: number; fade_out: number };
type Edit = { trim_start: number; trim_end: number; scene_mode: "single" | "multi"; scenes: Scene[]; subtitle_enabled: boolean; subtitle_mode: "off" | "manual" | "auto" | "import"; subtitle_segments: Segment[]; subtitle_tracks: SubtitleTrack[]; subtitle_active_track_id: string | null; subtitle_active_translation_id: string | null; subtitle_timebase: "clip" | "source" | "output"; subtitle_display_mode: "original" | "translated" | "bilingual"; subtitle_caption_mode: "sentence" | "phrase" | "word" | "karaoke" | "word_pop"; subtitle_preset: string; subtitle_animation: "none" | "fade" | "pop" | "scale"; subtitle_animation_intensity: number; subtitle_animation_duration: number; subtitle_font: string; subtitle_outline_color: string; subtitle_highlight_color: string; subtitle_outline: number; subtitle_shadow: number; subtitle_background: boolean; subtitle_alignment: "top" | "center" | "bottom"; subtitle_caption_width: number; subtitle_safe_margin: number; style: "Clean" | "Bold" | "Highlight"; resolution: "720" | "1080"; fps: 30 | 60; quality: "smaller" | "balanced" | "high"; crop_x: number; crop_y: number; subtitle_size: number; subtitle_position: number; subtitle_color: string; subtitle_overrides: Record<string, string>; audio: Audio; title_overlay: TitleOverlay };
type YouTubeReference = { canonical_url: string; video_id: string; start: number; end: number; source_association: "user_selected" | "auto_imported" };
type Data = { clip: { id: string; source_id: string; title: string; reason: string; start: number; end: number; rank: number; status: string; origin: string; review_status: ReviewStatus; rendered: boolean; edit: Edit; youtube_reference: YouTubeReference | null }; source: { name: string; duration: number; audio_codec: string | null }; transcript: { start: number; end: number; text: string }[]; subtitle_stt: { local: boolean; openai: boolean; gemini: boolean }; subtitle_status: { composition_signature: string; composition_fingerprint: string; stale_track_ids: string[]; outdated_translation_ids: string[] }; jobs: Job[] };
type Job = { id: string; kind: string; provider?: string; status: string; phase: string; progress: number | null; message: string };
type PublishAccount = { id: string; channel_title: string; status: string };
type PublishForm = { account_id: string; title: string; description: string; tags: string; privacy_status: "private" | "unlisted" | "public"; made_for_kids: "" | "yes" | "no"; contains_synthetic_media: "" | "yes" | "no" };
type CutRange = { start: number; end: number } | null;
type EditHistory = { undo: Edit[]; redo: Edit[] };

function groupCaptionWords(words: Word[]) {
  const groups: Word[][] = [];
  let current: Word[] = [];
  for (const word of words) {
    current.push(word);
    if (/[.!?]$/.test(word.text) || current.length >= 7) { groups.push(current); current = []; }
  }
  if (current.length) groups.push(current);
  return groups;
}

export default function ClipEditorPage() {
  const params = useParams<{ id: string }>();
  const [data, setData] = useState<Data | null>(null);
  const [batchId, setBatchId] = useState("");
  const [edit, setEdit] = useState<Edit | null>(null);
  const [saved, setSaved] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [previewRendered, setPreviewRendered] = useState(false);
  const [previewUnavailable, setPreviewUnavailable] = useState(false);
  const [previewMuted, setPreviewMuted] = useState<boolean | null>(null);
  const [previewCollapsed, setPreviewCollapsed] = useState(false);
  const [previewFullscreen, setPreviewFullscreen] = useState(false);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [publishOpen, setPublishOpen] = useState(false);
  const [publishStep, setPublishStep] = useState<"details" | "confirm">("details");
  const [publishAccounts, setPublishAccounts] = useState<PublishAccount[]>([]);
  const [publishForm, setPublishForm] = useState<PublishForm>({ account_id: "", title: "", description: "", tags: "", privacy_status: "private", made_for_kids: "", contains_synthetic_media: "" });
  const [publishBusy, setPublishBusy] = useState(false);
  const [publishError, setPublishError] = useState("");
  const [publishNotice, setPublishNotice] = useState(false);
  const [referenceBusy, setReferenceBusy] = useState(false);
  const [subtitleBusy, setSubtitleBusy] = useState(false);
  const [subtitleSaving, setSubtitleSaving] = useState(false);
  const [subtitleNotice, setSubtitleNotice] = useState("");
  const [translationProvider, setTranslationProvider] = useState<"openai" | "gemini">("gemini");
  const [translationTarget, setTranslationTarget] = useState<"id-ID" | "en-US">("id-ID");
  const [subtitleSelectedIds, setSubtitleSelectedIds] = useState<string[]>([]);
  const [translationDirty, setTranslationDirty] = useState(false);
  const [selectedSceneId, setSelectedSceneId] = useState("");
  const [compositionTime, setCompositionTime] = useState(0);
  const [previewPlaying, setPreviewPlaying] = useState(false);
  const [timelineCollapsed, setTimelineCollapsed] = useState(false);
  const [sceneZoom, setSceneZoom] = useState(34);
  const [dragSceneId, setDragSceneId] = useState("");
  const [cutRange, setCutRange] = useState<CutRange>(null);
  const [resizePreview, setResizePreview] = useState<Scene[] | null>(null);
  const [subtitleDragPreview, setSubtitleDragPreview] = useState<{ id: string; start: number; end: number } | null>(null);
  const [newSceneRange, setNewSceneRange] = useState({ start: 0, end: 3 });
  const [historyVersion, setHistoryVersion] = useState(0);
  const [subtitleProvider, setSubtitleProvider] = useState<"local" | "openai" | "gemini">("local");
  const [subtitleLanguage, setSubtitleLanguage] = useState<"auto" | "indonesia" | "english">("auto");
  const subtitleSaveQueue = useRef<Promise<void>>(Promise.resolve());
  const subtitleSaveFailure = useRef("");
  const previewRef = useRef<HTMLVideoElement>(null);
  const previewStageRef = useRef<HTMLDivElement>(null);
  const previewSceneId = useRef("");
  const editRef = useRef<Edit | null>(null);
  const historyRef = useRef<EditHistory>({ undo: [], redo: [] });
  const timelineStateRef = useRef<{ time: number; scenes: Scene[] }>({ time: 0, scenes: [] });
  const timelineGesture = useRef<
    | { kind: "select"; start: number }
    | { kind: "resize"; id: string; edge: "start" | "end"; originX: number; sourceStart: number; sourceEnd: number; baseEdit: Edit }
    | { kind: "subtitle"; id: string; edge: "move" | "start" | "end"; originX: number; start: number; end: number; baseEdit: Edit }
    | null
  >(null);
  const timelineTrackRef = useRef<HTMLDivElement>(null);

  const refresh = () => request<Data>(`/clips/${params.id}`).then((next) => { subtitleSaveFailure.current = ""; setData(next); editRef.current = next.clip.edit; historyRef.current = { undo: [], redo: [] }; setHistoryVersion((value) => value + 1); setEdit(next.clip.edit); setSaved(JSON.stringify(next.clip.edit)); setSelectedSceneId(next.clip.edit.scenes?.[0]?.id || ""); setNewSceneRange({ start: next.clip.start, end: Math.min(next.source.duration, next.clip.start + 3) }); setCompositionTime(0); setCutRange(null); setPreviewRendered(false); setSubtitleProvider(next.subtitle_stt.local ? "local" : next.subtitle_stt.gemini ? "gemini" : "openai"); setTranslationProvider(next.subtitle_stt.gemini ? "gemini" : "openai"); const active = next.jobs.find((item) => ["queued", "preparing", "preparing_audio", "uploading", "transcribing", "processing_result", "rendering"].includes(item.status)); if (active) setJob(active); setSubtitleNotice(""); setTranslationDirty(false); }).catch((reason) => setError(reason.message));
  useEffect(() => { setBatchId(new URLSearchParams(window.location.search).get("batch") || ""); void refresh(); }, [params.id]);
  useEffect(() => {
    if (!data || !edit || !saved || subtitleBusy || subtitleSaving) return;
    const snapshot = edit;
    const snapshotKey = JSON.stringify(snapshot);
    if (snapshotKey === subtitleSaveFailure.current || snapshotKey === saved) return;
    const timer = setTimeout(() => {
      subtitleSaveQueue.current = subtitleSaveQueue.current.then(async () => {
        setSubtitleSaving(true);
        try {
          const next = await request<Edit>(`/clips/${data.clip.id}`, { method: "PATCH", body: JSON.stringify(snapshot) });
          subtitleSaveFailure.current = "";
          setSaved(JSON.stringify(next));
          setEdit((current) => {
            if (!current || JSON.stringify(current) !== snapshotKey) return current;
            editRef.current = next;
            return next;
          });
          setData((current) => current ? { ...current, clip: { ...current.clip, status: current.clip.rendered ? "needs_render" : current.clip.status, review_status: "needs_review" } } : current);
          setPreviewRendered(false);
        } catch (reason) { subtitleSaveFailure.current = snapshotKey; setError((reason as Error).message); }
        finally { setSubtitleSaving(false); }
      });
    }, 650);
    return () => clearTimeout(timer);
  }, [data?.clip.id, edit, saved, subtitleBusy, subtitleSaving]);
  useEffect(() => {
    if (!job || !["queued", "preparing", "preparing_audio", "uploading", "transcribing", "processing_result", "analyzing", "rendering"].includes(job.status)) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await request<Job>(`/jobs/${job.id}`);
        if (!alive) return;
        setJob((current) => ({ ...next, provider: current?.provider }));
        if (next.status === "completed") {
          if (next.kind === "render") { setCompositionTime(0); await refresh(); setPreviewRendered(true); }
          else {
            const latest = await request<Data>(`/clips/${params.id}`);
            if (!alive) return;
            setData(latest);
            setEdit((current) => {
              if (!current) return latest.clip.edit;
              const tracks = [...latest.clip.edit.subtitle_tracks];
              for (const track of current.subtitle_tracks) {
                const index = tracks.findIndex((item) => item.id === track.id);
                if (index < 0) tracks.push(track); else tracks[index] = track;
              }
              const merged = { ...latest.clip.edit, ...current, subtitle_tracks: tracks };
              editRef.current = merged;
              return merged;
            });
            setSaved((value) => {
              const base = JSON.parse(value || "{}") as Edit;
              const tracks = [...latest.clip.edit.subtitle_tracks];
              for (const track of base.subtitle_tracks || []) if (!tracks.some((item) => item.id === track.id)) tracks.push(track);
              return JSON.stringify({ ...base, subtitle_tracks: tracks });
            });
            if (next.kind === "subtitle_translate") setTranslationDirty(false);
            setSubtitleNotice(next.message);
          }
          return;
        }
        if (["failed", "cancelled"].includes(next.status)) return;
        timer = setTimeout(poll, 800);
      } catch (reason) { if (alive) setError((reason as Error).message); }
    };
    timer = setTimeout(poll, 650);
    return () => { alive = false; clearTimeout(timer); };
  }, [job?.id]);
  useEffect(() => {
    const video = previewRef.current;
    if (!video || !edit) return;
    video.volume = Math.max(0, Math.min(1, edit.audio.volume));
    video.muted = previewMuted ?? edit.audio.muted;
  }, [data?.clip.id, data?.clip.source_id, edit?.audio.volume, edit?.audio.muted, previewMuted, previewRendered]);

  useEffect(() => {
    const syncFullscreen = () => setPreviewFullscreen(document.fullscreenElement === previewStageRef.current);
    document.addEventListener("fullscreenchange", syncFullscreen);
    return () => document.removeEventListener("fullscreenchange", syncFullscreen);
  }, []);

  const editorStatus = clipEditorStatus({ edit, saved, saving: subtitleSaving, saveFailure: subtitleSaveFailure.current, rendered: data?.clip.rendered ?? false, clipStatus: data?.clip.status ?? "" });
  const dirty = editorStatus.dirty;
  const sourceStart = data?.clip.start || 0;
  const compositionScenes = useMemo(() => {
    if (!data || !edit) return [] as Scene[];
    const scenes = edit.scene_mode === "multi" ? edit.scenes : [{
      id: `scene-${data.clip.id}`,
      role: edit.scenes[0]?.role || "body" as const,
      source_start: data.clip.start + edit.trim_start,
      source_end: data.clip.start + edit.trim_end,
      order: 0,
    }];
    return sceneTimeline(scenes) as Scene[];
  }, [data?.clip.id, data?.clip.start, edit]);
  const visibleSegments = useMemo(() => edit?.subtitle_segments.map((segment, index) => ({
    ...segment,
    index: segment.id.startsWith("transcript-") ? Number(segment.id.slice(11)) : index,
    start: edit.subtitle_timebase === "output" || edit.subtitle_timebase === "source" ? segment.start : sourceStart + segment.start,
    end: edit.subtitle_timebase === "output" || edit.subtitle_timebase === "source" ? segment.end : sourceStart + segment.end,
  })).sort((a, b) => a.start - b.start).filter((segment) => edit.subtitle_timebase === "output"
    ? segment.start < (compositionScenes.at(-1)?.timeline_end || 0) && segment.end > 0
    : compositionScenes.some((scene) => segment.end > scene.source_start && segment.start < scene.source_end)) || [], [compositionScenes, edit, sourceStart]);
  const displayedScenes = resizePreview || compositionScenes;
  const timelineDuration = compositionScenes.at(-1)?.timeline_end || 0;
  const timelineScale = timelineDuration ? Math.max(timelineDuration * sceneZoom, 360) / timelineDuration : sceneZoom;
  const timelineWidth = Math.max(timelineDuration * timelineScale, 360);
  const currentSourceTime = outputToSource(compositionScenes, compositionTime)?.sourceTime ?? sourceStart;
  const sceneSignature = compositionScenes.map((scene) => `${scene.id}:${scene.source_start.toFixed(3)}:${scene.source_end.toFixed(3)}`).join("|");
  const timelineSubtitleSegments = useMemo(() => visibleSegments.flatMap((segment) => {
    if (edit?.subtitle_timebase === "output") return [{ ...segment, id: segment.id, outputStart: segment.start, outputEnd: segment.end }];
    return compositionScenes.flatMap((scene) => {
      const start = Math.max(scene.source_start, segment.start), end = Math.min(scene.source_end, segment.end);
      return start < end ? [{ ...segment, id: `${scene.id}-${segment.id}`, outputStart: (scene.timeline_start || 0) + start - scene.source_start, outputEnd: (scene.timeline_start || 0) + end - scene.source_start }] : [];
    });
  }), [visibleSegments, compositionScenes, edit?.subtitle_timebase]);
  const activeSubtitleTrack = edit?.subtitle_tracks.find((track) => track.id === edit.subtitle_active_track_id) || null;
  const activeTranslationTrack = edit?.subtitle_tracks.find((track) => track.id === edit.subtitle_active_translation_id) || null;
  const staleActiveSubtitle = Boolean(activeSubtitleTrack?.timebase === "output" && (
    activeSubtitleTrack.composition_signature !== sceneSignature
    || data?.subtitle_status.stale_track_ids.includes(activeSubtitleTrack.id)
  ));

  useEffect(() => {
    timelineStateRef.current = { time: compositionTime, scenes: compositionScenes };
  }, [compositionTime, compositionScenes]);

  useEffect(() => {
    const video = previewRef.current;
    if (!video || previewRendered) return;
    const { time, scenes } = timelineStateRef.current;
    const total = scenes.at(-1)?.timeline_end || 0;
    const clampedTime = Math.max(0, Math.min(total, time));
    if (clampedTime !== time) setCompositionTime(clampedTime);
    const mapped = outputToSource(scenes, clampedTime);
    if (!mapped) return;
    previewSceneId.current = mapped.sceneId;
    if (Math.abs(video.currentTime - mapped.sourceTime) > 0.08) video.currentTime = mapped.sourceTime;
  }, [sceneSignature, previewRendered]);

  const commitEdit = (next: Edit, previous = editRef.current): boolean => {
    if (!previous) return false;
    if (JSON.stringify(next) === JSON.stringify(previous)) return true;
    if (next.scene_mode === "single" && (
      !Number.isFinite(next.trim_start) || !Number.isFinite(next.trim_end)
      || next.trim_start < 0 || next.trim_end > ((data?.clip.end || 0) - (data?.clip.start || 0))
      || next.trim_end <= next.trim_start
    )) {
      setError("Trim Single Scene harus berada di dalam kandidat dan memiliki durasi positif."); return false;
    }
    if (next.scene_mode === "multi" && (
      next.scenes.length < 1 || next.scenes.length > 12
      || next.scenes.reduce((sum, scene) => sum + scene.source_end - scene.source_start, 0) > 180
      || next.scenes.some((scene) => !Number.isFinite(scene.source_start) || !Number.isFinite(scene.source_end) || scene.source_start < 0 || scene.source_end > (data?.source.duration || 0) || scene.source_end - scene.source_start < 0.5)
    )) {
      setError("Multi-Scene dibatasi 12 scene, 180 detik total, dan 0,5 detik minimum per scene."); return false;
    }
    historyRef.current = pushEditHistory(historyRef.current, previous);
    editRef.current = next;
    setEdit(next);
    setHistoryVersion((value) => value + 1);
    setPreviewRendered(false);
    setError("");
    return true;
  };
  const applyEdit = (transform: (current: Edit) => Edit) => {
    const current = editRef.current;
    if (current) commitEdit(transform(current), current);
  };
  const undo = () => {
    const history = historyRef.current;
    const current = editRef.current;
    if (!current) return;
    const result = undoEditHistory(history, current);
    if (!result) return;
    historyRef.current = result.history;
    editRef.current = result.edit;
    setEdit(result.edit);
    setHistoryVersion((value) => value + 1);
    setCutRange(null);
    setResizePreview(null);
    setPreviewRendered(false);
    setError("");
  };
  const redo = () => {
    const history = historyRef.current;
    const current = editRef.current;
    if (!current) return;
    const result = redoEditHistory(history, current);
    if (!result) return;
    historyRef.current = result.history;
    editRef.current = result.edit;
    setEdit(result.edit);
    setHistoryVersion((value) => value + 1);
    setCutRange(null);
    setResizePreview(null);
    setPreviewRendered(false);
    setError("");
  };
  const canUndo = historyRef.current.undo.length > 0;
  const canRedo = historyRef.current.redo.length > 0;
  const toSourceTimedEdit = (current: Edit, scenes: Scene[]): Edit => ({
    ...current,
    scene_mode: "multi",
    scenes: scenes.map(({ id, source_start, source_end, order, role }) => ({ id, source_start, source_end, order, role })),
    subtitle_timebase: current.subtitle_timebase === "output" ? "output" : "source",
    subtitle_segments: current.subtitle_timebase === "source" || current.subtitle_timebase === "output"
      ? current.subtitle_segments
      : current.subtitle_segments.map((segment) => ({
        ...segment, start: segment.start + sourceStart, end: segment.end + sourceStart,
        words: segment.words?.map((word) => ({ ...word, start: word.start == null ? null : word.start + sourceStart, end: word.end == null ? null : word.end + sourceStart })),
      })),
  });
  const editWithScenes = (current: Edit, scenes: Scene[]): Edit => current.scene_mode === "multi"
    ? { ...current, scenes: scenes.map(({ id, source_start, source_end, order, role }) => ({ id, source_start, source_end, order, role })) }
    : (() => {
      const { id, source_start, source_end, role } = scenes[0];
      return {
        ...current,
        trim_start: source_start - sourceStart,
        trim_end: source_end - sourceStart,
        scenes: [{ id, source_start, source_end, order: 0, role }],
      };
    })();
  const seekOutput = (value: number) => {
    const next = Math.max(0, Math.min(timelineDuration, value));
    setCompositionTime(next);
    const video = previewRef.current;
    if (!video) return;
    if (previewRendered) {
      video.currentTime = next;
      return;
    }
    const mapped = outputToSource(compositionScenes, next);
    if (!mapped) return;
    previewSceneId.current = mapped.sceneId;
    setSelectedSceneId(mapped.sceneId);
    video.currentTime = mapped.sourceTime;
  };
  const markIn = () => setCutRange((current) => ({ start: compositionTime, end: current?.end != null && current.end > compositionTime ? current.end : compositionTime }));
  const markOut = () => setCutRange((current) => ({ start: current?.start != null && current.start < compositionTime ? current.start : 0, end: compositionTime }));
  const deleteSelectedRange = () => {
    if (!edit || !cutRange) return;
    const scenes = deleteOutputRange(compositionScenes, cutRange.start, cutRange.end) as Scene[] | null;
    if (!scenes) { setError("Bagian tersisa harus berdurasi minimal 0,5 detik dan komposisi maksimal 12 scene."); return; }
    const next = edit.scene_mode === "single" && scenes.length === 1
      ? editWithScenes(edit, scenes)
      : toSourceTimedEdit(edit, scenes);
    if (!commitEdit(next)) return;
    setCutRange(null);
    setSelectedSceneId(scenes[0]?.id || "");
    const outputTime = Math.min(cutRange.start, scenes.reduce((sum, scene) => sum + scene.source_end - scene.source_start, 0));
    setCompositionTime(outputTime);
    const mapped = outputToSource(scenes, outputTime);
    if (mapped) {
      previewSceneId.current = mapped.sceneId;
      if (previewRendered && previewRef.current) previewRef.current.currentTime = outputTime;
      else if (previewRef.current) previewRef.current.currentTime = mapped.sourceTime;
    }
    setPreviewRendered(false);
  };
  const splitAtPlayhead = () => {
    if (!edit) return;
    const mapped = outputToSource(compositionScenes, compositionTime);
    if (!mapped) return;
    const scenes = splitScene(compositionScenes, mapped.sceneId, mapped.sourceTime) as Scene[] | null;
    if (!scenes) { setError("Split perlu menyisakan minimal 0,5 detik per scene; batas 12 scene."); return; }
    if (!commitEdit(toSourceTimedEdit(edit, scenes))) return;
    setCutRange(null);
    setPreviewRendered(false);
  };
  const addScene = () => {
    if (!edit || newSceneRange.start < 0 || newSceneRange.end - newSceneRange.start < 0.5 || newSceneRange.end > (data?.source.duration || 0) || compositionScenes.length >= 12) {
      setError("Scene perlu 0,5 detik atau lebih, di dalam durasi sumber, maksimal 12 scene."); return;
    }
    const current = toSourceTimedEdit(edit, compositionScenes);
    const scenes = [...compositionScenes, {
      id: crypto.randomUUID(), source_start: newSceneRange.start, source_end: newSceneRange.end,
      order: compositionScenes.length, role: "body" as const,
    }];
    if (!commitEdit({ ...current, scenes: scenes.map(({ id, source_start, source_end, order, role }) => ({ id, source_start, source_end, order, role })) })) return;
    setSelectedSceneId(scenes.at(-1)?.id || "");
    setCutRange(null);
  };
  const deleteSelectedScene = () => {
    if (!edit) return;
    const scenes = deleteScene(compositionScenes, selectedSceneId) as Scene[] | null;
    if (!scenes) return;
    if (!commitEdit(toSourceTimedEdit(edit, scenes))) return;
    setSelectedSceneId(scenes[0].id);
    setCutRange(null);
  };
  const duplicateSelectedScene = () => {
    if (!edit) return;
    const scenes = duplicateScene(compositionScenes, selectedSceneId) as Scene[] | null;
    if (!scenes) return;
    if (!commitEdit(toSourceTimedEdit(edit, scenes))) return;
    setSelectedSceneId(scenes.find((scene) => !compositionScenes.some((old) => old.id === scene.id))?.id || selectedSceneId);
  };
  const setSceneRole = (id: string, role: Scene["role"]) => {
    if (!edit) return;
    const scenes = compositionScenes.map((scene) => ({ ...scene, role: scene.id === id ? role : scene.role === role ? "body" as const : scene.role }));
    commitEdit(editWithScenes(edit, scenes));
  };

  useEffect(() => {
    if (!data || !compositionScenes.length) return;
    if (!compositionScenes.some((scene) => scene.id === selectedSceneId)) setSelectedSceneId(compositionScenes[0].id);
  }, [data?.clip.id, compositionScenes, selectedSceneId]);
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (publishOpen || subtitleBusy || subtitleSaving || Boolean(job && ["queued", "preparing", "rendering"].includes(job.status))) return;
      const target = event.target as HTMLElement | null;
      if (event.altKey || target?.isContentEditable || target?.closest("input, textarea, select, button, a, [contenteditable=true]")) return;
      const key = event.key.toLowerCase();
      if ((event.ctrlKey || event.metaKey) && key === "z") {
        event.preventDefault();
        if (event.shiftKey) redo(); else undo();
      } else if ((event.ctrlKey || event.metaKey) && key === "y") {
        event.preventDefault(); redo();
      } else if (!event.ctrlKey && !event.metaKey && key === "i") markIn();
      else if (!event.ctrlKey && !event.metaKey && key === "o") markOut();
      else if (!event.ctrlKey && !event.metaKey && key === "s") { event.preventDefault(); splitAtPlayhead(); }
      else if (event.key === "Delete" && cutRange) { event.preventDefault(); deleteSelectedRange(); }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [publishOpen, subtitleBusy, subtitleSaving, job?.status, compositionTime, cutRange, compositionScenes, edit, selectedSceneId, historyVersion]);

  if (!data || !edit) return <div className="loading-page">{error || "Memuat editor…"}</div>;
  const length = data.clip.end - data.clip.start;
  const minSubtitleDuration = Math.min(0.1, length);
  const update = <K extends keyof Edit>(key: K, value: Edit[K]) => applyEdit((current) => ({ ...current, [key]: value }));
  const changeStyle = (style: Edit["style"]) => applyEdit((current) => {
    const color = style === "Highlight" && current.style !== "Highlight" && current.subtitle_color.toLowerCase() === "#ffffff"
      ? "#ffd700"
      : current.style === "Highlight" && style !== "Highlight" && current.subtitle_color.toLowerCase() === "#ffd700"
        ? "#ffffff"
        : current.subtitle_color;
    return { ...current, style, subtitle_color: color };
  });
  const setSubtitleMode = (mode: Edit["subtitle_mode"]) => applyEdit((current) => ({ ...current, subtitle_mode: mode, subtitle_enabled: mode !== "off" }));
  const addSubtitleSegment = () => applyEdit((current) => {
    if (current.subtitle_segments.length >= 500) { setError("Subtitle track limit is 500 cues."); return current; }
    setTranslationDirty(true);
    const sourceTimed = current.subtitle_timebase === "source";
    const outputTimed = current.subtitle_timebase === "output";
    const base = sourceTimed || outputTimed ? 0 : sourceStart;
    const maxTime = sourceTimed ? data.source.duration : outputTimed ? timelineDuration : length;
    const position = sourceTimed ? currentSourceTime : outputTimed ? compositionTime : currentSourceTime - sourceStart;
    const start = Math.max(0, Math.min(maxTime - minSubtitleDuration, position));
    const end = Math.min(maxTime, start + 2);
    return { ...current, subtitle_mode: "manual", subtitle_enabled: true, subtitle_overrides: {}, subtitle_segments: [...current.subtitle_segments, { id: crypto.randomUUID(), start, end, text: "", edited: false }] };
  });
  const updateSubtitleSegment = (id: string, field: "start" | "end" | "text", value: string | number) => applyEdit((current) => {
    const subtitle_segments = current.subtitle_segments.map((segment) => {
      if (segment.id !== id) return segment;
      if (field === "text") {
        setTranslationDirty(true);
        return { ...segment, original_text: segment.original_text ?? segment.text, word_alignment_reviewed: segment.words?.length ? false : segment.word_alignment_reviewed, text: String(value), edited: true };
      }
      if (!Number.isFinite(value)) return segment;
      setTranslationDirty(true);
      const maxTime = current.subtitle_timebase === "source" ? data.source.duration : current.subtitle_timebase === "output" ? timelineDuration : length;
      if (field === "start") {
        const start = Math.max(0, Math.min(maxTime - minSubtitleDuration, Number(value)));
        return { ...segment, word_alignment_reviewed: segment.words?.length ? false : segment.word_alignment_reviewed, start, end: Math.min(maxTime, Math.max(segment.end, start + minSubtitleDuration)), edited: true };
      }
      return { ...segment, word_alignment_reviewed: segment.words?.length ? false : segment.word_alignment_reviewed, end: Math.max(segment.start + minSubtitleDuration, Math.min(maxTime, Number(value))), edited: true };
    });
    return { ...current, subtitle_segments, subtitle_overrides: field === "text" ? {} : current.subtitle_overrides };
  });
  const addManualWordTiming = (id: string) => applyEdit((current) => ({ ...current, subtitle_segments: current.subtitle_segments.map((segment) => segment.id !== id ? segment : {
    ...segment,
    words: segment.text.trim().split(/\s+/).filter(Boolean).map((text) => ({ id: `word-${crypto.randomUUID()}`, text, start: null, end: null })),
    word_alignment_reviewed: false,
    edited: true,
  }) }));
  const updateManualWord = (segmentId: string, wordId: string, field: "text" | "start" | "end", value: string) => { setTranslationDirty(true); applyEdit((current) => ({ ...current, subtitle_segments: current.subtitle_segments.map((segment) => {
    if (segment.id !== segmentId) return segment;
    const words = (segment.words || []).map((word) => word.id !== wordId ? word : { ...word, [field]: field === "text" ? value : value === "" ? null : Number(value) });
    return { ...segment, original_text: segment.original_text ?? segment.text, words, text: field === "text" ? joinWordText(words) : segment.text, word_alignment_reviewed: false, edited: true };
  }) })); };
  const addManualWord = (segmentId: string) => { setTranslationDirty(true); applyEdit((current) => ({ ...current, subtitle_segments: current.subtitle_segments.map((segment) => segment.id !== segmentId ? segment : {
    ...segment, words: [...(segment.words || []), { id: `word-${crypto.randomUUID()}`, text: "", start: null, end: null }], word_alignment_reviewed: false, edited: true,
  }) })); };
  const removeManualWord = (segmentId: string, wordId: string) => { setTranslationDirty(true); applyEdit((current) => ({ ...current, subtitle_segments: current.subtitle_segments.map((segment) => {
    if (segment.id !== segmentId) return segment;
    const words = (segment.words || []).filter((word) => word.id !== wordId);
    return { ...segment, words, text: joinWordText(words), word_alignment_reviewed: false, edited: true };
  }) })); };
  const splitManualWord = (segmentId: string, wordId: string) => { setTranslationDirty(true); applyEdit((current) => ({ ...current, subtitle_segments: current.subtitle_segments.map((segment) => {
    if (segment.id !== segmentId) return segment;
    const words = (segment.words || []).flatMap((word) => {
      if (word.id !== wordId) return [word];
      const parts = word.text.trim().split(/\s+/).filter(Boolean);
      return parts.length > 1 ? parts.map((text) => ({ id: `word-${crypto.randomUUID()}`, text, start: null, end: null })) : [word];
    });
    return { ...segment, words, text: joinWordText(words), word_alignment_reviewed: false, edited: true };
  }) })); };
  const mergeManualWord = (segmentId: string, wordId: string) => { setTranslationDirty(true); applyEdit((current) => ({ ...current, subtitle_segments: current.subtitle_segments.map((segment) => {
    if (segment.id !== segmentId) return segment;
    const words = [...(segment.words || [])];
    const index = words.findIndex((word) => word.id === wordId);
    if (index < 0 || index >= words.length - 1) return segment;
    words.splice(index, 2, { ...words[index], text: joinWordText(words.slice(index, index + 2)), start: null, end: null });
    return { ...segment, words, text: joinWordText(words), word_alignment_reviewed: false, edited: true };
  }) })); };
  const reviewManualWordTiming = (segmentId: string) => applyEdit((current) => {
    const segment = current.subtitle_segments.find((item) => item.id === segmentId);
    if (!segment || !validWordAlignment({ ...segment, word_alignment_reviewed: true })) { setError("Check every word: text must match caption, timings must stay inside cue, and words must not overlap."); return current; }
    setError("");
    return { ...current, subtitle_segments: current.subtitle_segments.map((item) => item.id === segmentId ? { ...item, word_alignment_reviewed: true } : item) };
  });
  const deleteSubtitleSegment = (id: string) => { setTranslationDirty(true); setSubtitleSelectedIds((current) => current.filter((item) => item !== id)); applyEdit((current) => ({ ...current, subtitle_overrides: {}, subtitle_segments: current.subtitle_segments.filter((segment) => segment.id !== id) })); };
  const splitSubtitleSegment = (id: string) => applyEdit((current) => {
    if (current.subtitle_segments.length >= 500) { setError("Subtitle track limit is 500 cues."); return current; }
    const segment = current.subtitle_segments.find((item) => item.id === id);
    if (!segment) return current;
    const words = segment.words || [];
    const alignmentValid = validWordAlignment(segment);
    const middle = Math.floor(words.length / 2);
    const leftWords = words.length > 1 ? words.slice(0, middle) : [];
    const rightWords = words.length > 1 ? words.slice(middle) : [];
    const textParts = segment.text.trim().split(/\s+/);
    const textMiddle = Math.max(1, Math.floor(textParts.length / 2));
    const splitTime = alignmentValid && words.length > 1 ? words[middle].start! : (segment.start + segment.end) / 2;
    if (splitTime - segment.start < minSubtitleDuration || segment.end - splitTime < minSubtitleDuration) return current;
    setTranslationDirty(true);
    return { ...current, subtitle_segments: current.subtitle_segments.flatMap((item) => item.id !== id ? [item] : [
      { ...item, end: splitTime, text: leftWords.length ? joinWordText(leftWords) : textParts.slice(0, textMiddle).join(" "), words: leftWords.length ? leftWords : undefined, word_alignment_reviewed: leftWords.length ? alignmentValid : undefined, edited: true },
      { ...item, id: crypto.randomUUID(), start: splitTime, text: rightWords.length ? joinWordText(rightWords) : textParts.slice(textMiddle).join(" "), words: rightWords.length ? rightWords : undefined, word_alignment_reviewed: rightWords.length ? alignmentValid : undefined, edited: true },
    ]) };
  });
  const duplicateSubtitleSegment = (id: string) => applyEdit((current) => {
    if (current.subtitle_segments.length >= 500) { setError("Subtitle track limit is 500 cues."); return current; }
    const source = current.subtitle_segments.find((item) => item.id === id);
    if (!source) return current;
    const maxTime = current.subtitle_timebase === "source" ? data.source.duration : current.subtitle_timebase === "output" ? timelineDuration : length;
    const duration = source.end - source.start;
    const start = source.end + duration <= maxTime ? source.end : source.start - duration >= 0 ? source.start - duration : -1;
    if (start < 0) return current;
    const delta = start - source.start;
    setTranslationDirty(true);
     return { ...current, subtitle_segments: [...current.subtitle_segments, { ...source, id: crypto.randomUUID(), start, end: start + duration, words: source.words?.map((word) => ({ ...word, id: crypto.randomUUID(), start: word.start == null ? null : word.start + delta, end: word.end == null ? null : word.end + delta })), word_alignment_reviewed: source.words?.length ? false : source.word_alignment_reviewed, edited: true }] };
  });
  const mergeSelectedSubtitles = () => {
    if (subtitleSelectedIds.length < 2) return;
    setTranslationDirty(true);
    applyEdit((current) => {
      const selected = current.subtitle_segments.filter((segment) => subtitleSelectedIds.includes(segment.id)).sort((a, b) => a.start - b.start);
      if (selected.length < 2) return current;
      const first = selected[0], last = selected.at(-1)!;
      const words = selected.every((segment) => segment.words?.length) ? selected.flatMap((segment) => segment.words || []) : undefined;
      const mergedText = words?.length ? joinWordText(words) : selected.map((segment) => segment.text.trim()).filter(Boolean).join(" ");
      const merged: Segment = { ...first, end: last.end, text: mergedText, words, word_alignment_reviewed: words?.length && selected.every((segment) => validWordAlignment(segment)) ? true : false, edited: true };
      const selectedSet = new Set(selected.map((segment) => segment.id));
      return { ...current, subtitle_segments: current.subtitle_segments.filter((segment) => !selectedSet.has(segment.id) || segment.id === first.id).map((segment) => segment.id === first.id ? merged : segment) };
    });
    setSubtitleSelectedIds([]);
  };
  const convertSubtitlesToOutput = () => {
    if (edit.subtitle_timebase === "output") return;
    if (edit.subtitle_tracks.length >= 20) { setError("Subtitle track limit reached (20). Remove a draft before mapping cues."); return; }
    const mapped: Segment[] = edit.subtitle_segments.flatMap((segment) => {
      const sourceStartTime = edit.subtitle_timebase === "source" ? segment.start : sourceStart + segment.start;
      const sourceEndTime = edit.subtitle_timebase === "source" ? segment.end : sourceStart + segment.end;
      return compositionScenes.flatMap((scene) => {
        const start = Math.max(sourceStartTime, scene.source_start), end = Math.min(sourceEndTime, scene.source_end);
        if (start >= end) return [];
        const delta = (scene.timeline_start || 0) - scene.source_start;
        const words = segment.words?.flatMap((word) => {
          if (word.start == null || word.end == null) return [{ ...word, id: crypto.randomUUID(), start: null, end: null }];
          const wordStart = word.start + (edit.subtitle_timebase === "clip" ? sourceStart : 0);
          const wordEnd = word.end + (edit.subtitle_timebase === "clip" ? sourceStart : 0);
          if (wordEnd <= scene.source_start || wordStart >= scene.source_end) return [];
          const source_word_start = Math.max(wordStart, scene.source_start), source_word_end = Math.min(wordEnd, scene.source_end);
          return [{ ...word, start: source_word_start + delta, end: source_word_end + delta, source_start: source_word_start, source_end: source_word_end }];
        });
        const mappedWords = words?.length ? words : undefined;
        if (edit.subtitle_caption_mode === "word_pop" && segment.words?.length && !mappedWords?.length) return [];
        return [{
          ...segment, id: compositionScenes.length > 1 ? `seg-${crypto.randomUUID()}` : segment.id,
          start: start + delta, end: end + delta, words: mappedWords,
          text: edit.subtitle_caption_mode === "word_pop" && mappedWords?.every((word) => word.start != null && word.end != null) ? joinWordText(mappedWords) : segment.text,
          edited: true,
        }];
      });
    });
    const track: SubtitleTrack = {
      id: `manual-${crypto.randomUUID()}`, source_type: "manual", language: "und", timebase: "output",
      segments: mapped, composition_signature: sceneSignature,
      composition_fingerprint: data.subtitle_status.composition_fingerprint,
      word_timestamps: mapped.some((segment) => segment.words?.length), speaker_identification: false, edited: true,
    };
    if (mapped.length > 500) { setError("Mapping across scenes produced over 500 cues. Reduce scenes or merge cues before mapping."); return; }
    setTranslationDirty(true);
    setSubtitleSelectedIds([]);
    applyEdit((current) => ({
      ...current, subtitle_segments: mapped, subtitle_timebase: "output",
      subtitle_tracks: [...current.subtitle_tracks, track].slice(-20),
      subtitle_active_track_id: track.id, subtitle_active_translation_id: null,
      subtitle_display_mode: "original", subtitle_mode: "manual", subtitle_enabled: true,
    }));
    setSubtitleNotice("Cues mapped to current output timeline. Scene edits will make these cues stale; regenerate or remap after scene changes.");
  };
  const save = async () => {
    setError(""); setSubtitleSaving(true);
    try { const savedEdit = await request<Edit>(`/clips/${data.clip.id}`, { method: "PATCH", body: JSON.stringify(edit) }); subtitleSaveFailure.current = ""; editRef.current = savedEdit; setEdit(savedEdit); setSaved(JSON.stringify(savedEdit)); setPreviewRendered(false); setData((current) => current ? { ...current, clip: { ...current.clip, status: current.clip.rendered ? "needs_render" : current.clip.status, review_status: "needs_review" } } : current); return true; }
    catch (reason) { setError((reason as Error).message); return false; }
    finally { setSubtitleSaving(false); }
  };
  const returnToBatch = async () => {
    if (!batchId || dirty && !(await save())) return;
    window.location.assign(`/batches/${batchId}`);
  };
  const generateSubtitles = async () => {
    if (subtitleProvider !== "local" && !window.confirm(`Audio komposisi output (${formatDuration(timelineDuration)}) dapat dikirim ke ${subtitleProvider === "gemini" ? "Google Gemini" : "OpenAI"} jika belum ada draft cocok. API mungkin berbayar; biaya tidak dapat dihitung di sini. Lanjutkan?`)) return;
    setSubtitleBusy(true); setError("");
    try {
      if (dirty && !(await save())) return;
      const result = await request<{ id?: string; status?: string; provider?: string; duration?: number; cached?: boolean; track?: SubtitleTrack }>(`/clips/${data.clip.id}/subtitles/transcribe`, {
        method: "POST",
        body: JSON.stringify({ provider: subtitleProvider, language: subtitleLanguage, consent: subtitleProvider !== "local" }),
      });
      if (result.cached && result.track) {
        applyEdit((current) => ({ ...current, subtitle_tracks: [...current.subtitle_tracks.filter((track) => track.id !== result.track!.id), result.track!] }));
        setSubtitleNotice("Transkrip komposisi cocok ditemukan di draft. Tinjau lalu pilih Gunakan track.");
      } else if (result.id) {
        setJob({ id: result.id, kind: "subtitle_transcribe", provider: subtitleProvider, status: "queued", phase: "queued", progress: null, message: "Menunggu transkripsi komposisi" });
      }
    } catch (reason) { setError((reason as Error).message); }
    finally { setSubtitleBusy(false); }
  };
  const translateSubtitles = async () => {
    if (!window.confirm(`Teks subtitle (${visibleSegments.length} cue) dapat dikirim ke ${translationProvider === "gemini" ? "Google Gemini" : "OpenAI"} jika belum ada terjemahan cocok. API mungkin berbayar. Lanjutkan?`)) return;
    setSubtitleBusy(true); setError("");
    try {
      if (dirty && !(await save())) return;
      const result = await request<{ id?: string; status?: string; cached?: boolean; track?: SubtitleTrack }>(`/clips/${data.clip.id}/subtitles/translate`, {
        method: "POST", body: JSON.stringify({ provider: translationProvider, target_language: translationTarget, consent: true }),
      });
      if (result.cached && result.track) {
        applyEdit((current) => ({ ...current, subtitle_tracks: [...current.subtitle_tracks.filter((track) => track.id !== result.track!.id), result.track!] }));
        setTranslationDirty(false);
        setSubtitleNotice("Terjemahan cocok ditemukan di draft. Tinjau sebelum memilih track.");
      } else if (result.id) {
        setJob({ id: result.id, kind: "subtitle_translate", provider: translationProvider, status: "queued", phase: "queued", progress: null, message: "Menunggu terjemahan subtitle" });
      }
    } catch (reason) { setError((reason as Error).message); }
    finally { setSubtitleBusy(false); }
  };
  const cancelJob = async () => {
    if (!job) return;
    try { await request(`/jobs/${job.id}/cancel`, { method: "POST" }); setJob({ ...job, status: "cancelled", phase: "cancelled", message: "Pembatalan diminta. Provider mungkin tetap menyelesaikan request aktif." }); }
    catch (reason) { setError((reason as Error).message); }
  };
  const retryJob = async () => {
    if (!job) return;
    const cloud = job.provider ? job.provider !== "local" : job.kind === "subtitle_translate";
    if (cloud && !window.confirm("Retry mengirim ulang audio/teks ke provider dan dapat menimbulkan biaya baru. Setuju?")) return;
    try {
      const result = await request<{ id: string; status: string }>(`/jobs/${job.id}/retry`, { method: "POST", body: JSON.stringify({ consent: cloud }) });
      setJob({ id: result.id, kind: job.kind, provider: job.provider, status: result.status, phase: result.status, progress: null, message: "Retry masuk antrean" });
    } catch (reason) { setError((reason as Error).message); }
  };
  const useSubtitleTrack = (track: SubtitleTrack) => {
    const current = editRef.current;
    if (!current) return;
    if (track.timebase === "output" && track.composition_signature !== sceneSignature) {
      setError("Track output-time sudah stale setelah perubahan scene. Generate/import ulang untuk komposisi saat ini."); return;
    }
    if (current.subtitle_caption_mode === "word_pop") {
      if (track.source_type === "translation") { setError("Word Pop supports original captions only. Select an original track."); return; }
      const offset = track.timebase === "clip" ? sourceStart : 0;
      const currentTrackSegments = track.segments.filter((segment) => track.timebase === "output"
        ? segment.start < timelineDuration && segment.end > 0
        : compositionScenes.some((scene) => segment.end + offset > scene.source_start && segment.start + offset < scene.source_end));
      if (!currentTrackSegments.length || currentTrackSegments.some((segment) => !validWordAlignment(segment))) {
        setError("Word Pop needs reviewed word timings for every visible cue. Select another track or review its alignment first."); return;
      }
    }
    if (track.source_type === "translation") {
      const sourceId = track.source_track_id === "legacy" ? null : track.source_track_id || null;
      const original = sourceId ? current.subtitle_tracks.find((item) => item.id === sourceId) : null;
      applyEdit((value) => ({
        ...value,
        subtitle_active_track_id: sourceId,
        subtitle_active_translation_id: track.id,
        ...(original ? { subtitle_segments: original.segments, subtitle_timebase: original.timebase } : {}),
        subtitle_display_mode: "translated",
        subtitle_enabled: true,
        subtitle_mode: "manual",
      }));
      return;
    }
    if (!track.segments.length) { setError("Track hanya berisi transkrip teks tanpa timestamp. Buat timing manual sebelum digunakan."); return; }
    applyEdit((value) => ({
      ...value,
      subtitle_active_track_id: track.id,
      subtitle_active_translation_id: null,
      subtitle_display_mode: "original",
      subtitle_segments: track.segments,
      subtitle_timebase: track.timebase,
      subtitle_mode: track.source_type === "imported" ? "import" : track.source_type === "generated" ? "auto" : "manual",
      subtitle_enabled: true,
    }));
    setTranslationDirty(false);
  };
  const useTranslationTrack = (trackId: string) => {
    const track = editRef.current?.subtitle_tracks.find((item) => item.id === trackId);
    if (!track) return;
    if (data.subtitle_status.outdated_translation_ids.includes(track.id) || translationDirty) {
      setError("Translation may be outdated. Translate current original cues again before use."); return;
    }
    useSubtitleTrack(track);
  };
  const removeSubtitleTrack = (trackId: string) => {
    const current = editRef.current;
    if (!current) return;
    const removedTrack = current.subtitle_tracks.find((track) => track.id === trackId);
    if (!removedTrack) return;
    const removedIds = new Set([trackId, ...current.subtitle_tracks.filter((track) => track.source_track_id === trackId).map((track) => track.id)]);
    applyEdit((value) => {
      const subtitle_tracks = value.subtitle_tracks.filter((track) => !removedIds.has(track.id));
      const activeRemoved = Boolean(value.subtitle_active_track_id && removedIds.has(value.subtitle_active_track_id));
      const translationRemoved = Boolean(value.subtitle_active_translation_id && removedIds.has(value.subtitle_active_translation_id));
      if (activeRemoved) {
        const replacement = [...subtitle_tracks].reverse().find((track) => track.source_type !== "translation" && track.segments.length > 0 && (
          track.timebase !== "output" || track.composition_signature === sceneSignature
          && track.composition_fingerprint === data.subtitle_status.composition_fingerprint
        ));
        if (!replacement) return {
          ...value, subtitle_tracks, subtitle_segments: [], subtitle_active_track_id: null,
          subtitle_active_translation_id: null, subtitle_timebase: "clip", subtitle_display_mode: "original",
          subtitle_enabled: false, subtitle_mode: "off",
        };
        return {
          ...value, subtitle_tracks, subtitle_segments: replacement.segments, subtitle_timebase: replacement.timebase,
          subtitle_active_track_id: replacement.id, subtitle_active_translation_id: null,
          subtitle_display_mode: "original", subtitle_mode: replacement.source_type === "generated" ? "auto" : replacement.source_type === "imported" ? "import" : "manual",
        };
      }
      return {
        ...value, subtitle_tracks,
        ...(translationRemoved ? { subtitle_active_translation_id: null, subtitle_display_mode: "original" as const } : {}),
      };
    });
    setSubtitleNotice("Subtitle draft removed.");
  };
  const importSubtitleFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if ((editRef.current?.subtitle_tracks.length ?? 0) >= 20) { setError("Remove a subtitle draft before importing another track (20-track limit)."); return; }
    const format = file.name.toLowerCase().endsWith(".srt") ? "srt" : file.name.toLowerCase().endsWith(".vtt") ? "vtt" : null;
    if (!format || file.size > 2 * 1024 * 1024) { setError("Choose UTF-8/UTF-16 SRT or VTT up to 2 MiB."); return; }
    setSubtitleBusy(true); setError("");
    try {
      const bytes = await file.arrayBuffer();
      const view = new Uint8Array(bytes);
      const encoding = view[0] === 0xff && view[1] === 0xfe ? "utf-16le" : view[0] === 0xfe && view[1] === 0xff ? "utf-16be" : "utf-8";
      let text: string;
      try { text = new TextDecoder(encoding, { fatal: true }).decode(bytes); }
      catch { throw new Error("Subtitle file encoding is invalid or unsupported. Save as UTF-8 or UTF-16."); }
      const send = (clamp: boolean) => request<{ track: SubtitleTrack | null; warnings: string[]; needs_clamp: boolean }>(`/clips/${data.clip.id}/subtitles/import`, {
        method: "POST", body: JSON.stringify({ format, text, clamp }),
      });
      let result = await send(false);
      if (result.needs_clamp && window.confirm(`Some cues exceed current output duration (${formatDuration(timelineDuration)}). Clamp/drop out-of-range cues?`)) result = await send(true);
      if (!result.track) { setSubtitleNotice(result.warnings.join(" ") || "Import needs duration correction."); return; }
      applyEdit((current) => ({ ...current, subtitle_tracks: [...current.subtitle_tracks.filter((track) => track.id !== result.track!.id), result.track!] }));
      setSubtitleNotice(result.warnings.length ? result.warnings.join(" ") : "Subtitle imported. Review track, then choose Gunakan track.");
    } catch (reason) { setError((reason as Error).message); }
    finally { setSubtitleBusy(false); }
  };
  const applySubtitlePreset = (preset: string) => {
    const config: Record<string, Partial<Edit>> = {
      "Minimal Clean": { style: "Clean", subtitle_color: "#ffffff", subtitle_outline: 2, subtitle_shadow: 1, subtitle_background: false },
      "Bold Viral": { style: "Bold", subtitle_color: "#ffffff", subtitle_outline: 4, subtitle_shadow: 1, subtitle_background: false },
      "Karaoke Highlight": { style: "Highlight", subtitle_color: "#ffffff", subtitle_highlight_color: "#ffd700", subtitle_outline: 3, subtitle_shadow: 1, subtitle_background: false },
      Cinematic: { style: "Clean", subtitle_color: "#f4e7ca", subtitle_outline: 2, subtitle_shadow: 2, subtitle_background: false, subtitle_position: 72 },
      "Podcast Caption": { style: "Bold", subtitle_color: "#ffffff", subtitle_outline: 3, subtitle_shadow: 1, subtitle_background: true },
      "Yellow Pop": { style: "Highlight", subtitle_color: "#ffd700", subtitle_outline: 4, subtitle_shadow: 1, subtitle_background: false },
      "Soft Purple": { style: "Clean", subtitle_color: "#eadbff", subtitle_outline: 2, subtitle_shadow: 2, subtitle_background: false },
      "Classic White": { style: "Clean", subtitle_color: "#ffffff", subtitle_outline: 2, subtitle_shadow: 0, subtitle_background: false },
      "Word Pop": { style: "Bold", subtitle_font: "Arial", subtitle_size: 58, subtitle_color: "#FFDF36", subtitle_outline_color: "#000000", subtitle_outline: 4, subtitle_shadow: 1, subtitle_background: false, subtitle_alignment: "center", subtitle_position: 70, subtitle_caption_width: 85, subtitle_animation: "pop", subtitle_animation_intensity: 0.12, subtitle_animation_duration: 100 },
    };
    applyEdit((current) => ({ ...current, subtitle_preset: preset, ...config[preset] }));
  };
  const seekSubtitleSegment = (segment: Segment) => {
    if (edit.subtitle_timebase === "output") { seekOutput(segment.start); return; }
    const sourceTime = segment.start;
    const scene = compositionScenes.find((item) => sourceTime >= item.source_start && sourceTime < item.source_end);
    if (scene) seekOutput((scene.timeline_start || 0) + sourceTime - scene.source_start);
  };
  const seekSubtitleWord = (word: Word) => {
    if (word.start == null) return;
    if (edit.subtitle_timebase === "output") { seekOutput(word.start); return; }
    const sourceTime = edit.subtitle_timebase === "clip" ? sourceStart + word.start : word.start;
    const scene = compositionScenes.find((item) => sourceTime >= item.source_start && sourceTime < item.source_end);
    if (scene) seekOutput((scene.timeline_start || 0) + sourceTime - scene.source_start);
  };
  const render = async () => {
    if (edit.subtitle_enabled && staleActiveSubtitle) { setError("Subtitle output track stale after scene edits. Choose another track or regenerate/import for current composition."); return; }
    if (edit.subtitle_enabled && edit.subtitle_display_mode !== "original" && (!activeTranslationTrack || translationOutdated)) { setError("Selected translation missing or outdated. Choose Original Only or translate current cues again."); return; }
    if (edit.subtitle_enabled && edit.subtitle_caption_mode === "word_pop" && !wordPopReady) { setError("Word Pop needs reviewed, non-overlapping word timestamps for every visible caption. Add manual timings or use a word-timestamp provider."); return; }
    if (dirty && !(await save())) return;
    try {
      const result = await request<{ id: string; status: string }>(`/clips/${data.clip.id}/render`, { method: "POST" });
      setPreviewRendered(false); setData((current) => current ? { ...current, clip: { ...current.clip, status: current.clip.rendered ? "needs_render" : current.clip.status, review_status: "needs_review" } } : current); setJob({ id: result.id, kind: "render", status: result.status, phase: result.status, progress: null, message: "Job masuk antrean" });
    } catch (reason) { setError((reason as Error).message); }
  };
  const decideReview = async (status: "approved" | "needs_revision") => {
    setError(""); setReviewBusy(true);
    try {
      const result = await request<{ id: string; review_status: ReviewStatus }>(`/clips/${data.clip.id}/review`, { method: "POST", body: JSON.stringify({ status }) });
      setData((current) => current ? { ...current, clip: { ...current.clip, review_status: result.review_status } } : current);
    } catch (reason) { setError((reason as Error).message); }
    finally { setReviewBusy(false); }
  };
  const openPublish = async () => {
    setPublishError(""); setPublishNotice(false); setPublishStep("details");
    try {
      const result = await request<{ accounts: PublishAccount[] }>("/youtube/accounts");
      const connected = result.accounts.filter((account) => account.status === "connected");
      setPublishAccounts(connected);
      setPublishForm({ account_id: connected[0]?.id || "", title: data.clip.title, description: "", tags: "", privacy_status: "private", made_for_kids: "", contains_synthetic_media: "" });
      setPublishOpen(true);
    } catch (reason) { setPublishError((reason as Error).message); }
  };
  const confirmPublish = async () => {
    if (!publishForm.account_id || !publishForm.made_for_kids || !publishForm.contains_synthetic_media) {
      setPublishError("Pilih channel, Made for Kids, dan synthetic-content disclosure."); return;
    }
    setPublishBusy(true); setPublishError("");
    try {
      await request(`/clips/${data.clip.id}/youtube-publications`, {
        method: "POST",
        body: JSON.stringify({
          account_id: publishForm.account_id, title: publishForm.title, description: publishForm.description,
          tags: publishForm.tags.split(",").map((tag) => tag.trim()).filter(Boolean), privacy_status: publishForm.privacy_status,
          made_for_kids: publishForm.made_for_kids === "yes", contains_synthetic_media: publishForm.contains_synthetic_media === "yes",
          confirmed: true,
        }),
      });
      setPublishOpen(false); setPublishNotice(true);
    } catch (reason) { setPublishError((reason as Error).message); }
    finally { setPublishBusy(false); }
  };
  const changePublish = <K extends keyof PublishForm>(key: K, value: PublishForm[K]) => setPublishForm((current) => ({ ...current, [key]: value }));
  const clearYouTubeReference = async () => {
    setReferenceBusy(true);
    try {
      await request(`/clips/${data.clip.id}/youtube-reference`, { method: "DELETE" });
      setData((current) => current ? { ...current, clip: { ...current.clip, youtube_reference: null } } : current);
    } catch (reason) { setError((reason as Error).message); }
    finally { setReferenceBusy(false); }
  };
  const timelineTimeAt = (clientX: number) => {
    const rect = timelineTrackRef.current?.getBoundingClientRect();
    return rect ? Math.max(0, Math.min(timelineDuration, (clientX - rect.left) / timelineScale)) : 0;
  };
  const beginRangeSelection = (event: React.PointerEvent<HTMLDivElement>) => {
    if (running || !timelineDuration) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const start = timelineTimeAt(event.clientX);
    timelineGesture.current = { kind: "select", start };
    setCutRange({ start, end: start });
  };
  const beginSceneResize = (event: React.PointerEvent<HTMLButtonElement>, id: string, edge: "start" | "end") => {
    event.preventDefault(); event.stopPropagation();
    if (!edit || running) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const scene = compositionScenes.find((item) => item.id === id);
    if (!scene) return;
    timelineGesture.current = { kind: "resize", id, edge, originX: event.clientX, sourceStart: scene.source_start, sourceEnd: scene.source_end, baseEdit: edit };
  };
  const beginSubtitleGesture = (event: React.PointerEvent<HTMLElement>, id: string, edge: "move" | "start" | "end") => {
    event.preventDefault(); event.stopPropagation();
    if (!edit || running || edit.subtitle_timebase !== "output") return;
    const segment = edit.subtitle_segments.find((item) => item.id === id);
    if (!segment) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    timelineGesture.current = { kind: "subtitle", id, edge, originX: event.clientX, start: segment.start, end: segment.end, baseEdit: edit };
    setSubtitleSelectedIds([id]);
  };
  const moveTimelinePointer = (event: React.PointerEvent<HTMLDivElement>) => {
    const gesture = timelineGesture.current;
    if (!gesture) return;
    if (gesture.kind === "select") {
      const time = timelineTimeAt(event.clientX);
      setCutRange({ start: Math.min(gesture.start, time), end: Math.max(gesture.start, time) });
      return;
    }
    if (gesture.kind === "subtitle") {
      const delta = (event.clientX - gesture.originX) / timelineScale;
      let start = gesture.start, end = gesture.end;
      if (gesture.edge === "move") {
        const shifted = Math.max(-gesture.start, Math.min(timelineDuration - gesture.end, delta));
        start += shifted; end += shifted;
      } else if (gesture.edge === "start") start = Math.max(0, Math.min(gesture.end - minSubtitleDuration, gesture.start + delta));
      else end = Math.max(gesture.start + minSubtitleDuration, Math.min(timelineDuration, gesture.end + delta));
      setSubtitleDragPreview({ id: gesture.id, start, end });
      return;
    }
    const baseScenes = gesture.baseEdit.scene_mode === "multi" ? gesture.baseEdit.scenes : compositionScenes;
    const delta = (event.clientX - gesture.originX) / timelineScale;
    const start = gesture.edge === "start" ? gesture.sourceStart + delta : gesture.sourceStart;
    const end = gesture.edge === "end" ? gesture.sourceEnd + delta : gesture.sourceEnd;
    setResizePreview(updateSceneRange(baseScenes, gesture.id, start, end, data.source.duration) as Scene[] | null);
  };
  const endTimelinePointer = () => {
    const gesture = timelineGesture.current;
    timelineGesture.current = null;
    if (gesture?.kind === "resize" && resizePreview) {
      if (commitEdit(editWithScenes(gesture.baseEdit, resizePreview), gesture.baseEdit)) setPreviewRendered(false);
    } else if (gesture?.kind === "subtitle" && subtitleDragPreview) {
      const selected = gesture.baseEdit.subtitle_segments.find((item) => item.id === gesture.id);
      const delta = selected ? subtitleDragPreview.start - selected.start : 0;
      const next = { ...gesture.baseEdit, subtitle_segments: gesture.baseEdit.subtitle_segments.map((item) => item.id === gesture.id ? {
        ...item, start: subtitleDragPreview.start, end: subtitleDragPreview.end,
        words: item.words?.map((word) => ({ ...word, start: word.start == null ? null : word.start + delta, end: word.end == null ? null : word.end + delta })),
        word_alignment_reviewed: item.words?.length ? false : item.word_alignment_reviewed, edited: true,
      } : item) };
      setTranslationDirty(true);
      commitEdit(next, gesture.baseEdit);
    }
    setResizePreview(null);
    setSubtitleDragPreview(null);
  };
  const handleSceneDrop = (targetId: string) => {
    if (!edit || !dragSceneId || dragSceneId === targetId) return;
    const reordered = reorderScene(compositionScenes, dragSceneId, targetId) as Scene[];
    commitEdit(toSourceTimedEdit(edit, reordered));
    setDragSceneId("");
  };
  const updateSelectedSceneRange = (start: number, end: number) => {
    if (!edit || !selectedScene) return;
    const next = updateSceneRange(compositionScenes, selectedScene.id, start, end, data.source.duration) as Scene[] | null;
    if (!next) { setError("Rentang scene perlu minimal 0,5 detik dan harus berada di dalam sumber."); return; }
    if (edit.scene_mode === "single" && (start < sourceStart || end > data.clip.end)) {
      setError("Single Scene trim harus tetap di dalam kandidat Quick Clip."); return;
    }
    if (!commitEdit(editWithScenes(edit, next))) return;
    setCutRange(null);
  };
  const onPreviewLoaded = (event: React.SyntheticEvent<HTMLVideoElement>) => {
    setPreviewUnavailable(false);
    const mapped = outputToSource(compositionScenes, compositionTime);
    const time = previewRendered ? 0 : mapped?.sourceTime ?? sourceStart + edit.trim_start;
    if (mapped && !previewRendered) previewSceneId.current = mapped.sceneId;
    event.currentTarget.currentTime = time;
  };
  const onPreviewTimeUpdate = (event: React.SyntheticEvent<HTMLVideoElement>) => {
    const video = event.currentTarget;
    if (previewRendered) {
      setCompositionTime(Math.min(timelineDuration, video.currentTime));
      return;
    }
    const scene = compositionScenes.find((item) => item.id === previewSceneId.current);
    if (!scene || video.currentTime < scene.source_start - 0.05 || video.currentTime > scene.source_end + 0.5) return;
    if (video.currentTime >= scene.source_end - 0.015) {
      const index = compositionScenes.findIndex((item) => item.id === scene?.id);
      const next = compositionScenes[index + 1];
      if (next) {
        previewSceneId.current = next.id;
        setSelectedSceneId(next.id);
        setCompositionTime(next.timeline_start || 0);
        video.currentTime = next.source_start;
      } else {
        video.pause();
        setCompositionTime(timelineDuration);
      }
      return;
    }
    setCompositionTime((scene.timeline_start || 0) + video.currentTime - scene.source_start);
  };
  const togglePlayback = () => {
    const video = previewRef.current;
    if (!video) return;
    if (video.paused) {
      if (compositionTime >= timelineDuration) seekOutput(0);
      void video.play().catch(() => setError("Browser tidak dapat memulai preview video."));
    } else video.pause();
  };
  const togglePreviewFullscreen = async () => {
    const stage = previewStageRef.current;
    if (!stage) return;
    try {
      if (document.fullscreenElement === stage) await document.exitFullscreen();
      else await stage.requestFullscreen();
    } catch { setError("Browser tidak dapat membuka preview layar penuh."); }
  };
  const switchSceneMode = (mode: Edit["scene_mode"]) => {
    if (mode === edit.scene_mode) return;
    if (mode === "multi") {
      if (timelineDuration > 180) { setError("Multi-Scene output tidak dapat melebihi 180 detik."); return; }
      if (!commitEdit(toSourceTimedEdit(edit, compositionScenes))) return;
      setSelectedSceneId(compositionScenes[0]?.id || "");
      return;
    }
    const scene = compositionScenes.find((item) => item.id === selectedSceneId) || compositionScenes[0];
    if (!scene) return;
    if (scene.source_start < sourceStart || scene.source_end > data.clip.end) {
      setError("Scene berada di luar batas kandidat Quick Clip; gunakan mode Multi-Scene untuk rentang ini."); return;
    }
    const { id, source_start, source_end, role } = scene;
    commitEdit({
      ...edit,
      scene_mode: "single",
      scenes: [{ id, source_start, source_end, order: 0, role }],
      trim_start: source_start - sourceStart,
      trim_end: source_end - sourceStart,
      subtitle_timebase: edit.subtitle_timebase === "output" ? "output" : "clip",
       subtitle_segments: edit.subtitle_timebase === "source"
         ? edit.subtitle_segments.flatMap((segment) => {
           const start = Math.max(source_start, segment.start);
           const end = Math.min(source_end, segment.end);
           return start < end ? [{
             ...segment, start: start - sourceStart, end: end - sourceStart,
             words: segment.words?.map((word) => ({ ...word, start: word.start == null ? null : word.start - sourceStart, end: word.end == null ? null : word.end - sourceStart })),
           }] : [];
         })
        : edit.subtitle_segments,
    });
  };
  const phaseName: Record<string, string> = { queued: "Antrean lokal", preparing: "Menyiapkan", preparing_audio: "Menyiapkan audio komposisi", uploading: "Mengunggah ke provider", transcribing: "Transkripsi berjalan", processing_result: "Memvalidasi hasil", analyzing: "Menganalisis", rendering: "FFmpeg merender", completed: "Selesai", failed: "Gagal", cancelled: "Dibatalkan" };
  const running = Boolean(job && job.kind === "render" && ["queued", "preparing", "rendering"].includes(job.status));
  const subtitleJobRunning = Boolean(job && job.kind !== "render" && ["queued", "preparing", "preparing_audio", "uploading", "transcribing", "processing_result"].includes(job.status));
  const canReview = data.clip.rendered && data.clip.status === "completed" && !dirty && !running && !reviewBusy;
  const videoUrl = previewRendered && data.clip.rendered ? `${API}/api/clips/${data.clip.id}/file` : `${API}/api/sources/${data.clip.source_id}/file`;
  const subtitleClock = edit.subtitle_timebase === "output" ? compositionTime : edit.subtitle_timebase === "source" ? currentSourceTime : currentSourceTime - sourceStart;
  const activeSubtitle = visibleSegments.find((segment) => {
    const start = edit.subtitle_timebase === "clip" ? segment.start - sourceStart : segment.start;
    const end = edit.subtitle_timebase === "clip" ? segment.end - sourceStart : segment.end;
    return start <= subtitleClock && end > subtitleClock;
  });
  const translationOutdated = Boolean(activeTranslationTrack && (translationDirty || data.subtitle_status.outdated_translation_ids.includes(activeTranslationTrack.id)));
  const translatedCaption = !translationOutdated && activeSubtitle
    ? activeTranslationTrack?.segments.find((item) => item.source_segment_id === activeSubtitle.id)?.text
    : undefined;
  const wordPopSegments = visibleSegments.map((visible) => edit.subtitle_segments.find((segment) => segment.id === visible.id)).filter((segment): segment is Segment => Boolean(segment));
  const wordPopReady = !staleActiveSubtitle && edit.subtitle_display_mode === "original" && wordPopSegments.length > 0 && wordPopSegments.every(validWordAlignment);
  const originalCaption = activeSubtitle ? edit.subtitle_overrides[String(activeSubtitle.index)] ?? activeSubtitle.text : "";
  const captionWords = activeSubtitle?.words || [];
  const activeWordSegment = activeSubtitle ? edit.subtitle_segments.find((segment) => segment.id === activeSubtitle.id) : undefined;
  const activeWordIndex = edit.subtitle_caption_mode === "word_pop" && (staleActiveSubtitle || edit.subtitle_display_mode !== "original" || !validWordAlignment(activeWordSegment)) ? -1 : activeWordIndexAt(captionWords, subtitleClock);
  const activeWord = activeWordIndex >= 0 ? captionWords[activeWordIndex] : null;
  const phrase = groupCaptionWords(captionWords).find((group) => group.some((word) => word.start != null && word.end != null && word.start <= subtitleClock && word.end > subtitleClock));
  const previewOriginal = edit.subtitle_caption_mode === "word_pop" && edit.subtitle_display_mode === "original" && activeWord
    ? activeWord.text
    : edit.subtitle_display_mode === "translated" && translatedCaption
    ? translatedCaption
    : edit.subtitle_caption_mode === "word" && activeWordIndex >= 0
    ? captionWords[activeWordIndex].text
    : edit.subtitle_caption_mode === "phrase" && phrase?.length
       ? joinWordText(phrase)
      : edit.subtitle_display_mode === "translated" && translatedCaption ? translatedCaption : originalCaption;
  const previewCaption = activeSubtitle && (edit.subtitle_caption_mode !== "word_pop" || activeWord) ? <>
    {edit.subtitle_caption_mode === "word_pop" ? <span key={activeWord?.id}>{activeWord?.text}</span> : edit.subtitle_display_mode !== "translated" && edit.subtitle_caption_mode === "karaoke" && captionWords.length ? captionWords.map((word, index) => <span key={word.id} className={index === activeWordIndex ? "preview-word-active" : ""} style={index === activeWordIndex ? { color: edit.subtitle_highlight_color } : undefined}>{word.text}{index < captionWords.length - 1 && !/^[,.;:!?%)\]}]/.test(captionWords[index + 1].text) ? " " : ""}</span>) : previewOriginal}
    {edit.subtitle_caption_mode !== "word_pop" && edit.subtitle_display_mode === "bilingual" && translatedCaption && <span className="preview-caption-translation">{translatedCaption}</span>}
  </> : null;
  const wordPopDefaults: Partial<Edit> = { style: "Bold", subtitle_font: "Arial", subtitle_size: 58, subtitle_color: "#FFDF36", subtitle_outline_color: "#000000", subtitle_outline: 4, subtitle_shadow: 1, subtitle_background: false, subtitle_alignment: "center", subtitle_position: 70, subtitle_caption_width: 85, subtitle_animation: "pop", subtitle_animation_intensity: 0.12, subtitle_animation_duration: 100, subtitle_preset: "Word Pop" };
  const changeSubtitleType = (type: Edit["subtitle_caption_mode"]) => {
    if (type === "word_pop" && !wordPopReady) { setSubtitleNotice("Word Pop needs word-level timings for every visible cue. Use Gemini word timing or set manual word timings, then mark them reviewed."); return; }
    setSubtitleNotice("");
    applyEdit((current) => ({ ...current, subtitle_caption_mode: type, ...(type === "word_pop" ? { ...wordPopDefaults, subtitle_display_mode: "original" as const } : {}) }));
  };
  const activeWordDuration = activeWord?.start != null && activeWord.end != null ? activeWord.end - activeWord.start : 0;
  const wordPopAnimating = edit.subtitle_caption_mode === "word_pop" && activeWordDuration >= 0.18 && edit.subtitle_animation !== "none";
  const wordPopPosition = Math.min(Math.min(90, 100 - edit.subtitle_safe_margin), Math.max(Math.max(10, edit.subtitle_safe_margin), edit.subtitle_position));
  const wordPopGlyphUnits = Array.from(activeWord?.text || " ").reduce((units, char) => units + ((char.codePointAt(0) || 0) > 0x2e80 ? 1 : 0.58), 0);
  const wordPopMinimumFont = 12 * 100 / (edit.resolution === "1080" ? 1920 : 1280);
  const captionStyle: React.CSSProperties & { "--word-pop-scale"?: string; "--word-pop-duration"?: string } = {
    left: edit.subtitle_caption_mode === "word_pop" ? "50%" : `${edit.subtitle_safe_margin}%`,
    right: edit.subtitle_caption_mode === "word_pop" ? "auto" : `${edit.subtitle_safe_margin}%`,
    top: edit.subtitle_caption_mode === "word_pop" ? `${wordPopPosition}%` : edit.subtitle_alignment === "top" ? `${100 - edit.subtitle_position}%` : edit.subtitle_alignment === "center" ? "50%" : undefined,
    bottom: edit.subtitle_caption_mode === "word_pop" ? undefined : edit.subtitle_alignment === "bottom" ? `${Math.max(5, edit.subtitle_position / 4)}%` : undefined,
    transform: edit.subtitle_caption_mode === "word_pop" || edit.subtitle_alignment === "center" ? "translate(-50%,-50%)" : undefined,
    maxWidth: `${edit.subtitle_caption_mode === "word_pop" ? Math.min(edit.subtitle_caption_width, 100 - edit.subtitle_safe_margin * 2) : edit.subtitle_caption_width}%`, marginInline: "auto",
    fontFamily: edit.subtitle_font,
    fontSize: edit.subtitle_caption_mode === "word_pop"
      ? `max(${wordPopMinimumFont}cqh,min(${edit.subtitle_size / 12.8}cqh,${Math.min(edit.subtitle_caption_width, 100 - edit.subtitle_safe_margin * 2) / (Math.max(1, wordPopGlyphUnits) * 0.62)}cqw))`
      : `${Math.max(12, edit.subtitle_size / 3)}px`,
    color: edit.subtitle_color, fontWeight: edit.style === "Bold" ? 900 : 700,
    textShadow: edit.subtitle_caption_mode === "word_pop"
      ? `-${edit.subtitle_outline / 12.8}cqh 0 ${edit.subtitle_outline_color}, ${edit.subtitle_outline / 12.8}cqh 0 ${edit.subtitle_outline_color}, 0 -${edit.subtitle_outline / 12.8}cqh ${edit.subtitle_outline_color}, 0 ${edit.subtitle_outline / 12.8}cqh ${edit.subtitle_outline_color}, 0 ${edit.subtitle_shadow / 12.8}cqh ${edit.subtitle_shadow / 6.4}cqh #000`
      : `-${edit.subtitle_outline / 5}px 0 ${edit.subtitle_outline_color}, ${edit.subtitle_outline / 5}px 0 ${edit.subtitle_outline_color}, 0 -${edit.subtitle_outline / 5}px ${edit.subtitle_outline_color}, 0 ${edit.subtitle_outline / 5}px ${edit.subtitle_outline_color}, 0 ${edit.subtitle_shadow}px ${edit.subtitle_shadow * 2}px #000`,
    backgroundColor: edit.subtitle_background ? "rgba(4,12,16,.72)" : undefined,
    padding: edit.subtitle_background ? "5px 9px" : undefined,
    whiteSpace: edit.subtitle_caption_mode === "word_pop" ? "nowrap" as const : undefined,
    "--word-pop-scale": String(1 - edit.subtitle_animation_intensity),
    "--word-pop-duration": `${Math.min(edit.subtitle_animation_duration, activeWordDuration * 350)}ms`,
    animationDuration: wordPopAnimating ? `${Math.min(edit.subtitle_animation_duration, activeWordDuration * 350)}ms` : undefined,
  };
  const captionAnimationClass = edit.subtitle_caption_mode === "word_pop"
    ? wordPopAnimating ? edit.subtitle_animation === "fade" ? "word-pop-preview-fade" : edit.subtitle_animation === "pop" ? "word-pop-preview-pop" : "word-pop-preview-animation" : ""
    : edit.subtitle_animation === "fade" ? "caption-anim-fade" : edit.subtitle_animation === "pop" || edit.subtitle_animation === "scale" ? "caption-anim-pop" : "";
  const timelineScenes = sceneTimeline(displayedScenes) as Scene[];
  const selectedScene = compositionScenes.find((scene) => scene.id === selectedSceneId) || compositionScenes[0];
  const validCutRange = Boolean(cutRange && cutRange.end - cutRange.start >= 0.001 && cutRange.end <= timelineDuration);

  return <>
    <div className="page-intro clip-editor-intro">{batchId ? <button type="button" className="back-link mode-back" onClick={() => void returnToBatch()}><ArrowLeft size={14}/> Kembali ke Batch</button> : <Link href={`/sources/${data.clip.source_id}`} className="back-link"><ArrowLeft size={14}/> Kandidat klip</Link>}<div className="eyebrow">{data.clip.origin === "quick_clip" ? "QUICK CLIP EDITOR" : "AI SMART CLIP EDITOR"} · #{String(data.clip.rank).padStart(2,"0")}</div><h1>{data.clip.title}</h1><p>{data.source.name} · {formatDuration(data.clip.start)}–{formatDuration(data.clip.end)} · {data.clip.origin === "quick_clip" ? "Timestamp manual; editor tidak menjalankan AI." : "Editor tidak mengulang transkripsi atau analisis AI."}</p></div>
    {data.clip.youtube_reference && <section className="youtube-origin-notice"><div><strong>{data.clip.youtube_reference.source_association === "auto_imported" ? "Segmen impor · adapter lokal opsional" : "Referensi YouTube · file lokal pilihan pengguna"}</strong><span>{data.clip.youtube_reference.source_association === "auto_imported" ? <>Quick Clip memakai segmen lokal <b>{data.source.name}</b>, diminta pada timestamp ini. yt-dlp bukan metode resmi YouTube; pastikan metode pengambilan dan penggunaan konten diizinkan.</> : <>Quick Clip memakai file lokal <b>{data.source.name}</b>, dipilih pengguna. Klipnara tidak memverifikasi kecocokan file dengan preview.</>}</span><small>{data.clip.youtube_reference.start.toFixed(0)}–{data.clip.youtube_reference.end.toFixed(0)} dtk · ID {data.clip.youtube_reference.video_id}</small></div><a href={data.clip.youtube_reference.canonical_url} target="_blank" rel="noreferrer">Buka referensi <ExternalLink size={12}/></a><button type="button" className="button button-quiet" onClick={() => void clearYouTubeReference()} disabled={referenceBusy}>{referenceBusy ? <LoaderCircle size={13} className="spin"/> : <X size={13}/>} Hapus referensi</button></section>}
    <section className="review-toolbar" aria-live="polite">
      <div className="review-status-summary"><span>Status review</span><strong className={`review-status-chip review-${data.clip.review_status.replace("_", "-")}`}>{reviewStatusLabel(data.clip.review_status)}</strong></div>
      <div className="review-actions">
        <button className="button button-outline" onClick={() => void decideReview("needs_revision")} disabled={!canReview || data.clip.review_status === "needs_revision"}><RotateCcw size={14}/> Perlu Revisi</button>
        <button className="button button-primary" onClick={() => void decideReview("approved")} disabled={!canReview || data.clip.review_status === "approved"}><CheckCircle2 size={14}/> Setujui Klip</button>
      </div>
      {!canReview && <small>{reviewBusy ? "Menyimpan keputusan review…" : dirty ? "Simpan edit dan render ulang sebelum review." : data.clip.status !== "completed" || !data.clip.rendered ? "Render final MP4 sebelum review." : "Tunggu render selesai sebelum review."}</small>}
      </section>
      <section className="clip-editor-actions" aria-label="Draft and render actions">
        <div className="clip-editor-statuses" aria-live="polite">
          <span className={`clip-editor-save-status save-${editorStatus.draft}`}><Save size={13}/>{editorStatus.draft === "saving" ? "Saving" : editorStatus.draft === "failed" ? "Save failed" : editorStatus.draft === "unsaved" ? "Unsaved changes" : "Saved"}</span>
          {editorStatus.renderRequired && <span className="clip-editor-render-status">{editorStatus.renderOutdated ? "Render perlu diperbarui" : "Render diperlukan"}</span>}
        </div>
        <div className="clip-editor-action-buttons">
          {data.clip.review_status === "approved" && data.clip.status === "completed" && data.clip.rendered && !dirty && <button className="button button-youtube" onClick={() => void openPublish()} disabled={running || subtitleBusy || subtitleSaving}><Youtube size={14}/> Posting ke YouTube</button>}
          <button className="button button-outline" onClick={save} disabled={!dirty || subtitleSaving}><Save size={14}/>{dirty ? subtitleSaving ? "Menyimpan…" : "Simpan edit" : "Tersimpan"}{!dirty && <Check size={13}/>}</button>
          {batchId ? <button className="button button-primary" onClick={() => void returnToBatch()} disabled={subtitleSaving}>Simpan & kembali ke Batch<ArrowLeft className="render-arrow" size={14}/></button> : <button className="button button-primary" onClick={render} disabled={running || subtitleBusy || subtitleSaving}><Sparkles size={14}/>{running ? "Sedang render…" : "Render ulang"}<ArrowLeft className="render-arrow" size={14}/></button>}
          {data.clip.rendered && <a href={`${API}/api/clips/${data.clip.id}/download`} className="download-link"><Download size={14}/>{editorStatus.renderOutdated ? "Download render lama" : "Download MP4"}</a>}
        </div>
      </section>
      {job && <section className="panel editor-job" aria-live="polite"><div><strong>{phaseName[job.status] || job.phase}</strong><span>{job.message}</span>{job.progress != null && <progress max={1} value={job.progress}/>}</div><div>{subtitleJobRunning && <button className="button button-outline" type="button" onClick={() => void cancelJob()}><X size={13}/> Batalkan</button>}{["failed", "cancelled"].includes(job.status) && <button className="button button-outline" type="button" onClick={() => void retryJob()}><RotateCcw size={13}/> Retry</button>}</div></section>}
     {subtitleNotice && <div className="notice notice-success"><CheckCircle2 size={15}/>{subtitleNotice}</div>}
     {error && <div className="notice notice-error"><AlertCircle size={15}/>{error}</div>}
     {publishNotice && <div className="notice notice-success"><CheckCircle2 size={15}/>Upload masuk antrean. Lihat status di <Link href="/accounts">Publishing History</Link>.</div>}
     {publishError && !publishOpen && <div className="notice notice-error"><AlertCircle size={15}/>{publishError}</div>}
      <div className="clip-editor-workspace">
      <section className={`panel clip-preview-workspace ${previewCollapsed ? "preview-collapsed" : ""}`}>
       <div className="editor-panel-heading"><div><strong>Preview komposisi</strong><span>{edit.scene_mode === "multi" ? `${compositionScenes.length} scene · hard cut` : "Single Scene · Quick Clip"} · {edit.resolution === "720" ? "720 × 1280" : "1080 × 1920"}</span></div><div className="preview-actions">{data.clip.rendered && <button type="button" className={`preview-toggle ${previewRendered ? "active" : ""}`} onClick={() => { setCompositionTime(0); setPreviewRendered((value) => !value); }}><Eye size={13}/>{previewRendered ? editorStatus.renderOutdated ? "Render lama" : "Hasil render" : "Sumber"}</button>}<button type="button" className="preview-toggle preview-collapse-toggle" aria-expanded={!previewCollapsed} aria-label={previewCollapsed ? "Expand live preview" : "Collapse live preview"} title={previewCollapsed ? "Expand live preview" : "Collapse live preview"} onClick={() => setPreviewCollapsed((value) => !value)}><ChevronDown size={13}/></button><span className="local-only-pill"><LockKeyhole size={12}/> LOCAL</span></div></div>
          <div className="clip-preview-grid"><div ref={previewStageRef} className="portrait-stage clip-composition-stage"><video key={`${videoUrl}-${previewRendered}`} ref={previewRef} src={videoUrl} muted={previewMuted ?? edit.audio.muted} playsInline preload="metadata" style={{ objectFit: "cover", objectPosition: `${edit.crop_x}% ${edit.crop_y}%` }} onLoadedMetadata={onPreviewLoaded} onError={() => setPreviewUnavailable(true)} onTimeUpdate={onPreviewTimeUpdate} onPlay={() => setPreviewPlaying(true)} onPause={() => setPreviewPlaying(false)}/>{edit.title_overlay.enabled && !previewRendered && compositionTime < edit.title_overlay.duration && <div className="preview-title-overlay" style={{ top: `${edit.title_overlay.position}%`, color: edit.title_overlay.color, fontFamily: edit.title_overlay.font, fontSize: `${Math.max(12, edit.title_overlay.size / 3)}px` }}>{edit.title_overlay.text}</div>}{edit.subtitle_enabled && !previewRendered && activeSubtitle && <div className={`preview-caption style-${edit.style.toLowerCase()} ${captionAnimationClass}`} style={captionStyle}>{previewCaption}</div>}{previewUnavailable && <div className="preview-media-unavailable" role="status">Preview tidak tersedia. Draft tetap utuh; periksa file sumber atau MP4 hasil render.</div>}<div className="preview-fullscreen-controls"><button type="button" className="preview-control-icon" aria-label={previewPlaying ? "Pause preview" : "Play preview"} onClick={togglePlayback}>{previewPlaying ? <Pause size={16}/> : <Play size={16}/>}</button><button type="button" className="preview-control-icon" aria-label={(previewMuted ?? edit.audio.muted) ? "Unmute preview" : "Mute preview"} onClick={() => setPreviewMuted(!(previewMuted ?? edit.audio.muted))}>{(previewMuted ?? edit.audio.muted) ? <VolumeX size={16}/> : <Volume2 size={16}/>}</button><button type="button" className="preview-control-icon" aria-label="Exit fullscreen preview" onClick={() => void togglePreviewFullscreen()}><Minimize2 size={16}/></button></div><div className="preview-fullscreen-seek"><input aria-label="Fullscreen output seek" type="range" min="0" max={Math.max(timelineDuration, 0.01)} step="0.01" value={Math.min(compositionTime, timelineDuration)} onChange={(event) => seekOutput(Number(event.target.value))}/><span>{formatDuration(compositionTime)} / {formatDuration(timelineDuration)}</span></div><span className="preview-frame-label"><Film size={12}/> {previewRendered ? "RENDERED MP4" : "LIVE SOURCE PREVIEW"}</span></div>
         <div className="clip-preview-controls"><div className="preview-transport"><button className="button button-outline" type="button" onClick={togglePlayback}>{previewPlaying ? <Pause size={14}/> : <Play size={14}/>} {previewPlaying ? "Pause" : "Play"}</button><button className="button button-outline" type="button" onClick={() => { seekOutput(0); if (previewRef.current) void previewRef.current.play().catch(() => {}); }}>Ulangi</button><button type="button" className="icon-button preview-control-icon" aria-label={(previewMuted ?? edit.audio.muted) ? "Unmute preview" : "Mute preview"} title={(previewMuted ?? edit.audio.muted) ? "Unmute preview" : "Mute preview"} onClick={() => setPreviewMuted(!(previewMuted ?? edit.audio.muted))}>{(previewMuted ?? edit.audio.muted) ? <VolumeX size={14}/> : <Volume2 size={14}/>}</button><button type="button" className="icon-button preview-control-icon" aria-label={previewFullscreen ? "Exit fullscreen preview" : "Fullscreen preview"} title={previewFullscreen ? "Exit fullscreen" : "Fullscreen"} onClick={() => void togglePreviewFullscreen()}>{previewFullscreen ? <Minimize2 size={14}/> : <Maximize2 size={14}/>}</button><span>{formatDuration(compositionTime)} / {formatDuration(timelineDuration)}</span></div><input aria-label="Scrubber komposisi output" type="range" min="0" max={Math.max(timelineDuration, 0.01)} step="0.01" value={Math.min(compositionTime, timelineDuration)} onChange={(event) => seekOutput(Number(event.target.value))}/><p>Preview browser melompat antar rentang sumber; render final memakai FFmpeg. {previewRendered && editorStatus.renderOutdated ? "MP4 yang ditampilkan belum mencakup edit terbaru." : ""}</p></div></div>
     </section>
      <div className={`editor-layout-legacy ${edit.scene_mode}`}>


      <div className={`editor-tools ${running || subtitleBusy || subtitleSaving ? "tools-disabled" : ""}`} aria-disabled={running || subtitleBusy || subtitleSaving}>
        <details className="panel tool-panel" open><summary className="tool-heading"><span className="tool-icon"><Scissors size={15}/></span><div><strong>Trim klip</strong><small>Batasi potongan di dalam kandidat</small></div><ChevronDown size={14}/></summary><div className="trim-track"><div className="trim-fill"/><i/><i/></div><div className="trim-fields"><label><span>Awal klip</span><div><input type="number" min="0" max={edit.trim_end - 1} step="0.1" value={edit.trim_start} onChange={(event) => update("trim_start", Number(event.target.value))}/><small>detik</small></div></label><span className="trim-separator">—</span><label><span>Akhir klip</span><div><input type="number" min={edit.trim_start + 0.1} max={length} step="0.1" value={edit.trim_end} onChange={(event) => update("trim_end", Number(event.target.value))}/><small>detik</small></div></label></div><div className="trim-boundaries"><span>{formatDuration(data.clip.start + edit.trim_start)} sumber</span><span>{formatDuration(data.clip.start + edit.trim_end)} sumber</span></div></details>

        <details className="panel tool-panel" open><summary className="tool-heading"><span className="tool-icon purple"><Settings2 size={15}/></span><div><strong>Crop & fokus</strong><small>Posisi sumber dalam frame 9:16</small></div><ChevronDown size={14}/></summary><div className="range-control"><div><label>Horizontal</label><span>{edit.crop_x === 50 ? "Center" : `${edit.crop_x}%`}</span></div><input aria-label="Posisi crop horizontal" type="range" min="0" max="100" value={edit.crop_x} onChange={(event) => update("crop_x", Number(event.target.value))}/><div className="range-labels"><span>Kiri</span><span>Tengah</span><span>Kanan</span></div></div><div className="range-control"><div><label>Vertikal</label><span>{edit.crop_y === 50 ? "Center" : `${edit.crop_y}%`}</span></div><input aria-label="Posisi crop vertikal" type="range" min="0" max="100" value={edit.crop_y} onChange={(event) => update("crop_y", Number(event.target.value))}/><div className="range-labels"><span>Atas</span><span>Tengah</span><span>Bawah</span></div></div><div className="field compact-field"><span>Resolusi output</span><select value={edit.resolution} onChange={(event) => update("resolution", event.target.value as Edit["resolution"])}><option value="720">720 × 1280</option><option value="1080">1080 × 1920</option></select></div></details>

         <details className="panel tool-panel subtitle-tool" open>
           <summary className="tool-heading"><span className="tool-icon amber-tool"><Type size={15}/></span><div><strong>Subtitle & translation</strong><small>{visibleSegments.length} cues · {edit.subtitle_timebase === "output" ? "output time" : edit.subtitle_timebase === "source" ? "source time" : "clip time"}</small></div><ChevronDown size={14}/></summary>
           <label className="field compact-field subtitle-mode-control"><span>Mode</span><select value={edit.subtitle_mode} onChange={(event) => setSubtitleMode(event.target.value as Edit["subtitle_mode"])}><option value="off">Off</option><option value="manual">Manual</option><option value="auto">Transcribe</option><option value="import">Import SRT/VTT</option></select></label>
           {edit.subtitle_mode === "auto" && <div className="subtitle-auto-controls">
             <div className="subtitle-auto-row"><label className="field compact-field"><span>Speech-to-text provider</span><select value={subtitleProvider} onChange={(event) => setSubtitleProvider(event.target.value as typeof subtitleProvider)}>
               {data.subtitle_stt.local && <option value="local">Local · whisper.cpp · segment timestamps</option>}{data.subtitle_stt.gemini && <option value="gemini">Gemini · word timestamps + speakers</option>}{data.subtitle_stt.openai && <option value="openai">OpenAI · transcript text only</option>}
             </select></label><label className="field compact-field"><span>Language</span><select value={subtitleLanguage} onChange={(event) => setSubtitleLanguage(event.target.value as typeof subtitleLanguage)}><option value="auto">Auto detect</option><option value="indonesia">Indonesian</option><option value="english">English</option></select></label></div>
              <button type="button" className="button button-outline subtitle-generate-button" onClick={() => void generateSubtitles()} disabled={subtitleBusy || subtitleJobRunning || edit.subtitle_tracks.length >= 20 || !data.source.audio_codec || !(subtitleProvider === "local" ? data.subtitle_stt.local : subtitleProvider === "gemini" ? data.subtitle_stt.gemini : data.subtitle_stt.openai)}>{subtitleBusy ? <LoaderCircle size={13} className="spin"/> : <Sparkles size={13}/>} {subtitleBusy ? "Queuing transcription…" : `Transcribe full composition · ${formatDuration(timelineDuration)}`}</button>
             <small className="subtitle-privacy-note">{subtitleProvider === "local" ? "Audio stays on this computer. Whisper returns segment timing." : subtitleProvider === "gemini" ? "Composition audio uploads only after confirmation. Verbatim word timings; max 30 minutes." : "Composition audio uploads only after confirmation. Text only; no timestamps are invented."}</small>
             {!data.source.audio_codec && <p className="empty-subtitles">Source has no audio. Manual and import remain available.</p>}
             {!data.subtitle_stt.local && !data.subtitle_stt.gemini && !data.subtitle_stt.openai && <p className="empty-subtitles">Configure local Whisper or a cloud API key to transcribe.</p>}
           </div>}
            {edit.subtitle_mode === "import" && <div className="subtitle-import-controls"><label className="button button-outline subtitle-file-button"><Download size={13}/> Choose SRT/VTT<input type="file" accept=".srt,.vtt,text/vtt,application/x-subrip" disabled={subtitleJobRunning || subtitleBusy || edit.subtitle_tracks.length >= 20} onChange={(event) => void importSubtitleFile(event)}/></label><small>UTF-8/UTF-16 · max 2 MiB · output-relative time. Import creates review draft; active captions stay unchanged.</small></div>}
           <div className="subtitle-track-list"><div className="subtitle-list-heading"><span>TRACKS · REVIEW BEFORE USE</span><span>{edit.subtitle_tracks.length}</span></div>
             {edit.subtitle_tracks.length ? edit.subtitle_tracks.map((track) => {
                const trackStale = track.timebase === "output" && (
                  track.composition_signature !== sceneSignature || data.subtitle_status.stale_track_ids.includes(track.id)
                );
               const outdated = data.subtitle_status.outdated_translation_ids.includes(track.id);
               const selected = track.id === edit.subtitle_active_track_id || track.id === edit.subtitle_active_translation_id;
               return <article className={`subtitle-track-card ${selected ? "selected" : ""}`} key={track.id}>
                 <div className="subtitle-track-title"><strong>{track.source_type === "translation" ? `Translation · ${track.language}` : track.source_type}</strong><span>{track.provider || "manual/import"} · {track.segments.length} timed cues{track.word_timestamps ? " · word timing" : ""}{track.speaker_identification ? " · speakers" : ""}</span></div>
                 {trackStale && <small className="subtitle-warning">Stale composition. Re-transcribe/import for current scene order and trims.</small>}{outdated && <small className="subtitle-warning">Source cues changed. Translation is outdated.</small>}
                 {!track.segments.length && track.transcript_text && <div className="subtitle-transcript-only"><small>Transcript text only · no timestamps. Copy text, then time cues manually.</small><pre>{track.transcript_text}</pre><button type="button" className="button button-outline" onClick={() => void navigator.clipboard.writeText(track.transcript_text || "").then(() => setSubtitleNotice("Transcript copied to clipboard.")).catch(() => setError("Clipboard unavailable; select and copy transcript text manually."))}><Copy size={12}/> Copy transcript</button></div>}
                  <div className="subtitle-track-actions"><button type="button" className="button button-outline" onClick={() => track.source_type === "translation" ? useTranslationTrack(track.id) : useSubtitleTrack(track)} disabled={trackStale || outdated || !track.segments.length}>Use track</button><a className="button button-outline" href={`${API}/api/clips/${data.clip.id}/subtitles/export?format=srt&track_id=${encodeURIComponent(track.id)}`} download>Export SRT</a><a className="button button-outline" href={`${API}/api/clips/${data.clip.id}/subtitles/export?format=vtt&track_id=${encodeURIComponent(track.id)}`} download>VTT</a><button type="button" className="button button-outline" onClick={() => removeSubtitleTrack(track.id)} aria-label={`Remove ${track.source_type} subtitle track`}><Trash2 size={12}/> Remove</button></div>
               </article>;
             }) : <p className="empty-subtitles">No generated or imported drafts yet.</p>}
           </div>
           {edit.subtitle_enabled && <div className="subtitle-translation-controls"><div className="subtitle-list-heading"><span>TRANSLATE CURRENT CUES</span><span>{visibleSegments.length}</span></div>
             <div className="subtitle-auto-row"><label className="field compact-field"><span>Provider</span><select value={translationProvider} onChange={(event) => setTranslationProvider(event.target.value as typeof translationProvider)}><option value="gemini" disabled={!data.subtitle_stt.gemini}>Gemini</option><option value="openai" disabled={!data.subtitle_stt.openai}>OpenAI</option></select></label><label className="field compact-field"><span>Target language</span><select value={translationTarget} onChange={(event) => setTranslationTarget(event.target.value as typeof translationTarget)}><option value="id-ID">Indonesian</option><option value="en-US">English</option></select></label></div>
              <button type="button" className="button button-outline" onClick={() => void translateSubtitles()} disabled={subtitleBusy || subtitleJobRunning || edit.subtitle_tracks.length >= 20 || !visibleSegments.length || !(translationProvider === "gemini" ? data.subtitle_stt.gemini : data.subtitle_stt.openai)}><Sparkles size={13}/> Translate to {translationTarget === "id-ID" ? "Indonesian" : "English"}</button>
             <small className="subtitle-privacy-note">Only subtitle text is sent after confirmation. Cue IDs and timing stay local; original track stays unchanged.</small>
              <label className="field compact-field"><span>Rendered language</span><select value={edit.subtitle_display_mode} onChange={(event) => update("subtitle_display_mode", event.target.value as Edit["subtitle_display_mode"])}><option value="original">Original only</option><option value="translated" disabled={edit.subtitle_caption_mode === "word_pop" || !activeTranslationTrack || translationOutdated}>Translated only</option><option value="bilingual" disabled={edit.subtitle_caption_mode === "word_pop" || !activeTranslationTrack || translationOutdated}>Bilingual</option></select></label>
             {translationOutdated && <small className="subtitle-warning">Translation disabled until current cues are translated again.</small>}
           </div>}
           {edit.subtitle_tracks.length >= 20 && <small className="subtitle-warning">Track limit reached (20). Remove an unused draft to add another.</small>}
            <div className="subtitle-edit-toolbar"><button type="button" className="button button-outline" onClick={addSubtitleSegment} disabled={running}><Plus size={13}/> Add cue</button>{edit.subtitle_timebase !== "output" && <button type="button" className="button button-outline" onClick={convertSubtitlesToOutput} disabled={!visibleSegments.length || edit.subtitle_tracks.length >= 20 || subtitleJobRunning}>Map cues to output timeline</button>}<label className="field compact-field"><span>Tipe Subtitle</span><select value={edit.subtitle_caption_mode} onChange={(event) => changeSubtitleType(event.target.value as Edit["subtitle_caption_mode"])}><option value="sentence">Standard · sentence</option><option value="phrase">Phrase by Phrase</option><option value="karaoke">Karaoke Highlight</option><option value="word_pop">Word Pop · one word</option><option value="word">Word · legacy</option></select></label></div>
            {edit.subtitle_caption_mode === "word_pop" && <small className={wordPopReady ? "subtitle-word-ready" : "subtitle-warning"}>{wordPopReady ? "Word Pop ready · reviewed word timestamps found." : "Word Pop locked until every visible cue has reviewed word-level timestamps. Use Gemini word timing or edit each cue manually."}</small>}
            <div className="subtitle-style-row"><label className="field compact-field"><span>Preset Style</span><select value={edit.subtitle_preset} onChange={(event) => applySubtitlePreset(event.target.value)}>{["Minimal Clean", "Bold Viral", "Karaoke Highlight", "Cinematic", "Podcast Caption", "Yellow Pop", "Soft Purple", "Classic White", "Word Pop"].map((preset) => <option key={preset}>{preset}</option>)}</select></label><label className="field compact-field"><span>Font family</span><select value={edit.subtitle_font} onChange={(event) => update("subtitle_font", event.target.value as Edit["subtitle_font"])}>{["Arial", "Georgia", "Segoe UI", "Tahoma", "Trebuchet MS", "Times New Roman"].map((font) => <option key={font}>{font}</option>)}</select></label></div>
           <div className="subtitle-style-row"><label className="field compact-field"><span>Weight</span><select value={edit.style} onChange={(event) => changeStyle(event.target.value as Edit["style"])}><option>Clean</option><option>Bold</option><option>Highlight</option></select></label><label className="field compact-field"><span>Size · px</span><input type="number" min="20" max="120" value={edit.subtitle_size} onChange={(event) => update("subtitle_size", Number(event.target.value))}/></label></div>
           <div className="subtitle-color-row"><label>Text<input type="color" aria-label="Subtitle text color" value={edit.subtitle_color} onChange={(event) => update("subtitle_color", event.target.value)}/></label><label>Outline<input type="color" aria-label="Subtitle outline color" value={edit.subtitle_outline_color} onChange={(event) => update("subtitle_outline_color", event.target.value)}/></label><label>Highlight<input type="color" aria-label="Karaoke highlight color" value={edit.subtitle_highlight_color} onChange={(event) => update("subtitle_highlight_color", event.target.value)}/></label></div>
           <div className="subtitle-style-row"><label className="field compact-field"><span>Outline width · {edit.subtitle_outline}</span><input type="range" min="0" max="8" step="0.5" value={edit.subtitle_outline} onChange={(event) => update("subtitle_outline", Number(event.target.value))}/></label><label className="field compact-field"><span>Shadow · {edit.subtitle_shadow}</span><input type="range" min="0" max="4" step="0.5" value={edit.subtitle_shadow} onChange={(event) => update("subtitle_shadow", Number(event.target.value))}/></label></div>
            <div className="subtitle-style-row"><label className="field compact-field"><span>Alignment</span><select value={edit.subtitle_alignment} onChange={(event) => update("subtitle_alignment", event.target.value as Edit["subtitle_alignment"])}><option value="top">Top</option><option value="center">Center</option><option value="bottom">Bottom</option></select></label><label className="field compact-field"><span>Animation</span><select value={edit.subtitle_animation} onChange={(event) => update("subtitle_animation", event.target.value as Edit["subtitle_animation"])}><option value="none">None</option><option value="pop">Pop</option><option value="scale">Scale</option><option value="fade">Fade</option></select></label></div>
            {edit.subtitle_caption_mode === "word_pop" && <div className="subtitle-style-row"><label className="field compact-field"><span>Animation intensity · {Math.round(edit.subtitle_animation_intensity * 100)}%</span><input type="range" min="0.05" max="0.2" step="0.01" value={edit.subtitle_animation_intensity} onChange={(event) => update("subtitle_animation_intensity", Number(event.target.value))}/></label><label className="field compact-field"><span>Animation duration · {edit.subtitle_animation_duration} ms</span><input type="range" min="50" max="250" step="10" value={edit.subtitle_animation_duration} onChange={(event) => update("subtitle_animation_duration", Number(event.target.value))}/></label></div>}
           <div className="subtitle-style-row"><label className="field compact-field"><span>Text width · {edit.subtitle_caption_width}%</span><input type="range" min="30" max="100" value={edit.subtitle_caption_width} onChange={(event) => update("subtitle_caption_width", Number(event.target.value))}/></label><label className="field compact-field"><span>Safe margin · {edit.subtitle_safe_margin}%</span><input type="range" min="0" max="20" value={edit.subtitle_safe_margin} onChange={(event) => update("subtitle_safe_margin", Number(event.target.value))}/></label></div>
           <label className="clip-checkbox subtitle-background-option"><input type="checkbox" checked={edit.subtitle_background} onChange={(event) => update("subtitle_background", event.target.checked)}/> Caption background</label>
            <div className="range-control position-control"><div><label>Vertical position</label><span>{edit.subtitle_position}%</span></div><input aria-label="Subtitle vertical position" type="range" min={edit.subtitle_caption_mode === "word_pop" ? 10 : 0} max={edit.subtitle_caption_mode === "word_pop" ? 90 : 100} value={edit.subtitle_position} onChange={(event) => update("subtitle_position", Number(event.target.value))}/><div className="range-labels"><span>Top</span><span>Bottom</span></div></div>
            <div className="subtitle-edit-list"><div className="subtitle-list-heading"><span>WORD TIMING · EDIT CUES</span><button type="button" className="button button-outline" onClick={mergeSelectedSubtitles} disabled={subtitleSelectedIds.length < 2}>Merge selected ({subtitleSelectedIds.length})</button></div>
              {visibleSegments.length ? visibleSegments.map((segment) => {
                const storedSegment = edit.subtitle_segments.find((item) => item.id === segment.id) || segment;
                return <div key={segment.id} className={`subtitle-segment-row ${subtitleSelectedIds.includes(segment.id) ? "selected" : ""}`}>
                <div className="subtitle-segment-toolbar"><label><input type="checkbox" checked={subtitleSelectedIds.includes(segment.id)} onChange={(event) => setSubtitleSelectedIds((current) => event.target.checked ? [...current, segment.id] : current.filter((id) => id !== segment.id))}/> Cue {segment.index + 1}</label><button type="button" className="icon-button" title="Seek to cue" onClick={() => seekSubtitleSegment(segment)}><Play size={12}/></button><button type="button" className="icon-button" title="Split cue" onClick={() => splitSubtitleSegment(segment.id)}><Scissors size={12}/></button><button type="button" className="icon-button" title="Duplicate cue" onClick={() => duplicateSubtitleSegment(segment.id)}><Copy size={12}/></button><button type="button" className="icon-button subtitle-delete-button" aria-label="Delete subtitle cue" onClick={() => deleteSubtitleSegment(segment.id)} disabled={running}><Trash2 size={13}/></button></div>
                <div className="subtitle-timing-fields"><label><span>Start · {edit.subtitle_timebase}</span><input type="number" min="0" max={(edit.subtitle_timebase === "source" ? data.source.duration : edit.subtitle_timebase === "output" ? timelineDuration : length) - minSubtitleDuration} step="0.01" value={Number((edit.subtitle_timebase === "output" || edit.subtitle_timebase === "source" ? segment.start : segment.start - sourceStart).toFixed(2))} onChange={(event) => updateSubtitleSegment(segment.id, "start", Number(event.target.value))}/></label><label><span>End · seconds</span><input type="number" min={minSubtitleDuration} max={edit.subtitle_timebase === "source" ? data.source.duration : edit.subtitle_timebase === "output" ? timelineDuration : length} step="0.01" value={Number((edit.subtitle_timebase === "output" || edit.subtitle_timebase === "source" ? segment.end : segment.end - sourceStart).toFixed(2))} onChange={(event) => updateSubtitleSegment(segment.id, "end", Number(event.target.value))}/></label></div>
                <textarea maxLength={500} value={segment.text} onChange={(event) => updateSubtitleSegment(segment.id, "text", event.target.value)} aria-label={`Subtitle text at ${formatDuration(segment.start)}`} disabled={running}/>
                {storedSegment.words?.length ? <div className="subtitle-word-editor">
                   <div className="subtitle-word-editor-heading"><small>{storedSegment.words.length} words · {storedSegment.word_alignment_reviewed !== true ? "needs review" : validWordAlignment(storedSegment) ? "timing valid" : "alignment invalid"}</small><button type="button" className="button button-outline" onClick={() => addManualWord(segment.id)}>Add word</button></div>
                  {storedSegment.words.map((word, index) => <div className="subtitle-word-row" key={word.id}>
                    <button type="button" className="icon-button" title="Seek to word" aria-label={`Seek to word ${word.text || index + 1}`} onClick={() => seekSubtitleWord(word)} disabled={word.start == null}><Play size={11}/></button>
                    <input aria-label={`Word ${index + 1} text`} value={word.text} maxLength={500} onChange={(event) => updateManualWord(segment.id, word.id, "text", event.target.value)}/>
                    <input type="number" aria-label={`Word ${index + 1} start time`} min="0" step="0.01" value={word.start ?? ""} onChange={(event) => updateManualWord(segment.id, word.id, "start", event.target.value)}/>
                    <input type="number" aria-label={`Word ${index + 1} end time`} min="0" step="0.01" value={word.end ?? ""} onChange={(event) => updateManualWord(segment.id, word.id, "end", event.target.value)}/>
                    <button type="button" className="icon-button" title="Split word" aria-label={`Split word ${word.text || index + 1}`} onClick={() => splitManualWord(segment.id, word.id)} disabled={!word.text.trim().includes(" ")}><Scissors size={11}/></button>
                    <button type="button" className="icon-button" title="Merge with next word" aria-label={`Merge word ${index + 1} with next`} onClick={() => mergeManualWord(segment.id, word.id)} disabled={index >= storedSegment.words!.length - 1}><Copy size={11}/></button>
                    <button type="button" className="icon-button subtitle-delete-button" aria-label={`Delete word ${word.text || index + 1}`} onClick={() => removeManualWord(segment.id, word.id)}><Trash2 size={11}/></button>
                  </div>)}
                   <div className="subtitle-word-actions"><button type="button" className="button button-outline" onClick={() => reviewManualWordTiming(segment.id)} disabled={!validWordAlignment({ ...storedSegment, word_alignment_reviewed: true })}>Mark alignment reviewed</button><small>Times use {edit.subtitle_timebase} seconds. Gaps allowed; overlaps block Word Pop.</small></div>
                </div> : <button type="button" className="button button-outline subtitle-manual-word-button" onClick={() => addManualWordTiming(segment.id)} disabled={!segment.text.trim()}>Add manual word timings</button>}
                {storedSegment.words?.length ? <small>{storedSegment.words.length} word timings · speakers {Array.from(new Set(storedSegment.words.map((word) => word.speaker_id).filter(Boolean))).join(", ") || "not identified"}</small> : null}
              </div>}) : <p className="empty-subtitles">No timed cues. Transcript-only providers never invent timestamps; copy text, add timed cues, then enter word timings manually.</p>}
           </div>
         </details>

          <details className={`panel clip-export-panel ${running || subtitleBusy || subtitleSaving ? "clip-edit-disabled" : ""}`} open><summary className="tool-heading"><span className="tool-icon purple"><Settings2 size={15}/></span><div><strong>Audio, judul & export</strong><small>Audio original default; enhancement opt-in</small></div><ChevronDown size={14}/></summary>
       <div className="clip-export-grid"><label>Resolusi<select value={edit.resolution} onChange={(event) => update("resolution", event.target.value as Edit["resolution"])}><option value="720">720 × 1280</option><option value="1080">1080 × 1920</option></select></label><label>FPS<select value={edit.fps} onChange={(event) => update("fps", Number(event.target.value) as Edit["fps"])}><option value={30}>30 FPS</option><option value={60}>60 FPS</option></select></label><label>Kualitas<select value={edit.quality} onChange={(event) => update("quality", event.target.value as Edit["quality"])}><option value="smaller">Smaller File</option><option value="balanced">Balanced</option><option value="high">High Quality</option></select></label><label>Audio volume<input type="range" min="0" max="2" step="0.05" value={edit.audio.volume} onChange={(event) => applyEdit((current) => ({ ...current, audio: { ...current.audio, volume: Number(event.target.value) } }))}/><span>{Math.round(edit.audio.volume * 100)}%</span></label><label>Fade in (s)<input type="number" min="0" max="10" step="0.1" value={edit.audio.fade_in} onChange={(event) => applyEdit((current) => ({ ...current, audio: { ...current.audio, fade_in: Number(event.target.value) } }))}/></label><label>Fade out (s)<input type="number" min="0" max="10" step="0.1" value={edit.audio.fade_out} onChange={(event) => applyEdit((current) => ({ ...current, audio: { ...current.audio, fade_out: Number(event.target.value) } }))}/></label><label className="clip-checkbox"><input type="checkbox" checked={edit.audio.muted} onChange={(event) => applyEdit((current) => ({ ...current, audio: { ...current.audio, muted: event.target.checked } }))}/>{edit.audio.muted ? <VolumeX size={14}/> : <Volume2 size={14}/>} Mute</label><label className="clip-checkbox"><input type="checkbox" checked={edit.audio.normalize} onChange={(event) => applyEdit((current) => ({ ...current, audio: { ...current.audio, normalize: event.target.checked } }))}/> Normalize audio</label><label className="clip-checkbox"><input type="checkbox" checked={edit.audio.limiter} onChange={(event) => applyEdit((current) => ({ ...current, audio: { ...current.audio, limiter: event.target.checked } }))}/> Peak limiter</label>
         <label className="clip-checkbox"><input type="checkbox" checked={edit.title_overlay.enabled} onChange={(event) => applyEdit((current) => ({ ...current, title_overlay: { ...current.title_overlay, enabled: event.target.checked } }))}/> Title overlay</label><label>Judul<input maxLength={120} value={edit.title_overlay.text} onChange={(event) => applyEdit((current) => ({ ...current, title_overlay: { ...current.title_overlay, text: event.target.value } }))}/></label><label>Font<select value={edit.title_overlay.font} onChange={(event) => applyEdit((current) => ({ ...current, title_overlay: { ...current.title_overlay, font: event.target.value as TitleOverlay["font"] } }))}><option>Arial</option><option>Georgia</option><option>Segoe UI</option><option>Tahoma</option><option>Trebuchet MS</option><option>Times New Roman</option></select></label><label>Ukuran judul<input type="number" min="20" max="120" value={edit.title_overlay.size} onChange={(event) => applyEdit((current) => ({ ...current, title_overlay: { ...current.title_overlay, size: Number(event.target.value) } }))}/></label><label>Warna judul<input type="color" value={edit.title_overlay.color} onChange={(event) => applyEdit((current) => ({ ...current, title_overlay: { ...current.title_overlay, color: event.target.value } }))}/></label><label>Posisi vertikal<input type="range" min="10" max="90" value={edit.title_overlay.position} onChange={(event) => applyEdit((current) => ({ ...current, title_overlay: { ...current.title_overlay, position: Number(event.target.value) } }))}/></label><label>Durasi judul (s)<input type="number" min="0.5" max="15" step="0.1" value={edit.title_overlay.duration} onChange={(event) => applyEdit((current) => ({ ...current, title_overlay: { ...current.title_overlay, duration: Number(event.target.value) } }))}/></label><label>Fade in judul (s)<input type="number" min="0" max="2" step="0.1" value={edit.title_overlay.fade_in} onChange={(event) => applyEdit((current) => ({ ...current, title_overlay: { ...current.title_overlay, fade_in: Number(event.target.value) } }))}/></label><label>Fade out judul (s)<input type="number" min="0" max="2" step="0.1" value={edit.title_overlay.fade_out} onChange={(event) => applyEdit((current) => ({ ...current, title_overlay: { ...current.title_overlay, fade_out: Number(event.target.value) } }))}/></label><label>Target loudness (LUFS)<input type="number" min="-24" max="-14" step="1" value={edit.audio.target_lufs} onChange={(event) => applyEdit((current) => ({ ...current, audio: { ...current.audio, target_lufs: Number(event.target.value) } }))}/></label></div>
     </details>
        </div>
      </div>
      </div>
      <section className={`panel clip-timeline-panel ${timelineCollapsed ? "timeline-collapsed" : ""} ${running || subtitleBusy || subtitleSaving ? "clip-edit-disabled" : ""}`} onPointerMove={moveTimelinePointer} onPointerUp={endTimelinePointer} onPointerCancel={endTimelinePointer}>
       <div className="clip-timeline-heading"><div><strong>Timeline output</strong><span>{compositionScenes.length} scene · {formatDuration(timelineDuration)} total · source time terpisah dari output time</span></div><div className="clip-history-actions"><button type="button" className="button button-outline" aria-expanded={!timelineCollapsed} aria-label={timelineCollapsed ? "Expand timeline" : "Collapse timeline"} onClick={() => setTimelineCollapsed((value) => !value)}><ChevronDown size={13}/>{timelineCollapsed ? "Expand Timeline" : "Collapse Timeline"}</button><button type="button" className="button button-outline" onClick={undo} disabled={!canUndo || running} title="Undo · Ctrl+Z"><Undo2 size={13}/> Undo</button><button type="button" className="button button-outline" onClick={redo} disabled={!canRedo || running} title="Redo · Ctrl+Y"><Redo2 size={13}/> Redo</button><label>Zoom <input aria-label="Zoom timeline" type="range" min="12" max="80" value={sceneZoom} onChange={(event) => setSceneZoom(Number(event.target.value))}/></label><span className="clip-autosave-state">{editorStatus.draft === "saving" ? "Menyimpan draft…" : editorStatus.draft === "failed" ? "Save gagal" : editorStatus.draft === "unsaved" ? "Autosave tertunda" : "Draft tersimpan"}</span></div></div>
       <div className="clip-timeline-shortcuts"><span><kbd>I</kbd> Tandai Awal</span><span><kbd>O</kbd> Tandai Akhir</span><span><kbd>S</kbd> Split</span><span><kbd>Delete</kbd> Hapus Bagian</span><span><kbd>Ctrl+Z</kbd> Undo</span></div>
       <div className="clip-timeline-scroll"><div className="clip-timeline-track" ref={timelineTrackRef} style={{ width: `${timelineWidth}px` }}>
         <div className="clip-timeline-ruler" tabIndex={0} aria-label="Penggaris timeline output; drag untuk memilih Cut Range" style={{ width: `${timelineWidth}px` }} onPointerDown={beginRangeSelection}>
           {[0, 0.25, 0.5, 0.75, 1].map((fraction) => <span key={fraction} style={{ left: `${timelineWidth * fraction}px` }}>{formatDuration(timelineDuration * fraction)}</span>)}
           {cutRange && <i className="clip-cut-selection" style={{ left: `${cutRange.start * timelineScale}px`, width: `${Math.max(2, (cutRange.end - cutRange.start) * timelineScale)}px` }}/>}<i className="clip-playhead" style={{ left: `${compositionTime * timelineScale}px` }}/>
         </div>
          <div className="clip-scene-lane">
           {timelineScenes.map((scene, index) => <div key={scene.id} className={`clip-scene-block ${scene.id === selectedSceneId ? "selected" : ""} ${dragSceneId === scene.id ? "dragging" : ""}`} draggable={!running} style={{ left: `${(scene.timeline_start || 0) * timelineScale}px`, width: `${Math.max(2, (scene.duration || 0) * timelineScale)}px` }} onDragStart={() => setDragSceneId(scene.id)} onDragOver={(event) => event.preventDefault()} onDrop={() => handleSceneDrop(scene.id)} onDragEnd={() => setDragSceneId("")}>
             <button type="button" className="clip-scene-select" onClick={() => { setSelectedSceneId(scene.id); seekOutput(scene.timeline_start || 0); }} aria-label={`Pilih scene ${index + 1}`}><GripVertical size={12}/><strong>{index + 1}</strong><span>{formatDuration(scene.duration || 0)}</span></button>
             <small>{formatDuration(scene.source_start)}–{formatDuration(scene.source_end)} sumber</small>
             <button type="button" className="clip-scene-edge left" aria-label="Trim awal scene" onPointerDown={(event) => beginSceneResize(event, scene.id, "start")}/><button type="button" className="clip-scene-edge right" aria-label="Trim akhir scene" onPointerDown={(event) => beginSceneResize(event, scene.id, "end")}/>
           </div>)}
            {cutRange && <i className="clip-cut-selection clip-cut-lane" style={{ left: `${cutRange.start * timelineScale}px`, width: `${Math.max(2, (cutRange.end - cutRange.start) * timelineScale)}px` }}/>}<i className="clip-playhead clip-playhead-lane" style={{ left: `${compositionTime * timelineScale}px`}} onPointerDown={() => {}}/>
          </div>
          <div className="clip-subtitle-lane" aria-label="Subtitle cue timeline">
            <span className="clip-lane-label">SUBTITLES</span>
            {timelineSubtitleSegments.map((segment) => {
              const start = subtitleDragPreview?.id === segment.id ? subtitleDragPreview.start : segment.outputStart;
              const end = subtitleDragPreview?.id === segment.id ? subtitleDragPreview.end : segment.outputEnd;
              const canDrag = edit.subtitle_timebase === "output";
              return <button key={segment.id} type="button" className={`clip-subtitle-block ${segment.words?.length ? "word-timed" : ""} ${subtitleSelectedIds.includes(segment.id) ? "selected" : ""}`} style={{ left: `${start * timelineScale}px`, width: `${Math.max(5, (end - start) * timelineScale)}px` }} title={`${formatDuration(start)}–${formatDuration(end)} · ${segment.text}`} onPointerDown={canDrag ? (event) => beginSubtitleGesture(event, segment.id, "move") : undefined} onClick={() => seekOutput(segment.outputStart)}>
                <span>{segment.text}</span>{canDrag && <><i className="clip-subtitle-edge left" onPointerDown={(event) => beginSubtitleGesture(event, segment.id, "start")}/><i className="clip-subtitle-edge right" onPointerDown={(event) => beginSubtitleGesture(event, segment.id, "end")}/></>}
              </button>;
            })}
          </div>
        </div></div>
       <div className="clip-cut-controls"><div className="clip-cut-fields"><label>In · output detik<input type="number" min="0" max={timelineDuration} step="0.01" value={cutRange?.start ?? ""} placeholder="Tandai Awal" onChange={(event) => setCutRange({ start: Math.max(0, Math.min(timelineDuration, Number(event.target.value))), end: cutRange?.end ?? timelineDuration })}/></label><button type="button" className="button button-outline" onClick={markIn} disabled={running}>Tandai Awal</button><label>Out · output detik<input type="number" min="0" max={timelineDuration} step="0.01" value={cutRange?.end ?? ""} placeholder="Tandai Akhir" onChange={(event) => setCutRange({ start: cutRange?.start ?? 0, end: Math.max(0, Math.min(timelineDuration, Number(event.target.value))) })}/></label><button type="button" className="button button-outline" onClick={markOut} disabled={running}>Tandai Akhir</button><button type="button" className="button button-outline" onClick={splitAtPlayhead} disabled={running}><Scissors size={13}/> Split</button><button type="button" className="button button-danger" onClick={deleteSelectedRange} disabled={running || !validCutRange}><Trash2 size={13}/> Hapus Bagian</button></div><small>Drag di penggaris untuk memilih rentang. Ripple delete hanya mengubah komposisi; file sumber tetap utuh.</small></div>
       <div className="clip-scene-properties"><div className="clip-mode-switch"><span>Mode</span><button type="button" className={edit.scene_mode === "single" ? "active" : ""} onClick={() => switchSceneMode("single")}>Single Scene</button><button type="button" className={edit.scene_mode === "multi" ? "active" : ""} onClick={() => switchSceneMode("multi")}>Multi-Scene</button></div>
          {selectedScene && <><label>Scene terpilih<select value={selectedScene.role} onChange={(event) => setSceneRole(selectedScene.id, event.target.value as Scene["role"])}><option value="hook">Hook</option><option value="body">Isi</option><option value="ending">Ending</option></select></label><label>In sumber (detik)<input type="number" min={edit.scene_mode === "single" ? sourceStart : 0} max={data.source.duration} step="0.01" value={selectedScene.source_start} onChange={(event) => updateSelectedSceneRange(Number(event.target.value), selectedScene.source_end)}/></label><label>Out sumber (detik)<input type="number" min={0} max={edit.scene_mode === "single" ? data.clip.end : data.source.duration} step="0.01" value={selectedScene.source_end} onChange={(event) => updateSelectedSceneRange(selectedScene.source_start, Number(event.target.value))}/></label><button type="button" className="button button-outline" onClick={duplicateSelectedScene} disabled={running || compositionScenes.length >= 12}><Copy size={13}/> Duplikasi</button><button type="button" className="button button-outline" onClick={deleteSelectedScene} disabled={running || compositionScenes.length <= 1}><Trash2 size={13}/> Hapus Scene</button>{selectedScene.role === "hook" && selectedScene.order !== 0 && <button type="button" className="button button-outline" onClick={() => { const moved = reorderScene(compositionScenes, selectedScene.id, compositionScenes[0].id) as Scene[]; commitEdit(toSourceTimedEdit(edit, moved)); }}>Pindahkan Hook ke awal</button>}{selectedScene.role === "ending" && (selectedScene.duration || 0) < 1.5 && <small className="clip-ending-hint">Ending pendek; periksa apakah pesan terpotong.</small>}</>}
       </div>
       <div className="clip-add-scene"><strong>Tambah rentang sumber</strong><label>In<input type="number" min="0" max={data.source.duration} step="0.01" value={newSceneRange.start} onChange={(event) => setNewSceneRange((value) => ({ ...value, start: Number(event.target.value) }))}/></label><label>Out<input type="number" min="0" max={data.source.duration} step="0.01" value={newSceneRange.end} onChange={(event) => setNewSceneRange((value) => ({ ...value, end: Number(event.target.value) }))}/></label><button type="button" className="button button-outline" onClick={addScene} disabled={running || compositionScenes.length >= 12}><Plus size={13}/> Tambah Scene</button></div>
     </section>

      {publishOpen && <div className="modal-backdrop" onClick={(event) => { if (event.target === event.currentTarget && !publishBusy) setPublishOpen(false); }}><section className="confirm-modal publishing-modal clip-publish-modal" role="dialog" aria-modal="true" aria-labelledby="youtube-publish-title" aria-describedby="youtube-publish-description">
        <div className="clip-publish-heading"><div><span className="eyebrow">YOUTUBE · FINAL CLIP</span><h2 id="youtube-publish-title">Posting ke YouTube</h2></div><button type="button" className="modal-close icon-button" aria-label="Tutup" onClick={() => { if (!publishBusy) setPublishOpen(false); }} disabled={publishBusy}><X size={15}/></button></div>
        <p id="youtube-publish-description" className="clip-publish-intro">Caption manual. Video final disimpan lokal sampai upload dimulai.</p>
        {publishAccounts.length ? <>
          <div className="clip-publish-preview"><video className="publishing-preview" src={`${API}/api/clips/${data.clip.id}/file`} controls playsInline preload="metadata"/></div>
          {publishStep === "details" ? <div className="publishing-form clip-publish-form">
            <label className="field"><span>Channel · wajib</span><select value={publishForm.account_id} onChange={(event) => changePublish("account_id", event.target.value)}>{publishAccounts.map((account) => <option key={account.id} value={account.id}>{account.channel_title}</option>)}</select></label>
            <label className="field"><span>Judul · wajib</span><input maxLength={100} value={publishForm.title} onChange={(event) => changePublish("title", event.target.value)}/></label>
            <label className="field clip-publish-wide"><span>Deskripsi</span><textarea maxLength={5000} value={publishForm.description} onChange={(event) => changePublish("description", event.target.value)}/></label>
            <label className="field"><span>Tags · pisahkan koma</span><input value={publishForm.tags} onChange={(event) => changePublish("tags", event.target.value)} placeholder="tag satu, tag dua"/></label>
            <label className="field"><span>Privacy</span><select value={publishForm.privacy_status} onChange={(event) => changePublish("privacy_status", event.target.value as PublishForm["privacy_status"])}><option value="private">Private</option><option value="unlisted">Unlisted</option><option value="public">Public</option></select></label>
            <fieldset><legend>Apakah konten dibuat untuk anak-anak? <span>Wajib</span></legend><label><input type="radio" name="made-for-kids" checked={publishForm.made_for_kids === "yes"} onChange={() => changePublish("made_for_kids", "yes")}/> Ya</label><label><input type="radio" name="made-for-kids" checked={publishForm.made_for_kids === "no"} onChange={() => changePublish("made_for_kids", "no")}/> Tidak</label></fieldset>
            <fieldset><legend>Apakah ada konten sintetis realistis? <span>Wajib</span></legend><label><input type="radio" name="synthetic" checked={publishForm.contains_synthetic_media === "yes"} onChange={() => changePublish("contains_synthetic_media", "yes")}/> Ya, ungkapkan</label><label><input type="radio" name="synthetic" checked={publishForm.contains_synthetic_media === "no"} onChange={() => changePublish("contains_synthetic_media", "no")}/> Tidak</label></fieldset>
            {publishError && <p className="publishing-error" role="alert">{publishError}</p>}
            <div className="publishing-form-actions"><button type="button" className="button button-outline" onClick={() => setPublishOpen(false)}>Batal</button><button type="button" className="button button-primary" onClick={() => { if (!publishForm.title.trim() || !publishForm.account_id || !publishForm.made_for_kids || !publishForm.contains_synthetic_media) { setPublishError("Isi judul dan pilih channel, Made for Kids, serta pengungkapan konten sintetis."); return; } setPublishError(""); setPublishStep("confirm"); }}>Lanjut konfirmasi <ArrowRight size={14}/></button></div>
          </div> : <div className="publishing-form clip-publish-form">
            <div className="clip-publish-review"><span className="clip-publish-review-heading">Periksa sebelum upload</span><dl>
              <div><dt>Channel</dt><dd>{publishAccounts.find((account) => account.id === publishForm.account_id)?.channel_title}</dd></div>
              <div><dt>Judul</dt><dd>{publishForm.title}</dd></div>
              <div><dt>Privacy</dt><dd>{publishForm.privacy_status}</dd></div>
              <div><dt>Made for Kids</dt><dd>{publishForm.made_for_kids === "yes" ? "Ya" : "Tidak"}</dd></div>
              <div><dt>Konten sintetis realistis</dt><dd>{publishForm.contains_synthetic_media === "yes" ? "Ya" : "Tidak"}</dd></div>
              <div><dt>Tags</dt><dd>{publishForm.tags || "—"}</dd></div>
            </dl></div>
            {publishError && <p className="publishing-error" role="alert">{publishError}</p>}
            <div className="publishing-form-actions"><button type="button" className="button button-outline" onClick={() => setPublishStep("details")} disabled={publishBusy}>Kembali</button><button type="button" className="button button-youtube" onClick={() => void confirmPublish()} disabled={publishBusy}>{publishBusy ? <LoaderCircle size={14} className="spin"/> : <Youtube size={14}/>} Konfirmasi & Posting Sekarang</button></div>
          </div>}
        </> : <div className="publishing-no-account">Belum ada channel Connected. Hubungkan channel dahulu di <Link href="/accounts">Connected Accounts</Link>; upload tidak dimulai.</div>}
      </section></div>}
  </>;
}

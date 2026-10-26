# Product Roadmap

Roadmap captures latest product direction, not a claim that planned code already exists. Source tree and tests remain implementation authority.

## Product direction

- Keep Klipnara personal, single-user, local-first, Windows-first.
- No cloud hosting or mobile app for now.
- **Quick Clip from user-supplied timestamps is the primary workflow.**
- Whisper/Ollama remain available for AI Smart Clip but are not required by Quick Clip.
- Keep Cloud AI limited to selected features and require explicit user consent per operation.
- Keep FFmpeg as video processing engine.
- Preserve and maintain existing YouTube V1.1 publishing flow.

## V2.1 Studio phase status

| Phase | State | Scope/status |
|---|---|---|
| Multi-mode Create Video | **Implemented** | Quick Clip and AI Smart Clip retain existing workflows; AI Mood Quotes opens a dedicated workspace; YouTube Clip URL import is accurately disabled as Segera Hadir. |
| Mood categories and quote generation | **Implemented; live provider not verified in this checkout** | Eight data-driven groups, 61 subcategories, nine writing styles, POV/length/language selection, Gemini default/OpenAI alternative, per-request consent, strict five-quote validation, favorites, history and regenerate preservation. |
| Drafts and editor | **Implemented; runtime recheck pending** | Existing additive tables retained; mode/segments live in `composition_json` without migration. New drafts default to Sequential Text; old drafts stay Single Text. Autosaved editor adds local segment timing/animation, responsive preview, visual/audio controls, and no-AI edits/render. |
| Media composition and FFmpeg | **Implemented; expanded synthetic E2E pending** | Image/video/solid/gradient, segmented ASS text, music trim/resampling/mix/fades/loop, selected-audio signal and MP4 stream/duration/resolution checks, 720p H.264/AAC default and optional 1080p, progress/cancel/retry, review SHA-256/download. Existing 24 Oct results cover earlier cases; new scenarios were not run in this checkout and synthetic media cannot certify arbitrary user footage. |
| Library/review/publishing | **Implemented except Mood YouTube adapter** | Drafts and Mood outputs appear in Clip Library; review fingerprint/download supported. Mood projects are not coerced into `clips` and do not expose a Publish button. Existing Quick/AI Smart Clip YouTube workflow remains unchanged. |

## V2.3 Mood Quotes cinematic phase

| Phase | State | Scope/status |
|---|---|---|
| Smart Visual Presets | **Implemented in source; validation pending** | Ten typed/versioned data-driven styles, mood recommendations, visual-only application, one-step undo/reset, and no automatic asset/music selection. |
| Motion/color/atmosphere | **Implemented in source; FFmpeg/browser validation pending** | Existing Mood renderer adds bounded zoom/pan/Ken Burns, colorbalance/eq, vignette, grain, dark/gradient overlays; browser previews simulate effects from shared draft settings. No glow or new rendering pipeline. |
| Indonesian semantic segmentation | **Implemented in source; tests not run** | Deterministic clause merge/split rules avoid hanging openers/connectors; manual segments require explicit confirmed re-segmentation. Old Single Text drafts remain supported. |
| V2.3 QA | **Pending user runtime check** | Regression and synthetic-render test code added/updated but not executed. Compare Live Preview, Preview Penuh, and MP4; no build/server/browser/FFmpeg run was performed for this update. |

## V2.4 Mood Quotes visual timeline phase

| Phase | State | Scope/status |
|---|---|---|
| Composition timeline | **Implemented in source; validation pending** | Collapsible text/background/music lanes, shared playhead, zoom/snap, drag/resize, music offset/mute, segment split/merge/duplicate/reorder/reset. Selection/zoom/snap stay UI-only; edits use existing composition JSON. |
| Audio timing and draft safety | **Implemented in source; validation pending** | Backward-compatible offset/mute defaults, asset/span validation, delayed/faded FFmpeg music, preview sync, serialized autosave, immutable render snapshot. No SQLite migration. |
| Regression and manual QA | **Pending** | Frontend helper tests, backend assertions, synthetic offset/mute render cases, and manual checklist added; none run. No typecheck/build/browser/FFmpeg runtime validation performed. |

## V2.0 phase status

| Phase | State | Scope/status |
|---|---|---|
| Fase 0 — Audit & Compatibility | **Implemented** | Existing SQLite tables/jobs/render/review/YouTube flow audited. Quick Clip reuses current `jobs`/`clips` schema; no Quick Clip migration or source-file rewrite. Backup/rollback guidance documented. |
| Fase 1 — Lightweight Quick Clip | **Implemented and tested** | Create page defaults to Quick Clip; timestamp form, playhead capture, source Library, direct FFmpeg render, audio-optional input, shared editor/review/approval, and source-origin label. Mocked AI-isolation tests plus real-media and synthetic-silent E2E pass; details in Testing docs. |
| Fase 2 — Lightweight Rendering | **Planned** | Further render latency/CPU optimization. Existing FFmpeg render remains; no stream-copy/Fast Cut optimization is claimed yet. |
| Fase 3 — Simple Editor | **Planned** | Continue editor work for Quick Clip-specific usability. Existing V1 editor (trim/crop/subtitle controls for transcript-backed clips) remains implemented and shared. |
| Fase 4 — Optional Cloud AI | **Planned expansion** | Existing opt-in OpenAI/Gemini highlight analysis remains. Cloud Transcription is not implemented; any future cloud feature must require explicit user consent. |

## Status by feature

| Area | Current source status | Direction |
|---|---|---|
| AI Mood Quotes | **V2.4 source implementation; runtime/tests pending** for consented generation, deterministic segmentation, cinematic presets/effects, visual timeline, audio offset/mute, local FFmpeg composition. No V2.4 test/build/live AI/browser/FFmpeg run was performed. | Follow V2.4 manual QA; measure effects on target hardware and validate timeline/audio preview-render parity before calling verified. |
| Quick Clip by timestamp | **Implemented.** Current Create default; accepts `MM:SS`/`HH:MM:SS`, creates clip/job without transcript/candidate/AI, renders selected interval, supports sources without audio. | Keep primary, lightweight path; Fase 2 may optimize FFmpeg latency later. |
| Whisper transcription | **Implemented; used for fresh sources/cache misses** in AI Smart Clip. Local whisper.cpp, `small` recommended, `base` fallback, language auto/Indonesian/English. | Optional for the product's primary Quick Clip flow; retain for AI Smart Clip. |
| Ollama highlight analysis | **Implemented, default** local provider for AI Smart Clip; OpenAI/Gemini can replace it with explicit consent. | Optional for the product's primary Quick Clip flow. |
| Cloud highlight analysis | **Implemented, optional** OpenAI/Gemini provider with per-job transcript-sharing consent. | Continue feature-specific, opt-in cloud use; no fallback without consent. |
| Cloud transcription | **Planned, not implemented.** No cloud speech-to-text route/provider exists. | Evaluate only for specific user-requested feature, with explicit consent/data disclosure. |
| FFmpeg | **Implemented** for probe/extract/crop/subtitle/render and remains required media engine. | Keep as engine; no replacement planned. |
| YouTube Publishing V1.1 | **Implemented with mocked HTTP tests.** OAuth, approval gate, resumable upload, processing confirmation, history. No real OAuth/upload validation yet. | Preserve; run real Private upload validation after user config. Scheduler may be evaluated only after direct upload proves stable. |
| Mobile / hosted SaaS | **Not implemented.** | No near-term work planned. |

## Suggested next sequence

1. Run V2.4 Mood Quotes manual QA on target hardware; test timeline interactions and offset/mute audio, compare Live Preview, Preview Penuh, and MP4, then execute automated tests only with user authorization. Validate live Gemini/OpenAI separately with explicit consent and quota checks.
2. Decide whether to add a source-less YouTube publishing adapter for Mood render records without changing existing clip approval/upload invariants.
3. Keep YouTube Clip URL import disabled until a rights-aware and secure supported ingest approach is scoped; do not add an arbitrary downloader.
4. Configure a real personal YouTube OAuth client, complete one Private upload, and verify channel/video ID/privacy/processing in YouTube Studio for existing clip outputs.
5. Keep Cloud Transcription, scheduler, mobile, hosted SaaS, and other social platforms planned only until separately scoped.

No estimates or release dates are assigned. Quick Clip V2.0 Fase 1 and Mood Quotes V2.1 creation/render/review/download phases are implemented. Mood Quotes YouTube publishing, YouTube Clip URL import, Cloud Transcription, and other listed expansions remain not implemented.

Current technical structure: [Architecture](architecture.md). Current implemented workflows: [Features and Workflows](features-and-workflows.md).

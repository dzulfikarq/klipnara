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
| Quick Clip by timestamp | **Implemented.** Current Create default; accepts `MM:SS`/`HH:MM:SS`, creates clip/job without transcript/candidate/AI, renders selected interval, supports sources without audio. | Keep primary, lightweight path; Fase 2 may optimize FFmpeg latency later. |
| Whisper transcription | **Implemented; used for fresh sources/cache misses** in AI Smart Clip. Local whisper.cpp, `small` recommended, `base` fallback, language auto/Indonesian/English. | Optional for the product's primary Quick Clip flow; retain for AI Smart Clip. |
| Ollama highlight analysis | **Implemented, default** local provider for AI Smart Clip; OpenAI/Gemini can replace it with explicit consent. | Optional for the product's primary Quick Clip flow. |
| Cloud highlight analysis | **Implemented, optional** OpenAI/Gemini provider with per-job transcript-sharing consent. | Continue feature-specific, opt-in cloud use; no fallback without consent. |
| Cloud transcription | **Planned, not implemented.** No cloud speech-to-text route/provider exists. | Evaluate only for specific user-requested feature, with explicit consent/data disclosure. |
| FFmpeg | **Implemented** for probe/extract/crop/subtitle/render and remains required media engine. | Keep as engine; no replacement planned. |
| YouTube Publishing V1.1 | **Implemented with mocked HTTP tests.** OAuth, approval gate, resumable upload, processing confirmation, history. No real OAuth/upload validation yet. | Preserve; run real Private upload validation after user config. Scheduler may be evaluated only after direct upload proves stable. |
| Mobile / hosted SaaS | **Not implemented.** | No near-term work planned. |

## Suggested next sequence

1. Optimize selected-interval FFmpeg processing while retaining current output safety and measuring on target i3/RX 570 hardware.
2. Continue Fase 3 editor usability for Quick Clip without creating a second editor.
3. Keep Whisper/Ollama optional outside AI Smart Clip; do not add Cloud Transcription until specifically scoped and consented.
4. Configure a real personal YouTube OAuth client, complete one Private upload and verify channel/video ID/privacy/processing in YouTube Studio before extending publishing scope.
5. Consider scheduler or more channels only after direct upload is live-verified and requested.

No estimates or release dates are assigned. Quick Clip Fase 1 is implemented; Fase 2/3/4 expansions and Cloud Transcription remain planned, not implemented.

Current technical structure: [Architecture](architecture.md). Current implemented workflows: [Features and Workflows](features-and-workflows.md).

# Klipnara

**V3.2.1 multi-account publishing:** connect multiple accounts per provider, choose defaults, keep destination metadata separate, and queue/recover each destination independently. Google OAuth grants exposing multiple YouTube channels still fail closed; connect separate Google accounts with `prompt=select_account`.

**Klipnara Studio is a local-first Windows video creator.** Create timestamp-based Quick Clips with single- or multi-scene editing, optional AI Smart Clips, YouTube-preview-based Quick Clips with an optional explicitly enabled local segment adapter or a local-file fallback, or AI Mood Quotes videos with original text, reused local backgrounds/music, and animated typography. Asset Library manages local video/image/music and offers user-selected official Pexels footage search/import. V2.8 adds reviewed subtitle/translation tracks, composition transcription, SRT/VTT import/export, and expanded caption controls. V2.12 adds Word Pop: one timed word at a time, manual alignment, live preview, and per-word ASS rendering. V2.9 adds Batch Creator for up to 10 outputs. V2.11 adds YouTube Publishing Studio for approved Clip and Mood outputs: metadata drafts/templates, native YouTube scheduling, upload history/calendar, and custom thumbnails through existing OAuth/resumable uploader. V3.1 adds official YouTube Analytics with separate channel/Klipnara scopes, comparisons, retention, CSV export, rule-based insights, and immutable production attribution. V3.2 adds conditional TikTok Inbox transfer and Facebook Login for Business Instagram Reels resumable publishing, independent status/recovery, and always-available manual export. V3.2.1 adds multiple connected destinations, per-account metadata/defaults, and independent jobs per selected account.

Klipnara keeps media, SQLite state, Whisper/Ollama processing, and YouTube OAuth tokens on the local Windows user profile. Cloud AI requires per-request consent. Highlight analysis, Mood Quotes, and translation send text; optional cloud subtitle transcription uploads composition audio only after separate explicit confirmation. Local Whisper keeps audio on-device.

## Quick start

Requirements: Windows 10/11, Python 3.10+, Node.js 20.9+, FFmpeg/ffprobe. Whisper/model and Ollama/model are optional AI Smart Clip runtimes. Mood Quotes generation needs a configured Gemini or OpenAI backend key and explicit consent per request; rendering itself needs no AI runtime. YouTube OAuth is optional for approved Clip or Mood render outputs.

1. Follow [Getting Started](docs/getting-started.md). FFmpeg/ffprobe required; Whisper/Ollama setup is optional for AI Smart Clip. Configure `GEMINI_API_KEY` or `OPENAI_API_KEY` for Mood Quotes generation.
2. Prepare backend environment from repository root:

   ```powershell
   Set-Location backend
   python -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
   if (-not (Test-Path .env)) { Copy-Item .env.example .env }
   # Edit local binary/model paths as needed; do not put real secrets in source control.
   Set-Location ..
   ```

3. Install root runner and frontend dependencies:

   ```powershell
   npm install
   npm --prefix frontend install
   ```

4. From repository root, start both services with one command:

   ```powershell
   npm run dev
   ```

   Concurrent output labels distinguish `BACKEND` and `FRONTEND`; `Ctrl+C` stops both. Separate commands: `npm run dev:frontend` and `npm run dev:backend`. Preflight reports missing `.venv`, backend packages, `.env`, frontend dependencies or root `concurrently` with setup commands.

5. Open `http://localhost:3000`. Backend API docs and health: `http://127.0.0.1:8000/api/docs` and `/api/health`.

## Implemented

- MP4/MOV upload and direct public HTTPS media-file import with ffprobe validation and DNS/IP protections.
- Quick Clip from user-selected timestamps, including sources without audio; no Whisper, Ollama, or cloud calls.
- YouTube Clip: strict URL/ID validation, official IFrame preview, optional official Data API metadata, and timestamp selection. Optional local `yt-dlp` section adapter is disabled by default, not official YouTube tooling, and usable only for content whose acquisition and use are permitted; otherwise Source Library/upload remains available. Successful imports become managed sources and enter existing Quick Clip/render/editor flow.
- Optional AI Smart Clip with local whisper.cpp/Ollama or OpenAI/Gemini highlight analysis using explicit consent.
- AI Mood Quotes: 8 configurable mood groups, 5 schema-validated alternatives per cloud request, favorites/history, resumable local drafts, legacy Single Text and Sequential Text, semantic local segmentation, and editable timed segments.
- Mood Quotes V2.4 source: collapsible text/background/music timeline, draggable text timing and music offset, segment properties/split/merge/duplicate/reorder, playhead/snap/zoom, and timeline-synced browser audio. Timeline edits share `composition_json`; no parallel timeline state or SQLite migration.
- Mood Quotes: 10 Smart Cinematic Presets, deterministic mood recommendations, adaptive typography, slow zoom/pan/Ken Burns, color grading, vignette, grain, and gradient/dark overlays. Presets preserve quote, manual timing, selected media background, and music; solid/gradient palettes follow preset.
- Mood Quotes Live/Full Preview and existing FFmpeg renderer consume one composition snapshot, including music offset/mute/trim/fades. Render jobs retain cancel/retry/progress, audio signal checks, 9:16 H.264/AAC MP4, review fingerprint, Clip Library listing, and download.
- Token-bounded transcript chunking, SQLite chunk checkpoints, candidate validation/deduplication and global ranking.
- Portrait FFmpeg H.264/AAC render, trim, center/manual crop and editable ASS subtitles.
- V2.6 Clip Editor source implementation: ordered scenes, browser preview, source/output time mapping, timeline trim/reorder/split, Cut Range ripple delete, bounded Undo/Redo, and full-edit autosave. Audio/title/export controls reuse existing `clips.edit_json`, render queue and approval gate.
- V2.10 Clip Editor workspace source implementation: Quick Clip, YouTube Clip output and AI Smart Clip share editing controls beside a sticky portrait preview on desktop; preview mute/fullscreen/collapse, timeline collapse, and explicit save/render freshness status reuse existing editor state. Browser preview stays separate from FFmpeg final render. Manual QA pending.
- V2.8 subtitle workflow: queued full-composition local Whisper, consent-gated Gemini word timing/speaker labels (30-minute cap), or consent-gated OpenAI text-only transcription; each result stays a separate review draft. Edit cues, map to output time, drag/resize output-time cues, translate text to separate language tracks, import/export SRT/VTT, and style ASS captions. Generated tracks never replace active captions automatically; selected stale output-time tracks are blocked from render.
- V2.12 Word Pop subtitle type: reviewed Gemini word timing or manually entered word text/timing; punctuation and silence gaps retained, edited alignment must be reviewed again. Preview and FFmpeg emit one current word; Pop, Scale, Fade, and None animations, long-word fitting, scene-cut mapping, and strict render gating. Segment-only/text-only providers never receive invented word times. Presets change appearance only.
- V2.7 Asset Library: shared metadata, canonical source-backed video files, local image/music storage, favorites, license notes, storage usage, and Mood Quotes reuse without per-project copies. Official Pexels video search, preview, user-selected MP4 import, retry/cancel, and creator/license citations; API key stays backend-only.
- V2.9 Batch Creator: build up to 10 timestamp clips or saved/manual Mood Quotes items, edit each in existing editors, and render one-at-a-time through the existing FIFO worker. Pause/resume/cancel/retry, SQLite recovery, per-output review/download; quote generation and media analysis never run automatically.
- Separate clip review/render states with approval bound to final MP4 SHA-256.
- YouTube Publishing Studio: connected-channel verification, approved Clip/Mood render upload via same resumable uploader, metadata drafts/templates, per-output explicit confirmation, timezone-aware native scheduling, queue/history/calendar, and managed custom thumbnails. V3.1 Analytics uses official YouTube Analytics reports, records actual granted scopes, separates channel-wide totals from Klipnara-published video totals, and keeps Views distinct from Engaged Views. Connected Accounts adds channel-bound incremental Analytics consent; credentials stay backend-only.
- Social publishing V3.2: conditional TikTok Inbox transfer (`user.info.basic` + `video.upload`; no `video.publish`/Direct Post) and Instagram Professional Reels publishing through Facebook Login for Business local resumable upload. Jobs, failures, retries, provider reconciliation, rights confirmation, and manual export stay independent. TikTok Inbox needs creator action; only provider-confirmed completion is Published. App review, eligibility, and live API access are not inferred.
- Multi-account publishing V3.2.1: connect multiple YouTube, TikTok, and Instagram destinations; set provider defaults; save per-account metadata; enqueue independent jobs; preserve history and shared grants on disconnect. Google grants exposing multiple YouTube channels still fail closed.

**Limits:** V2.6–V3.2 source changes and regression assertions are not runtime-validated in this checkout; no tests, typecheck/build, server, browser, provider, FFmpeg, OAuth, or live YouTube API action ran. Analytics requires YouTube Data API v3 and YouTube Analytics API enabled in Google Cloud plus actual `youtube.readonly` and `yt-analytics.readonly` grants; it requests no monetary scope. Channel scope is channel-wide; Klipnara scope is limited to published video IDs tied to local publication records and new publications only receive immutable production snapshots. Reports may lag, retention may be unavailable, cache lasts six hours, and rule-based comparisons require minimum samples. See Analytics manual QA and API notes before claiming verified. V2.8–V2.12 checks remain unrun. V2.10 uses stacked, non-sticky preview below 1080px; dark theme is not implemented. Cloud STT/translation costs and accuracy depend on provider; audio uploads require confirmation; OpenAI transcription supplies no timestamps; Gemini word timing is capped at 30 minutes; local Whisper stays segment-timed. Word Pop requires reviewed word times and rejects ASS intervals below 10 ms precision; manual Preview-vs-MP4 QA remains pending. Pexels checks are mocked only; no live request. Pexels imports cap at 512 MiB and one import runs at a time; legacy Mood project assets must be linked to shared Asset Library before batching. Users must review licenses and rights. Multi-Scene uses one source, hard cuts, max 12 scenes, 0.5-second minimum per interval, 180 seconds total; browser seeking can lag. YouTube segment import requires optional external `yt-dlp`, FFmpeg/ffprobe, explicit backend opt-in, and user rights/permission; platform terms may still prohibit retrieval. No video is guaranteed importable. Mobile app, hosting, and multi-user SaaS remain unimplemented. Social API publishing is conditional; manual export remains available. Mood Quotes keeps separate project/render tables and review fingerprint. See [Design](docs/design.md) and [Roadmap](docs/roadmap.md).

`YOUTUBE_DATA_API_KEY` is optional and backend-only for YouTube Clip metadata; IFrame preview needs no key. Publishing tests mock Google HTTP requests. No live OAuth, upload, schedule, or thumbnail has been verified; no real video ID has been verified. Start OAuth setup from **Akun → Lihat Panduan Setup**; documentation: [Getting Started](docs/getting-started.md), [YouTube Shorts Publishing](docs/youtube-shorts-publishing.md), and [Design](docs/design.md).

V3.2.1 mocked coverage and manual account-switch/destination/disconnect checks remain unrun. Google grants exposing multiple YouTube channels still fail closed; connect separate Google accounts with `prompt=select_account`.

## Documentation index

| Document | Contents |
|---|---|
| [Architecture](docs/architecture.md) | Components, data boundaries, worker design, key trade-offs |
| [Design](docs/design.md) | Shared clip-editor workspace, OAuth setup guide, responsive layout, controls and status conventions |
| [Getting Started](docs/getting-started.md) | Windows prerequisites, installs, run commands, environment variables |
| [Features and Workflows](docs/features-and-workflows.md) | Ingest, AI generation, edit/review/render and publishing lifecycles |
| [AI Pipeline](docs/ai-pipeline.md) | Whisper, Ollama/cloud adapters, chunking, cache, benchmarks and limits |
| [Video Processing](docs/video-processing.md) | Import safeguards, storage, FFmpeg render, encoder benchmarks |
| [API and Database](docs/api-and-database.md) | Endpoints, request contracts, schema, statuses and worker queue |
| [Git Workflow & Commit Standards](docs/GIT_WORKFLOW.md) | Mandatory review, staging, Conventional Commits, authorization, and push rules |
| [Testing and Troubleshooting](docs/testing-and-troubleshooting.md) | Automated checks, recorded/live test boundaries and diagnostics |
| [YouTube Shorts Publishing](docs/youtube-shorts-publishing.md) | Google Cloud/OAuth setup, resumable upload and reconciliation |
| [Roadmap](docs/roadmap.md) | Product direction and planned-vs-implemented boundary |

## Checks

From `backend` after `pip install -r requirements-dev.txt`:

```powershell
.venv\Scripts\python.exe tests\test_core.py
.venv\Scripts\python.exe tests\test_api.py
.venv\Scripts\python.exe tests\test_quick_clip.py
.venv\Scripts\python.exe tests\test_youtube_clip.py
.venv\Scripts\python.exe tests\test_youtube_import.py
.venv\Scripts\python.exe tests\test_mood_quotes.py
.venv\Scripts\python.exe tests\test_asset_library.py
.venv\Scripts\python.exe tests\test_subtitles.py
.venv\Scripts\python.exe tests\test_batch_studio.py
.venv\Scripts\python.exe tests\test_youtube.py
.venv\Scripts\python.exe tests\test_youtube_analytics.py
.venv\Scripts\python.exe tests\test_platform_publishing.py
.venv\Scripts\python.exe -m compileall -q clipper tests
```

From `frontend`:

```powershell
npm run typecheck
npm run build
node --test lib/clip-editor-state.test.mjs
node --test lib/word-pop.test.mjs
```

Frontend helper regression code is in `frontend/lib/`; run from `frontend` with `node --test lib/mood-timeline.test.mjs lib/youtube-clip.test.mjs lib/clip-timeline.test.mjs`. V2.4–V2.9 checks/runtime/browser/render QA remain unrun in this checkout; see [Testing and Troubleshooting](docs/testing-and-troubleshooting.md) for mocked coverage and manual QA.

Optional real-media Quick Clip check with isolated DB/output roots (defaults to 14:00–15:00; pass a suitable source and a new/empty output folder):

```powershell
.venv\Scripts\python.exe tests\run_quick_clip_e2e.py `
  --video C:\path\owned-video.mp4 `
  --start 720 --end 780 `
  --output-dir "$env:LOCALAPPDATA\Temp\klipnara-quick-e2e"
```

Quick Clip E2E passed on the audited i3-9100F/RX 570 machine for audio and synthetic no-audio sources. Recorded device, transcription, chunking, render, and Quick Clip metrics with limits are in the AI, Video Processing, and Testing documents; single-run measurements are not guarantees.

Optional synthetic Mood Quotes render E2E (no AI/network/user media; verifies video/image/solid/gradient backgrounds, looping/mixed audio and silent AAC, Unicode text, animation, codec, duration, and progress):

```powershell
.venv\Scripts\python.exe tests\run_mood_render_e2e.py
```

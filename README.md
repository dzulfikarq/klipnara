# Klipnara

**Klipnara Studio is a local-first Windows video creator.** Create timestamp-based Quick Clips, optional AI Smart Clips, or AI Mood Quotes videos with original text, uploaded/Library backgrounds, music, and animated typography. Clip outputs use existing review and YouTube publishing workflow; Mood Quotes supports draft, review, and download.

Klipnara keeps media, SQLite state, Whisper/Ollama processing, and YouTube OAuth tokens on the local Windows user profile. Cloud AI requires explicit request consent: AI Smart Clip sends transcript prompts; Mood Quotes sends selected text settings. Neither sends video/audio assets to AI providers.

## Quick start

Requirements: Windows 10/11, Python 3.10+, Node.js 20.9+, FFmpeg/ffprobe. Whisper/model and Ollama/model are optional AI Smart Clip runtimes. Mood Quotes generation needs a configured Gemini or OpenAI backend key and explicit consent per request; rendering itself needs no AI runtime. YouTube OAuth is optional for approved clip outputs.

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
- Optional AI Smart Clip with local whisper.cpp/Ollama or OpenAI/Gemini highlight analysis using explicit consent.
- AI Mood Quotes: 8 configurable mood groups, 5 schema-validated alternatives per cloud request, favorites/history, resumable local drafts, legacy Single Text and Sequential Text, semantic local segmentation, and editable timed segments.
- Mood Quotes V2.4 source: collapsible text/background/music timeline, draggable text timing and music offset, segment properties/split/merge/duplicate/reorder, playhead/snap/zoom, and timeline-synced browser audio. Timeline edits share `composition_json`; no parallel timeline state or SQLite migration.
- Mood Quotes: 10 Smart Cinematic Presets, deterministic mood recommendations, adaptive typography, slow zoom/pan/Ken Burns, color grading, vignette, grain, and gradient/dark overlays. Presets preserve quote, manual timing, selected media background, and music; solid/gradient palettes follow preset.
- Mood Quotes Live/Full Preview and existing FFmpeg renderer consume one composition snapshot, including music offset/mute/trim/fades. Render jobs retain cancel/retry/progress, audio signal checks, 9:16 H.264/AAC MP4, review fingerprint, Clip Library listing, and download.
- Token-bounded transcript chunking, SQLite chunk checkpoints, candidate validation/deduplication and global ranking.
- Portrait FFmpeg H.264/AAC render, trim, center/manual crop and editable ASS subtitles.
- Separate clip review/render states with approval bound to final MP4 SHA-256.
- YouTube V1.1 Connected Accounts and Publishing History; OAuth, approval-gated resumable upload and processing confirmation.

**Not implemented:** YouTube URL-based Clip import, Mood Quotes YouTube publishing adapter, Cloud Transcription, scheduled posting, mobile app, cloud hosting, multi-user SaaS or other social-platform publishing. Mood Quotes is not inserted into the source-bound `clips` table; it has project/render tables and an independent review fingerprint. See [Roadmap](docs/roadmap.md).

YouTube live credentials are not configured in this checkout; automated publishing tests mock Google HTTP requests. No real YouTube upload/video ID has been verified. Setup steps are in [YouTube Shorts Publishing](docs/youtube-shorts-publishing.md).

## Documentation index

| Document | Contents |
|---|---|
| [Architecture](docs/architecture.md) | Components, data boundaries, worker design, key trade-offs |
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
.venv\Scripts\python.exe tests\test_mood_quotes.py
.venv\Scripts\python.exe tests\test_youtube.py
.venv\Scripts\python.exe -m compileall -q clipper tests
```

From `frontend`:

```powershell
npm run typecheck
npm run build
```

Frontend timeline regression code is in `frontend/lib/mood-timeline.test.mjs`; run from `frontend` with `node --test lib/mood-timeline.test.mjs`. V2.4 tests and runtime/browser/render QA remain unrun in this checkout; see [Testing and Troubleshooting](docs/testing-and-troubleshooting.md).

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

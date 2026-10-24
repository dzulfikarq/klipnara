# Klipnara

**Local-first Windows video clipper and YouTube Shorts publisher.** Quick Clip is timestamp-based and requires no AI runtime. Optional AI Smart Clip generates transcript-based highlight candidates; both paths support review/edit/render, then optional YouTube publishing for approved MP4s.

Klipnara keeps media, SQLite state, Whisper/Ollama processing, and YouTube OAuth tokens on the local Windows user profile. Cloud highlight providers are optional and require per-job consent; only transcript-based prompt data is sent, never source video/audio.

## Quick start

Requirements: Windows 10/11, Python 3.10+, Node.js 20.9+, FFmpeg/ffprobe. Whisper/model and Ollama/model are optional AI Smart Clip runtimes; OpenAI/Gemini can replace Ollama for highlight analysis with user consent. YouTube OAuth is optional.

1. Follow [Getting Started](docs/getting-started.md). FFmpeg/ffprobe required; Whisper/Ollama setup is optional for AI Smart Clip.
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
- Token-bounded transcript chunking, SQLite chunk checkpoints, candidate validation/deduplication and global ranking.
- Portrait FFmpeg H.264/AAC render, trim, center/manual crop and editable ASS subtitles.
- Separate clip review/render states with approval bound to final MP4 SHA-256.
- YouTube V1.1 Connected Accounts and Publishing History; OAuth, approval-gated resumable upload and processing confirmation.

**Not implemented:** Cloud Transcription, scheduled posting, mobile app, cloud hosting, multi-user SaaS or other social-platform publishing. See [Roadmap](docs/roadmap.md).

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
| [Testing and Troubleshooting](docs/testing-and-troubleshooting.md) | Automated checks, recorded/live test boundaries and diagnostics |
| [YouTube Shorts Publishing](docs/youtube-shorts-publishing.md) | Google Cloud/OAuth setup, resumable upload and reconciliation |
| [Roadmap](docs/roadmap.md) | Product direction and planned-vs-implemented boundary |

## Checks

From `backend` after `pip install -r requirements-dev.txt`:

```powershell
.venv\Scripts\python.exe tests\test_core.py
.venv\Scripts\python.exe tests\test_api.py
.venv\Scripts\python.exe tests\test_quick_clip.py
.venv\Scripts\python.exe tests\test_youtube.py
.venv\Scripts\python.exe -m compileall -q clipper tests
```

From `frontend`:

```powershell
npm run typecheck
npm run build
```

Optional real-media Quick Clip check with isolated DB/output roots (defaults to 14:00–15:00; pass a suitable source and a new/empty output folder):

```powershell
.venv\Scripts\python.exe tests\run_quick_clip_e2e.py `
  --video C:\path\owned-video.mp4 `
  --start 720 --end 780 `
  --output-dir "$env:LOCALAPPDATA\Temp\klipnara-quick-e2e"
```

Quick Clip E2E passed on the audited i3-9100F/RX 570 machine for audio and synthetic no-audio sources. Recorded device, transcription, chunking, render, and Quick Clip metrics with limits are in the AI, Video Processing, and Testing documents; single-run measurements are not guarantees.

# Klipnara

**Local-first Windows video clipper and YouTube Shorts publisher.** Import a source video, generate transcript-based highlight candidates, review/edit/render portrait MP4s, then optionally publish approved output to a connected YouTube channel.

Klipnara keeps media, SQLite state, Whisper/Ollama processing, and YouTube OAuth tokens on the local Windows user profile. Cloud highlight providers are optional and require per-job consent; only transcript-based prompt data is sent, never source video/audio.

## Quick start

Requirements: Windows 10/11, Python 3.10+, Node.js 20.9+, FFmpeg/ffprobe. Fresh-source AI generation uses whisper.cpp/model; default Local AI also needs Ollama/model. Choosing OpenAI/Gemini replaces Ollama, not local transcription. YouTube OAuth is optional.

1. Follow [Getting Started](docs/getting-started.md) to install FFmpeg, whisper.cpp, Ollama and their models.
2. From `backend`, create/install Python environment and configure `.env`:

   ```powershell
   python -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
   if (-not (Test-Path .env)) { Copy-Item .env.example .env }
   # Edit local binary/model paths as needed; do not put real secrets in source control.
   ```

3. Start backend from `backend`:

   ```powershell
   .venv\Scripts\python.exe -m uvicorn clipper.main:app --host 127.0.0.1 --port 8000 --env-file .env
   ```

4. Start frontend from `frontend`:

   ```powershell
   npm install
   npm run dev
   ```

5. Open `http://localhost:3000`. Backend API docs: `http://127.0.0.1:8000/api/docs`.

## Implemented

- MP4/MOV upload and direct public HTTPS media-file import with ffprobe validation and DNS/IP protections.
- Local whisper.cpp transcription and local Ollama highlight analysis; OpenAI/Gemini highlight analysis is optional with explicit consent.
- Token-bounded transcript chunking, SQLite chunk checkpoints, candidate validation/deduplication and global ranking.
- Portrait FFmpeg H.264/AAC render, trim, center/manual crop and editable ASS subtitles.
- Separate clip review/render states with approval bound to final MP4 SHA-256.
- YouTube V1.1 Connected Accounts and Publishing History; OAuth, approval-gated resumable upload and processing confirmation.

**Not implemented:** timestamp-first Quick Clip, Cloud Transcription, scheduled posting, mobile app, cloud hosting, multi-user SaaS or other social-platform publishing. See [Roadmap](docs/roadmap.md).

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
.venv\Scripts\python.exe tests\test_youtube.py
.venv\Scripts\python.exe -m compileall -q clipper tests
```

From `frontend`:

```powershell
npm run typecheck
npm run build
```

Recorded device, transcription, chunking, and render benchmarks include hardware/input caveats in the AI and Video Processing documents. They are measurements from specific local runs, not guarantees for other hardware/media.

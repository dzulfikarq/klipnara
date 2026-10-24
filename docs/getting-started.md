# Getting Started

Supported workflow targets Windows 10/11, one local user, loopback-only backend, and a separate local Next.js frontend. Follow this guide for fresh setup; environment variables and YouTube configuration are listed below and in [YouTube publishing](youtube-shorts-publishing.md).

## Requirements

- Windows 10/11; Python 3.10+; Node.js 20.9+.
- FFmpeg and ffprobe. Build must include libx264 and libass; audited 1080p path also requires working `h264_amf`.
- whisper.cpp CLI plus multilingual `small` model recommended for **AI Smart Clip**; `base` is faster and less accurate fallback. Neither is required for Quick Clip.
- Ollama and `qwen2.5:1.5b` for default local AI Smart Clip highlight selection. Ollama is not required by Quick Clip.
- Google Cloud OAuth web client only if connecting YouTube.

## Install media runtimes

Install FFmpeg (example: Gyan full build):

```powershell
winget install --id Gyan.FFmpeg --exact
ffmpeg -version
ffprobe -version
ffmpeg -encoders | findstr libx264
ffmpeg -filters | findstr ass
```

For the tested RX 570 1080p path, also check `ffmpeg -encoders | findstr h264_amf`. `h264_amf` unavailable means 1080p render will fail; use 720p x264. FFmpeg build licensing matters if redistributing.

Optional for AI Smart Clip: build whisper.cpp CPU-only and download `small`:

```powershell
winget install --id Kitware.CMake --exact
winget install --id Microsoft.VisualStudio.2022.BuildTools --exact --override "--wait --quiet --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
New-Item -ItemType Directory -Force C:\tools | Out-Null
git clone --depth 1 --branch v1.9.5 https://github.com/ggml-org/whisper.cpp.git C:\tools\whisper.cpp
Set-Location C:\tools\whisper.cpp
cmake -S . -B build -G "Visual Studio 17 2022" -A x64 -DGGML_VULKAN=OFF
cmake --build build --config Release --parallel 4
.\models\download-ggml-model.cmd small .\models
# Faster, lower-accuracy fallback:
# .\models\download-ggml-model.cmd base .\models
```

Optional for AI Smart Clip: install Ollama and model for local highlight analysis:

```powershell
winget install --id Ollama.Ollama --exact
ollama pull qwen2.5:1.5b
```

Start Ollama Desktop or run `ollama serve` in another terminal. AI Smart Clip checks local service/model with bounded attempts and fails without cloud fallback. Quick Clip does not check/load the local model.

## Prepare backend

From repository root:

```powershell
Set-Location backend
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```

Edit `backend/.env` paths if needed. Example media roots can live on another drive:

```dotenv
# Optional for AI Smart Clip only:
# WHISPER_CPP_PATH=C:/tools/whisper.cpp/build/bin/Release/whisper-cli.exe
# WHISPER_MODEL_PATH=C:/tools/whisper.cpp/models/ggml-small.bin
# OLLAMA_URL=http://127.0.0.1:11434
# OLLAMA_MODEL=qwen2.5:1.5b
# Optional media roots:
# CLIPPER_SOURCE_DIR=G:/Klipnara/sources
# CLIPPER_CLIP_DIR=G:/Klipnara/clips
```

`--env-file .env` is passed by the root dev runner so Uvicorn reads this file. Process/OS variables take precedence. Never commit actual keys.

## Run both services from repository root

Install concurrently at repository root and the existing Next.js dependencies in `frontend`:

```powershell
npm install
npm --prefix frontend install
```

Then, from repository root, start frontend and backend together:

```powershell
npm run dev
```

Services: frontend `http://localhost:3000`; backend `http://127.0.0.1:8000`; health `http://127.0.0.1:8000/api/health`; API docs `http://127.0.0.1:8000/api/docs`. Concurrent output is tagged `FRONTEND` and `BACKEND`. Press `Ctrl+C` to stop both; backend wrapper forwards shutdown to Uvicorn. Next.js dev server provides frontend HMR; backend does not run with auto-reload.

Keep port 3000 free for the requested frontend URL. Next.js may automatically choose the next free port when 3000 is already occupied; stop that process, then restart Klipnara to use port 3000.

Separate service commands remain available from repository root:

```powershell
npm run dev:frontend
npm run dev:backend
```

Preflight reports missing root `concurrently`, `frontend/node_modules/next`, `backend/.venv/Scripts/python.exe`, backend Python packages, or `backend/.env` with setup commands. Runner checks dependencies only; it does not import the app during preflight or start Whisper/Ollama. With no persisted queued jobs, backend worker stays idle until a user submits a job. A queued job persisted from a prior run is resumed by the existing queue.

`NEXT_PUBLIC_API_URL` can override default backend URL before building frontend. If overridden, configure CORS in backend for that local frontend origin.

## First local workflow

1. Open **Buat Klip AI** and upload MP4/MOV or import direct public HTTPS media URL.
2. Choose candidate count, target length, style, resolution, crop focus, language, and AI provider. Cloud provider requires per-job consent.
3. Generate candidates. Local queue reports worker status; completed analysis routes to source candidate review.
4. Open candidate in editor, adjust trim/crop/subtitles, render final MP4, then approve or request revision.
5. YouTube setup and verified-account requirements are in [YouTube Shorts Publishing](youtube-shorts-publishing.md).

## Environment variable reference

| Variable | Default / purpose |
|---|---|
| `CLIPPER_DATA_DIR` | SQLite/work/log root; `%LOCALAPPDATA%\Klipnara` on Windows |
| `CLIPPER_SOURCE_DIR` | Original source root; defaults to data root `sources` |
| `CLIPPER_CLIP_DIR` | Render root; defaults to data root `clips` |
| `CLIPPER_MAX_UPLOAD_BYTES` | Upload/import cap; default 2 GiB |
| `FFMPEG_PATH`, `FFPROBE_PATH` | Binary overrides; default executable names |
| `WHISPER_CPP_PATH`, `WHISPER_MODEL_PATH` | whisper.cpp executable and model file |
| `OLLAMA_URL`, `OLLAMA_MODEL` | Local Ollama endpoint and model; defaults `http://127.0.0.1:11434`, `qwen2.5:1.5b` |
| `OLLAMA_TIMEOUT_SECONDS` | Local inference timeout; default 600, allowed 1–1800 |
| `AI_REQUEST_TIMEOUT_SECONDS` | OpenAI/Gemini request timeout; default 180, allowed 1–1800 |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Optional backend-only OpenAI configuration |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Optional backend-only Gemini configuration |
| `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET` | Optional OAuth web client; backend only |
| `YOUTUBE_REDIRECT_URI` | Exact local callback URI; default `http://localhost:8000/api/youtube/oauth/callback` |
| `YOUTUBE_FRONTEND_URL` | Local post-OAuth return URL; default `http://localhost:3000/accounts` |
| `CLINFO_PATH`, `VULKANINFO_PATH` | Optional diagnostics executable overrides |

`MIN_FREE_BYTES` is a code constant of 1 GiB rather than an environment option. See [API and Database](api-and-database.md) for storage locations and schemas.

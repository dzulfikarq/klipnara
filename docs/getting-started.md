# Getting Started

Supported workflow targets Windows 10/11, one local user, loopback-only backend, and a separate local Next.js frontend. Follow this guide for fresh setup; environment variables and YouTube configuration are listed below and in [YouTube publishing](youtube-shorts-publishing.md).

## Requirements

- Windows 10/11; Python 3.10+; Node.js 20.9+.
- FFmpeg and ffprobe. Build must include libx264 and libass; audited 1080p path also requires working `h264_amf`.
- whisper.cpp CLI plus multilingual `small` model recommended; `base` is faster and less accurate fallback.
- Ollama and `qwen2.5:1.5b` for default local highlight selection. Ollama is optional for ingest/render, but generation using Local AI requires it.
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

Build whisper.cpp CPU-only and download `small`:

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

Install Ollama and model for local highlight analysis:

```powershell
winget install --id Ollama.Ollama --exact
ollama pull qwen2.5:1.5b
```

Start Ollama Desktop or run `ollama serve` in another terminal. App checks local service/model with bounded attempts and fails without cloud fallback.

## Backend

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
WHISPER_CPP_PATH=C:/tools/whisper.cpp/build/bin/Release/whisper-cli.exe
WHISPER_MODEL_PATH=C:/tools/whisper.cpp/models/ggml-small.bin
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5:1.5b
# Optional media roots:
# CLIPPER_SOURCE_DIR=G:/Klipnara/sources
# CLIPPER_CLIP_DIR=G:/Klipnara/clips
```

Run backend from `backend`:

```powershell
.venv\Scripts\python.exe -m uvicorn clipper.main:app --host 127.0.0.1 --port 8000 --env-file .env
```

`--env-file .env` is required for Uvicorn to read the sample file. Process/OS variables take precedence. Never commit actual keys. Local API docs: `http://127.0.0.1:8000/api/docs`.

## Frontend

In another terminal from repository root:

```powershell
Set-Location frontend
npm install
npm run dev
```

Open `http://localhost:3000`. `NEXT_PUBLIC_API_URL` can override default backend `http://127.0.0.1:8000` before frontend build.

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

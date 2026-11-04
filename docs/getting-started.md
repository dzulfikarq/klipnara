# Getting Started

Supported workflow targets Windows 10/11, one local user, loopback-only backend, and a separate local Next.js frontend. Follow this guide for fresh setup; environment variables and YouTube configuration are listed below and in [YouTube publishing](youtube-shorts-publishing.md).

## Requirements

- Windows 10/11; Python 3.10+; Node.js 20.9+.
- FFmpeg and ffprobe. Build must include libx264 and libass. V2.6 source-clip 1080p uses `h264_amf` when listed and falls back to x264 when absent; a listed but incompatible AMF driver can still fail.
- whisper.cpp CLI plus multilingual `small` model recommended for **AI Smart Clip** and optional local subtitle transcription; `base` is faster and less accurate fallback. Neither is required for Quick Clip or Manual subtitles.
- Ollama and `qwen2.5:1.5b` for default local AI Smart Clip highlight selection. Ollama is not required by Quick Clip.
- Gemini or OpenAI backend API key for AI Mood Quotes **generation**. Mood Quotes FFmpeg rendering does not require either key or a local AI runtime.
- Google Cloud OAuth web client only if connecting YouTube.
- Optional Google Cloud API key restricted to YouTube Data API v3 for YouTube title/channel/thumbnail/duration metadata. IFrame preview needs no key.
- Optional standalone `yt-dlp` executable only when enabling local YouTube segment import. It is disabled by default, is not official YouTube tooling, and may not be permitted for a given video or use.
- Optional Pexels API key for official stock-video search/preview and explicit single-video import. Local Asset Library, uploads, and Mood reuse work without key/network.

## Install media runtimes

Install FFmpeg (example: Gyan full build):

```powershell
winget install --id Gyan.FFmpeg --exact
ffmpeg -version
ffprobe -version
ffmpeg -encoders | findstr libx264
ffmpeg -filters | findstr ass
```

For hardware-assisted 1080p on the tested RX 570, also check `ffmpeg -encoders | findstr h264_amf`. Without it, source-clip export uses x264 fallback; 720p remains x264. Verify driver/build compatibility locally. FFmpeg build licensing matters if redistributing.

Clip Editor adds no runtime dependency or environment setting. It reuses existing FFmpeg/ffprobe, `clips.edit_json`, and the serial render queue. Multi-Scene uses one source, up to 12 scenes, and per-join transitions; Zoom Blur currently falls back to Crossfade. Drafts may exceed 180 seconds; final editor renders cap at 180 seconds.

V2.8 subtitles add no package or database dependency. Local transcription reuses whisper.cpp; Gemini/OpenAI transcription and translation use existing backend keys and require separate in-app consent per request.

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

Start Ollama Desktop or run `ollama serve` in another terminal. AI Smart Clip checks local service/model with bounded attempts and fails without cloud fallback. Quick Clip and Mood Quotes rendering do not check/load the local model.

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

For AI Mood Quotes generation, configure `GEMINI_API_KEY` (default when present) or `OPENAI_API_KEY` in `backend/.env`. If Gemini is absent and OpenAI is configured, new drafts select OpenAI. Configure a provider only if you intend to send quote-generation text to that provider; each request still requires an in-app consent check. No video/image/audio assets or credentials are sent. Missing key/quota does not switch providers. Quote selection/editing, draft reopen, preview, and FFmpeg rendering need no AI call. System fonts are used; Klipnara does not download font files.

The same `OPENAI_API_KEY` / `GEMINI_API_KEY` can enable optional subtitle transcription and translation. V2.8 OpenAI `gpt-transcribe` uploads composition audio after confirmation and returns text without timestamps (25 MiB cap). Gemini `gemini-3.5-transcribe` uploads composition audio after confirmation and requests word timing/speaker labels (30-minute cap). Translation sends subtitle text only after its own confirmation. Review output before rendering; no cloud request happens automatically.

For optional YouTube Clip metadata, enable YouTube Data API v3 in Google Cloud, create an API key restricted to that API, and set `YOUTUBE_DATA_API_KEY` in backend `.env`. Keep key backend-only. Without it, URL validation and IFrame preview still work; title/channel/thumbnail/duration remain unavailable. Metadata is fetched on explicit request and not stored. This key does not authorize or download YouTube media. YouTube OAuth publishing credentials remain separate.

### Optional YouTube Publishing OAuth

Open **Akun → Lihat Panduan Setup** for the six-step Google Cloud walkthrough. Enable both YouTube Data API v3 and YouTube Analytics API. The page reads effective callback URI, requested scopes, OAuth credential readiness, and callback validation error from `GET /api/youtube/config`; it does not infer Google Cloud setup progress. New consent requests `youtube.upload` to publish, `youtube.readonly` to verify channel identity and authorize `reports.query`, and `yt-analytics.readonly` for Analytics reports. Copy the displayed callback URI exactly into the Web application client's **Authorized redirect URIs**. If no valid URI is returned, inspect `YOUTUBE_REDIRECT_URI` in the backend environment; do not guess a port or path. No monetary scope is requested.

Set `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET` only in `backend/.env` or the backend process environment, then reload the backend and refresh Connected Accounts. Never enter either value in the browser or commit it. UI readiness means both variables exist and callback configuration is valid; it does not mean a channel is connected. A channel appears only after explicit Google consent and successful backend channel-identity lookup. See [YouTube Shorts Publishing](youtube-shorts-publishing.md) for token handling and OAuth troubleshooting.

Use **Hubungkan Channel Lain** for another Google identity; OAuth prompts for account selection and preserves existing channels. Set a default destination in Connected Accounts, then select one or more channels in Publishing Studio. Google grants returning multiple YouTube channels still fail closed because channel selection within one grant is unsupported. TikTok and Instagram have separate **Hubungkan Akun Lain** actions and per-provider defaults.

### YouTube Analytics consent and reports

After connecting a channel, use **Aktifkan Analytics** on that channel card to grant Analytics without switching channel identity or discarding upload permission. Backend verifies channel ID and stores Google's actual returned scopes; it never treats requested scopes as granted. Narrow or unverifiable scope responses leave existing credentials unchanged. Older accounts without recorded granted scopes must reconnect before publishing or Analytics can rely on permissions. Analytics reads only the authenticated channel through official YouTube Analytics API; there is no arbitrary channel ID input, scraping, or earnings report.

Publishing Studio's Analytics tab separates **Channel** totals from **Klipnara** totals. Klipnara totals filter YouTube-published video IDs linked to local publication records. `Views` and `Engaged Views` are separate official metrics. Reports default to last 28 complete UTC days (current day excluded), compare equal-length previous period, and reuse local cache for six hours. YouTube reporting can lag; audience retention may be unavailable for new/small videos and is queried one video per request. Disconnect deletes that channel's cached reports. See [Analytics setup, API contract, and manual QA](youtube-shorts-publishing.md#youtube-analytics-v31).

For optional official Pexels video search, create an API key under Pexels and set `PEXELS_API_KEY` in `backend/.env`. Keep it backend-only; never use `NEXT_PUBLIC_*`. Restart backend after editing `.env`. Search sends query/filter metadata to Pexels; preview loads Pexels thumbnails/video directly in browser. No media is downloaded until user selects one MP4 and starts import. Import is single-threaded, capped at 512 MiB, and saved to local Source Library plus Asset Library; it does not create a clip or send media to AI. Read Pexels terms/license and assess people/logo/property rights yourself. Without key/network, local uploads, reuse, and rendering still work.

### Optional YouTube segment adapter

Adapter stays disabled unless explicitly opted in. Install a trusted standalone `yt-dlp` executable separately and configure backend `.env`:

```dotenv
YOUTUBE_IMPORT_ENABLED=1
YT_DLP_PATH=C:/tools/yt-dlp/yt-dlp.exe
# Set these if FFmpeg is not already on PATH:
# FFMPEG_PATH=C:/ffmpeg/bin/ffmpeg.exe
# FFPROBE_PATH=C:/ffmpeg/bin/ffprobe.exe
```

Restart backend after changing environment. Keep `YOUTUBE_IMPORT_ENABLED=0` (or unset) to disable. Do not supply cookies, browser profiles, login credentials, or yt-dlp config that adds authentication. `--ignore-config` is passed by adapter. Use only when you have rights to acquire/use content and the retrieval method is allowed by applicable terms; user confirmation cannot verify either. yt-dlp is not an official YouTube API or universally permitted method. Restricted/unsupported video may fail; local Source Library/upload remains fallback. Partial download requests selected interval but may transfer extra data or fail depending on stream format. No DRM or access-control bypass is attempted.

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

`NEXT_PUBLIC_API_URL` can override default backend base URL before building frontend; set host/root (for example `http://127.0.0.1:8000`) or include one trailing `/api`. Frontend normalizes the prefix and adds `/api` exactly once. If overridden, configure CORS in backend for that local frontend origin.

## First local workflow

1. Open **Buat Video** and choose Quick Clip, AI Smart Clip, YouTube Clip, or AI Mood Quotes. YouTube Clip validates URL and previews via official IFrame API. With optional adapter enabled and permitted use, choose timestamp then **Impor & Buat Klip**; otherwise choose local Source Library/upload fallback.
2. Quick Clip and AI Smart Clip use existing MP4/MOV upload, public HTTPS file import, or Source Library. Cloud AI Smart Clip requires consent.
3. AI Mood Quotes: choose mood/subcategory/topic/style, select provider, consent for that request, generate five choices, pick/edit one, then customize/render without another AI request.
4. Open **Asset Library** to upload local videos/images/music or search Pexels. Reuse stored media in Mood Quotes without copying files per draft; source-backed video remains available to Quick Clip. Use media you have rights to use. Review and download Mood MP4 from Mood workspace or Clip Library.
5. Approve each completed Clip or Mood output, then open **YouTube Studio** to set metadata and confirm upload. OAuth setup and account verification are in [YouTube Shorts Publishing](youtube-shorts-publishing.md).

## Environment variable reference

| Variable | Default / purpose |
|---|---|
| `CLIPPER_DATA_DIR` | SQLite/work/log root; `%LOCALAPPDATA%\Klipnara` on Windows |
| `CLIPPER_SOURCE_DIR` | Original source root; defaults to data root `sources` |
| `CLIPPER_CLIP_DIR` | Render root; defaults to data root `clips` |
| `CLIPPER_MAX_UPLOAD_BYTES` | Upload/import cap; default 2 GiB |
| `FFMPEG_PATH`, `FFPROBE_PATH` | Binary overrides; default executable names |
| `YOUTUBE_IMPORT_ENABLED` | Optional YouTube segment adapter opt-in; default `0` |
| `YT_DLP_PATH` | Optional standalone yt-dlp executable; default `yt-dlp` on PATH |
| `WHISPER_CPP_PATH`, `WHISPER_MODEL_PATH` | whisper.cpp executable and model file |
| `OLLAMA_URL`, `OLLAMA_MODEL` | Local Ollama endpoint and model; defaults `http://127.0.0.1:11434`, `qwen2.5:1.5b` |
| `OLLAMA_TIMEOUT_SECONDS` | Local inference timeout; default 600, allowed 1–1800 |
| `AI_REQUEST_TIMEOUT_SECONDS` | OpenAI/Gemini request timeout; default 180, allowed 1–1800 |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Optional backend-only OpenAI configuration |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Optional backend-only Gemini configuration |
| `PEXELS_API_KEY` | Optional backend-only official stock-video API key; never expose to frontend |
| `YOUTUBE_DATA_API_KEY` | Optional backend-only YouTube Data API v3 key for metadata; does not enable segment import |
| `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET` | Optional OAuth web client; backend only |
| `YOUTUBE_REDIRECT_URI` | Optional exact local callback override; effective value is returned by `GET /api/youtube/config` and shown in Connected Accounts when valid |
| `YOUTUBE_FRONTEND_URL` | Local post-OAuth return URL; default `http://localhost:3000/accounts` |
| `CLINFO_PATH`, `VULKANINFO_PATH` | Optional diagnostics executable overrides |

`MIN_FREE_BYTES` is a code constant of 1 GiB rather than an environment option. See [API and Database](api-and-database.md) for storage locations and schemas.

Pexels imports cap at 512 MiB. Existing Source Library video upload keeps its `CLIPPER_MAX_UPLOAD_BYTES` cap (2 GiB default); direct Asset Library/Mood video uploads cap at 512 MiB, images at 25 MiB, audio at 100 MiB. Pexels adapter downloads only one explicitly selected video at a time; there is no bulk downloader, Pixabay/music/font downloader, or cloud media store. Mood render requires FFmpeg with `libass`, `libx264`, AAC encoding; 1080p uses `h264_amf` when present and falls back to CPU x264. See [Video Processing](video-processing.md) for details and measured synthetic E2E results.

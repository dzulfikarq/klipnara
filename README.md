# Klipnara

**AI Video Clipper & Publisher**<br>
*Dari Video Panjang, Jadi Konten Menarik.*

Local-first video clipper for one personal workstation. Upload MP4/MOV or import a direct public HTTPS media URL; transcribe locally, rank timestamped highlight candidates, edit trim/crop/subtitles, then render H.264/AAC 9:16 MP4.

## Start

Requirements: Windows 10/11, Python 3.10+, Node.js 20.9+, FFmpeg/ffprobe, whisper.cpp CLI and multilingual `small` model (recommended; `base` is faster, less accurate fallback). Ollama is needed for local highlight analysis. `npm install` installs the web dependencies.

### 1. Install media runtimes

- Install a full FFmpeg build with `ffprobe`, `libx264`, and `libass`; audited RX 570 1080p also needs working `h264_amf`: `winget install --id Gyan.FFmpeg --exact`. Verified Gyan full build uses GPL-3.0 components; review build licensing before redistribution. WinGet installs command aliases under `%LOCALAPPDATA%\Microsoft\WinGet\Links`; open a new terminal or add that directory to PATH.
- Install [CMake](https://cmake.org/) and Visual Studio C++ Build Tools, then build whisper.cpp CPU-only. Verified with CMake 4.4.4 and VS Build Tools 17.14.42:

```powershell
winget install --id Kitware.CMake --exact
winget install --id Microsoft.VisualStudio.2022.BuildTools --exact --override "--wait --quiet --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
New-Item -ItemType Directory -Force C:\tools | Out-Null
git clone --depth 1 --branch v1.9.5 https://github.com/ggml-org/whisper.cpp.git C:\tools\whisper.cpp
cd C:\tools\whisper.cpp
cmake -S . -B build -G "Visual Studio 17 2022" -A x64 -DGGML_VULKAN=OFF
cmake --build build --config Release --parallel 4
.\models\download-ggml-model.cmd small .\models
# Faster, lower-accuracy alternative: .\models\download-ggml-model.cmd base .\models
```

- Install Ollama: `winget install --id Ollama.Ollama --exact`, start Ollama Desktop, then `ollama pull qwen2.5:1.5b`. If `ollama` is not on PATH, add `$env:LOCALAPPDATA\Programs\Ollama`. Ollama is optional for ingest/render; local highlight analysis needs service and model. If Desktop is not running, `ollama serve` starts the local API in a separate terminal.

Bounded service/model check (max three 1-second attempts; no Cloud fallback):

```powershell
$ready = $false
for ($try = 1; $try -le 3 -and -not $ready; $try++) {
  try { $tags = Invoke-RestMethod http://127.0.0.1:11434/api/tags -TimeoutSec 1; $ready = $tags.models.name -contains "qwen2.5:1.5b" }
  catch { if ($try -lt 3) { Start-Sleep -Milliseconds 250 } }
}
if (-not $ready) { throw "Start Ollama Desktop/ollama serve, then run ollama pull qwen2.5:1.5b" }
```

Verify FFmpeg build:

```powershell
ffmpeg -version
ffprobe -version
ffmpeg -encoders | findstr libx264
ffmpeg -encoders | findstr h264_amf
ffmpeg -filters | findstr ass
```

FFmpeg's source is LGPL 2.1+; enabling GPL components such as libx264 makes the resulting FFmpeg build GPL. Choose a build/license suitable for your use. Klipnara does not bundle FFmpeg or model files.

### 2. Run backend

Open PowerShell at repository root:

```powershell
cd backend
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:WHISPER_CPP_PATH = "C:\tools\whisper.cpp\build\bin\Release\whisper-cli.exe"
$env:WHISPER_MODEL_PATH = "C:\tools\whisper.cpp\models\ggml-small.bin"
$env:OLLAMA_URL = "http://127.0.0.1:11434"
$env:OLLAMA_MODEL = "qwen2.5:1.5b"
$env:CLIPPER_SOURCE_DIR = "G:\Klipnara\sources"
$env:CLIPPER_CLIP_DIR = "G:\Klipnara\clips"
# Optional if package aliases are not on PATH
$env:FFMPEG_PATH = "$env:LOCALAPPDATA\Microsoft\WinGet\Links\ffmpeg.exe"
$env:FFPROBE_PATH = "$env:LOCALAPPDATA\Microsoft\WinGet\Links\ffprobe.exe"
uvicorn clipper.main:app --host 127.0.0.1 --port 8000 --env-file .env
```

Uvicorn loads `.env` only because command uses `--env-file`; process environment overrides sample values. Keep cloud keys in process/OS environment, not `.env`.

Worker runs in backend process. SQLite and temporary files stay under `%LOCALAPPDATA%\Klipnara` by default; `CLIPPER_SOURCE_DIR` and `CLIPPER_CLIP_DIR` set original-video and rendered-output roots independently. This setup uses `G:\Klipnara\sources` and `G:\Klipnara\clips`. `CLIPPER_DATA_DIR` changes database/temp root. Existing media paths remain readable from the previous managed folders. Backend defaults bind to loopback; do not expose it to LAN without adding authentication.

Optional cloud keys must be set in backend process environment, never in UI, SQLite, or logs:

```powershell
$env:OPENAI_API_KEY = "..."
$env:GEMINI_API_KEY = "..."
$env:OPENAI_MODEL = "gpt-4o-mini"
$env:GEMINI_MODEL = "gemini-3.5-flash-lite"
# Alternative model: $env:GEMINI_MODEL = "gemini-3.6-flash"
```

Keys are read only by backend and sent in `x-goog-api-key`, not URL/SQLite/logs. Use Gemini API key from Free Tier project with billing disabled; tier belongs to the Google project. Cloud generation and every cloud retry require explicit consent. Gemini sends transcript text/timestamps and limited metadata, never video/audio. HTTP 429 stops job with quota guidance; no automatic paid upgrade or provider fallback. Configure alternative with `GEMINI_MODEL=gemini-3.6-flash`. Local API docs: `http://127.0.0.1:8000/api/docs`.

### 3. Run frontend

Open a second PowerShell at repository root:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. API defaults to `http://127.0.0.1:8000`; set `NEXT_PUBLIC_API_URL` before building if using another local port.

## Implemented

- Dashboard, source library, clip library, settings/diagnostics, AI clip form, candidate review, simple editor with render approval and revision decisions.
- Local YouTube Shorts publishing: Google OAuth channel connection, approval-gated resumable upload, upload progress, processing reconciliation, and publication history.
- MP4/MOV upload and direct HTTPS media download. Import validates format/codecs/duration via ffprobe, enforces 2 GiB source and 4-hour duration limits, checks free disk, pins DNS to public IP, rejects internal/private IPs, limits redirects to three and validates each redirect. Page URLs such as YouTube are not downloaded.
- SQLite source/transcript/candidate/job/edit/render records; local files; one in-process persistent queue; queued/running progress, cancel, retry, error log and temporary cleanup.
- Local whisper.cpp transcription, multilingual `small` recommended, cached by source/language/model fingerprint; `base` faster fallback. Phrase timestamps used for subtitle Highlight fallback.
- Ollama/OpenAI/Gemini adapters use strict JSON schemas, chunk-local candidate limits, then global AI ranking. Ollama starts with 180-second transcript windows and 25-second overlap, measures prompt tokens before inference, and splits oversized windows at sentence/segment boundaries. Chunks run sequentially and checkpoint to SQLite; retries reuse matching completed chunks. Job progress reports chunk count and token usage. Local limits: fixed 4096 context, 1536 output tokens, 256-token safety reserve, 600-second request timeout. Short AI proposals expand only to neighboring measured speech boundaries; strict validation and overlap deduplication apply.
- FFmpeg H.264/AAC render, portrait 720p/1080p, center/manual crop, ASS subtitle burn-in, trim and text/style/size/color/position edits. 720p uses libx264; RX 570 1080p uses benchmarked h264_amf. Subtitle edits/render retries reuse stored transcript and do not rerun transcription or AI.
- Custom delete confirmations; old render marked stale after edit and retained until replacement render succeeds.
- Clip review lifecycle: `review_status` is `needs_review`, `approved`, or `needs_revision`, separate from render `status`. `POST /api/clips/{id}/review` accepts `approved` or `needs_revision` only after completed output re-probes as non-empty H.264/AAC MP4. Changed edits and every new render reset review to `needs_review`. Future publishing queue must require approved status plus completed status and revalidate final MP4 at enqueue.

## Audit & compatibility

Repository was empty. Hardware/runtime audit on 22 Oct 2026:

| Component | Observed |
|---|---|
| OS | Windows 11 Pro, build 26200, 64-bit |
| CPU | Intel Core i3-9100F, 4 cores / 4 threads |
| RAM | 15.9 GiB |
| GPU | Radeon RX 570 Series, 4 GiB VRAM, driver 31.0.21924.61 |
| GPU APIs | `clinfo`: AMD OpenCL 2.1 GPU detected. `vulkaninfo`: RX 570, Vulkan 1.3.260 detected. `rocminfo` absent. |
| Python / Node | Python 3.10.6; Node 22.22.1 |
| Free disk | E: 65.5 GiB at audit |
| FFmpeg / ffprobe | Gyan full build 9.0.2, GPL-3.0 build; `libx264`, `libass`, and `h264_amf` listed |
| whisper.cpp / models | v1.9.5 CPU build (`GGML_VULKAN=OFF`); `small` 488 MB recommended, `base` 148 MB faster fallback |
| Ollama / Qwen | Ollama 0.40.8; `qwen2.5:1.5b` Q4_K_M, 986 MB |
| NVIDIA tools | `nvidia-smi` absent |

`clinfo` reports AMD OpenCL 2.1 and `vulkaninfo` reports RX 570 Vulkan 1.3.260; whisper.cpp was built CPU-only and logged AVX2/four threads. Ollama reported `100% GPU` for Qwen (backend allocation, not measured GPU utilization). Standalone AMF probe encoded 60×720×1280 frames in 1.74 s (2-second clip, 1.13× realtime). Final render uses libx264 at 720p and h264_amf at 1080p. No ROCm was installed.

### Reuse/licence review

| Project | Licence/status/fit | Decision |
|---|---|---|
| [AutoClip](https://github.com/artbyjazi/autoclip) | MIT, pre-1.0 alpha; audited `pyproject.toml` targets Python 3.11/3.12 and pulls faster-whisper, MediaPipe, SceneDetect, GPU extras and `yt-dlp`; its reframe/speaker tracking is beyond MVP. | No code reuse. Dependency weight, Python mismatch, and platform downloader are poor fit. |
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | MIT; actively maintained; supports Windows, CPU inference and multilingual timestamps. `-ml 1` word timestamps are experimental. | Selected as local subprocess; phrase timestamps used by default, no fake word sync. |
| [Ollama](https://github.com/ollama/ollama) | MIT; active; local structured output supported. | Selected local LLM adapter. Default `qwen2.5:1.5b`; model card is Apache-2.0. Test `ollama ps` reported model on GPU; local inference latency listed below. |
| [auto-editor](https://github.com/WyattBlue/auto-editor) | Unlicense; active, Nim-based silence/content editing. | Not used: silence removal does not select semantic highlights. |
| [ClipsAI](https://github.com/ClipsAI/clipsai) | MIT; repository last pushed Jan 2024 at audit; uses WhisperX/large Torch stack and gated pyannote speaker-diarization setup. | Not used: stale for this pipeline and dependency/hardware overhead not justified. |
| [FFmpeg](https://ffmpeg.org/legal.html) | LGPL 2.1+ source; builds with GPL components become GPL. | Selected at runtime for probe, audio extraction, crop, subtitle burn-in and H.264/AAC render. |

Direct app dependency licences: Next.js and React (MIT), lucide-react (ISC), TypeScript (Apache-2.0), FastAPI/Pydantic (MIT), Uvicorn (BSD-3-Clause), python-multipart (Apache-2.0). Test-only psutil is BSD-3-Clause. No video/AI project code above is vendored.

## Test results

Run Python checks after `pip install -r requirements-dev.txt` from `backend`:

```powershell
.venv\Scripts\python.exe tests\test_core.py
.venv\Scripts\python.exe tests\test_api.py
.venv\Scripts\python.exe tests\test_youtube.py
.venv\Scripts\python.exe -m compileall -q clipper tests
# One live call with a confirmed Free Tier key; synthetic transcript only.
.venv\Scripts\python.exe tests\test_gemini_live.py
```

Run frontend checks from `frontend`:

```powershell
npm run typecheck
npm run build
npm audit
```

Real integration run used 13 human-read Indonesian clips from [Google FLEURS `id_id/test`](https://huggingface.co/datasets/google/fleurs), CC-BY-4.0, concatenated with 250 ms gaps over FFmpeg `testsrc2`. Synthetic test MP4, not a user video. Run the reusable API/worker benchmark with your own owned/licensed MP4:

```powershell
# From backend; set the runtime paths as shown above.
python -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe tests\run_real_pipeline.py `
  --video C:\path\indonesian-1-3min.mp4 `
  --long-video C:\path\indonesian-5min.mp4 `
  --output-dir "$env:LOCALAPPDATA\Klipnara\test-results"
```

Measured on i3-9100F / 15.9 GiB RAM / RX 570:

| Stage | 149.5 sec source | 300 sec source |
|---|---:|---:|
| whisper.cpp `base`, four CPU threads | 41.1 sec | 61.0 sec |
| Ollama Qwen local analysis | 47.0 sec | 21.6 sec (three 180-second chunks) |
| Total generate job | 88.7 sec | 83.7 sec |
| Peak test process RSS | 1.57 GiB | 2.20 GiB |
| Peak system CPU sample | 100% | 100% |

Long-context verification after token-bounded chunking used cached transcripts (analysis only; no Whisper run), Ollama Qwen 1.5B, context 4096, 100% GPU allocation:

| Input | Transcript | Chunks | AI analysis | Candidates | Max measured prompt tokens | Peak tracked RSS |
|---|---:|---:|---:|---:|---:|---:|
| Short FLEURS sample | 149.5 sec / 19 segments | 1 | 18.6 sec | 3 of 5 requested | 792 | not sampled |
| Long local source | 1545.7 sec / 266 segments | 15 | 43.6 sec | 5 of 5 requested | 1436 | 1.65 GiB |

Configured Ollama prompt budget was 2304 tokens (`4096 - 1536 - 256`). Ollama 0.40 has no tokenizer endpoint, so 25:45 test used 32 calls: 15 one-token prompt preflights, 15 chunk analyses, one ranking preflight, one global-ranking call. Cached retry reused all 15 chunk results and reranked five candidates in 8.9 sec. Available system RAM: 2.03 GiB before, 2.17 GiB after; Qwen remained loaded. Short sample passed with three valid candidates; count is an upper bound, not a guarantee.

Indonesian transcription benchmark used same 149.53 sec / 13-clip Google FLEURS `id_id/test` sample for both models. Official human reference rows matched to clip IDs and exact waveform positions; reference totals 242 words / 1686 normalized characters. Installed whisper-cli reports `1.9.5-dev` from v1.9.5 source. Direct JSON artifacts compare forced `id` with `auto`:

Decoder audit of whisper.cpp v1.9.5 CLI source: app previously omitted `-l` for `language=auto`, while CLI default language is `en`—Indonesian auto jobs could be forced to English. App now passes explicit `-l auto`; `indonesia`/`english` map to `id`/`en`. Other CLI defaults retained: CPU build, four threads, beam search 5, temperature 0 with fallback increments of 0.2, no prior-text context, no translation, no VAD.

| Model | Language | Detected | WER | CER | Time | Peak RSS | Model file |
|---|---|---|---:|---:|---:|---:|---:|
| `base` | `id` | `id` | 35.54% | 15.84% | 19.6–34.0 sec | 410 MiB | 147.95 MB |
| `base` | `auto` | `id` | 35.54% | 15.84% | 24.54 sec | 410 MiB | 147.95 MB |
| `small` | `id` | `id` | 19.01% | 11.27% | 49.6–84.7 sec | 876 MiB | 487.60 MB |
| `small` | `auto` | `id` | 19.01% | 11.27% | 104.94 sec | 875 MiB | 487.60 MB |

WER/CER use NFKC, lowercase, punctuation removal and whitespace collapse; CER includes spaces. Small cuts WER by 16.53 percentage points and CER by 4.57 points. Direct outputs: `%LOCALAPPDATA%\Temp\opencode\accuracy-qa-20261023\direct-*.json`. Forced-id times varied between low (0.85 GiB free) and normal (5.97 GiB free) RAM runs; small's longer wall time tracks model size and system pressure.

Direct CLI Auto and forced-id outputs were text-identical and both detected Indonesian. Keep Auto for multilingual sources; choose Indonesia when known. `.env` now configures the installed small model. Direct CLI preprocessing comparison:

| Audio input | Model | WER | CER | Time |
|---|---|---:|---:|---:|
| Native 16 kHz mono | `base` | 35.54% | 15.84% | 19.64 sec |
| Native 16 kHz mono | `small` | 19.01% | 11.27% | 49.55 sec |
| Resampled 22.05 kHz mono | `base` | 32.64% | 10.68% | 18.02 sec |
| Resampled 22.05 kHz mono | `small` | 19.83% | 10.91% | 48.88 sec |
| Duplicated stereo | `base` | 38.43% | 16.55% | 17.10 sec |
| 16 kHz mono + `loudnorm=I=-20:TP=-1.5:LRA=11` | `base` | 31.82% | 11.09% | 17.96 sec |
| 16 kHz mono + `loudnorm=I=-20:TP=-1.5:LRA=11` | `small` | 15.29% | 3.74% | 49.73 sec |

Sample mean volume −25.3 dBFS, peak 0 dBFS. Direct-cli normalization improved both models on this reference; app now applies it before mono 16 kHz PCM extraction. Stereo duplication worsened base; 22.05 kHz gave mixed model results. Keep mono/16 kHz. FLEURS is human-read clip concatenation, not conversational Indonesian.

FLEURS reference strings are human-annotated dataset text; clip IDs were manually checked against all 13 exact PCM segments in the 149.53 sec fixture. No subjective audio listening was performed, so dataset reference errors remain possible.

Actual backend UAT used 4-minute cut from existing Indonesian source: configured `small`, requested `auto`, detected `id`, 40 segments, four candidates, `ready_for_review` in 132.03 sec. Whisper/transcription phase took 87.89 sec. Peak tracked RSS (Python, whisper-cli, FFmpeg, Ollama) was 1.56 GiB; available system RAM 5.14→3.33 GiB. Rank-1 Clean/720p export took 2.66 sec and decoded as H.264/AAC, 9:16, 0.02 sec A/V duration delta, no black interval. MP4: `G:\Klipnara\clips\qa-indonesian-20261023\kkn-small-auto-loudnorm-highlight-clean-720.mp4`; manual punctuation override saved and rerendered in 3.29 sec as `kkn-small-loudnorm-manual-edited-720.mp4`, with transcript, timestamps, AI jobs, and provider usage unchanged. Small output still contains likely ASR errors (`mengedepkan`, `mahasisvi`, `gula kejenyata`); no human audio check was available. Qwen supplied Chinese candidate reasons on this Indonesian job; AI pipeline left unchanged.

Earlier CPU x264 baseline: 720p renders (19.5 sec clip) took 3.3–4.1 sec; 1080p took 9.0 sec. Clean/Bold/Highlight frames were visually checked; Highlight is phrase-level, yellow. Manual crop x/y values exercised. Rerender preserved exact transcript. Live render cancel stopped FFmpeg, kept previous render, and retry completed. Missing ffprobe/FFmpeg/whisper and missing Ollama model returned explicit local errors. Real-media run had no Cloud key and used Local AI only; provider usage rows were local only.

### End-to-end render/output quality — 23 Oct 2026

Used saved AI candidate rank 4 (`Heat Reflectors`, 38.26 sec) from the 25:45 source; no analysis or transcription rerun. Export edits trimmed 0.25–0.5 sec from boundaries. Tested Clean/Bold/Highlight, center/manual crop, 720p/1080p, subtitle overrides, repeat edits, and decoded every MP4 with FFmpeg.

| Render | Encoder | Encoder stage | Output | SSIM vs x264 |
|---|---|---:|---:|---:|
| 720p Clean/Bold/Highlight, 37.5–37.8 sec | libx264 veryfast CRF 23 | 14.1–18.5 sec | 10.5–11.5 MB | baseline |
| 720p equivalent AMF benchmark | h264_amf VBR Peak, 2.3 Mbps | 9.8 sec | 11.5 MB | 0.9723 |
| 1080p Highlight, 37.76 sec, prior CPU baseline | libx264 veryfast CRF 23 | 31.4 sec | 19.21 MB | baseline |
| 1080p Highlight, same edits, final app encoder | h264_amf VBR Peak, 4 Mbps | 18.6 sec | 19.76 MB | 0.9805 |

Kept x264 at 720p: AMF speed gain was modest and measured luma SSIM lower. Switched 1080p to AMF: 1.69× faster in app, 2.8% larger file, visually similar inspected frame. 1080 AMF MP4 decoded cleanly. Encoder selection targets audited RX 570; 1080p rendering requires working AMD AMF support in FFmpeg/driver.

All seven style/crop exports: H.264/AAC, exact 9:16 dimensions, complete decode, no detected black intervals, A/V duration difference 0.012–0.028 sec, trim output within 0.03 sec of target. Center vs manual crop frames differ as expected. Indonesian override captions from saved English transcript were visually checked in Clean/Bold/Highlight and fit inside frame; translation was not independently verified against spoken audio. Native Indonesian base output visibly contains ASR errors (`Stratak`, `terbukta`, `cipil`, “selamat dua apa terakhir”); base-derived subtitle content accuracy **failed**. A separate 20 sec export using saved direct-CLI `small` output matched first FLEURS reference text in rendered subtitle and stayed inside frame; video is synthetic testsrc, audio is real FLEURS read speech. Segment-level timestamping still presents sentence as one 9-line block. Do not use base-derived Indonesian captions without correction.

Changing subtitle text, trim and crop then rerendering left transcript, AI job count, and provider-usage count unchanged. Missing-FFmpeg render failed clearly; previous MP4 remained; retry completed. Active AMF render cancel removed partial output, preserved prior MP4, then retry completed. Process-restart simulation marked interrupted render `failed/interrupted`; retry completed without AI/transcription. Forced process exit during 25:45 analysis left 10/15 SQLite chunk checkpoints; startup recovered job, retry reused 10 chunks and finished five candidates in 20.75 sec with cached transcript unchanged.

Generated files and frames: `G:\Klipnara\clips\quality-e2e-20261023\`. Main final AMF 1080p MP4: `long-highlight-id-1080-amf-app.mp4`; small-transcript Indonesian subtitle sample: `short-small-fleurs-clean-720.mp4`; Clean/Bold/Highlight 720p, native Indonesian test, cancel/retry and restart-recovery MP4s are in same folder. Reports: `render-report.json`, `render-recovery-report.json`, `app-restart-report.json`, `short-small-fleurs-report.json`.

One test attempt found Ollama Desktop/service stopped while idle: local request failed immediately; no Cloud fallback. Starting Ollama restored `/api/tags` in 134 ms. Backend now checks service/model with at most three 1-second attempts and distinguishes stopped service, missing model, and inference timeout with explicit `ollama serve` / `ollama pull` guidance. Active FFmpeg render cancellation stopped the encoder; previous MP4 remained until retry succeeded. Ollama returned and Klipnara persisted 792 input / 1,271 output tokens for cached-transcript reanalysis; no cost estimate was generated. Tracked workload RSS reached 2.20 GiB (Python, Whisper, FFmpeg and Ollama runner); system RAM was 15.9 GiB. After unloading Qwen, available RAM measured 4.8 GiB in this agent environment; stop/unload the model after heavy tests when RAM is tight. In final test run, MP4s and screenshot frames are under `%LOCALAPPDATA%\Temp\opencode\klipnara-tests\run-06\`; no media fixture is committed.

Storage-path smoke passed on G: (119.7 GiB free at check): new upload landed under `G:\Klipnara\sources`; H.264/AAC render landed under `G:\Klipnara\clips`; API delete removed both test files. Existing source row/file in `%LOCALAPPDATA%\Klipnara\sources` was left in place and remains readable through legacy-path handling.

Gemini model catalog, using the configured Free Tier key, confirmed both requested model IDs support `generateContent`. One live `gemini-3.5-flash-lite` structured-output request used synthetic timestamped text only (no video/audio), returned two valid candidates, 206 input / 160 output tokens in 1.18 sec. `gemini-3.6-flash` generation was not called. Structured schema conversion, consent rejection, and simulated HTTP 429 quota messaging pass tests; no automatic retry/fallback.

Not run: 10-minute varied-content source, full browser E2E, offline-isolated test, OpenAI live call, Gemini 3.6 live call, actual Gemini 429 response, human review of every subtitle, 1080p beyond the selected clip. The 5-minute source looped 2.5-minute speech twice, so long-content variety remains unverified.

## YouTube Shorts publishing (V1.1)

Uses official [YouTube Data API v3](https://developers.google.com/youtube/v3/docs/videos/insert) `videos.insert`, server-side OAuth authorization-code flow, and only `https://www.googleapis.com/auth/youtube.upload`. It does not request a Google password or expose OAuth tokens to the browser. Video title, description, tags, privacy, Made for Kids, and synthetic-media disclosure are entered manually; no AI caption generation is used.

Detailed architecture, API contract, queue states, reconciliation behavior, and operations guide: [`docs/youtube-shorts-publishing.md`](docs/youtube-shorts-publishing.md).

### Google Cloud setup

1. Create/select a Google Cloud project and enable **YouTube Data API v3**.
2. Configure the OAuth consent screen. For personal testing, use External/Testing and add the channel's Google account as a test user. Public use of a sensitive YouTube scope can require Google's OAuth verification and YouTube API compliance review.
3. Create an OAuth Client ID of type **Web application**. Add this exact authorized redirect URI:

   ```text
   http://localhost:8000/api/youtube/oauth/callback
   ```

4. Put credentials in `backend/.env` (never commit it), then restart backend:

   ```dotenv
   YOUTUBE_CLIENT_ID=your-client-id.apps.googleusercontent.com
   YOUTUBE_CLIENT_SECRET=your-client-secret
   YOUTUBE_REDIRECT_URI=http://localhost:8000/api/youtube/oauth/callback
   YOUTUBE_FRONTEND_URL=http://localhost:3000/accounts
   ```

   Existing run command loads `.env` with `uvicorn ... --env-file .env`. Keep backend bound to loopback. Redirect URI must exactly match Google Cloud configuration; use `localhost` for Google's local HTTP exception.

5. Open **Akun** → **Hubungkan YouTube** and consent. Check channel title/ID under Connected Accounts. If Google does not return a refresh token, revoke Klipnara access in Google Account settings and reconnect with consent.

Refresh/access tokens and resumable session URIs are encrypted with Windows user-scoped DPAPI before SQLite storage. They decrypt only under same Windows user; moving the data folder or changing Windows user requires reconnecting. OAuth state is random, hashed in SQLite, one-use, ten-minute expiry, and bound to HttpOnly/SameSite cookie. Callback access logs omit authorization query. Client secret stays in backend environment.

### Upload contract

- Publishing requires `review_status='approved'`, render `status='completed'`, current non-empty MP4, H.264/AAC codecs, and SHA-256 matching bytes captured at approval. Shorts validation requires square/portrait aspect ratio and duration ≤180 seconds ([official eligibility](https://support.google.com/youtube/answer/15424877)). Changes/renders reset approval using existing review behavior; pending/uploading clips cannot be edited, rerendered, re-reviewed, or deleted. Existing approved clips without a stored fingerprint reset to `needs_review` once during migration and need one fresh approval.
- Form defaults privacy to **Private**. Made for Kids and realistic synthetic-content disclosure require an explicit Yes/No choice. A second confirmation precedes queue creation.
- Queue statuses are Pending, Uploading, Processing, Published, Failed, Cancelled; separate from render/review status. Existing single worker handles uploads; processing checks run when queue is idle. Scheduled posting is not implemented.
- Upload uses resumable `videos.insert` chunks of 8 MiB (multiple of 256 KiB). Progress counts bytes acknowledged by YouTube `Range`, not bytes read locally. On timeout/disconnect, worker probes session status before resending. Retry resumes saved session; if session expired after bytes may have been sent and no video ID can be recovered, automatic upload is blocked and user must reconcile in YouTube Studio. This fail-closed path prevents duplicate videos.
- A video is Published only after YouTube returns a video ID and `videos.list` confirms processed status, selected channel, and requested privacy. Requested Made for Kids/synthetic fields are sent and compared when YouTube returns them. History includes video ID/URL and processing result.

### Quota, verification, and test status

- Official docs currently list `videos.insert` in a **100 uploads/day** quota bucket (method cost 1 in that bucket); projects also receive 10,000 general quota units/day by default, and `channels.list`/`videos.list` cost 1 unit each. Check current project quota in Google Cloud Console before batch use.
- Google OAuth external apps in Testing may have refresh-token lifetime limits; reconnect after `invalid_grant`. Consent-screen verification and YouTube API compliance requirements depend on distribution and audience.
- `.venv\Scripts\python.exe tests\test_youtube.py` exercises DPAPI encryption, OAuth state/callback with mocked Google responses, channel status, expired-token handling, approval guard, resumable byte-range recovery, privacy payload, duplicate prevention, cancellation, and unknown-outcome reconciliation. Network calls are mocked. **No live Google OAuth credentials are configured here; no real YouTube upload or channel video ID has been tested.** Before relying on posting, configure OAuth above and run one real Private upload; confirm returned video ID, channel, and Private status in YouTube Studio.

### Known limits

- Personal/local-first single worker; no scheduler, multi-user auth, Instagram, Facebook, TikTok, or AI-generated YouTube captions.
- Upload status polling pauses while other queued jobs are running. Long processing may remain Processing until worker becomes idle.
- OAuth stores first channel returned by `channels.list(mine=true)`; channel chooser for accounts with multiple channels is not implemented. Upload response channel ID is checked before Published; verify one Private upload before selecting Public.
- An expired resumable session after possibly accepted bytes cannot be safely auto-retried without a known video ID; check YouTube Studio manually. No channel-wide search is used because title matching is not reliable duplicate reconciliation.
- Shorts eligibility check covers duration and frame aspect ratio; YouTube may still reject copyright, community-policy, channel, account, or API-project restrictions.

## Known limits

- Local highlight analysis fails clearly if Ollama/model is unavailable; it never falls back to cloud or deterministic fake candidates.
- Transcription uses segment-level timestamps. Highlight subtitle styling therefore highlights phrases, not individual words.
- Crop is fixed-position center/manual; no face tracking.
- URL ingest accepts public HTTPS media-file responses only (port 443); authenticated links and generic platform-page downloads are unsupported.
- Cloud key presence is checked before job creation; live provider/network validation occurs only after explicit per-job consent and first request.
- No scheduled posting, other social platforms, SaaS, billing, multi-user, or advanced timeline editor.

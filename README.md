# Klipnara

**AI Video Clipper & Publisher**<br>
*Dari Video Panjang, Jadi Konten Menarik.*

Local-first video clipper for one personal workstation. Upload MP4/MOV or import a direct public HTTPS media URL; transcribe locally, rank timestamped highlight candidates, edit trim/crop/subtitles, then render H.264/AAC 9:16 MP4.

## Start

Requirements: Windows 10/11, Python 3.10+, Node.js 20.9+, FFmpeg/ffprobe, whisper.cpp CLI and multilingual `base` model. Ollama is needed for local highlight analysis. `npm install` installs the web dependencies.

### 1. Install media runtimes

- Install a full FFmpeg build with `ffprobe`, `libx264`, and `libass`: `winget install --id Gyan.FFmpeg --exact`. Verified Gyan full build uses GPL-3.0 components; review build licensing before redistribution.
- Install [CMake](https://cmake.org/) and Visual Studio C++ Build Tools, then build whisper.cpp CPU-only. Verified with CMake 4.4.4 and VS Build Tools 17.14.42:

```powershell
winget install --id Kitware.CMake --exact
winget install --id Microsoft.VisualStudio.2022.BuildTools --exact --override "--wait --quiet --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
New-Item -ItemType Directory -Force C:\tools | Out-Null
git clone --depth 1 --branch v1.9.5 https://github.com/ggml-org/whisper.cpp.git C:\tools\whisper.cpp
cd C:\tools\whisper.cpp
cmake -S . -B build -G "Visual Studio 17 2022" -A x64 -DGGML_VULKAN=OFF
cmake --build build --config Release --parallel 4
.\models\download-ggml-model.cmd base .\models
# Optional accuracy comparison; set WHISPER_MODEL_PATH to this file to use it.
.\models\download-ggml-model.cmd small .\models
```

- Install Ollama: `winget install --id Ollama.Ollama --exact`, start Ollama Desktop, then `ollama pull qwen2.5:1.5b`. Ollama is optional for ingest/render; local highlight analysis needs service and model. If Desktop is not running, `ollama serve` starts the local API in a separate terminal.

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
ffmpeg -filters | findstr ass
```

FFmpeg's source is LGPL 2.1+; enabling GPL components such as libx264 makes the resulting FFmpeg build GPL. Choose a build/license suitable for your use. Klipnara does not bundle FFmpeg or model files.

### 2. Run backend

Open PowerShell at repository root:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:WHISPER_CPP_PATH = "C:\tools\whisper.cpp\build\bin\Release\whisper-cli.exe"
$env:WHISPER_MODEL_PATH = "C:\tools\whisper.cpp\models\ggml-base.bin"
# Optional if package aliases are not on PATH
$env:FFMPEG_PATH = "$env:LOCALAPPDATA\Microsoft\WinGet\Links\ffmpeg.exe"
$env:FFPROBE_PATH = "$env:LOCALAPPDATA\Microsoft\WinGet\Links\ffprobe.exe"
uvicorn clipper.main:app --host 127.0.0.1 --port 8000
```

`.env.example` is a reference only. Uvicorn reads `.env` only when invoked with `--env-file .env`; keep cloud keys in process/OS environment, not `.env`.

Worker runs in backend process; persistent SQLite database and media live under `%LOCALAPPDATA%\Klipnara` by default. Set `CLIPPER_DATA_DIR` to change location. Backend defaults bind to loopback; do not expose it to LAN without adding authentication.

Optional cloud keys must be set in backend process environment, never in UI, SQLite, or logs:

```powershell
$env:OPENAI_API_KEY = "..."
$env:GEMINI_API_KEY = "..."
$env:OPENAI_MODEL = "gpt-4o-mini"
$env:GEMINI_MODEL = "gemini-2.0-flash"
```

Keys are read only by backend. Cloud generation and every cloud retry require explicit consent. Cloud receives transcript text/timestamps and limited job metadata, never video/audio. No automatic provider fallback. OpenAI/Gemini price and live connectivity depend on user's account; app does not invent cost estimates. Local API docs: `http://127.0.0.1:8000/api/docs`.

### 3. Run frontend

Open a second PowerShell at repository root:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. API defaults to `http://127.0.0.1:8000`; set `NEXT_PUBLIC_API_URL` before building if using another local port.

## Implemented

- Dashboard, source library, clip library, settings/diagnostics, AI clip form, candidate review, simple editor.
- MP4/MOV upload and direct HTTPS media download. Import validates format/codecs/duration via ffprobe, enforces 2 GiB source and 4-hour duration limits, checks free disk, pins DNS to public IP, rejects internal/private IPs, limits redirects to three and validates each redirect. Page URLs such as YouTube are not downloaded.
- SQLite source/transcript/candidate/job/edit/render records; local files; one in-process persistent queue; queued/running progress, cancel, retry, error log and temporary cleanup.
- Local whisper.cpp transcription, multilingual `base`, cached by source and transcription language; phrase timestamps used for subtitle Highlight fallback.
- Ollama/OpenAI/Gemini adapters share strict JSON candidate schema. Long transcripts split into 180-second chunks with 90-second overlap and ranked interleaving; short AI proposals expand only to neighboring measured speech boundaries, then strict validation and overlap deduplication apply.
- FFmpeg CPU render, H.264/AAC, portrait 720p/1080p, center/manual crop, ASS subtitle burn-in, trim and text/style/size/color/position edits. Subtitle edits/render retries reuse stored transcript and do not rerun LLM.
- Custom delete confirmations; old render marked stale after edit and retained until replacement render succeeds.

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
| whisper.cpp / models | v1.9.5 CPU build (`GGML_VULKAN=OFF`); multilingual `base` 147 MiB and optional `small` 487 MiB |
| Ollama / Qwen | Ollama 0.40.8; `qwen2.5:1.5b` Q4_K_M, 986 MB |
| NVIDIA tools | `nvidia-smi` absent |

`clinfo` reports AMD OpenCL 2.1 and `vulkaninfo` reports RX 570 Vulkan 1.3.260; whisper.cpp was built CPU-only and logged AVX2/four threads. Ollama reported `100% GPU` for Qwen (backend allocation, not measured GPU utilization). Standalone AMF probe encoded 60×720×1280 frames in 1.74 s (2-second clip, 1.13× realtime). Klipnara render still uses CPU/libx264. No ROCm was installed.

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
.venv\Scripts\python.exe -m compileall -q clipper tests
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

Five candidates returned in both successful runs. App-pipeline base WER was 41.7% on this selected 242-word FLEURS sample; direct base CLI WER 35.5%. Optional `small` direct CLI improved this sample to 19.0% WER, but took 74.3 sec versus 40.9 sec for base; small not run through full app pipeline. Transcripts need user review; WER is sample-specific, not a general accuracy claim.

720p renders (19.5 sec clip) took 3.3–4.1 sec; 1080p took 9.0 sec. H.264/AAC, 9:16 dimensions, complete FFmpeg decode, zero detected black frames, A/V start offset below 100 ms. Clean/Bold/Highlight frames were visually checked; Highlight is phrase-level, yellow. Manual crop x/y values exercised. Rerender preserved exact transcript. Live render cancel stopped FFmpeg, kept previous render, and retry completed. Missing ffprobe/FFmpeg/whisper and missing Ollama model returned explicit local errors. Cloud keys were unset; provider usage rows were local only.

One test attempt found Ollama Desktop/service stopped while idle: local request failed immediately; no Cloud fallback. Starting Ollama restored `/api/tags` in 134 ms. Backend now checks service/model with at most three 1-second attempts and distinguishes stopped service, missing model, and inference timeout with explicit `ollama serve` / `ollama pull` guidance. Active FFmpeg render cancellation stopped the encoder; previous MP4 remained until retry succeeded. Ollama returned and Klipnara persisted 792 input / 1,271 output tokens for cached-transcript reanalysis; no cost estimate was generated. Tracked workload RSS reached 2.20 GiB (Python, Whisper, FFmpeg and Ollama runner); system RAM was 15.9 GiB. After unloading Qwen, available RAM measured 4.8 GiB in this agent environment; stop/unload the model after heavy tests when RAM is tight. In final test run, MP4s and screenshot frames are under `%LOCALAPPDATA%\Temp\opencode\klipnara-tests\run-06\`; no media fixture is committed.

Not run: 10-minute varied-content source, full browser E2E, offline-isolated test, OpenAI/Gemini live calls, human review of every subtitle, 1080p beyond the selected clip. The 5-minute source looped 2.5-minute speech twice, so long-content variety remains unverified.

## Known limits

- Local highlight analysis fails clearly if Ollama/model is unavailable; it never falls back to cloud or deterministic fake candidates.
- Transcription uses segment-level timestamps. Highlight subtitle styling therefore highlights phrases, not individual words.
- Crop is fixed-position center/manual; no face tracking.
- URL ingest accepts public HTTPS media-file responses only (port 443); authenticated links and generic platform-page downloads are unsupported.
- Cloud key presence is checked before job creation; live provider/network validation occurs only after explicit per-job consent and first request.
- No publishing, social-platform posting, SaaS, billing, multi-user, or advanced timeline editor.

# Testing and Troubleshooting

Automated tests are standalone Python assertion scripts, not pytest suites. Run from `backend` after installing `requirements-dev.txt`.

## Test commands

```powershell
.venv\Scripts\python.exe tests\test_core.py
.venv\Scripts\python.exe tests\test_api.py
.venv\Scripts\python.exe tests\test_quick_clip.py
.venv\Scripts\python.exe tests\test_youtube.py
.venv\Scripts\python.exe -m compileall -q clipper tests
```

Frontend scripts from `frontend`:

```powershell
npm run typecheck
npm run build
```

`frontend/package.json` defines no browser E2E or test-runner script. Browser workflows have not been validated by automated E2E in this repository.

## What checks cover

- `test_core.py`: strict candidate parsing/deduplication, timestamp chunk/token bounds, rank parsing, prompt/schema/context configuration, language flag, transcription cache fingerprint, local provider preflight, URL SSRF address checks and ASS subtitle output.
- `test_api.py`: FastAPI validation, cloud consent persistence, retry checkpoint copy, source/clip routes, approval guard/codecs, no approval during render, changed-edit invalidation and render reset.
- `test_quick_clip.py`: timestamp bounds, silent source acceptance, AI Smart Clip rejection without audio, Quick Clip worker AI-call isolation, review/subtitle gates, cancellation/retry, and FFmpeg silent-AAC command construction. FFmpeg execution is mocked by this automated test.
- `test_youtube.py`: DPAPI encrypt/decrypt round-trip; state cookie/state one-use logic and OAuth callback with mocked token/channel response; account status/disconnect; expired refresh token; approval/fingerprint/format/aspect/duration gate; manually entered metadata/default Private; resumable chunk acknowledgement after simulated connection loss; retry endpoint resumes known offset; duplicate prevention; cancel before upload; unknown session expiry fails closed.
- `test_gemini_live.py`: opt-in, exactly one actual Gemini request using synthetic timestamped text only; requires a configured Free Tier key and does not send media.
- `run_real_pipeline.py`: opt-in actual local API/worker/render test using an owned/licensed video and installed FFmpeg/ffprobe/Whisper/Ollama. Required `--video`, `--output-dir`; optional `--long-video`, `--timeout`. It exercises local pipeline failures/retry, renders, cancellation, and optional long-source handling. It is not run by the default scripts.
- `run_quick_clip_e2e.py`: opt-in real-media Quick Clip API/worker/FFmpeg test. It points to an existing source, uses isolated DB/output roots, disables Whisper/Ollama/cloud configuration, leaves source untouched, and reports rendered duration/codecs, elapsed time, sampled process-tree RSS and system CPU. Accepts `--video`, `--start`, `--end`, `--resolution`, and `--output-dir`.

### Verification categories

| Status | Evidence / boundary |
|---|---|
| Implemented and automated | core/API assertions and frontend typecheck/build |
| YouTube OAuth/upload mocked | `test_youtube.py`; DPAPI is exercised locally, Google HTTP requests are mocked |
| Local media integration previously recorded | `run_real_pipeline.py` and rendering QA measurements in [AI](ai-pipeline.md)/[Video](video-processing.md) docs; those use specific local hardware/media |
| Live Gemini previously recorded | One structured-output Free Tier request with synthetic transcript only; no video/audio |
| Live YouTube OAuth/upload | Not verified: no `YOUTUBE_CLIENT_ID`/`YOUTUBE_CLIENT_SECRET` configured in this checkout |
| Browser E2E | No browser E2E script/config in repository; not run |
| Offline-isolated run | Not run |
| Root dev-runner smoke | Backend `/api/health` returned 200; frontend returned 200 at 3011 with `PORT=3011`. Default port 3000 was occupied by another local app, so the exact 3000 URL was not independently verified in this environment |

Other not-run cases recorded in the repository audit: 10-minute varied-content source, OpenAI live call, Gemini 3.6 live call, actual Gemini 429 response, human review of every subtitle, and 1080p across varied source videos. A prior five-minute long-source fixture repeated a 2.5-minute speech segment twice, so semantic variety at that duration remains unverified.

### Quick Clip E2E — 24 Oct 2026

Target machine was Windows 11 Pro, Intel i3-9100F (4C/4T), 15.9 GiB RAM and Radeon RX 570 4 GiB. E2E used temporary DB/output directories, original sources remained unchanged, Whisper/Ollama paths were disabled and AI functions were guarded to raise if called. Existing Source Library contained one 14:09 source, shorter than requested 20–25 min; therefore tested its 12:00–13:00 interval rather than 14:00–15:00. Its rights were not independently audited; source stayed local and was not copied or uploaded. Also tested a synthetic 20 s silent H.264 `testsrc2` source at 00:05–00:15.

| Source | Interval | Output | FFmpeg render | Worker completion | Peak process-tree RSS | Sampled system CPU avg | AI calls |
|---|---|---|---:|---:|---:|---:|---:|
| Existing 849.147 s AAC source | 720–780 s (60 s) | 720×1280, H.264/AAC, 60.0 s, 3,295,225 bytes | 7.17 s | 7.85 s | 206.0 MiB | 93.6% | 0 |
| Synthetic 20 s silent source | 5–15 s (10 s) | 720×1280, H.264/AAC with silent audio, 10.0 s, 1,377,170 bytes | 1.42 s | 2.08 s | 189.7 MiB | 89.4% | 0 |

Both final outputs passed ffprobe and review approval. System CPU average is sampled whole-machine utilization, not Quick Clip process utilization; RSS aggregates sampled backend/child process tree. Runs are short one-off samples, not a cross-video benchmark. Silent-source content is synthetic, not user media.
GPU utilization was not sampled; these 720p tests use x264. No 20–25 min source was available in Source Library; source interval differs from target sample. Re-run with an owned/licensed source:

```powershell
.venv\Scripts\python.exe tests\run_quick_clip_e2e.py `
  --video C:\path\owned-video.mp4 `
  --start 720 --end 780 `
  --output-dir "$env:LOCALAPPDATA\Temp\klipnara-quick-e2e"
```

Do not interpret mocked YouTube success as a real platform upload. Before account use, configure OAuth and verify one Private upload's channel, video ID, privacy, and processing status in YouTube Studio.

## Troubleshooting

| Symptom | Check / action |
|---|---|
| Frontend says backend offline | Start Uvicorn at `127.0.0.1:8000`; frontend default `NEXT_PUBLIC_API_URL` points there |
| Upload/render says ffprobe/FFmpeg missing | Check PATH or set `FFPROBE_PATH`/`FFMPEG_PATH`; verify `ffmpeg -encoders` includes libx264 and `ffmpeg -filters` includes ASS/libass |
| 1080p render fails with encoder not found | Current 1080p path uses `h264_amf`; check AMD driver and FFmpeg AMF support, or select 720p |
| “Keep at least 1 GiB free” | Free space on data, work and selected source/output roots; this is hardcoded `MIN_FREE_BYTES` |
| whisper.cpp/model missing | Set `WHISPER_CPP_PATH` and `WHISPER_MODEL_PATH`; confirm `.env` is loaded with `--env-file .env` |
| Transcript seems stale after model/language change | Cache includes transcript config/language/model binary+model file fingerprint; settings change or rerun generation to regenerate |
| Local generation reports Ollama unavailable/model missing | Start Ollama Desktop/`ollama serve`; `ollama pull qwen2.5:1.5b` or set `OLLAMA_MODEL`; there is no cloud fallback |
| Ollama prompt too large | Code measures actual prompt with one-token request and splits at timestamped boundaries; a single unsplittable oversized segment fails explicitly |
| OpenAI/Gemini job rejected | Configure backend API key; choose provider and tick per-job consent. Cloud receives transcript-only prompt. Gemini 429 is not auto-retried/upgraded |
| Approval reset after code update | New migration resets old `approved` records lacking `reviewed_render_sha256`; inspect final render and approve once |
| YouTube “redirect_uri_mismatch” | `YOUTUBE_REDIRECT_URI` must exactly match the Google Cloud Web Client URI, including localhost, port, and callback path |
| YouTube account Expired | Refresh token returned `invalid_grant`; reconnect account. In OAuth Testing, refresh tokens may expire according to Google's current testing policy |
| YouTube upload Failed but retry available | Retry through Publishing History; worker probes saved session first and resumes at server-acknowledged byte offset |
| YouTube says outcome uncertain / retry blocked | Session expired after bytes may have reached YouTube without recovered video ID; inspect YouTube Studio manually before any new upload |
| YouTube publication remains Processing | Worker polls only while no queued jobs; account must stay/reconnect and YouTube must return processed status |
| YouTube account shows Error | Check OAuth client ID/secret, consent, granted scope and local redirect URI; credential values are not returned by API |
| AI Smart Clip on silent source | Current route rejects when fresh transcription is needed; use timestamp-based Quick Clip |
| Quick Clip final contains silent audio | Expected for silent input: renderer adds silent AAC to retain the final H.264/AAC review/publishing contract |

For API behavior and exact status schema, see [API and Database](api-and-database.md). For live YouTube setup, see [YouTube publishing](youtube-shorts-publishing.md).

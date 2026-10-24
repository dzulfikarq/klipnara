# Testing and Troubleshooting

Automated tests are standalone Python assertion scripts, not pytest suites. Run from `backend` after installing `requirements-dev.txt`.

## Test commands

```powershell
.venv\Scripts\python.exe tests\test_core.py
.venv\Scripts\python.exe tests\test_api.py
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
- `test_youtube.py`: DPAPI encrypt/decrypt round-trip; state cookie/state one-use logic and OAuth callback with mocked token/channel response; account status/disconnect; expired refresh token; approval/fingerprint/format/aspect/duration gate; manually entered metadata/default Private; resumable chunk acknowledgement after simulated connection loss; retry endpoint resumes known offset; duplicate prevention; cancel before upload; unknown session expiry fails closed.
- `test_gemini_live.py`: opt-in, exactly one actual Gemini request using synthetic timestamped text only; requires a configured Free Tier key and does not send media.
- `run_real_pipeline.py`: opt-in actual local API/worker/render test using an owned/licensed video and installed FFmpeg/ffprobe/Whisper/Ollama. Required `--video`, `--output-dir`; optional `--long-video`, `--timeout`. It exercises local pipeline failures/retry, renders, cancellation, and optional long-source handling. It is not run by the default scripts.

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

Other not-run cases recorded in the repository audit: 10-minute varied-content source, OpenAI live call, Gemini 3.6 live call, actual Gemini 429 response, human review of every subtitle, and 1080p across varied source videos. A prior five-minute long-source fixture repeated a 2.5-minute speech segment twice, so semantic variety at that duration remains unverified.

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

For API behavior and exact status schema, see [API and Database](api-and-database.md). For live YouTube setup, see [YouTube publishing](youtube-shorts-publishing.md).

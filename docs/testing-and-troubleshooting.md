# Testing and Troubleshooting

Automated tests are standalone Python assertion scripts, not pytest suites. Run from `backend` after installing `requirements-dev.txt`.

## Test commands

```powershell
.venv\Scripts\python.exe tests\test_core.py
.venv\Scripts\python.exe tests\test_api.py
.venv\Scripts\python.exe tests\test_quick_clip.py
.venv\Scripts\python.exe tests\test_mood_quotes.py
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
- `test_mood_quotes.py`: category/config and 10-preset schema, deterministic recommendations, preset field preservation, old-draft defaults, visual JSON reload, Indonesian semantic segmentation, bounded filtergraph/portrait output, safe text margins, effect validation, per-request consent/provider behavior, five-quote schema/similarity, malformed output, regeneration/favorites, assets, jobs, review, and additive schema/data preservation. AI provider and FFmpeg job execution are mocked.
- `test_youtube.py`: DPAPI encrypt/decrypt round-trip; state cookie/state one-use logic and OAuth callback with mocked token/channel response; account status/disconnect; expired refresh token; approval/fingerprint/format/aspect/duration gate; manually entered metadata/default Private; resumable chunk acknowledgement after simulated connection loss; retry endpoint resumes known offset; duplicate prevention; cancel before upload; unknown session expiry fails closed.
- `test_gemini_live.py`: opt-in, exactly one actual Gemini request using synthetic timestamped text only; requires a configured Free Tier key and does not send media.
- `run_real_pipeline.py`: opt-in actual local API/worker/render test using an owned/licensed video and installed FFmpeg/ffprobe/Whisper/Ollama. Required `--video`, `--output-dir`; optional `--long-video`, `--timeout`. It exercises local pipeline failures/retry, renders, cancellation, and optional long-source handling. It is not run by the default scripts.
- `run_quick_clip_e2e.py`: opt-in real-media Quick Clip API/worker/FFmpeg test. It points to an existing source, uses isolated DB/output roots, disables Whisper/Ollama/cloud configuration, leaves source untouched, and reports rendered duration/codecs, elapsed time, sampled process-tree RSS and system CPU. Accepts `--video`, `--start`, `--end`, `--resolution`, and `--output-dir`.
- `run_mood_render_e2e.py`: local synthetic FFmpeg E2E for legacy backgrounds/audio plus Ken Burns/color/overlay video and pan/still-image cases, silent AAC, Unicode text/ASS animation, progress, codecs/resolution/duration. It makes no AI/network calls and uses no user media. V2.3 cases were added but not executed.

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
| Mood Quotes provider tests | Automated provider mocks and negative cases pass; live Gemini/OpenAI Mood Quotes request and current provider quota are not verified by synthetic render E2E |
| Mood Quotes FFmpeg synthetic E2E | Four actual local renders; details below. No 1080p/AMF run or browser preview parity test |
| Step 3 live preview visual check | Not run for this two-column UI revision per workspace instruction. Thumbnail cache is covered by Mood API test; follow manual checklist below |
| V2.3 cinematic/segmentation additions | Test code updated; **not run**. No V2.3 build, runtime, browser, or FFmpeg validation was performed in this checkout |

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

### Mood Quotes FFmpeg E2E — 24 Oct 2026

Actual FFmpeg/ffprobe runs on the local Windows workstation used only generated test patterns and sine-wave audio; AI calls/network requests/user media were zero. Each output was 4.0 seconds, 720×1280, 30 FPS, H.264/AAC and passed ffprobe.

| Case | Background/audio | Render elapsed | Output bytes | Result |
|---|---|---:|---:|---|
| Short looping background video | Synthetic H.264/AAC video + looped synthetic music, mixed audio, Unicode/segment-typewriter text | 0.67 s | 763,549 | Pass |
| Solid color | FFmpeg color source + silent AAC | 0.48 s | 17,498 | Pass |
| Gradient | Generated PPM gradient + silent AAC | 0.97 s | 29,707 | Pass |
| Still image | Synthetic PNG + silent AAC | 0.78 s | 17,125 | Pass |

These short synthetic samples validate command/media paths only. They do not measure longer user footage, subjective font/animation quality, 1080p, AMF, browser-vs-render parity, or AI text quality.

The E2E script also includes sequential Unicode text, music trim/loop/fades, mono 44.1 kHz resampling, no-loop short music, background-only audio, muted/zero-volume silence, corrupt/silent selected audio, output signal checks, and V2.3 synthetic motion/color/overlay cases. These new scenarios have **not been run in this checkout**; historical results above cover only their listed cases. To run manually:

```powershell
.venv\Scripts\python.exe tests\run_mood_render_e2e.py
```

Do not interpret mocked YouTube success as a real platform upload. Before account use, configure OAuth and verify one Private upload's channel, video ID, privacy, and processing status in YouTube Studio.

### Manual Mood Quotes sequence/audio/render check

0. In Clip Library, select **Edit draft** on an existing Mood Quotes row; confirm its `?id=` draft opens without increasing the project count. Use **Hapus** only on a selected duplicate and confirm the dialog removes only that draft.
1. Open an old draft without `text_mode`; confirm it loads as **Single Text** with prior timing/appearance. Create a new draft; confirm **Sequential Text** default and no SQLite migration/data loss.
2. Select Indonesian quotes starting with “Terkadang,” and with comma/semicolon conjunctions. Confirm no hanging one-word opener, punctuation/text reconstruction, reasonable reading time, and warning for very long text/short duration. Edit a segment manually, press **Segmentasi ulang**, cancel confirmation and verify text/timing survive; confirm then verify only explicit reset replaces them. No AI request.
3. Choose Bahagia and Romantis moods; inspect **Direkomendasikan** vs **Preset lainnya**. Apply Happy Sunshine, Sad Night, Romantic Dream, Vintage Memories. Confirm visible effect variation. Change typography manually, apply another preset, use Undo and Reset Visual Style; quote/segments/timing/media assets/music must remain. Solid/gradient palette changes on preset apply and returns to defaults on reset.
4. Use image/video background and test all motion directions, Ken Burns, three intensities, and None. Scrub Live Preview; confirm crop has no black edges. Video thumb should remain a labeled static frame while its transform simulates motion; Preview Penuh should play actual video. Color grade, temp, vignette, grain, dark and gradient overlays should update without AI calls.
5. Change text font/weight/size/color/alignment/position/line spacing/opacity, Auto Contrast, text gradient, and segment animation. Check safe-margin warning, 720p and 1080p layouts, and narrow desktop width.
6. Compare **Editor Live Preview → Preview Penuh → MP4 final** at same playhead/segment. Verify motion direction/speed, grading/overlay, typography, text animation/timing, crop, H.264/AAC, duration/resolution. Small CSS/libass/color/grain differences are expected; log any material mismatch.
7. Test music trim/loop/fades/volume, background audio on/off/zero, no music, and silent/corrupt selected audio. No selection or zero volume may produce silent AAC; selected active silent/corrupt audio should fail clearly. Confirm visual presets never select music or external assets.
8. Approve output, mark **Perlu revisi**, edit composition, rerender, and confirm approval fingerprint invalidates while old render stays available. Download final MP4; reopen draft and confirm visual settings, quote/assets/history, manual segments, music, and legacy Single Text persist.
9. Run existing Quick Clip, AI Smart Clip, review, and YouTube mocked regression suites separately; confirm their forms/routes/render/publishing behavior did not change. Confirm edit/preview/render never call AI.

## Troubleshooting

| Symptom | Check / action |
|---|---|
| Frontend says backend offline | Start Uvicorn at `127.0.0.1:8000`; frontend default `NEXT_PUBLIC_API_URL` points there |
| Upload/render says ffprobe/FFmpeg missing | Check PATH or set `FFPROBE_PATH`/`FFMPEG_PATH`; verify `ffmpeg -encoders` includes libx264 and `ffmpeg -filters` includes ASS/libass |
| 1080p clip render fails with encoder not found | Existing source-clip 1080p path uses `h264_amf`; check AMD driver/FFmpeg AMF support or select 720p. Mood Quotes uses AMF when available and falls back to x264 |
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
| Mood quote generation says key missing | Set `GEMINI_API_KEY` (default) or select configured `OPENAI_API_KEY` in backend environment, restart backend, then explicitly consent per request. No provider fallback occurs |
| Mood quote request returns 429/502/schema error | Check selected provider/model and quota; request stops without automatic retry. Regenerate only after reviewing provider quota; malformed output is not saved |
| Mood render fails on font/ASS | Confirm `ffmpeg -filters` includes `ass` and FFmpeg has libass. Installed Windows fonts are Arial/Georgia/Segoe UI/Tahoma/Trebuchet MS/Times New Roman; missing family falls back through libass/OS substitution |
| Mood render rejects selected audio as silent/corrupt | Check selected trim range, source signal, and volume; choose another licensed file or explicitly select **Tanpa musik**/mute background. A mood label does not select music |
| Mood background/music rejected | Check supported file extension, per-kind size cap, valid ffprobe streams, and trim times within asset duration. Mood uploads stay under local `%LOCALAPPDATA%\Klipnara\mood` |
| Cannot delete Source Library video | Detach it from each Mood Quotes draft first; a restricting SQLite reference prevents deleting a source that a draft still uses |
| Mood output not in YouTube publish UI | Mood renders support review/download, but no source-less YouTube publication adapter is implemented. Existing clip publishing remains unchanged |

For API behavior and exact status schema, see [API and Database](api-and-database.md). For live YouTube setup, see [YouTube publishing](youtube-shorts-publishing.md).

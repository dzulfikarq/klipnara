# Testing and Troubleshooting

Automated tests are standalone Python assertion scripts, not pytest suites. Run from `backend` after installing `requirements-dev.txt`.

## Test commands

```powershell
.venv\Scripts\python.exe tests\test_core.py
.venv\Scripts\python.exe tests\test_api.py
.venv\Scripts\python.exe tests\test_quick_clip.py
.venv\Scripts\python.exe tests\test_youtube_clip.py
.venv\Scripts\python.exe tests\test_youtube_import.py
.venv\Scripts\python.exe tests\test_mood_quotes.py
.venv\Scripts\python.exe tests\test_asset_library.py
.venv\Scripts\python.exe tests\test_subtitles.py
.venv\Scripts\python.exe tests\test_batch_studio.py
.venv\Scripts\python.exe tests\test_youtube.py
.venv\Scripts\python.exe tests\test_platform_publishing.py
.venv\Scripts\python.exe -m compileall -q clipper tests
```

Frontend scripts from `frontend`:

```powershell
npm run typecheck
npm run build
```

Timeline helper regression code, from `frontend`:

```powershell
node --test lib/mood-timeline.test.mjs
node --test lib/youtube-clip.test.mjs
node --test lib/youtube-oauth.test.mjs
node --test lib/clip-timeline.test.mjs
node --test lib/clip-editor-state.test.mjs
node --test lib/word-pop.test.mjs
```

`frontend/package.json` defines no browser E2E or test-runner script. Browser workflows have not been validated by automated E2E in this repository.

## What checks cover

- `test_core.py`: strict candidate parsing/deduplication, timestamp chunk/token bounds, rank parsing, prompt/schema/context configuration, language flag, transcription cache fingerprint, local provider preflight, URL SSRF address checks, legacy ASS output, clip-relative ASS trim offsets, scene ordering, subtitle cut/duplicate mapping, Word Pop per-word ASS events/animation/long-word sizing/720p-1080p sizing/sub-centisecond rejection, and optional audio filter construction.
- `test_api.py`: FastAPI validation, cloud consent persistence, retry checkpoint copy, source/clip routes, approval guard/codecs, no approval during render, changed-edit invalidation/render reset, Word Pop disabled-selection/track-selection guards, and reviewed-alignment invalidation after cue or word edits.
- `test_quick_clip.py`: timestamp bounds, silent source acceptance, AI Smart Clip rejection without audio, Quick Clip worker AI-call isolation, manual subtitle save/reopen/render without transcript, no-audio STT error, cloud-consent gate, selected-trim extraction offsets, generated clip-relative timing, multi-scene edit persistence/render snapshot/subtitle mapping, title-only render without disabled captions, review, cancellation/retry, and single/multi-scene FFmpeg command construction. FFmpeg/STT/network execution is mocked by this automated test.
- `test_youtube_clip.py`: both reported `Zz7os_kWwnM` URL formats including `si`, supported URL/ID validation and malicious host rejection, `t`/`start` parsing, registered POST path vs wrong method/path 405/404, YouTube metadata 404/provider failures mapped separately from app-route 404, unavailable/quota/network responses with mocked Google requests, embed-disabled metadata, server-key containment, no direct-file DNS/download for YouTube pages, local-duration revalidation, explicit local-source association without identity inference, Quick Clip parameter/provenance forwarding and cleanup, plus AI Smart Clip/Mood Quotes route regression. No external media is downloaded.
- `test_youtube_import.py`: canonical YouTube ID/URL validation, timestamp argument forwarding to `--download-sections`, opt-in/adapter-unavailable paths, rights attestation, mocked partial MP4 validation/hash/progress, invalid-output cleanup, cancellation cleanup, persisted import status, automatic Quick Clip source/provenance handoff, queued cancellation, and retry. Downloader/ffprobe are mocked; no network, real yt-dlp, or FFmpeg runs.
- `test_mood_quotes.py`: category/config and 10-preset schema, deterministic recommendations, preset field preservation, old-draft music defaults, visual JSON reload, Indonesian semantic segmentation, music timing/snapshot validation, bounded filtergraph/portrait output, safe text margins, effect validation, per-request consent/provider behavior, five-quote schema/similarity, malformed output, regeneration/favorites, assets, jobs, review, and additive schema/data preservation. AI provider and FFmpeg job execution are mocked.
- `test_asset_library.py`: sanitized Pexels result parsing and unsafe URL rejection, local duration filtering without unsupported API params, mocked search/rate-limit response, provider favorites, local audio upload/hash dedupe/metadata/filter, Mood shared asset attach/detach/delete guards/attribution, mocked Pexels import registration/hash reuse/failure/retry/cancel/non-overwrite, and source compatibility. Test file added for V2.7; **not run**.
- `test_subtitles.py`: SRT/VTT parsing/export/clamping/overlap, word grouping/Gemini annotations, explicit reviewed text/timing alignment, punctuation and silence gaps, word clipping across scene cuts, Word Pop rejection without timing, translation ID validation/fingerprints, stale output-track rejection, mocked OpenAI/Gemini requests, and interrupted-job audio cleanup. **Not run**.
- `test_batch_studio.py`: batch item limit, sequential child scheduling, pause/resume/reorder/remove, retry, Mood quote cloning without generation, individual review state, restart recovery, and guards against standalone render cancel/retry. Added for V2.9; **not run**. Uses synthetic DB/source rows and mocked disk space; no FFmpeg, provider, media probe, or browser.
- `lib/mood-timeline.test.mjs`: timeline pointer mapping/snapping, non-ripple segment moves/resizes, split/merge/duplicate/reset, Indonesian semantic split rules, music offset/trim/loop span, and serialized draft-save ordering/recovery.
- `lib/youtube-clip.test.mjs`: reported watch/short URL normalization despite `si`, strict host rejection, app-route 404 diagnosis, timestamp formatting/parsing, known/unknown duration range validation, and specific IFrame unavailable/embed/API error messages.
- `lib/clip-timeline.test.mjs`: output/source seek mapping, reorder, subtitle clipping/repetition, split/duplicate/delete, cut-range ripple across scenes, minimum-fragment rejection, duration/audio alignment, and bounded undo/redo plus draft JSON round-trip.
- `lib/clip-editor-state.test.mjs`: saved/unsaved/saving/failed snapshot status and render-required/outdated derivation. Added for V2.10; **not run**. No DOM/browser test framework exists in frontend dependencies.
- `lib/word-pop.test.mjs`: punctuation reconstruction, Indonesian/English words, silence gaps, current-word lookup, and rejection of absent/unreviewed/mismatched/overlapping/out-of-cue timing. Added for V2.12; **not run**.
- `test_youtube.py`: DPAPI encrypt/decrypt round-trip; state expiration/one-use, per-attempt cookie separation, exact authorization/token-exchange redirect URI, `select_account`, structured callback errors, granted scopes, mocked channel lookup, encrypted-storage failure/no-account persistence, legacy authorization/default/publication-snapshot migration, account status/disconnect, per-account drafts/defaults, multi-destination metadata/results/identity snapshots, and queued cancellation; expired refresh token; approval/fingerprint/format/aspect/duration gate; resumable acknowledgement after simulated connection loss; retry offset recovery; duplicate prevention; unknown session expiry fails closed.
- `test_youtube_analytics.py`: mocked official report parsing, separate Views/Engaged Views, channel-vs-attributed filters, cache reuse, previous-period comparison, video detail, retention mapping, structured scope failure, invalid date and malformed-response rejection. No live Google request.
- `test_platform_publishing.py`: separate social metadata/manual-export records, actual OAuth scopes, legacy authorization/default migration, account-specific drafts/defaults, multi-destination outcomes and disconnect cancellation, provider identity match/mismatch, mocked TikTok Inbox transfer and creator-action/Published distinction, mocked Instagram resumable container/upload/publish confirmation, session-secret stripping, interrupted-transfer recovery, duplicate-risk gate, and provider reconciliation. No provider request or media upload; **not run**.
- `lib/youtube-oauth.test.mjs`: success/cancel/error notification styling and destructive styling for structured OAuth failures, including unknown failure codes.
- `test_gemini_live.py`: opt-in, exactly one actual Gemini request using synthetic timestamped text only; requires a configured Free Tier key and does not send media.
- `run_real_pipeline.py`: opt-in actual local API/worker/render test using an owned/licensed video and installed FFmpeg/ffprobe/Whisper/Ollama. Required `--video`, `--output-dir`; optional `--long-video`, `--timeout`. It exercises local pipeline failures/retry, renders, cancellation, and optional long-source handling. It is not run by the default scripts.
- `run_quick_clip_e2e.py`: opt-in real-media Quick Clip API/worker/FFmpeg test. It points to an existing source, uses isolated DB/output roots, disables Whisper/Ollama/cloud configuration, leaves source untouched, and reports rendered duration/codecs, elapsed time, sampled process-tree RSS and system CPU. Accepts `--video`, `--start`, `--end`, `--resolution`, and `--output-dir`.
- `run_mood_render_e2e.py`: local synthetic FFmpeg E2E for legacy backgrounds/audio plus Ken Burns/color/overlay video and pan/still-image cases, silent AAC, Unicode text/ASS animation, music offset/mute/trim/fade, progress, codecs/resolution/duration. It makes no AI/network calls and uses no user media. V2.4 cases were added but not executed.

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
| V2.4 source checks | Frontend helper tests, backend regression assertions, and offset/mute synthetic-render cases added; **none run** in this checkout. No typecheck/build/server/browser/FFmpeg validation performed. |
| V2.5 YouTube Clip source checks | Backend parser/metadata/local-source tests and frontend timestamp/player-error tests added; **none run**. No Data API key, browser/iframe check, server, build, network call, or media runtime was used. |
| V2.5.1 segment import source checks | URL/partial-range/adapter/cleanup/cancel/Quick Clip regression code added; **not run**. No yt-dlp, server, build, tests, FFmpeg, browser automation, or external media retrieval used for this revision. |
| V2.6 Clip Editor/Cut Range source checks | Multi-Scene persistence/render/subtitle mapping, FFmpeg filtergraph assertions, ripple range operations, timebase mapping, duration/audio alignment and bounded history tests added; **not run**. No server, build, tests, FFmpeg, browser automation, or runtime checks performed for this revision. |
| Quick Clip subtitle source checks | Manual segment persistence, trim-only STT, consent gates, and clip-relative ASS timing regression code added; **not run**. No server, build, tests, FFmpeg, browser automation, or live OpenAI request used for this revision. |
| Step 3 live preview visual check | Not run for V2.3 two-column UI revision per workspace instruction. Thumbnail cache is covered by Mood API test; V2.4 timeline/audio changes also need manual QA below |
| V2.6 browser/render QA | Not run. Browser seek latency, cut-range selection, autosave/reload, output sync, presets and approval gates require user-run manual validation. |
| V2.7 Asset Library source checks | Mocked Pexels/API/upload/Mood reuse test added; **not run**. No Pexels live request, typecheck/build/server/browser/FFmpeg check or runtime validation performed. |
| V2.8 subtitle/translation source checks | Parser/provider/stale-track assertions added; **not run**. No typecheck/build/server/browser/provider request/FFmpeg/runtime validation performed. |
| V2.9 Batch Creator source checks | Batch persistence/scheduling/control/recovery guards added; **not run**. No tests, typecheck/build/server/browser/FFmpeg/runtime validation performed. |
| V2.10 editor workspace source checks | Draft/render status assertions added; **not run**. No typecheck/build/server/browser automation/runtime check performed. Sticky layout, controls, responsive behavior and playback need user manual QA. |
| V2.11 YouTube Publishing Studio source checks | Mocked Clip/Mood uploads, source-less worker, schedule reconciliation, channel verification, metadata/templates/events, thumbnail confirmation/failure assertions added; **not run**. No typecheck/build/server/browser/FFmpeg/OAuth/live YouTube action performed. |
| V3.2 social publishing source checks | Mocked TikTok Inbox/Instagram resumable jobs, status distinctions, recovery, and duplicate-risk assertions added; **not run**. No test, typecheck/build, server, browser, provider request, OAuth, or upload performed. Live account scopes/app review/eligibility unavailable. |
| V3.2.1 multi-account source checks | Mocked migration/backfill, OAuth account selection/state isolation, defaults, per-account metadata, independent fan-out, identity checks, and disconnect cancellation assertions added; **not run**. No test, typecheck/build, server, browser, provider request, OAuth, or upload performed. |
| V2.12 Word Pop source checks | Reviewed alignment, manual timing, scene mapping, ASS animation/long-word/resolution and missing-timing guards added; **not run**. No tests, typecheck/build/server/browser/FFmpeg validation performed. |
| V2.3 cinematic/segmentation additions | Test code updated; **not run**. No V2.3 build, runtime, browser, or FFmpeg validation was performed in this checkout |

### V3.2 social publishing manual QA — not run

1. Without provider credentials, open Connected Accounts and Publishing Studio. Confirm both providers report manual export, manual MP4 download works for a current approved output, and no upload job is created.
2. With a test TikTok app, verify OAuth requests only `user.info.basic` and `video.upload`. Confirm missing scopes hide Inbox action; `video.publish` and Direct Post remain absent. Queue an approved, rights-confirmed test video and verify independent job progress and provider status.
3. Confirm TikTok `SEND_TO_USER_INBOX` displays creator action required, never Published. Complete post in TikTok; only provider `PUBLISH_COMPLETE` may change local status to Published. Test provider `FAILED`, expired upload URL, transfer interruption, and status-poll errors.
4. With reviewed Meta app and eligible Instagram Professional account linked to a Page, verify Facebook Login for Business scopes and method. Test container creation, local resumable bytes, processing, `media_publish`, and provider-confirmed Published. `FINISHED` container status alone must not show Published. Confirm Instagram Login `video_url` path is not used.
5. Test denied scopes, unreviewed app, missing Page authorization, ineligible account, invalid media properties, expired token refresh, and provider 401/429/5xx. Manual export must remain available; errors must not expose tokens or provider secrets.
6. Interrupt before initialization, during transfer, after container creation, and after publish request. Confirm startup marks ambiguous work `needs_reconciliation`; reconcile provider state before retry. Unknown result with no operation ID must require explicit duplicate-risk confirmation. No automatic duplicate transfer.
7. Cancel queued work and active transfer. Queued cancel should not contact provider; active cancel must retain honest uncertain status when bytes may have arrived. Change/review the output after queueing and confirm worker fingerprint gate blocks upload.
8. Review history for separate TikTok/Instagram/manual rows, safe status/progress, independent failures, retry confirmations, event history, and no session/token fields. Repeat manual export after output fingerprint changes; stale download must return 409.

Live provider steps require user-supplied test apps/accounts and authorization. They were not run in this checkout.

### V3.2.1 multi-account manual QA — not run

1. Connect two Google identities using **Hubungkan Channel Lain**. Confirm each account gets a distinct OAuth state cookie and existing channel cards remain. A grant returning multiple YouTube channels must fail closed.
2. Set and change one default per provider. Save different YouTube titles/declarations and TikTok/Instagram captions per destination; reload Publishing Studio and confirm drafts remain isolated.
3. Select multiple destinations for one approved output. Review each destination's metadata and declarations, submit once, and confirm separate queue/history rows. Force one invalid/disconnected destination and verify successful targets remain queued while failed targets report their own errors.
4. Disconnect an account with queued work. Confirm only that account's queued job is cancelled, history remains, other destinations keep running, and shared provider authorization remains active while another account uses it.
5. Change a stored target identity/authorization in a mocked worker case and confirm provider preflight blocks transfer before bytes are sent. Keep YouTube Analytics scoped to one selected channel.

These checks use no live provider credentials unless separately authorized. They were not run in this checkout.

Other not-run cases recorded in the repository audit: 10-minute varied-content source, OpenAI live call, Gemini 3.6 live call, actual Gemini 429 response, human review of every subtitle, and 1080p across varied source videos. A prior five-minute long-source fixture repeated a 2.5-minute speech segment twice, so semantic variety at that duration remains unverified.

### Word Pop manual Preview-vs-MP4 checklist

1. Use owned/synthetic footage with clear Indonesian/English speech, punctuation, silence gaps, one long word, and at least two scene cuts. Start with legacy sentence, phrase, karaoke, and Word modes to confirm they still render unchanged.
2. Generate Gemini word timestamps only after cloud-audio consent, or add a manual cue and enter each word/time. Confirm segment-only Whisper/OpenAI results show no invented word timing. Seek to words and check cue-relative/source/output timebase labels.
3. Test punctuation attachment (`I'm`, `(kata),`, `rumah!`), silence gaps, long words, missing start/end, overlap, cue-bound violations, and text mismatch. Alignment must stay unreviewed until explicit review; cue text/time edits and duplicated cues must mark it unreviewed while preserving editable word data.
4. Select Word Pop only after all visible cues are reviewed. Verify the appearance preset does not change subtitle type; test Pop, Scale, Fade, None, intensity/duration, safe margins, font/size/color/outline, and reduced-motion browser setting. Translation/bilingual selection must remain unavailable.
5. Save, reload, and preview at every word boundary, silence gap, repeated scene, and word crossing a cut. Render 720p and 1080p; compare Preview with final MP4 for word onset/offset, punctuation, placement, animation, long-word fit, cut mapping, and silence. Allow up to one output frame plus ASS 10 ms timestamp quantization.
6. Try to render with missing, mismatched, unreviewed, overlapping, or sub-10 ms ASS timing. Render must fail closed, preserve draft/previous MP4, and leave approval invalidated only according to existing edit/render rules. Then restore valid timing and confirm review/publishing gates still require new render approval.

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

### Quick Clip subtitles manual QA — not run

1. Open a silent Quick Clip. Confirm mode defaults Off; switch to Manual, add a stable-ID segment, edit text/start/end, save, reload editor, and confirm values persist. Manual mode must not ask for transcript or STT setup.
2. Use video controls to play/pause and seek across caption boundaries. Confirm source preview overlay follows clip-relative times. Change trim, save, and verify segment times remain relative to original candidate start.
3. For legacy `/subtitles/auto-generate` compatibility, confirm provider list reflects configured options only. For OpenAI, deny confirmation and verify no audio request; accept and confirm only selected trim/scene is sent. Local Whisper needs configured binary/model.
4. Try no-audio and silent/no-speech input. Expect clear transcription error while Manual remains usable. Confirm output mute/settings do not replace or erase source file used for STT.
5. Render and inspect MP4 subtitle in/out timing after trim, text corrections, font/size/color/position/style. Reopen and confirm saved segments; rerender/review/publish should use existing shared paths. Check AI Smart Clip, Mood Quotes, Review, and Publishing regression separately.

### V2.8 subtitles and translation manual QA — not run

1. Confirm editor offers only configured transcription providers. Local Whisper requires no consent and keeps audio local. Deny cloud audio confirmation and verify no job/upload; accept once and confirm queued job status/progress/cancel/retry. Retry cloud work only after fresh confirmation.
2. Test Gemini on a short permitted source: inspect word/speaker cues and human-correct boundaries. Test the 30-minute rejection without uploading. Test OpenAI: transcript text appears without timed cues; no generated timestamps. Copy text, add cues manually, and verify timing stays user-entered.
3. Edit scenes/order/trim and transcribe again; confirm audio follows output composition order and track remains a separate draft. Verify temporary local audio is removed on success/failure/cancel. Activate a stale output-time track and confirm render blocks; inactive stale drafts should remain reviewable/removable.
4. Translate current cues after confirmation; deny once and confirm no job. Confirm only text is shared, original track remains unchanged, IDs map exactly, and translation is saved separately. Edit/move/add/delete source cues and verify prior translation becomes outdated and translated/bilingual render is blocked.
5. Import UTF-8 and UTF-16 SRT/VTT, including multiline, overlaps, invalid timestamps, over-duration cues, >500 cues, and >2 MiB files. Confirm duration prompt/clamp behavior, warnings, inactive draft state, and SRT/VTT export round trips. Check missing track ID returns 404 and stale track export returns 409.
6. Exercise cue add/edit/split/merge/duplicate/delete, seek, output-time mapping, drag/resize timeline, undo/redo, autosave/reload and selected-track persistence. Check transcript-only cues are never rendered as captions without manual timing.
7. Compare preview and FFmpeg for sentence/phrase/word/karaoke, translated/bilingual display, eight presets, font/colors/outline/shadow/background, alignment/animation/safe margin/width. Check reduced-motion browser setting and subtitle contrast/readability.
8. Re-run existing Quick Clip, AI Smart Clip, Multi-Scene, review/approval, YouTube publication, and legacy synchronous `/subtitles/auto-generate` workflows. Confirm no database migration and old edit JSON remains readable.

### V2.6 Multi-Scene and Cut Range manual QA — not run

1. Open a Quick Clip. Confirm Single Scene remains default and trim/render still work. Switch to Multi-Scene, add source ranges, reorder by drag/drop, trim handles and numeric source times, duplicate/delete/split, tag Hook/Ending, and confirm source timestamps stay fixed while output positions recalculate.
2. Scrub/play browser preview across multiple scenes and a repeated source range. Confirm playhead skips unselected footage and follows reorder without FFmpeg preview render. Compare browser seek accuracy/latency with source timestamps.
3. Mark In/Out from playhead and set values numerically. Drag-select a Cut Range on ruler, then test Delete key and **Hapus Bagian** across one scene, scene boundaries and reordered scenes. Confirm all retained fragments stay at least 0.5 s, later scenes ripple left, and source file remains unchanged.
4. Test Split at playhead, scene trim/reorder, range delete, then Undo/Redo repeatedly. Check `Ctrl+Z`, `Ctrl+Y`, `Ctrl+Shift+Z`, `I`, `O`, `S`, and `Delete` while focus is outside text fields. Confirm typing in title/subtitle/input controls is never intercepted. Exercise more than 40 operations and confirm editor remains bounded.
5. Save, wait for autosave, reload editor, and confirm scene order/ranges, roles, cut result, subtitle timebase, audio/title/export values, and selected single/multi mode restore. Change edits after a completed approval and confirm approval/fingerprint invalidates; old MP4 remains downloadable as stale until replacement succeeds.
6. Add/trim source-time captions, including one crossing a scene boundary. Reorder, duplicate, split, and ripple-delete. Confirm cut captions disappear, boundary captions clip, repeated source captions repeat once per intentional scene, manual wording persists, and subtitle timing moves with output order. Try selected-scene STT only through legacy endpoint with local mock/runtime or explicit OpenAI audio consent.
7. Render a synthetic or permitted source with scenes at non-zero and reversed source times, audio and silent input. Check exact scene order, duration, 9:16 dimensions, H.264/AAC, frame-rate choice, audio/video sync at each hard cut, silence/padding behavior, fades/normalization/limiter, captions and title. Inspect output near cut boundaries for clicks/black frames. Confirm failed/cancelled render preserves previous output and removes partial output.
8. Exercise 720p/1080p, 30/60 FPS, Smaller/Balanced/High quality, title safe area/fades, audio mute/volume/fades/normalization. Compare AMF and x264 fallback only on compatible local FFmpeg/driver; no quality/performance result is claimed until measured.
9. Re-run single-scene Quick Clip, AI Smart Clip, YouTube Clip local fallback, AI Mood Quotes, review/approval, Clip Library and mocked YouTube publishing regression manually. No automatic publish should occur.

### V2.10 Clip Editor workspace manual QA — not run

1. At **1920×1080**, open Quick Clip, AI Smart Clip, and YouTube Clip output editors. Confirm same two-column workspace, readable controls, 9:16 preview, compact title/status/actions, and no duplicate hidden video preview. Scroll long controls; preview should remain below global topbar and stop at workspace end before timeline.
2. At **1366×768**, inspect sticky offset and preview height. Confirm preview does not overlap topbar/actions, portrait aspect stays intact, controls remain usable, and browser page has no horizontal overflow.
3. At tablet widths (try **1024×768** and **768×1024**), confirm preview stacks above controls, is not sticky, fits width, and can collapse/expand. Scroll subtitle/audio/export panels without clipping.
4. At mobile widths (try **390×844** and **360×640**), confirm no page-level horizontal overflow; only timeline scrolls horizontally. Check preview collapse, fullscreen exit, wrapped save/render buttons, 38px preview controls, and bottom navigation clearance.
5. With an editable subtitle, play and seek. Change text, color, font, size, weight, alignment, position, outline, background, preset, and title overlay while playing. Confirm browser overlay updates immediately, video element/playback/playhead do not reset, and no FFmpeg job starts.
6. Change crop X/Y during playback. Confirm crop updates without remount/seek jump for portrait and landscape sources. Check captions at several timeline positions and verify subtitle row/timeline selection seeks preview. Confirm preview-only mute does not change saved output mute setting.
7. Test long subtitle lists (100+ cues) and long timeline. Scroll/edit near bottom while preview remains usable on desktop. Zoom, horizontal-scroll, seek, select/reorder/trim/split scenes, select subtitle cue, Cut Range, ripple delete, Undo/Redo; collapse/expand timeline and verify edit/playhead state survives.
8. Test source switch, rendered MP4 switch, stale render label/download, unavailable source/render fallback, fullscreen, Replay, pause, end-of-timeline, and missing audio. Browser composition preview must be labeled distinct from final FFmpeg output.
9. Verify save state transitions: edit → Unsaved changes; autosave → Saving → Saved only after successful PATCH; force a failed save and verify Save failed plus error; recover and confirm status clears. Edit a rendered clip and confirm Render perlu diperbarui; render and verify editor state remains, then approval actions obey existing fingerprint gate.
10. Recheck trim/crop/subtitle accordions, defaults, validations, STT/translation/import/export, audio enhancement, title, export settings, batch return, review/approval, download/publish eligibility. Open Mood Quotes and confirm its existing workspace remains unchanged.
11. **Light theme:** check panel, controls, status contrast, focus outline, disabled state, dialogs, and timeline. **Dark theme:** unsupported in current app; do not treat as passed. Add app-wide theme support separately before dark-mode validation.

Automated state test command (not run): `node --test lib/clip-editor-state.test.mjs`. No visual or browser test runner is installed; all viewport, playback, browser media, and workflow checks above are manual.

### V2.11 YouTube Publishing Studio manual QA — not run

1. Open YouTube Studio navigation with no connected account; connect one OAuth grant exposing one channel, verify channel identity, and ensure no token data appears in UI/API. Confirm a multi-channel grant fails closed.
2. Open completed Clip and Mood outputs with unapproved, stale-fingerprint, active-render, missing-file, landscape, >180-second, and valid approved states. Confirm only valid approved square/portrait output can queue; approve each batch output independently.
3. Save metadata drafts/templates and reload. Confirm editing/saving never enqueues uploads. Validate title/description byte limits, tags/hashtags, category/language, and both required audience declarations.
4. Choose a future `datetime-local` time in a non-UTC timezone. Confirm summary/calendar show local time, backend stores UTC, scheduled upload requires Private, and naïve/past/public schedule requests fail without queueing.
5. Confirm upload requires final explicit checkbox and queue is per output. Verify Clip and Mood use same uploader, while Mood creates no fake source/clip/job rows. Exercise queued cancel, retry/session resume, uncertain-outcome reconciliation, account expiry, and backend restart without duplicate upload.
6. Upload valid local JPEG/PNG thumbnail, reject malformed/oversize/small/portrait files, confirm changed render invalidates old thumbnail, then apply to known video. Treat only confirmed YouTube response as success; check API failure is visible and retryable.
7. Inspect Queue, History, Calendar, and per-publication events for pending/uploading/processing/scheduled/published/failed/reconciliation states. Confirm YouTube owns scheduled publication if local app stops.

No V2.11 tests, typecheck/build, server, browser, FFmpeg, OAuth, upload, scheduling, or thumbnail call ran for this checkout. Only static source review and `git diff --check` are permitted for this revision.

### Connected Accounts OAuth fix manual QA — not run

1. With credentials absent, confirm the page says configuration is required, offers **Lihat Panduan Setup**, and never claims a channel is connected. Open/close all six accordion steps by mouse and keyboard.
2. Confirm backend reports `youtube.upload`, `youtube.readonly`, and `yt-analytics.readonly`; new consent asks for all three. `youtube.upload` alone must fail with `oauth_scope_insufficient`, before channel lookup or account persistence. No Google Cloud steps receive automatic completion badges.
3. With valid callback config, confirm Step 4 shows the exact backend-returned callback in a read-only field and copy button. Compare it byte-for-byte with Google Cloud's Authorized redirect URI. With invalid/unavailable callback, confirm no guessed URL is shown and troubleshooting points to backend `YOUTUBE_REDIRECT_URI`.
4. Confirm Step 5's copy example contains placeholders only, names `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, and only includes `YOUTUBE_REDIRECT_URI` when backend returns a valid callback. No secret-entry form, secret value, or OAuth token appears in browser UI/API.
5. With credentials present but no accounts, confirm **Hubungkan YouTube** is enabled only when callback/start URL is valid; otherwise disabled styling has readable contrast and visible reason. Guide remains accessible. After changing backend environment, reload backend and use **Cek ulang status** to read current state.
6. Complete OAuth manually after granting requested scopes; confirm a channel card appears only after backend channel lookup and encrypted persistence succeed. Try state mismatch/expiry, code exchange rejection, missing channel, API permission failure, missing refresh token, DPAPI/SQLite storage failure, and unexpected callback exception; each must return a safe code, show red destructive feedback, expose no code/state/cookie/token/secret, and create no new connected row. Verify channel actions' disabled reasons and mobile layout.

No server, build, test, browser automation, OAuth action, or live YouTube action was run for this fix. User performs manual QA.

### YouTube Analytics V3.1 manual QA — not run

1. In Google Cloud, enable YouTube Data API v3 and YouTube Analytics API. Connect a test channel through existing OAuth; verify backend reports actual grants only. Confirm `youtube.readonly` and `youtube.upload` remain after incremental Analytics consent, `yt-analytics.readonly` appears only after Google grants it, and consent cannot switch channel ID. Try a missing/narrow scope response and confirm stored valid credentials remain unchanged. Do not use monetary scopes.
2. Open Connected Accounts and use **Aktifkan Analytics** for one connected channel. Check consent callback outcome and refreshed account card. Legacy rows with unknown scope must require reconnect; publishing and Analytics must not infer permission from previously requested scopes.
3. Open Publishing Studio → Analytics. Compare Channel and Klipnara scope: Channel is channel-wide; Klipnara contains only video IDs linked to successful local publication records. Confirm Views and Engaged Views remain distinct, titles link to official YouTube pages, old publications display as unattributed, and no arbitrary channel selector exists.
4. Check default last 28 complete UTC days, maximum inclusive 366-day range, future/current date rejection, actual report coverage, equal-length previous period, zero/empty response and delayed coverage. Verify charts, weighted rate comparisons, CSV formula escaping, and local download.
5. Open an attributed video detail and retention. Confirm detail uses its stored publication ID, retention uses one video per query, time positions scale to render duration, and an empty retention report/error does not become zero retention. Rule insights must show timeframe/sample count, require at least five videos per compared group, and make no causal claims.
6. Force refresh once, then normal refresh within six hours; verify cache reuse. Inspect local `youtube_analytics_cache` for channel/query/coverage only, no token/media/audio. Disconnect account and confirm its cache clears while publication records remain. Test API-disabled, scope-denied, quota/rate-limit, expired OAuth, malformed-report and no-data states without exposing raw provider secrets.

No Analytics tests, typecheck/build, server, browser, OAuth, or live YouTube API request was run for this change. Only static inspection and `git diff --check` are permitted here; user owns runtime QA.

### Mood Quotes FFmpeg E2E — 24 Oct 2026

Actual FFmpeg/ffprobe runs on the local Windows workstation used only generated test patterns and sine-wave audio; AI calls/network requests/user media were zero. Each output was 4.0 seconds, 720×1280, 30 FPS, H.264/AAC and passed ffprobe.

| Case | Background/audio | Render elapsed | Output bytes | Result |
|---|---|---:|---:|---|
| Short looping background video | Synthetic H.264/AAC video + looped synthetic music, mixed audio, Unicode/segment-typewriter text | 0.67 s | 763,549 | Pass |
| Solid color | FFmpeg color source + silent AAC | 0.48 s | 17,498 | Pass |
| Gradient | Generated PPM gradient + silent AAC | 0.97 s | 29,707 | Pass |
| Still image | Synthetic PNG + silent AAC | 0.78 s | 17,125 | Pass |

These short synthetic samples validate command/media paths only. They do not measure longer user footage, subjective font/animation quality, 1080p, AMF, browser-vs-render parity, or AI text quality.

The E2E script also includes sequential Unicode text, music trim/loop/fades, offset delay, muted music, mono 44.1 kHz resampling, no-loop short music, background-only audio, zero-volume silence, corrupt/silent selected audio, output signal checks, and V2.3 synthetic motion/color/overlay cases. These new scenarios have **not been run in this checkout**; historical results above cover only their listed cases. To run manually:

```powershell
.venv\Scripts\python.exe tests\run_mood_render_e2e.py
```

Do not interpret mocked YouTube success as a real platform upload. Before account use, configure OAuth and verify one Private upload's channel, video ID, privacy, and processing status in YouTube Studio.

### Manual Mood Quotes sequence/audio/render check

0. In Clip Library, select **Edit draft** on an existing Mood Quotes row; confirm its `?id=` draft opens without increasing the project count. Use **Hapus** only on a selected duplicate and confirm the dialog removes only that draft.
1. Open an old draft without `text_mode`, `music.offset`, or `music.muted`; confirm it loads as **Single Text**, offset `0`, unmuted, with prior timing/appearance. Create a new draft; confirm **Sequential Text** default and no SQLite migration/data loss.
2. Select Indonesian quotes starting with “Terkadang,” and with comma/semicolon conjunctions. Confirm no hanging one-word opener, punctuation/text reconstruction, reasonable reading time, and warning for very long text/short duration. Edit a segment manually, press **Segmentasi ulang**, cancel confirmation and verify text/timing survive; confirm then verify only explicit reset replaces them. No AI request.
3. Choose Bahagia and Romantis moods; inspect **Direkomendasikan** vs **Preset lainnya**. Apply Happy Sunshine, Sad Night, Romantic Dream, Vintage Memories. Confirm visible effect variation. Change typography manually, apply another preset, use Undo and Reset Visual Style; quote/segments/timing/media assets/music must remain. Solid/gradient palette changes on preset apply and returns to defaults on reset.
4. Use image/video background and test all motion directions, Ken Burns, three intensities, and None. Scrub Live Preview; confirm crop has no black edges. Video thumb should remain a labeled static frame while its transform simulates motion; Preview Penuh should play actual video. Color grade, temp, vignette, grain, dark and gradient overlays should update without AI calls.
5. Change text font/weight/size/color/alignment/position/line spacing/opacity, Auto Contrast, text gradient, and segment animation. Check safe-margin warning, 720p and 1080p layouts, and narrow desktop width.
6. In Visual Timeline Editor, seek on ruler/tracks, zoom, toggle snap, drag/resize segments, and confirm neighbors do not ripple. Exercise split/merge/duplicate/reorder/reset, keyboard timing fields, selection/playhead sync, and autosave; test narrow viewport and collapse/expand panel.
7. Set nonzero music offset, drag music clip, seek before/after offset, and compare Live Preview, Preview Penuh, and rendered audio. Test trim/loop/fades/volume/mute, background audio on/off/zero, no music, and silent/corrupt selected audio. No selection, mute, or zero volume may produce silent AAC; selected active silent/corrupt audio should fail clearly. Confirm visual presets never select music or external assets.
8. Compare **Editor Live Preview → Preview Penuh → MP4 final** at same playhead/segment. Verify motion direction/speed, grading/overlay, typography, text animation/timing, crop, H.264/AAC, duration/resolution. Small CSS/libass/color/grain differences are expected; log any material mismatch.
9. Approve output, mark **Perlu revisi**, edit composition, rerender, and confirm approval fingerprint invalidates while old render stays available. Download final MP4; reopen draft and confirm visual settings, quote/assets/history, manual segments, offset/mute, and legacy Single Text persist.
10. Run existing Quick Clip, AI Smart Clip, review, and YouTube mocked regression suites separately; confirm their forms/routes/render/publishing behavior did not change. Confirm edit/preview/render never call AI.

## YouTube Clip manual QA sequence — not run

1. In **Buat Video → YouTube Clip**, paste `https://youtu.be/Zz7os_kWwnM?si=K1t7XMIZuDy10liL` and `https://www.youtube.com/watch?v=Zz7os_kWwnM`. Confirm both normalize to `Zz7os_kWwnM` and canonical watch URL. Try watch/short/youtu.be forms, `t`, `start`, `si`, malformed IDs, credentials, lookalikes, unsupported routes and overlong URL. Direct-file URL importer must reject YouTube hosts before DNS/network.
2. Verify metadata route and API base URL. Wrong path should produce app-route 404, GET should produce 405; neither establishes video availability. On route 404, UI should still permit validated preview and local-file fallback, with provenance limitation clearly stated.
3. Test no `YOUTUBE_DATA_API_KEY`: no invented metadata; iframe still attempts playback. With a restricted Data API key, verify metadata stays transient. Test empty result, quota/API denial, timeout and network failure; endpoint should return metadata status without blocking preview.
4. Confirm `GET /api/youtube-clips/import-capabilities` reports unavailable while `YOUTUBE_IMPORT_ENABLED` is unset/`0`. Step 3 must show reason and keep Source Library/upload available. To test a real adapter, enable only after installing trusted yt-dlp plus FFmpeg/ffprobe, and use a video and retrieval method you have verified are permitted by applicable rights and platform terms. The rights checkbox is not permission verification. Do not use cookies, browser profile, login, DRM bypass, or access-control workaround.
5. With adapter opted in, select Start/End and confirm request includes exact interval. Test supported content only: expect Preparing → Importing → Processing → Ready, validated managed source, automatic Quick Clip request, and original timestamps with `source_association=auto_imported`. Existing endpoint queues render before navigating to Clip Editor; verify editor/review/publishing use existing path. Imported source remains in library after clip deletion.
6. Cancel during queue/download; verify job cancellation, process termination, temp cleanup, and Retry creates a new job after fresh rights confirmation. Simulate unavailable binary, unsupported/private/restricted source only if safe to do so; verify specific reason and local fallback. Confirm oversized output, invalid MP4, bad duration, and low disk fail without creating source rows or overwriting existing files.
7. Capture Start/End from player; test `MM:SS`, `HH:MM:SS`, invalid/order/range-over-duration values, replay, pause at End, reset and step navigation. If duration is unknown, UI must not claim bounds checked. Compare imported segment duration/content manually; section transfer may include extra bytes or fail. Do not expect every source to import.
8. Test local fallback with a permitted Source Library file and separately uploaded MP4/MOV. Choose End beyond local duration; backend ffprobe must reject. Confirm local fallback provenance is `user_selected`, Klipnara does not claim source matches preview, and old sources/drafts remain untouched. Verify Clip Editor, review fingerprint, Video Library, and existing publishing controls; do not perform real YouTube upload.

## V2.7 Asset Library manual QA — not run

1. Start local backend/frontend only when authorized. With `PEXELS_API_KEY` unset, confirm local Asset Library uploads, Mood reuse, and rendering remain available; Stock Footage shows actionable setup error only after search. Confirm `/api/settings` exposes configured boolean, never key value.
2. Configure a test Pexels key in backend `.env` only after approval. Search with blank/nonblank query, quick searches, orientation, size, min/max duration, pagination, no results, and provider rate limit. Confirm requests only target official API, query goes to backend, and UI does not trigger search until a user submits text.
3. Preview Pexels thumbnail and selected MP4 qualities; open Pexels page/creator/license links. Favorite/unfavorite, reload, and verify metadata persists locally. Test missing key, invalid key, timeout, 429, malformed response, and no files; no fallback or key exposure.
4. Import one explicitly selected MP4. Confirm progress/status, 512 MiB/1 GiB free-space caps, cancel, failure/retry, restart recovery, and no overwrite of an existing destination. Verify one normal Source row and one library row, no transcript/AI/Quick Clip job, creator/license metadata and attribution, and reuse avoids a second download.
5. Upload same audio twice and confirm hash dedupe; also upload valid image/video, then test empty/wrong extension/wrong stream/oversize/bad file. Confirm library metadata/favorites/mood-tag filters, storage accounting, playback, and user-edited license/source/attribution fields.
6. Attach shared image/video/music to two Mood drafts and reuse imported footage in Quick Clip. Confirm no duplicate file, source path/hash hidden from API responses, duration/trim validation, preview/render reads shared path, and detach/draft-delete preserve shared media.
7. Attempt deleting media while Mood references or source jobs are active; expect 409 and unchanged bytes. Detach all references, delete selected asset, and confirm only expected managed file/source/clip outputs disappear. Test stale database rows with missing file without affecting neighboring files.
8. Reopen legacy Mood drafts and confirm existing project-scoped assets still work and were not migrated/deleted. Re-run Quick Clip, AI Smart Clip, YouTube Clip fallback, Mood render/review, Clip Library, and publishing regression after authorization; no live Pexels request required for local workflows.

## Troubleshooting

| Symptom | Check / action |
|---|---|
| Frontend says backend offline | Start Uvicorn at `127.0.0.1:8000`; frontend default `NEXT_PUBLIC_API_URL` points there |
| YouTube Clip says metadata route HTTP 404 | App route mismatch, not proof video missing. Check `POST /api/youtube-clips/metadata`, backend is V2.7.0 or newer, and `NEXT_PUBLIC_API_URL` is backend root or has exactly one `/api`. Preview/local fallback remain available; provenance may be omitted by legacy fallback |
| Pexels search says key missing | Set `PEXELS_API_KEY` in backend `.env` only, restart backend, and check `/api/settings` configured flag. Never use `NEXT_PUBLIC_PEXELS_API_KEY` or expose key in browser. Local library/reuse still work without it |
| Pexels search/import returns 401/403/429/504 | Check key/account/provider availability, rate limit, network and provider status. App does not retry/switch provider automatically; wait after 429. No live API check is implied by mocked tests |
| Pexels import stalls/fails | Check persisted import status, network, free space (minimum 1 GiB), selected MP4 availability and 512 MiB cap. Cancel then retry failed/cancelled job; one import runs at a time. Incompatible CDN redirect/host/content type fails closed |
| Asset delete blocked with Mood usage | Detach that asset from every listed Mood draft first. Active video jobs also block source deletion; failed/missing file records can be removed only inside managed roots |
| Local Asset Library preview/file missing | Check source root and `SOURCE_DIR/library-assets`; video is stored once as a normal Source, images/audio under shared library folder. Do not delete files manually while DB rows or Mood drafts reference them |
| Automatic YouTube import is unavailable | Default is disabled. Set `YOUTUBE_IMPORT_ENABLED=1`, install trusted external yt-dlp and verify `YT_DLP_PATH`, FFmpeg and ffprobe. Restart backend after `.env` change. Only enable/use when acquisition method and content use are permitted |
| yt-dlp cannot import selected video | Adapter is best-effort, not official YouTube tooling. Source may be private, restricted, unavailable, unsupported, or blocked; partial section requests can fail or transfer extra bytes. Do not add cookies/login or bypass restrictions. Use permitted Source Library/upload fallback |
| YouTube import stalls/fails disk validation | Check free space (at least 1 GiB), configured `CLIPPER_MAX_UPLOAD_BYTES` (default 2 GiB), selected interval (up to 4 hours), import status/message, and yt-dlp/FFmpeg/ffprobe paths. Cancel then retry; failed temp files are removed |
| Upload/render says ffprobe/FFmpeg missing | Check PATH or set `FFPROBE_PATH`/`FFMPEG_PATH`; verify `ffmpeg -encoders` includes libx264 and `ffmpeg -filters` includes ASS/libass |
| 1080p clip render fails | Source Clip renderer uses AMF when FFmpeg lists it and x264 fallback when absent; a listed but driver-incompatible AMF encoder may still fail. Check AMD driver/FFmpeg AMF support or select 720p. Mood Quotes uses its own AMF/x264 selection |
| Multi-Scene draft rejected | Check scene IDs are unique, order is contiguous from zero, each source interval is inside source duration and at least 0.5 s, scene count ≤12, and total Multi-Scene duration ≤180 s |
| Cut Range delete rejected | Timeline selection must have positive output duration; retained fragments must each be ≥0.5 s and leave at least one scene. Expand cut or adjust selection rather than relying on silent rounding |
| Multi-Scene preview stalls at cut | Browser seeks are asynchronous and may lag; wait for seek, verify source range/output playhead, and use final render for exact inspection |
| “Keep at least 1 GiB free” | Free space on data, work and selected source/output roots; this is hardcoded `MIN_FREE_BYTES` |
| whisper.cpp/model missing | Set `WHISPER_CPP_PATH` and `WHISPER_MODEL_PATH`; confirm `.env` is loaded with `--env-file .env` |
| Manual subtitle option unavailable | Manual mode no longer needs a transcript; reload matching frontend/backend revision. Check `subtitle_mode` and clip-owned `subtitle_segments` in clip edit response |
| Subtitle Auto Generate says no audio/no speech | Source without audio cannot auto-transcribe; silent/no-speech range returns no segments. Use Manual or select a segment containing speech |
| Local subtitle STT unavailable | Optional local mode needs whisper.cpp binary plus valid `WHISPER_MODEL_PATH`; Quick Clip Manual does not need either |
| OpenAI subtitle STT rejected | Set `OPENAI_API_KEY`; confirm audio-sharing prompt for each request. Selected audio limit is 25 MiB; shorten clip or select configured local STT |
| Subtitle provider option missing | Configure backend `OPENAI_API_KEY` or `GEMINI_API_KEY`, or valid local Whisper binary/model; restart backend and reload editor. Keys remain backend-only |
| Gemini subtitle transcription rejected | Composition limit is 30 minutes and uploaded audio must fit provider file cap. Shorten composition; check key/access/quota. No automatic retry/fallback |
| OpenAI transcript has no cues | Expected for V2.8 `gpt-transcribe`: text only, no timestamps. Copy transcript and create/edit cue timing manually; legacy sync route remains separate |
| Subtitle track marked stale | Output-time tracks bind to source hash and scene signature. Regenerate/import/remap for current composition; source-time tracks map through selected scenes |
| Translation marked outdated | Original cue ID/text/timing changed after translation. Translate current cues again; original track remains unchanged |
| SRT/VTT import asks to clamp | One or more cues exceed current output duration. Confirm to clamp/drop out-of-range cues or cancel and edit file; imported tracks remain drafts |
| Transcript seems stale after model/language change | Cache includes transcript config/language/model binary+model file fingerprint; settings change or rerun generation to regenerate |
| Local generation reports Ollama unavailable/model missing | Start Ollama Desktop/`ollama serve`; `ollama pull qwen2.5:1.5b` or set `OLLAMA_MODEL`; there is no cloud fallback |
| Ollama prompt too large | Code measures actual prompt with one-token request and splits at timestamped boundaries; a single unsplittable oversized segment fails explicitly |
| OpenAI/Gemini job rejected | Configure backend API key; choose provider and tick per-job consent. Cloud receives transcript-only prompt. Gemini 429 is not auto-retried/upgraded |
| Approval reset after code update | New migration resets old `approved` records lacking `reviewed_render_sha256`; inspect final render and approve once |
| YouTube `redirect_uri_mismatch` | On **Akun → Lihat Panduan Setup → Step 4**, copy **Callback URL Klipnara** and paste it exactly into the Google Cloud Web Client's Authorized redirect URIs. Host (`localhost` vs `127.0.0.1`), port, scheme, and path must match. If no URL is shown, inspect backend `YOUTUBE_REDIRECT_URI` and `GET /api/youtube/config`; do not guess. |
| OAuth setup warning remains after adding credentials | Confirm `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET` are in the backend environment (not frontend), check process environment precedence over `backend/.env`, then reload backend and select **Cek ulang status**. The warning reports backend-observed state only. |
| Callback URL missing or callback configuration alert shown | `GET /api/youtube/config` returns the effective URI and safe `redirect_error`. Correct `YOUTUBE_REDIRECT_URI` to a loopback URI with explicit port and `/api/youtube/oauth/callback`, then reload backend. UI intentionally hides invalid callback values. |
| OAuth callback reports `oauth_state_invalid` | Start connection again from Connected Accounts. The callback requires both the one-use, unexpired state in SQLite and matching HttpOnly/SameSite=Lax browser cookie. Use same callback hostname (`localhost` vs `127.0.0.1`); do not disable state or cookie checks. HTTP loopback uses a non-Secure cookie; HTTPS uses Secure. |
| OAuth reports `oauth_redirect_uri_mismatch` | Compare the exact callback URI returned by `GET /api/youtube/config` with the Web Client's Authorized redirect URI. Authorization and token exchange both use backend `YOUTUBE_REDIRECT_URI`; reload backend after changing it and begin a fresh OAuth attempt. |
| OAuth reports `oauth_scope_insufficient` | Reconnect and grant backend-reported scopes: `youtube.upload` for publishing, `youtube.readonly` for `channels.list(mine=true)` and Analytics `reports.query`, and `yt-analytics.readonly` for Analytics reports. Google's official [YouTube v3 Discovery document](https://www.googleapis.com/discovery/v1/apis/youtube/v3/rest) lists `youtube.readonly` (not `youtube.upload`) for `channels.list`; [`videos.insert`](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert) accepts `youtube.upload`. |
| Analytics says consent required | Enable YouTube Analytics API in the OAuth project, choose **Aktifkan Analytics** on the exact connected channel, and grant actual `youtube.readonly` plus `yt-analytics.readonly`. Klipnara verifies persisted grants; requested scopes alone do not count. |
| Analytics says API disabled or permission denied | Enable official YouTube Analytics API in Google Cloud. Confirm channel owner/manager access and consent. Official Analytics `reports.query` also requires `youtube.readonly`; no monetary scope is needed. Reconnect only from Connected Accounts and preserve existing upload grant. |
| Analytics report shows empty or partial dates | YouTube Analytics may lag recent days, channel metrics can be unavailable for selected periods, and retention can be missing for new/small videos. Check displayed coverage and last sync; do not treat missing rows as zero. Current UTC day is excluded. |
| Klipnara Analytics excludes a video | Only a video ID linked to a successful Klipnara publication record is attributed. Older records without immutable `attribution_json` remain unattributed; no settings are reconstructed from current drafts. |
| Analytics refresh fails after prior data loaded | UI retains last successful response with visible error; Sync now bypasses six-hour cache. Retry after rate/quota recovery. Disconnect clears channel cache; it does not delete publication history. |
| OAuth reports `oauth_token_exchange_failed`, `oauth_code_rejected`, or `oauth_client_rejected` | Start a fresh OAuth attempt; authorization codes are single-use and short-lived. For redirect mismatch, check exact callback. For client rejection, check backend Client ID/Secret and active Web application client. Error page does not expose Google's raw response or credentials. |
| OAuth reports `oauth_connection_failed` or legacy `youtube=error` | This is an unclassified/internal callback failure, not evidence that OAuth setup is wrong. Update/reload backend and frontend together, retry once, then inspect local backend log for exception type and source location. Logs omit exception text, authorization code, token, cookie, and credentials. Refresh Connected Accounts before retrying so existing channel state is clear. |
| OAuth reports `youtube_channel_not_found` | Google returned an empty `channels.list(mine=true)` result. Sign in with the Google account that owns/has access to a YouTube channel, then reconnect. A successful consent alone does not create a connected channel. |
| OAuth reports `youtube_api_failed` | Channel lookup failed outside a known scope rejection. Confirm YouTube Data API v3 is enabled for the OAuth project; check quota, API availability, and account/channel access. Backend redirects with a safe code, not raw provider response. |
| OAuth reports `oauth_token_storage_failed` | Channel lookup succeeded but DPAPI/SQLite persistence failed. No new account is marked connected; confirm same Windows user profile and writable local data directory, then reconnect. Existing valid credentials are not revoked as cleanup. |
| OAuth says Google refused permission | For Testing audience, add the signing-in Google account to Test Users, then retry and accept the requested scopes. Unverified-app warning alone does not identify the callback failure stage. |
| OAuth error notification appears green | Updated UI maps every OAuth failure code (including unknown codes) to the destructive `notice-error` style; only `connected` maps green. If this persists after frontend refresh, report browser console/runtime state. |
| OAuth credentials are detected but no channel card appears | Credentials do not mean connected. Complete Google consent; backend must exchange token and retrieve one channel identity before creating a connected account. Use a Google account with a YouTube channel; multi-channel grants fail closed. |
| Connecting another YouTube identity replaces or conflicts with current channel | Start **Hubungkan Channel Lain** and choose intended Google identity in Google's account selector. Klipnara keeps existing channel records. One grant exposing multiple YouTube channels remains unsupported and fails closed. |
| YouTube OAuth reports `youtube_multiple_channels` | Google returned multiple channel identities for one grant. Klipnara cannot choose safely; authorize a Google identity that exposes one intended channel. `prompt=select_account` switches Google identity, not channel within one grant. |
| YouTube account Expired | Refresh token returned `invalid_grant`; reconnect account. In OAuth Testing, refresh tokens may expire according to Google's current testing policy |
| One destination failed while others queued | Review each destination result/error and check its account status, scopes, metadata declarations, and existing publication history. A failed destination does not cancel successful per-account jobs. |
| Social upload blocked by destination identity mismatch | Worker rechecked provider identity before sending bytes. Reconnect the selected account and verify correct stable TikTok/Instagram identity; do not retry until account identity matches. |
| Disconnect leaves upload in history | Expected: disconnect cancels only not-yet-started work and preserves publication history. Started work may require provider reconciliation; a grant shared by another connected destination stays active. |
| YouTube upload Failed but retry available | Retry through Publishing History; worker probes saved session first and resumes at server-acknowledged byte offset |
| YouTube says outcome uncertain / retry blocked | Session expired after bytes may have reached YouTube without recovered video ID; inspect YouTube Studio manually before any new upload |
| YouTube publication remains Processing | Worker polls only while no queued jobs; account must stay/reconnect and YouTube must return processed status. `Scheduled` means YouTube confirmed native Private schedule; YouTube owns publish timing |
| YouTube account shows Error | Check OAuth client ID/secret, consent, granted scope and local redirect URI; credential values are not returned by API |
| AI Smart Clip on silent source | Current route rejects when fresh transcription is needed; use timestamp-based Quick Clip |
| Quick Clip final contains silent audio | Expected for silent input: renderer adds silent AAC to retain the final H.264/AAC review/publishing contract |
| Mood quote generation says key missing | Set `GEMINI_API_KEY` (default) or select configured `OPENAI_API_KEY` in backend environment, restart backend, then explicitly consent per request. No provider fallback occurs |
| Mood quote request returns 429/502/schema error | Check selected provider/model and quota; request stops without automatic retry. Regenerate only after reviewing provider quota; malformed output is not saved |
| Mood render fails on font/ASS | Confirm `ffmpeg -filters` includes `ass` and FFmpeg has libass. Installed Windows fonts are Arial/Georgia/Segoe UI/Tahoma/Trebuchet MS/Times New Roman; missing family falls back through libass/OS substitution |
| Mood render rejects selected audio as silent/corrupt | Check selected trim range, source signal, and volume; choose another licensed file or explicitly select **Tanpa musik**/mute background. A mood label does not select music |
| Mood background/music rejected | Check supported file extension, per-kind size cap, valid ffprobe streams, and trim times within asset duration. New files live in shared `sources/library-assets`; legacy Mood uploads remain under `%LOCALAPPDATA%\Klipnara\mood` |
| Cannot delete Source Library video | Detach it from each Mood Quotes draft first; a restricting SQLite reference prevents deleting a source that a draft still uses |
| Mood output not in YouTube publish UI | Refresh YouTube Studio after Mood render completes. Only individually approved current render fingerprints appear eligible; backend rechecks approval before queueing |

For API behavior and exact status schema, see [API and Database](api-and-database.md). For live YouTube setup, see [YouTube publishing](youtube-shorts-publishing.md).

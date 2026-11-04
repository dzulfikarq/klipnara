# API and Database

FastAPI is defined in `backend/clipper/main.py`, title **Klipnara Studio**, version `2.11.0`, API documentation at `/api/docs`. Default local base URL is `http://127.0.0.1:8000`; JSON API paths below include `/api`. Browser CORS allows HTTP(S) origins on `localhost` or `127.0.0.1` at any port so Next.js port fallback works; permitted methods include GET/POST/PUT/PATCH/DELETE.

## REST API

### Health, settings, capabilities

| Method/path | Result |
|---|---|
| `GET /api/health` | `{ "status": "ok" }` |
| `GET /api/settings` | CPU/RAM/GPU/runtime capability results, AI model/key-configured flags, `assets.pexels_configured` boolean, data/source/clip/mood roots, free bytes |
| `GET /api/system/capabilities` | Detailed OS, CPU/RAM/GPU, FFmpeg/ffprobe, encoders/filters, Ollama and Whisper detection |
| `POST /api/providers/{provider}/test` | `provider` is `local`, `openai`, or `gemini`; local performs bounded Ollama check, cloud checks configured key only |
| `POST /api/youtube-clips/metadata` | JSON `{ "url": "https://youtu.be/VIDEO_ID?t=30" }`; strict YouTube URL parse plus optional YouTube Data API metadata; no URL fetch to user host. Invalid URL: 422; metadata unavailable: 200 with status; missing route: HTTP 404; wrong method: 405 |
| `GET /api/youtube-clips/import-capabilities` | Adapter availability, reason, and non-official/permission notice; never downloads media |
| `POST /api/youtube-clips/imports` | JSON `{url,start,end,rights_confirmed:true}`; opt-in local section import job. 503 when disabled/unavailable, 422 for invalid URL/time/attestation, 507 for low disk |
| `GET /api/youtube-clips/imports/{job_id}` | Import progress/status and validated source metadata when ready; no local path |
| `POST /api/youtube-clips/imports/{job_id}/cancel` | Cancels queued/running segment import |
| `POST /api/youtube-clips/imports/{job_id}/retry` | `{ "rights_confirmed": true }`; creates a fresh import job from failed/cancelled request |
| `GET /api/docs` | FastAPI OpenAPI UI |

### Source and generation

| Method/path | Request / response contract |
|---|---|
| `POST /api/sources/upload` | Multipart `file`; validates/stores MP4/MOV, returns source metadata |
| `POST /api/sources/url` | JSON `{ "url": "https://.../media.mp4" }`; direct public HTTPS media only |
| `GET /api/sources` | Source metadata, candidate count, latest non-YouTube job status |
| `GET /api/sources/{source_id}` | Source metadata/transcript and its clips; path/hash removed |
| `GET /api/sources/{source_id}/file` | Inline original media |
| `DELETE /api/sources/{source_id}` | Deletes source and child clips/render files; active jobs, Mood references, or Video Clips batch references block delete |
| `POST /api/sources/{source_id}/quick-clips` | `QuickClipRequest`; queues timestamp-only render, no transcript or AI |
| `POST /api/sources/{source_id}/generate` | `GenerateOptions`, returns queued job ID |

`GenerateOptions` fields: `count` 3/5/10 (default 5); `duration` `15-30`/`30-60`/`60-90`; `style` Clean/Bold/Highlight; `subtitle_enabled`; `resolution` 720/1080; `focus` center/manual; `provider` local/openai/gemini; `language` auto/indonesia/english; `consent` boolean (false by default). Cloud providers require per-job consent and configured key.

### V2.7 Asset Library and Pexels

| Method/path | Request / response contract |
|---|---|
| `GET /api/assets` | Optional `kind=video|image|audio`, `favorite=true|false`, supported `mood`, `query`, `page`, `per_page`; returns local metadata and draft-use counts, never file paths/hashes |
| `GET /api/assets/storage` | Local library counts/bytes by kind and available disk bytes |
| `POST /api/assets/upload` | Multipart `kind`, `file`, optional title/artist/mood tags/license/source/attribution metadata; validates and hash-deduplicates local media (video cap 512 MiB, image 25 MiB, audio 100 MiB). Existing UI video upload uses `/api/sources/upload` and its 2 GiB default cap |
| `GET /api/assets/{id}` / `PATCH /api/assets/{id}` | Metadata; PATCH supports title, favorite, artist, mood tags, license type/notes, HTTPS source URL, attribution text |
| `GET /api/assets/{id}/file` | Inline managed local media |
| `DELETE /api/assets/{id}` | Removes unused local asset; active jobs or Mood references block video/shared media deletion |
| `GET /api/assets/stock/search` | Official Pexels video search: required `query`; optional orientation, size, page/per_page; min/max duration filter returned page locally. Returns metadata and sanitized preview/MP4 URLs |
| `GET /api/assets/stock/videos/{video_id}` | Current Pexels metadata for user-selected preview/favorite |
| `GET /api/assets/stock/favorites` / `POST /api/assets/stock/favorites` / `DELETE /api/assets/stock/favorites/{video_id}` | Persist/remove local provider favorite; POST JSON `{ "video_id": "12345" }` |
| `POST /api/assets/stock/imports` | JSON `{ "video_id": "12345", "video_file_id": "67890", "quality": "hd" }`; creates one bounded import, or returns existing local asset with `reused=true` |
| `GET /api/assets/stock/imports/{job_id}` | Persisted status/progress/bytes/message and ready asset metadata |
| `POST /api/assets/stock/imports/{job_id}/cancel` / `retry` | Cancel queued/running import; retry failed/cancelled job. One import runs at a time; cap 512 MiB |

`PEXELS_API_KEY` is read only by backend; settings returns only `assets.pexels_configured`. Search endpoint is official `https://api.pexels.com/v1/videos/search`; no live Pexels API validation is claimed here. Search responses are capped at 4 MiB and search-result cache holds 100 entries for five minutes; min/max duration filters apply to current returned page locally. Selected video metadata is re-fetched. Import accepts one selected MP4 file ID/quality, validates media CDN host/port and public DNS on every redirect, pins TLS connection, caps output at 512 MiB, probes/hashes file, reuses hash-identical local video when present, then registers a standard `sources` row plus `library_assets` metadata only when needed. It does not auto-create a Quick Clip, transcript, or AI job. Import statuses: `queued`, `downloading`, `probing`, `ready`, `failed`, `cancelled`; backend restart marks active imports failed, removes scoped temporary files, and removes a final orphan only when hard-link identity proves job ownership. Pexels license reference/creator/source/attribution are retained for user review; app does not establish legal clearance.

`/api/sources/upload` also registers normal video uploads in the shared library and retains its existing `CLIPPER_MAX_UPLOAD_BYTES` cap (2 GiB default). Video files remain in canonical `sources`; images/audio use managed `SOURCE_DIR/library-assets`. Hash-identical local uploads reuse an existing library row. Favorites for Pexels are metadata-only and can be listed without a Pexels request; opening a saved favorite for preview requires backend key/network.

`QuickClipRequest`: nonblank `title` (max 120), `start` seconds (`>=0`), `end` seconds (`>0`, must exceed start and be `<=source.duration`), optional `resolution` 720/1080 (default 720), optional `youtube_reference: {canonical_url,video_id,start?,end?}`. Reference URL must exactly be canonical and match the 11-character ID. Optional reference `start/end` preserve original YouTube timestamps when local source is an imported segment; clip `start/end` remain offsets into managed local source. API re-runs ffprobe and rejects End beyond current source duration. Server derives `source_association` (`auto_imported` only for source created by a ready import job; otherwise `user_selected`). Reference and original selected timestamps are saved in existing job `options_json`; no `clips`/`jobs` migration.

### Batch Creator V2.9

| Method/path | Request / response contract |
|---|---|
| `GET /api/batches` / `GET /api/batches/{id}` | Persistent batch list/details, ordered item state, job progress/message, editor/output/download links, and review status |
| `POST /api/batches/clips` | `{name,source_id,shared_settings?,items:[{name,start,end}]}`; creates 1–10 source-backed clip drafts without AI/rendering |
| `POST /api/mood-projects/{project_id}/batches` | `{name,items:[{name,quote}]}`; clones saved/manual quote snapshots and references shared assets; never generates quotes |
| `PATCH /api/batches/{id}` | Optional name or Video Clips `shared_settings`; `apply_to_pending` updates non-custom pending drafts. Shared settings change only before start or while paused |
| `POST /api/batches/{id}/start`, `/pause`, `/resume`, `/cancel`, `/retry-failed` | Lifecycle controls; one child render at a time. Pause waits for active child, cancel preserves completed outputs, retry uses a fresh item job |
| `POST /api/batches/{id}/items` | Adds one timestamp clip or one saved quote; max 10 items; additions allowed before start or while paused |
| `POST /api/batches/{id}/items/{item_id}/duplicate` / `/retry` | Duplicates an unstarted pending item or retries an eligible item through batch scheduler |
| `PATCH /api/batches/{id}/items/order` | `{item_ids:[...]}`; exact complete order, pending items only once started |
| `DELETE /api/batches/{id}/items/{item_id}` | Removes pending item only when no saved MP4 exists |
| `DELETE /api/batches/{id}` | Removes batch queue record only; item drafts and rendered outputs remain. Active child jobs block deletion |

Batch statuses: `draft`, `ready`, `queued`, `running`, `pausing`, `paused`, `completed`, `completed_with_errors`, `failed`, `cancelled`. Item statuses: `draft`, `ready`, `queued`, `rendering`, `completed`, `failed`, `cancelled`, `skipped`. Restart recovery pauses in-flight batches, marks interrupted children failed/retryable, and releases never-started child jobs for resume. Generic child cancel/retry/render routes reject batch-linked work; use Batch Creator controls.

`POST /api/youtube-clips/metadata` is registered directly on FastAPI. Frontend API client adds `/api` once and normalizes `NEXT_PUBLIC_API_URL` with or without trailing `/api`. App-route 404 is not YouTube availability. Preview may continue with unverified availability; a legacy route-404 fallback can still use local Quick Clip without provenance.

Endpoint accepts only `http(s)` YouTube hosts/path variants (`youtube.com/watch?v=...`, `youtu.be/...`, `/shorts/...`) and max 2048-character body URL. It returns `video_id`, canonical URL, optional parsed `start_seconds`, `metadata_status`, and nullable metadata `{title,channel,thumbnail_url,duration_seconds,embeddable}`. `YOUTUBE_DATA_API_KEY` is optional and read only from backend environment. Without key, API returns `not_configured`; unavailable/private/restricted, quota, API, provider, and network failures return HTTP 200 with a status/message and no fabricated fields, so IFrame preview can still run. A 404/empty result from YouTube Data API maps to `unavailable` metadata within HTTP 200; IFrame error 100 means video unavailable/restricted, while 101/150 specifically mean embedding disabled. Calls use fixed `www.googleapis.com` HTTPS destination, 8-second timeout, 256 KiB response cap, and no cache/database persistence. Only explicit requests refresh metadata. The browser uses official YouTube IFrame Player API directly for preview; it never supplies media to the backend.

`sources.audio_codec` is nullable. `probe()` accepts a video-only source; AI Smart Clip returns 409 when it would need to transcribe a source without audio, while Quick Clip proceeds without transcript.

`youtube_import_jobs` is additive, independent from generic `jobs` because import has no source until validation completes. Status values: `queued`, `preparing`, `importing`, `processing`, `ready`, `failed`, `cancelled`; progress/message update in worker. On success, job ID becomes source ID, validated MP4 enters managed `sources`, and frontend automatically calls existing `/quick-clips` route. Failed/cancelled imports can create fresh retry jobs; cancellation signals downloader process group and removes only that job's temporary directory. Startup marks interrupted imports failed and removes their scoped temp/final orphan files only when no source row exists. Completed imports remain ordinary user-managed sources and are not deleted by retry/clip cleanup.

`POST /api/youtube-clips/imports` validates the URL through strict YouTube parser, canonical video ID, finite safe timestamps `0 <= start < end`, selected interval no longer than 4 hours, explicit `rights_confirmed=true`, and capability. Adapter requires `YOUTUBE_IMPORT_ENABLED=1`, installed `yt-dlp` (`YT_DLP_PATH`), FFmpeg and ffprobe. Process receives argv list, fixed canonical URL, `--ignore-config`, `--no-playlist`, `--download-sections`, no browser cookies/config, and no user-selected host; partial range is requested, not guaranteed to transfer only selected bytes. Output caps: `CLIPPER_MAX_UPLOAD_BYTES` (default 2 GiB), ffprobe-supported MP4/MOV, positive duration through 4 hours, interval duration within tolerance. Temp files are scoped and cleaned on failure/cancel. Adapter is not official YouTube functionality; user attestation cannot verify legal rights or platform permission. Restricted, private, unavailable, unsupported, or inaccessible videos fail with fallback to permitted Source Library/upload. No DRM bypass, session theft, hidden auth, or access-control workaround is implemented.

The direct-file `POST /api/sources/url` importer still rejects YouTube site/embed hosts before DNS/network access. YouTube Import is a separate, disabled-by-default adapter; successful source enters unchanged Quick Clip/FFmpeg/Editor/review/publishing path.

### Mood Quotes projects

| Method/path | Request / response contract |
|---|---|
| `GET /api/mood-quotes/categories` | Stable category/subcategory config, styles, POV, length bands, languages, music moods, backward-compatible templates, typed/versioned `visual_presets`, system fonts, provider readiness, consent disclosure |
| `GET /api/mood-projects` | Up to 200 local drafts and current render summary |
| `POST /api/mood-projects` | Creates a draft with default composition, no source/clip rows |
| `GET /api/mood-projects/{id}` | Draft settings, selected quote, current quote batch, generation history, favorites, assets, render history |
| `PATCH /api/mood-projects/{id}` | Validated partial draft fields, selected quote, composition; changed text/style clears current render approval |
| `POST /api/mood-projects/{id}/generate` | `{provider: gemini|openai, consent: true}`; returns exactly five validated quotes and usage metadata |
| `GET /api/mood-projects/{id}/generations` | Saved quote batches, newest first |
| `POST /api/mood-projects/{id}/favorites` | `{quote, generation_id?}`; duplicate text returns existing favorite |
| `DELETE /api/mood-projects/{id}/favorites/{favorite_id}` | Deletes one favorite snapshot |
| `POST /api/mood-projects/{id}/assets` | Multipart `file` and `kind` (`background_image`, `background_video`, `music`); new uploads are ffprobe-validated and stored once in shared local Asset Library, then linked to draft |
| `POST /api/mood-projects/{id}/source-assets` | `{source_id}`; references managed Source Library video without copying; source deletion is blocked while referenced |
| `POST /api/mood-projects/{id}/library-assets` | `{ "asset_id": "..." }`; attaches existing shared video/image/audio without copying; repeats return existing draft link |
| `DELETE /api/mood-projects/{id}/assets/{asset_id}` | Detaches unused project link; shared media remains. Legacy project-owned files are deleted |
| `GET /api/mood-assets/{asset_id}/thumbnail?time={seconds}` | One cached FFmpeg JPEG frame for a background video; seek time must be within asset duration |
| `POST /api/mood-projects/{id}/render` | Validated full `MoodComposition`; queues source-less `mood_render` job and snapshot |
| `GET /api/mood-projects/{id}/renders` | Render history and review status |
| `GET /api/mood-jobs/{id}` | Mood job status/progress/message, no private options or paths |
| `POST /api/mood-jobs/{id}/cancel` / `retry` | Cancels queued/running render or retries failed/cancelled snapshot |
| `POST /api/mood-renders/{id}/review` | `{status: approved|needs_revision}`; approved H.264/AAC file gets SHA-256 fingerprint |
| `GET /api/mood-renders/{id}/file` / `download` | Inline preview or MP4 download |
| `GET /api/mood-assets/{id}/file` | Managed local image/video/audio asset |
| `DELETE /api/mood-projects/{id}` | Deletes draft, generation/favorite history, legacy project-owned assets and render files; active render or pending/uploading YouTube publication blocks deletion; shared Asset Library files remain |

`MoodComposition` is Pydantic-validated: 720/1080, 30 FPS, 5–40 seconds; solid/gradient/image/video; optional music `offset`, `muted`, trim/volume/fades/loop; typography, Auto Contrast, gradient backing and animation. Offset is seconds from video start; old drafts default to offset `0` and `muted=false`. Selected music timing is checked against available composition and asset duration. `text_mode` is `single` or `sequential`; `segments` holds up to eight `{id,text,start,end,animation,animation_duration}` records constrained to output duration without overlap. `visual` is optional for old drafts and defaults to version 1 safe values. It stores `preset_id`, motion (`none`, slow zoom in/out, four pan directions, Ken Burns), intensity, bounded brightness/contrast/saturation/temperature, vignette/grain/dark-overlay/gradient settings, and default segment animation. Text includes validated `font_weight`. Missing `text_mode` is treated as legacy Single Text; new drafts default to Sequential Text. Mode, segments, visual settings and music stay in existing `composition_json`; timeline selection/zoom/snap are UI-only and no SQLite migration is needed. Preset definitions include stable ID, description/category, mood recommendations, preview colors, version, effect/typography/animation defaults, and recommended music mood. Applying preset updates only those visual fields and preserves quote, manual segment/timing, chosen media background asset, and music; solid/gradient backgrounds take preset palette. Active selected audio is signal-checked; silent/corrupt audio fails, while no music, mute, or zero volume intentionally permits silent AAC. Asset IDs must belong to draft and requested media kind; text must fit safe frame. Asset caps: image 25 MiB, background video 512 MiB, audio 100 MiB; accepted extensions JPG/JPEG/PNG/WebP, MP4/MOV, MP3/WAV/M4A. Legacy Mood files remain project-scoped; new uploads/references point to shared library. Mood render jobs store quote/composition snapshots; Mood outputs are local only, with no YouTube route.

AI generation accepts only Gemini/OpenAI, requires `consent=true` every request, configured backend key, selected category/subcategory, and sends text settings only. Keys are never persisted or returned. Missing provider/quota/invalid output fails without retry/fallback. Successful generation records provider/model/request settings/consent time/usage where returned in `mood_generations`; not in the source-job `provider_usage` table.

### Clips, review and render

| Method/path | Request / response contract |
|---|---|
| `GET /api/clips` | Clip summaries include operational status, review status, rendered flag and source name |
| `GET /api/clips/{clip_id}` | Clip/edit, source metadata/transcript, STT availability, subtitle composition fingerprint/stale-track and outdated-translation IDs, non-YouTube clip jobs and nullable YouTube reference |
| `PATCH /api/clips/{clip_id}` | Partial `ClipEdit`; edit changes invalidate review fingerprint and mark an existing render stale |
| `POST /api/clips/{clip_id}/subtitles/auto-generate` | Synchronously transcribes current single-scene trim or selected Multi-Scene `scene_id` from original source audio; request fields: provider `local`/`openai`, language `auto`/`indonesia`/`english`, optional `consent` and `scene_id`; returns saved edit/provider |
| `POST /api/clips/{clip_id}/subtitles/transcribe` | Queues full-composition subtitle transcription. JSON: provider `local`/`openai`/`gemini`, language, explicit `consent` for cloud. Returns job ID/provider/duration or matching cached draft. |
| `POST /api/clips/{clip_id}/subtitles/translate` | Queues text-only translation of selected original cues. JSON: provider `openai`/`gemini`, target `id-ID`/`en-US`, explicit `consent`. Returns job ID or matching draft. |
| `POST /api/clips/{clip_id}/subtitles/import` | Parses SRT/VTT JSON `{format,text,clamp}`; returns unactivated draft, warnings, duration, and optional `needs_clamp`. |
| `GET /api/clips/{clip_id}/subtitles/export?format=srt&track_id=...` | Exports selected timed track as SRT or VTT; translation track exports translated text. Stale output tracks return 409. |
| `POST /api/clips/{clip_id}/review` | JSON `{ "status": "approved" }` or `needs_revision`; validates completed nonempty H.264/AAC MP4. Approval stores SHA-256 of final bytes |
| `POST /api/clips/{clip_id}/render` | Queues render; immediately resets review/fingerprint |
| `DELETE /api/clips/{clip_id}/youtube-reference` | Removes optional YouTube provenance from source Quick Clip job options; leaves source/clip/render intact |
| `GET /api/clips/{clip_id}/file` | Inline final/previous MP4 |
| `GET /api/clips/{clip_id}/download` | Download MP4 |
| `DELETE /api/clips/{clip_id}` | Deletes clip/render; active render or pending/uploading publication blocks |

`ClipEdit` retains trim start/end and adds `scene_mode` (`single`/`multi`), `scenes`, `transitions`, subtitle tracks/timebase/display/caption modes and styling, audio, title overlay, FPS, and quality to the existing edit object. Scene is `{id,source_start,source_end,order,role}`; stable ID, source seconds, and contiguous unique order are validated. `transitions` maps each adjacent `fromId>toId` pair to `{type,duration,timing_mode,smooth_audio}`; `timing_mode` is `insert_slot` or `overlap`. Missing mode on stored/legacy data and API requests means `overlap`; projects without transitions remain hard cuts. Omitted duration defaults to 0.5s for Insert Slot and 0.25s for legacy Overlap. The editor creates new visual transitions as Insert Slot; Crossfade and Dip to Black are supported in both modes. Zoom Blur is legacy Overlap-only and renders as Crossfade fallback. Transition durations count frames at 30/60 FPS; newly added/retimed values must be 0.1–2 seconds. Older durations remain valid until timing is edited, subject to overlap fitting both scenes and total overlap fitting available scene frames. Orphan pair keys are removed when scene relationships change. Multi-Scene intervals must be at least 0.5 seconds, with at most 12 scenes; PATCH accepts drafts over 180 seconds. `POST /render` rejects final output over 180 seconds in either mode. Single mode retains legacy candidate-relative trim bounds; Multi-Scene output positions derive from complete selected scene frames plus Insert Slot frames minus Overlap frames. Source ranges remain stored non-destructively; sub-frame source tails are not rendered. Overlapping/repeated source ranges are allowed intentionally.

Subtitle cue is `{id,start,end,text,words?,word_alignment_reviewed?,speaker_id?,source_segment_id?,original_text?,edited?}` (up to 500 cues, unique IDs, text ≤500). Each optional word is `{id,text,start,end,speaker_id?,source_start?,source_end?}` with unique stable ID per cue; mapped source fragments may carry source bounds for cut rejoining. Word text may be blank and word times may be null only in unreviewed manual drafts. `word_alignment_reviewed` must be exactly `true` for Word Pop; cue text must reconstruct from ordered string tokens with punctuation, each finite numeric interval must stay inside cue, and within-cue overlaps fail (silence gaps allowed). Changing cue text/bounds or word data invalidates review. A track adds `source_type` (`manual`/`generated`/`imported`/`translation`), language/provider/model, `timebase`, cues, optional transcript text, composition signature/fingerprint, translation source-track/fingerprint, word/speaker flags, and edited flag. `subtitle_timebase="clip"` means candidate-relative seconds; `"source"` means source seconds; `"output"` means composition-relative seconds. Source/clip captions remap through ordered scenes; output-time word tracks retain composition-relative timings and require matching source hash + composition fingerprint, otherwise render rejects them as stale. Translation freshness binds original cue IDs/text/timing. `subtitle_overrides` remains accepted for legacy transcript text. Caption settings include sentence/phrase/legacy `word`/karaoke/`word_pop` mode, nine appearance presets, font, color/outline/highlight, alignment, animation (`none`/`fade`/`pop`/`scale`), animation intensity/duration, safe margins, width and background. Presets do not select caption type. Audio settings include volume/mute/fades/optional normalization/limiter/target LUFS. Title overlay is opt-in. Export accepts 720/1080, 30/60 FPS, and smaller/balanced/high quality. Render job snapshots preserve one consistent edit. Subtitle tracks/settings use `clips.edit_json`; no table or migration is added.

Selecting `word_pop` via `PATCH /api/clips/{clip_id}` requires reviewed valid word timing for every cue intersecting current composition, including when subtitles are currently disabled. Enabling subtitles or selecting another active track while Word Pop is enabled performs same check; non-original display is rejected. Saving later timing/text edits may retain an unreviewed Word Pop draft, but `POST /render` fails closed until all current cues pass; ASS intervals shorter than 10 ms after timestamp quantization also fail closed. Gemini word timestamps may be used; segment-only and transcript-only providers supply no inferred word timing. Per-word ASS events clip/remap through scenes; scene splits/repeats preserve source word identity for safe rejoining.

The legacy auto-generation route extracts only the selected trim/scene. Local provider uses Whisper; OpenAI `whisper-1` returns segment timings. It is synchronous and does not update the source transcript cache.

V2.8 transcription snapshots ordered composition ranges and concatenates source audio. Local Whisper returns segment timings and stays local. Gemini `gemini-3.5-transcribe` requests verbatim word timestamps and speaker labels, capped at 1800 seconds. OpenAI `gpt-transcribe` returns transcript text only; no timestamps are synthesized. Cloud audio requires explicit frontend confirmation plus `consent=true`; OpenAI upload is capped at 25 MiB. Results are stored as inactive review drafts. Translation sends cue text/IDs only after separate consent, validates exact ID order/text, and saves a separate track. Retries require fresh cloud consent. `subtitle_import` accepts UTF-8/UTF-16 SRT/VTT up to 2 MiB and 500 cues; export returns SRT/VTT. Imported/generated tracks do not replace active captions automatically.

`quick_clip` jobs store an `edit` snapshot in existing `jobs.options_json` and a normal `clips` row. Initial edit uses full selected span, portrait center crop, 720p, subtitle disabled. `origin` returned by clip/source APIs is derived from parent `jobs.kind` (`quick_clip` vs `generate`); `batch_draft` clip source jobs are exposed as `quick_clip`, not a new column.

YouTube-linked Quick Clips add `{canonical_url,video_id,start,end,source_association}` to that same job JSON. Server records `auto_imported` only when source, video ID, and original timestamps match a completed import; otherwise records `user_selected`. Clip detail returns reference separately from local `source_id`; clearing reference leaves source/clip/render intact. Data API metadata is not persisted.

### Jobs

| Method/path | Purpose |
|---|---|
| `GET /api/jobs` | Recent non-YouTube worker jobs |
| `GET /api/jobs/{job_id}` | Job state/progress/message and provider usage; strips `options_json` |
| `POST /api/jobs/{job_id}/cancel` | Cancels generic queued/running job; YouTube uses publication cancellation route |
| `POST /api/jobs/{job_id}/retry` | Failed/cancelled generic job; cloud retry body must contain fresh `{ "consent": true }`; copies matching analysis checkpoints. YouTube retry is rejected here |

### YouTube

| Method/path | Purpose |
|---|---|
| `GET /api/youtube/config` | Returns backend credential readiness, requested scopes, effective redirect URI, local OAuth start URL and safe callback validation error; never returns credentials or tokens |
| `GET /api/youtube/oauth/start` | Generates per-attempt state/cookie and redirects to Google with `prompt=select_account`. Optional `account_id` starts channel-bound incremental Analytics consent |
| `GET /api/youtube/oauth/callback` | Validates one-use state/cookie, exchanges code, verifies same channel before encrypted persistence, records actual Google-granted scopes, then redirects with safe result/error code only; never forwards code/token/provider error |
| `GET /api/youtube/accounts` | Channel/account status and verified `granted_scopes`, `scopes_verified`, `upload_ready`, `analytics_ready`; never returns credential ciphertext |
| `POST /api/youtube/accounts/{account_id}/default` | Set connected YouTube destination default |
| `POST /api/youtube/accounts/{account_id}/verify` | Refreshes channel identity/title/avatar against stored channel ID |
| `DELETE /api/youtube/accounts/{account_id}` | Cancels queued uploads for this destination, disconnects locally, preserves history, revokes authorization only when unshared, and clears that channel's Analytics cache |
| `GET /api/youtube/analytics?account_id=&scope=channel\|klipnara&start_date=&end_date=&force=` | Official channel/video report, date coverage, distinct Views/Engaged Views, equal-length previous-period comparison, linked publication attribution and guarded insights. `force=true` bypasses cache |
| `GET /api/youtube/analytics/publications/{publication_id}?start_date=&end_date=&force=` | Daily report and summary for one published Klipnara publication |
| `GET /api/youtube/analytics/publications/{publication_id}/retention?...` | Audience retention for one video ID per YouTube request |
| `GET /api/publishing/content` | Rendered Clip and Mood outputs, review state, local metadata draft, thumbnail state and eligibility hint |
| `GET/PUT /api/publishing/{clip\|mood_render}/{content_id}/metadata?account_id=` | Read/save shared draft or selected YouTube account override; drafts never enqueue upload |
| `GET/POST /api/publishing/metadata-templates`, `DELETE /api/publishing/metadata-templates/{id}` | List/save/delete reusable metadata templates |
| `GET /api/publishing/calendar?start=&end=` | Native YouTube scheduled and completed schedule records |
| `GET /api/publishing/events?content_type=&content_id=&publication_id=` | Local publish/retry/upload/status/thumbnail event history |
| `POST /api/publishing/{clip\|mood_render}/{content_id}/youtube` | Explicitly confirmed metadata upload for approved Clip or Mood render; same uploader and fingerprint gate |
| `POST /api/publishing/{clip\|mood_render}/{content_id}/thumbnail` / `GET .../thumbnail` | Save/serve managed JPEG or PNG thumbnail tied to current render fingerprint/stat |
| `POST /api/youtube/publications/{id}/thumbnail` | Upload local thumbnail to existing YouTube video; success only after API returns thumbnail resource |
| `POST /api/clips/{clip_id}/youtube-publications` | Backward-compatible Clip endpoint; same metadata/confirmation/approval gates |
| `GET /api/youtube/publications` | Up to 500 history rows, newest first |
| `GET /api/youtube/publications/{publication_id}` | One status/progress/history record; removes local path/hash/session ciphertext |
| `POST /api/youtube/publications/{publication_id}/cancel` | Pending only, before upload may have started |
| `POST /api/youtube/publications/{publication_id}/retry` | Failed only; reconciles existing resumable session or checks known video ID before any upload |

V3.2.1 multi-destination YouTube requests use `account_ids` (max 50) and `metadata_by_account: {account_id: metadata}` on `/api/publishing/{clip|mood_render}/{content_id}/youtube`. Response contains independent `destinations[]` results; one account's validation/queue failure does not discard successful destinations. Every publication snapshots its destination authorization and stable YouTube channel ID. Legacy Clip endpoint remains single-account compatible.

### TikTok and Instagram V3.2

| Method/path | Purpose |
|---|---|
| `GET /api/publishing/platforms` | OAuth readiness, verified social account scopes, conditional upload methods, provider restrictions; no tokens |
| `GET /api/platforms/{platform}/oauth/start` and `/oauth/callback` | `{platform}` is `tiktok` or `instagram`; one-use state/cookie OAuth; TikTok requests `user.info.basic` + `video.upload`; Instagram uses Facebook Login for Business |
| `POST /api/platforms/{platform}/accounts/{account_id}/default` | Set connected TikTok or Instagram destination default |
| `DELETE /api/platforms/{platform}/accounts/{account_id}` | Cancel queued jobs for this destination; preserve history and shared OAuth grant; provider revocation best-effort when unshared |
| `GET/PUT /api/publishing/{clip\|mood_render}/{content_id}/platform-metadata/{platform}?account_id=` | Read/save shared platform draft or selected account override |
| `POST /api/publishing/{clip\|mood_render}/{content_id}/platforms/{platform}/manual-export` | Explicitly prepare current approved MP4 for manual posting; no provider request |
| `POST /api/publishing/{clip\|mood_render}/{content_id}/platforms/{platform}/upload` | Queue TikTok Inbox transfer or Instagram resumable Reels publish; requires `account_ids` (max 50), `confirmed=true`, `rights_confirmed=true`; optional `metadata_by_account` |
| `GET /api/platform-publications` | Social manual-export and API-job history; strips credentials/session ciphertext |
| `GET /api/platform-publications/{id}/download` | Download still-valid manual export only; rechecks approval SHA-256 |
| `POST /api/platform-publications/{id}/reconcile` | Query provider operation/container status before any ambiguous retry |
| `POST /api/platform-publications/{id}/retry` | Explicitly retry failed/cancelled/reconciled job; requires rights confirmation; ambiguous no-operation-ID case also requires `duplicate_risk_confirmed=true` |
| `POST /api/platform-publications/{id}/cancel` | Cancel queued job or request cancellation of active transfer; uncertain provider outcome becomes reconciliation-required |

Social API readiness is conditional on actual account scopes and login method. It does not imply app review, account eligibility, Page authorization, or successful live API access. Manual export is always available. TikTok Direct Post remains disabled: `video.publish` is never requested. `SEND_TO_USER_INBOX` means creator must finish the post in TikTok; only provider status `PUBLISH_COMPLETE` becomes Published. Instagram uses Facebook Login for Business local resumable transfer (`graph.facebook.com` container/publish/status and `rupload.facebook.com` bytes); Instagram Login `video_url` is not assumed. Container `FINISHED` is not Published; publish response/status must confirm success. Scheduling is unsupported for social providers.

Connected Accounts keeps one provider-scoped default for convenience; publishing destination IDs remain explicit and stable. V3.2.1 creates one job per selected social account and returns `destinations[]` outcomes. YouTube OAuth requests `prompt=select_account` to switch Google accounts; a single grant exposing multiple YouTube channels still fails closed rather than guessing a channel.

Each API job snapshots metadata, target account, approved MP4 SHA-256, media validation, and rights confirmation. Worker rechecks approval, fingerprint, account status/scopes, and media limits immediately before transfer. Jobs and events remain platform/account-specific. Restart or interrupted request after provider work starts fails closed to `needs_reconciliation`; no automatic duplicate upload. TikTok resumes only from provider-confirmed, chunk-aligned byte offsets. Instagram status query exposes container `status_code`, not acknowledged byte offsets; ambiguous transfer is status-polled and never resent automatically. Retry reuses confirmed TikTok session state or an Instagram container explicitly reconciled as `FINISHED`; an Instagram `IN_PROGRESS` container after five checks can be abandoned only with explicit risk confirmation, and never when a publish request remains ambiguous. Unknown provider state blocks retry. TikTok Inbox transfer is not treated as publication, and manual export status never implies upload.

Single-destination publication requires `confirmed=true`, `rights_confirmed=true`, `account_id`, title, and booleans `made_for_kids`/`contains_synthetic_media`. Multi-destination publication uses `account_ids` plus per-account overrides in `metadata_by_account`; every destination still requires a valid title and both declarations. Optional metadata: description, `tags`, `hashtags`, supported `category_id`, `video_language`, and `privacy_status`. Tags are trimmed/deduplicated and limited to 500 combined characters; title ≤100 characters; description ≤5000 UTF-8 bytes including appended hashtags. Privacy accepted: `private`, `unlisted`, `public`. `publish_at` must be an ISO 8601 timestamp with timezone and at least two minutes in future; native YouTube scheduling requires Private. UI converts browser-local `datetime-local` to UTC before explicit confirmation. A past schedule is rejected to prevent accidental immediate publication.

Analytics requires actual `youtube.readonly` plus `yt-analytics.readonly` grants; `youtube.readonly` also authorizes Analytics `reports.query`. Google-returned `scope` is persisted; when omitted, token-info must verify it. Missing/unverifiable or narrower grants do not replace existing credentials. No monetary scope is requested. `scope=channel` is channel-wide; `scope=klipnara` queries successful local publication video IDs individually because Analytics video filters accept one ID per request, then aggregates official daily counts and view-weights rate metrics. Default date range is last 28 complete UTC days; maximum inclusive range is 366 days; today is rejected. Reports page at 200 rows; date ranges split into ≤200-day requests and channel video details page through at most 500 rows. Responses expose actual report coverage because YouTube data can lag. Cache TTL is six hours, stale cache is removed after 30 days, and disconnect clears that channel's cache. Retention accepts one video ID per report call. Analytics errors use structured `detail: {code,message}`.

Clip and Mood render records keep separate schema and review fingerprints. `youtube_publications.content_type` distinguishes `clip` and `mood_render`; legacy `clip_id` stores content ID without FK so history survives deletion. Mood outputs use `youtube_upload_jobs` because they have no source row; source-backed Clip uploads keep existing `jobs` records. Both queue kinds call same `run_upload`, use same serial `JobRunner`, OAuth, resumable session, retry, reconciliation and remote status checks. Queue transaction and worker recheck current approval SHA-256 before bytes can transfer. Each batch output must be approved separately and user must confirm each publication separately; no batch auto-publish.

Custom thumbnails accept JPEG/PNG up to 2 MiB, min 640×360, landscape. Local thumbnail row stores render size/mtime and is rejected after render changes; applying to YouTube also rechecks the publication's output SHA-256. `remote_status` becomes `applied` only after successful `thumbnails.set` response with returned thumbnail resource. Failures persist `failed` plus error and are never shown as success. YouTube API may reject custom thumbnails due to channel eligibility or quota.

### Error behavior

FastAPI returns HTTP errors with `detail`. Common status codes: 400 for unsupported/privacy/consent configuration; 404 for missing resource; 409 for invalid state (unapproved, stale render, active operation, duplicate publication, unsafe retry, active asset reference, or no source audio for Auto Generate); 413 for source/asset size limit; 422 for Pydantic/field validation or no detected speech; 429 for Pexels rate limiting; 502/503/504 for provider/configuration/network failures; 507 for insufficient disk. YouTube provider errors are stored as publication `last_error`, never credentials.

## SQLite schema

`connect()` opens the configured DB with 30-second timeout, row factory, foreign keys enabled and commit-on-success. `init_db()` creates data folders, enables WAL, creates tables/indexes, applies additive migrations and recovers interrupted work.

| Table | Important columns / relation |
|---|---|
| `sources` | `id`, unique `path`, original name/size/duration/dimensions/codecs/hash/time, `transcript_json`, model/language/config fingerprint |
| `library_assets` | Shared media metadata: `id`, kind, local/Pexels source, provider ID/URLs/creator/license, optional canonical `source_id`, title/path/MIME/size/duration/dimensions/hash, favorite/last-used, artist/mood tags/license notes/attribution; video FK to `sources` uses `ON DELETE RESTRICT` |
| `asset_provider_favorites` | Provider/video ID, sanitized Pexels page/preview/creator, duration/dimensions/orientation, saved timestamp; metadata only, no downloaded media |
| `asset_import_jobs` | Pexels provider/file IDs and selected quality, status/phase/progress/download byte counts, cancellation request, optional `asset_id`, timestamps; one separate import worker |
| `jobs` | `id`, `source_id` FK cascade, optional `clip_id`, `kind`, `status`, `phase`, progress/message, `options_json` (including optional Quick Clip YouTube reference), timestamps |
| `youtube_import_jobs` | `id`, canonical `video_id`/URL, selected times, rights attestation, import status/progress/message, optional resulting `source_id`, timestamps; independent retryable queue |
| `clips` | `id`, source/job FKs, start/end/title/reason/rank, `edit_json`, operational `status`, `review_status`, `reviewed_render_sha256`, `rendered_path`, time |
| `provider_usage` | Per-job provider/model/input/output usage and timestamp; FK to job |
| `analysis_chunks` | Per-job chunk index, cache key, token count, candidate JSON and timestamp; composite `(job_id,chunk_index)` primary key |
| `youtube_oauth_states` | SHA-256 state hash, creation and epoch expiry; no plaintext state |
| `oauth_authorizations` | Provider-scoped encrypted grant, actual scopes, provider subject, expiry/token status; grants may back multiple provider destinations |
| `youtube_accounts` | Unique channel ID/title/avatar, verification timestamp, actual `granted_scopes_json`, default flag, authorization FK, `connected`/`expired`/`error`/`disconnected`, DPAPI token blob, expiry and safe error text |
| `youtube_oauth_states` additions | Optional target channel `account_id` and `purpose` (`connect` or `analytics`) for channel-bound incremental consent |
| `youtube_publications` | Account, authorization and target-channel snapshot, content type/ID/title snapshot, immutable `attribution_json`, publication and remote status, metadata/category/language/hashtags/native schedule, rendered path/hash/file media metadata, uploaded bytes/session ciphertext, video ID/URL, retry/reconciliation/poll state and timestamps |
| `youtube_analytics_cache` | Channel ID, canonical query hash/JSON, parsed response, actual report coverage, status, fetched/attempted times, and safe error code/message; six-hour reuse, 30-day retention |
| `youtube_upload_jobs` | Source-less Mood upload queue rows; Clip uploads remain in `jobs`; both use one worker/uploader |
| `publishing_metadata_drafts` / `youtube_account_metadata_drafts` / `publishing_metadata_templates` | Shared and per-YouTube-account output drafts, plus reusable metadata templates |
| `publishing_events` | Local timestamped publishing lifecycle events; no OAuth secrets |
| `publishing_thumbnails` | Managed local thumbnail metadata, MIME/size/dimensions, render stat fingerprint, remote status/error |
| `platform_accounts` / `platform_oauth_states` | TikTok/Instagram verified identity, actual scopes, default flag, authorization FK, safe account details, one-use OAuth state, DPAPI token ciphertext and expiry |
| `platform_metadata_drafts` / `platform_account_metadata_drafts` | Shared and account-specific per-content/platform caption, hashtags and options; never shared with YouTube metadata |
| `platform_publications` / `platform_publishing_events` | Manual-export records and lifecycle events; `prepared_manual` means no API transfer |
| `platform_upload_jobs` / `platform_upload_events` | Independent social API queue, target account and authorization snapshot, SHA-256/media snapshot, resumable offset/session ciphertext, remote operation ID, status/poll/retry/error state and safe event history |
| `mood_projects` | Draft settings/topic/provider, selected quote JSON, composition JSON, current generation/render IDs, timestamps; not related to `sources` or `clips` |
| `mood_generations` | Project FK, provider/model, consented request snapshot (no key), five-quote JSON, optional usage counts and timestamp |
| `mood_favorites` | Project FK, optional generation FK, quote JSON snapshot and timestamp; unaffected by regenerate |
| `mood_assets` | Project FK, optional `source_id` and `library_asset_id` FKs (`ON DELETE RESTRICT`), kind/path/mime/size/ffprobe metadata/hash; legacy uploads are project-scoped; V2.7 shared assets are referenced in place |
| `mood_jobs` | Source-less render FIFO records, project/render IDs, status/progress/message and composition/quote snapshot |
| `mood_renders` | Project and mood-job FKs, independent render path/status/review/fingerprint/composition snapshot |
| `video_batches` | Batch type/status, source or Mood source-draft reference, shared clip settings, error and timestamps |
| `video_batch_items` | Ordered item state, clip/Mood draft/job links, custom override, immutable render snapshot/fingerprint, error and retry count |

Indexes include `jobs(status,created_at)`, `youtube_import_jobs(status,created_at)`, `asset_import_jobs(status,created_at)`, `library_assets(kind,created_at)` and `(kind,sha256)`, partial unique `(source,provider_asset_id)`, `clips(source_id,rank)`, publication history by creation time, and partial unique `(account_id,rendered_sha256)` while publication is Pending/Uploading/Processing/Published. Thus same exact approved file cannot be duplicated on same account; a changed, reapproved render can be posted as a new item. Publication `clip_id` has no FK so history survives clip/source deletion; account rows remain after disconnect.

Existing migrations add `sources.transcript_config`, clip review fingerprints, `mood_assets.library_asset_id`, V2.9 batch tables, publishing metadata/event/thumbnail tables, source-less YouTube upload jobs, social account/OAuth/metadata/publication/upload-job tables, additive social `file_size`, account verification/granted-scope fields, OAuth state purpose/target, publication attribution, Analytics cache, and additive publication metadata/status columns. Startup seeds shared video metadata from existing `sources` without moving/copying media; legacy Mood project files remain in place. Previously-approved clip rows without fingerprint are demoted to `needs_review`. Subtitle tracks/styles, scenes, title/audio/export settings persist inside existing `clips.edit_json`; Quick Clip reuses existing `jobs.kind`, `jobs.options_json`, `clips`, and `edit_json`; render jobs snapshot full edit. Batch child drafts reuse clip/Mood project tables, while new batch tables hold ordering/state and immutable child snapshots; no media copy or renderer is added. YouTube import adds `youtube_import_jobs`; Pexels adds asset tables, while successful media remains ordinary `sources`. Mood Quotes retains separate project tables; no fake `sources`/`clips` rows are made. Startup marks interrupted subtitle jobs failed and removes job-scoped local transcription audio; interrupted imports also fail and safely clean scoped temp files. Batch startup recovery pauses active batches and preserves completed outputs. Interrupted YouTube and social transfers fail closed; social jobs with uncertain remote state require provider reconciliation before retry.

V3.2.1 adds provider-scoped `oauth_authorizations`, account defaults, YouTube/social account metadata-draft tables, and authorization/target identity snapshots. Existing encrypted account credentials and actual scopes backfill into grant rows; connected accounts receive one default per provider; queued destination jobs retain history when disconnect cancels work.

## Status lifecycle and worker

### Generic job status

Source-backed: `queued` → `preparing` → (generate: `transcribing` → `analyzing` → `ready_for_review`; render/quick_clip: `rendering` → `completed`; subtitle transcription: `preparing_audio` → optional `uploading` → `transcribing` → `processing_result` → `completed`; translation: `transcribing`/`processing_result` → `completed`) or `failed`/`cancelled`. Mood: `mood_jobs.queued` → `preparing` → `rendering` → `completed` or `failed`/`cancelled`. YouTube import: `queued` → `preparing` → `importing` → `processing` → `ready` or `failed`/`cancelled`. Pexels media import: `queued` → `downloading` (with metadata phase) → `probing` → `ready` or `failed`/`cancelled`; its dedicated single-thread executor is separate from render FIFO. Batch status is independent from child jobs; a batch schedules one next child only after previous child completion. Mood AI quote generation is a consented API request, separate from render queue.

### Clip status

- Operational render: `ready`, `rendering`, `completed`, `needs_render`.
- Review: `needs_review`, `approved`, `needs_revision`.
- New candidates start `ready` + `needs_review`. Successful render sets `completed` + `needs_review`. Edits to values reset approval; rerender request clears approval fingerprint immediately. Approval requires current completed H.264/AAC MP4 and stores its SHA-256. Editing/rerendering status is not inferred from YouTube publication state.
- Mood renders use the same independent `needs_review`/`approved`/`needs_revision` labels and SHA-256 principle, but in `mood_renders`. Editing the selected quote/composition marks the current render `needs_render` and clears fingerprint; prior MP4 remains available until replacement succeeds.

### Publication status

`pending` → `uploading` → `processing` → `published`, or `failed`/`cancelled`. `remote_status` separately tracks upload, processing, and native `scheduled` state. Publication status never replaces Clip/Mood review/render state. Worker persists session URI and acknowledged byte offset; interruption triggers a status probe before resend. Unknown final outcome with expired session has `reconciliation_required=true`; retry endpoint refuses another upload. Processing polls run through same worker only when queue is idle; future native schedules defer remote polling until scheduled time after YouTube confirms processing.

### Social platform upload status

`queued` → `uploading` → `processing` → `awaiting_manual_action` (TikTok Inbox) or provider-confirmed `published`; either path can become `failed`, `cancelled`, or `needs_reconciliation`. TikTok `SEND_TO_USER_INBOX` requires creator action; `PUBLISH_COMPLETE` alone records Published. Instagram `FINISHED` means container ready, then worker requests `media_publish`; only confirmed publish response/status records Published. Instagram resumable bytes use versioned `rupload.facebook.com/ig-api-upload/{version}/{container_id}` URL; container checks request only `status_code`. `needs_reconciliation` blocks unsafe resend. One serial worker handles social jobs and due status polls after existing queue work; cancel during transfer does not claim provider bytes were retracted.

## File paths

Default Windows root is `%LOCALAPPDATA%\Klipnara`; `CLIPPER_DATA_DIR` overrides. Defaults: database `clipper.sqlite3`, temp/logs under `work`/data, sources at `sources`, shared images/audio at `sources/library-assets`, clips at `clips`, legacy Mood uploads under `mood/{project_id}/assets`. Pexels import temp files use scoped `.pexels-import-{job_id}` folders under source root and final MP4 uses `{job_id}.mp4`; shared video has no extra copy. `CLIPPER_SOURCE_DIR` and `CLIPPER_CLIP_DIR` override source/render roots independently. Source clip files use `{clip_id}-{job_id}.mp4`; Mood render files use `mood-{render_id}.mp4` in managed clip output. Subtitle WAV/M4A and ASS/Mood work files are temporary and removed after job; restart recovery removes interrupted subtitle audio by job ID. Gemini provider files are deleted after requests when possible and otherwise expire per provider policy. Do not expose backend to LAN without adding authentication; current CORS/loopback setup is not a multi-user security boundary.

### Backup and rollback

Quick Clip reuses existing schema; optional YouTube/Pexels import and Asset Library add tables/metadata; shared media lives in configured source root while legacy Mood files remain under `MOOD_DIR`. Before updating a real installation, stop backend/Uvicorn so SQLite WAL is closed, back up full `DATA_DIR` plus configured source and clip roots, and retain current application version. For rollback, stop backend, restore database and media roots from same snapshot, then restart prior version. Do not copy only `.sqlite3` while process is running; WAL may contain committed data not checkpointed into that file.

For installation values see [Getting Started](getting-started.md); end-user lifecycle is in [Features and Workflows](features-and-workflows.md).

# API and Database

FastAPI is defined in `backend/clipper/main.py`, title **Klipnara Studio**, version `2.1.0`, API documentation at `/api/docs`. Default local base URL is `http://127.0.0.1:8000`; JSON API paths below include `/api`. Browser CORS allows `localhost:3000` and `127.0.0.1:3000`.

## REST API

### Health, settings, capabilities

| Method/path | Result |
|---|---|
| `GET /api/health` | `{ "status": "ok" }` |
| `GET /api/settings` | CPU/RAM/GPU/runtime capability results, AI model/key-configured flags, data/source/clip/mood roots, free bytes |
| `GET /api/system/capabilities` | Detailed OS, CPU/RAM/GPU, FFmpeg/ffprobe, encoders/filters, Ollama and Whisper detection |
| `POST /api/providers/{provider}/test` | `provider` is `local`, `openai`, or `gemini`; local performs bounded Ollama check, cloud checks configured key only |
| `GET /api/docs` | FastAPI OpenAPI UI |

### Source and generation

| Method/path | Request / response contract |
|---|---|
| `POST /api/sources/upload` | Multipart `file`; validates/stores MP4/MOV, returns source metadata |
| `POST /api/sources/url` | JSON `{ "url": "https://.../media.mp4" }`; direct public HTTPS media only |
| `GET /api/sources` | Source metadata, candidate count, latest non-YouTube job status |
| `GET /api/sources/{source_id}` | Source metadata/transcript and its clips; path/hash removed |
| `GET /api/sources/{source_id}/file` | Inline original media |
| `DELETE /api/sources/{source_id}` | Deletes source and child clips/render files; active source jobs block delete |
| `POST /api/sources/{source_id}/quick-clips` | `QuickClipRequest`; queues timestamp-only render, no transcript or AI |
| `POST /api/sources/{source_id}/generate` | `GenerateOptions`, returns queued job ID |

`GenerateOptions` fields: `count` 3/5/10 (default 5); `duration` `15-30`/`30-60`/`60-90`; `style` Clean/Bold/Highlight; `subtitle_enabled`; `resolution` 720/1080; `focus` center/manual; `provider` local/openai/gemini; `language` auto/indonesia/english; `consent` boolean (false by default). Cloud providers require per-job consent and configured key.

`QuickClipRequest`: nonblank `title` (max 120), `start` seconds (`>=0`), `end` seconds (`>0`, must exceed start and be `<=source.duration`), optional `resolution` 720/1080 (default 720). No maximum Quick Clip duration is imposed beyond source duration. Timestamp parser/preview is frontend-only; API receives seconds.

`sources.audio_codec` is nullable. `probe()` accepts a video-only source; AI Smart Clip returns 409 when it would need to transcribe a source without audio, while Quick Clip proceeds without transcript.

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
| `POST /api/mood-projects/{id}/assets` | Multipart `file` and `kind` (`background_image`, `background_video`, `music`); upload copied to local project storage and ffprobe-validated |
| `POST /api/mood-projects/{id}/source-assets` | `{source_id}`; references managed Source Library video without copying; source deletion is blocked while referenced |
| `DELETE /api/mood-projects/{id}/assets/{asset_id}` | Deletes an unused project asset; source reference is detached but original source remains |
| `GET /api/mood-assets/{asset_id}/thumbnail?time={seconds}` | One cached FFmpeg JPEG frame for a background video; seek time must be within asset duration |
| `POST /api/mood-projects/{id}/render` | Validated full `MoodComposition`; queues source-less `mood_render` job and snapshot |
| `GET /api/mood-projects/{id}/renders` | Render history and review status |
| `GET /api/mood-jobs/{id}` | Mood job status/progress/message, no private options or paths |
| `POST /api/mood-jobs/{id}/cancel` / `retry` | Cancels queued/running render or retries failed/cancelled snapshot |
| `POST /api/mood-renders/{id}/review` | `{status: approved|needs_revision}`; approved H.264/AAC file gets SHA-256 fingerprint |
| `GET /api/mood-renders/{id}/file` / `download` | Inline preview or MP4 download |
| `GET /api/mood-assets/{id}/file` | Managed local image/video/audio asset |
| `DELETE /api/mood-projects/{id}` | Deletes draft, generation/favorite history, project-uploaded assets and render files; active render blocks deletion; referenced Source Library files remain |

`MoodComposition` is Pydantic-validated: 720/1080, 30 FPS, 5–40 seconds; solid/gradient/image/video; optional music trim/volume/fades/loop; typography, Auto Contrast, gradient backing and animation. `text_mode` is `single` or `sequential`; `segments` holds up to eight `{id,text,start,end,animation,animation_duration}` records constrained to output duration without overlap. `visual` is optional for old drafts and defaults to version 1 safe values. It stores `preset_id`, motion (`none`, slow zoom in/out, four pan directions, Ken Burns), intensity, bounded brightness/contrast/saturation/temperature, vignette/grain/dark-overlay/gradient settings, and default segment animation. Text includes validated `font_weight`. Missing `text_mode` is treated as legacy Single Text; new drafts default to Sequential Text. Mode, segments, visual settings and music stay in existing `composition_json`; no SQLite migration. Preset definitions include stable ID, description/category, mood recommendations, preview colors, version, effect/typography/animation defaults, and recommended music mood. Applying preset updates only those visual fields and preserves quote, manual segment/timing, chosen media background asset, and music; solid/gradient backgrounds take preset palette. Active selected audio is signal-checked; silent/corrupt audio fails, while no music or zero volume intentionally permits silent AAC. Asset IDs must belong to draft and requested media kind; text must fit safe frame. Asset caps: image 25 MiB, background video 512 MiB, audio 100 MiB; accepted extensions JPG/JPEG/PNG/WebP, MP4/MOV, MP3/WAV/M4A. Mood outputs are local only; no YouTube route exists.

AI generation accepts only Gemini/OpenAI, requires `consent=true` every request, configured backend key, selected category/subcategory, and sends text settings only. Keys are never persisted or returned. Missing provider/quota/invalid output fails without retry/fallback. Successful generation records provider/model/request settings/consent time/usage where returned in `mood_generations`; not in the source-job `provider_usage` table.

### Clips, review and render

| Method/path | Request / response contract |
|---|---|
| `GET /api/clips` | Clip summaries include operational status, review status, rendered flag and source name |
| `GET /api/clips/{clip_id}` | Clip/edit, source metadata, transcript and non-YouTube clip jobs |
| `PATCH /api/clips/{clip_id}` | Partial `ClipEdit`; edit changes invalidate review fingerprint and mark an existing render stale |
| `POST /api/clips/{clip_id}/review` | JSON `{ "status": "approved" }` or `needs_revision`; validates completed nonempty H.264/AAC MP4. Approval stores SHA-256 of final bytes |
| `POST /api/clips/{clip_id}/render` | Queues render; immediately resets review/fingerprint |
| `GET /api/clips/{clip_id}/file` | Inline final/previous MP4 |
| `GET /api/clips/{clip_id}/download` | Download MP4 |
| `DELETE /api/clips/{clip_id}` | Deletes clip/render; active render or pending/uploading publication blocks |

`ClipEdit`: trim start/end, subtitle toggle, style, output resolution, crop x/y, subtitle size/position/color and indexed text overrides. Backend validates trim stays in candidate and subtitle override text ≤500 characters per segment.

`quick_clip` jobs store an `edit` snapshot in existing `jobs.options_json` and a normal `clips` row. Initial edit uses full selected span, portrait center crop, 720p, subtitle disabled. `origin` returned by clip/source APIs is derived from parent `jobs.kind` (`quick_clip` vs `generate`); it is not a new column.

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
| `GET /api/youtube/config` | Returns readiness, requested scope, redirect URI and local OAuth start URL/error |
| `GET /api/youtube/oauth/start` | Generates state/cookie and redirects to Google |
| `GET /api/youtube/oauth/callback` | Validates state/cookie, exchanges code, reads channel, redirects to frontend without code/token |
| `GET /api/youtube/accounts` | Channel/account status; never returns credential ciphertext |
| `DELETE /api/youtube/accounts/{account_id}` | Revokes token best-effort, clears local ciphertext |
| `POST /api/clips/{clip_id}/youtube-publications` | Manual metadata body: `account_id`, `title`, optional `description`/`tags`, optional `privacy_status` (private default), required booleans `made_for_kids` and `contains_synthetic_media` |
| `GET /api/youtube/publications` | Up to 100 history rows, newest first |
| `GET /api/youtube/publications/{publication_id}` | One status/progress/history record; removes local path/hash/session ciphertext |
| `POST /api/youtube/publications/{publication_id}/cancel` | Pending only, before upload may have started |
| `POST /api/youtube/publications/{publication_id}/retry` | Failed only; reconciles existing resumable session or checks known video ID before any upload |

Publication request validation trims/deduplicates tags, limits combined tag text to 500 characters, title to 100 and description to 5000. Privacy accepted: `private`, `unlisted`, `public`.

### Error behavior

FastAPI returns HTTP errors with `detail`. Common status codes: 400 for unsupported/privacy/consent configuration; 404 for missing resource; 409 for invalid state (unapproved, stale render, active operation, duplicate publication, unsafe retry); 413 for source size limit; 422 for Pydantic/field validation; 507 for insufficient disk. YouTube provider errors are stored as publication `last_error`, never credentials.

## SQLite schema

`connect()` opens the configured DB with 30-second timeout, row factory, foreign keys enabled and commit-on-success. `init_db()` creates data folders, enables WAL, creates tables/indexes, applies additive migrations and recovers interrupted work.

| Table | Important columns / relation |
|---|---|
| `sources` | `id`, unique `path`, original name/size/duration/dimensions/codecs/hash/time, `transcript_json`, model/language/config fingerprint |
| `jobs` | `id`, `source_id` FK cascade, optional `clip_id`, `kind`, `status`, `phase`, progress/message, `options_json`, timestamps |
| `clips` | `id`, source/job FKs, start/end/title/reason/rank, `edit_json`, operational `status`, `review_status`, `reviewed_render_sha256`, `rendered_path`, time |
| `provider_usage` | Per-job provider/model/input/output usage and timestamp; FK to job |
| `analysis_chunks` | Per-job chunk index, cache key, token count, candidate JSON and timestamp; composite `(job_id,chunk_index)` primary key |
| `youtube_oauth_states` | SHA-256 state hash, creation and epoch expiry; no plaintext state |
| `youtube_accounts` | Unique channel ID/title, `connected`/`expired`/`error`/`disconnected`, DPAPI token blob, expiry and safe error text |
| `youtube_publications` | Account FK, plain clip ID/title snapshot, publication status/metadata, rendered path/hash/file media metadata, uploaded bytes/session ciphertext, video ID/URL, retry/reconciliation/poll state and timestamps |
| `mood_projects` | Draft settings/topic/provider, selected quote JSON, composition JSON, current generation/render IDs, timestamps; not related to `sources` or `clips` |
| `mood_generations` | Project FK, provider/model, consented request snapshot (no key), five-quote JSON, optional usage counts and timestamp |
| `mood_favorites` | Project FK, optional generation FK, quote JSON snapshot and timestamp; unaffected by regenerate |
| `mood_assets` | Project FK, optional Source Library FK (`ON DELETE RESTRICT`), kind/path/mime/size/ffprobe metadata/hash; uploaded files are project-scoped, source video is referenced in place |
| `mood_jobs` | Source-less render FIFO records, project/render IDs, status/progress/message and composition/quote snapshot |
| `mood_renders` | Project and mood-job FKs, independent render path/status/review/fingerprint/composition snapshot |

Indexes include `jobs(status,created_at)`, `clips(source_id,rank)`, publication history by creation time, and partial unique `(account_id,rendered_sha256)` while publication is Pending/Uploading/Processing/Published. Thus same exact approved file cannot be duplicated on same account; a changed, reapproved render can be posted as a new item. Publication `clip_id` has no FK so history survives clip/source deletion; account rows remain after disconnect.

Existing migrations add `sources.transcript_config`, `clips.review_status`, and `clips.reviewed_render_sha256` if absent. Previously-approved rows without fingerprint are demoted to `needs_review`. **Quick Clip adds no table or column**; it uses existing `jobs.kind`, `clips`, and `edit_json`. **Mood Quotes adds only new tables/indexes**; it does not alter or fabricate source/clip rows, and existing V1.1/V2.0 schema/data remains intact. Startup marks interrupted generic jobs failed; completed Mood output with a stored path is recovered as completed, interrupted Mood renders fail and clean known temporary/partial output; YouTube recovery remains unchanged.

## Status lifecycle and worker

### Generic job status

Source-backed: `queued` → `preparing` → (generate: `transcribing` → `analyzing` → `ready_for_review`; render/quick_clip: `rendering` → `completed`) or `failed`/`cancelled`. Mood: `mood_jobs.queued` → `preparing` → `rendering` → `completed` or `failed`/`cancelled`. The single worker claims the oldest queued record across `jobs` and `mood_jobs`; maximum concurrent heavy job remains one. Mood AI quote generation is a consented API request, separate from render queue.

### Clip status

- Operational render: `ready`, `rendering`, `completed`, `needs_render`.
- Review: `needs_review`, `approved`, `needs_revision`.
- New candidates start `ready` + `needs_review`. Successful render sets `completed` + `needs_review`. Edits to values reset approval; rerender request clears approval fingerprint immediately. Approval requires current completed H.264/AAC MP4 and stores its SHA-256. Editing/rerendering status is not inferred from YouTube publication state.
- Mood renders use the same independent `needs_review`/`approved`/`needs_revision` labels and SHA-256 principle, but in `mood_renders`. Editing the selected quote/composition marks the current render `needs_render` and clears fingerprint; prior MP4 remains available until replacement succeeds.

### Publication status

`pending` → `uploading` → `processing` → `published`, or `failed`/`cancelled`. Publication status never replaces clip/job status. Worker persists session URI and acknowledged byte offset; interruption triggers a status probe before resend. Unknown final outcome with expired session has `reconciliation_required=true`; retry endpoint refuses another upload. Processing polls run through same worker only when queue is idle.

## File paths

Default Windows root is `%LOCALAPPDATA%\Klipnara`; `CLIPPER_DATA_DIR` overrides. Defaults: database `clipper.sqlite3`, temp/logs under `work`/data, sources at `sources`, clips at `clips`, mood uploads under `mood/{project_id}/assets`. `CLIPPER_SOURCE_DIR` and `CLIPPER_CLIP_DIR` override source/render roots independently. Source clip files use `{clip_id}-{job_id}.mp4`; Mood render files use `mood-{render_id}.mp4` in managed clip output. Transcription WAV/ASS and Mood ASS/gradient/error logs are temporary and cleaned after job. Do not expose backend to LAN without adding authentication; current CORS/loopback setup is not a multi-user security boundary.

### Backup and rollback

Quick Clip does not alter the SQLite schema; Mood Quotes adds dedicated tables and uploaded files under `MOOD_DIR` (default `DATA_DIR/mood`). Existing V1.1 additive review/YouTube migrations still run at startup. Before updating a real installation, stop backend/Uvicorn so SQLite WAL is closed, back up the full `DATA_DIR` (including mood assets) plus configured source and clip roots, and retain the current application version. For rollback, stop backend, restore the database and media roots from the same snapshot, then restart the prior application version. Do not copy only the `.sqlite3` file while the process is running; WAL may contain committed data not checkpointed into that file.

For installation values see [Getting Started](getting-started.md); end-user lifecycle is in [Features and Workflows](features-and-workflows.md).

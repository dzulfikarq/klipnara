# API and Database

FastAPI is defined in `backend/clipper/main.py`, title **Klipnara**, version `1.1.0`, API documentation at `/api/docs`. Default local base URL is `http://127.0.0.1:8000`; JSON API paths below include `/api`. Browser CORS allows `localhost:3000` and `127.0.0.1:3000`.

## REST API

### Health, settings, capabilities

| Method/path | Result |
|---|---|
| `GET /api/health` | `{ "status": "ok" }` |
| `GET /api/settings` | CPU/RAM/GPU/runtime capability results, AI model/key-configured flags, data/source/clip roots, free bytes |
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
| `POST /api/sources/{source_id}/generate` | `GenerateOptions`, returns queued job ID |

`GenerateOptions` fields: `count` 3/5/10 (default 5); `duration` `15-30`/`30-60`/`60-90`; `style` Clean/Bold/Highlight; `subtitle_enabled`; `resolution` 720/1080; `focus` center/manual; `provider` local/openai/gemini; `language` auto/indonesia/english; `consent` boolean (false by default). Cloud providers require per-job consent and configured key.

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

Indexes include `jobs(status,created_at)`, `clips(source_id,rank)`, publication history by creation time, and partial unique `(account_id,rendered_sha256)` while publication is Pending/Uploading/Processing/Published. Thus same exact approved file cannot be duplicated on same account; a changed, reapproved render can be posted as a new item. Publication `clip_id` has no FK so history survives clip/source deletion; account rows remain after disconnect.

Migrations add `sources.transcript_config`, `clips.review_status`, and `clips.reviewed_render_sha256` if absent. Previously-approved rows without fingerprint are demoted to `needs_review`. Startup marks interrupted generic jobs failed; an in-flight YouTube item with known video ID resumes as Processing, an uncertain upload becomes Failed for reconciliation, and pending jobs whose worker stopped are marked Failed.

## Status lifecycle and worker

### Generic job status

`queued` → `preparing` → (generation: `transcribing` → `analyzing` → `ready_for_review`; render: `rendering` → `completed`) or `failed`/`cancelled`. `ready_for_review` is generation job status, not a clip approval status. Queue selects oldest `queued` job; one worker thread runs at a time.

### Clip status

- Operational render: `ready`, `rendering`, `completed`, `needs_render`.
- Review: `needs_review`, `approved`, `needs_revision`.
- New candidates start `ready` + `needs_review`. Successful render sets `completed` + `needs_review`. Edits to values reset approval; rerender request clears approval fingerprint immediately. Approval requires current completed H.264/AAC MP4 and stores its SHA-256. Editing/rerendering status is not inferred from YouTube publication state.

### Publication status

`pending` → `uploading` → `processing` → `published`, or `failed`/`cancelled`. Publication status never replaces clip/job status. Worker persists session URI and acknowledged byte offset; interruption triggers a status probe before resend. Unknown final outcome with expired session has `reconciliation_required=true`; retry endpoint refuses another upload. Processing polls run through same worker only when queue is idle.

## File paths

Default Windows root is `%LOCALAPPDATA%\Klipnara`; `CLIPPER_DATA_DIR` overrides. Defaults: database `clipper.sqlite3`, temp/logs under `work`/data, sources at `sources`, clips at `clips`. `CLIPPER_SOURCE_DIR` and `CLIPPER_CLIP_DIR` override media roots independently. Render files are named `{clip_id}-{job_id}.mp4`; transient transcription audio/ASS files are removed after job. Do not expose backend to LAN without adding authentication; current CORS/loopback setup is not a multi-user security boundary.

For installation values see [Getting Started](getting-started.md); end-user lifecycle is in [Features and Workflows](features-and-workflows.md).

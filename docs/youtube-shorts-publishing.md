# YouTube Publishing & Analytics — V3.1

Implementation and operations guide for Klipnara's personal, local-first YouTube publishing and analytics. Publishing uses official YouTube Data API v3; Analytics uses official YouTube Analytics API v2. Metadata remains manual; native schedules are created by YouTube, not a local timer. No other social platforms.

System integration and persistence are described in [API and Database](api-and-database.md); first-time runtime setup is in [Getting Started](getting-started.md).

## Scope and invariants

- OAuth: Google Authorization Code Flow, backend-only client secret, actual Google-granted scopes persisted. Publishing requires `https://www.googleapis.com/auth/youtube.upload`; channel identity and Analytics `reports.query` require `https://www.googleapis.com/auth/youtube.readonly`; Analytics reports require `https://www.googleapis.com/auth/yt-analytics.readonly`. No monetary scope.
- Publish eligibility: Clip or Mood render review is `approved`; render status is `completed`; current non-empty MP4 is inside managed clip storage, contains H.264/AAC, is square or portrait, is at most 180 seconds, and matches SHA-256 stored at approval. Silent-source Quick Clips receive a silent AAC track from FFmpeg and still use same gate.
- Quick Clip and AI Smart Clip share existing approval and upload checks; direct timestamp cut does not trigger AI or auto-publish.
- Publication lifecycle is independent of clip review/render lifecycle: `pending`, `uploading`, `processing`, `published`, `failed`, `cancelled`.
- Metadata is manual: title, description, tags, hashtags, category, language, privacy, Made for Kids, synthetic-media disclosure, optional schedule. Privacy default is `private`; user confirms values before enqueue.
- No request is marked `published` until YouTube returns video ID and `videos.list` confirms processed status, expected channel, requested privacy, and schedule outcome where applicable.
- Native scheduling requires timezone-aware future time plus Private visibility; YouTube owns scheduled publication. A schedule in the past is rejected to avoid accidental immediate visibility.
- Custom thumbnail is successful only after `thumbnails.set` returns a thumbnail resource; local selection or failed request never looks remotely applied.
- `videos.insert` upload is resumable. Progress uses server-acknowledged `Range` bytes. Unknown upload outcome fails closed; no blind retry.

Implemented in `backend/clipper/youtube.py`, FastAPI routes in `backend/clipper/main.py`, queue integration in `backend/clipper/jobs.py`, schema in `backend/clipper/db.py`, Publishing Studio in `frontend/app/publishing/page.tsx`, Connected Accounts in `frontend/app/accounts/page.tsx`, and existing Clip Editor publish confirmation.

## Google Cloud setup

1. Create/select Google Cloud project and enable **YouTube Data API v3** and **YouTube Analytics API**. Analytics API is required only for reports; publishing remains on the existing Data API uploader.
2. Configure OAuth consent screen. For personal testing, set audience External/Testing and add the channel's Google account as a test user. Public distribution may require Google's OAuth verification and YouTube API compliance review for the requested scope.
3. Create OAuth Client ID with type **Web application**. In **Akun → Lihat Panduan Setup**, copy **Callback URL Klipnara** into **Authorized redirect URIs** exactly. The UI reads the effective URI from `GET /api/youtube/config`; if backend cannot validate it, check `YOUTUBE_REDIRECT_URI` in the backend environment and do not use a guessed URL. When the variable is unset, current backend default is `http://localhost:8000/api/youtube/oauth/callback`.

4. Set these values in `backend/.env`; keep real values out of source control:

   ```dotenv
   YOUTUBE_CLIENT_ID=your-client-id.apps.googleusercontent.com
   YOUTUBE_CLIENT_SECRET=your-client-secret
   # Optional override; match the callback URI shown by Connected Accounts exactly.
   # YOUTUBE_REDIRECT_URI=http://localhost:8000/api/youtube/oauth/callback
   YOUTUBE_FRONTEND_URL=http://localhost:3000/accounts
   ```

5. Reload backend after editing environment, then open **Akun → Hubungkan YouTube**. The guided UI's configured state means backend found both credential variables and a valid callback; it does not mean a channel is connected. New consent requests `youtube.upload`, `youtube.readonly`, and `yt-analytics.readonly`; Analytics consent can also be added later from **Aktifkan Analytics** on one verified account. Klipnara adds/updates a channel card only after token exchange and successful channel identity lookup; grants exposing multiple channels are rejected rather than guessed.

Connect additional Google identities with **Hubungkan Channel Lain**. OAuth uses `prompt=select_account`; this switches Google identity but does not select among multiple YouTube channels returned by one grant. Multiple-channel grants remain fail-closed. Each connected channel has a default flag, separate metadata overrides, and independently queued publication records.

`YOUTUBE_REDIRECT_URI` must use a loopback host, explicit port, and exact callback path `/api/youtube/oauth/callback`. Authorization and token exchange both read this same backend value; changing it between start and callback invalidates the authorization code. `GET /api/youtube/config` returns effective callback URI, current scopes, `configured`, local `start_url`, and safe `redirect_error`; it never returns Client Secret or token. Browser starts OAuth on same host as redirect URI so the HttpOnly, SameSite=Lax state cookie returns on Google's top-level GET callback. Each OAuth attempt gets its own state-cookie name, so starting Analytics consent or another connection does not overwrite an outstanding attempt. HTTP loopback uses a non-Secure cookie; HTTPS callback uses Secure. State remains random, hash-stored, one-time, and ten-minute-bound. `YOUTUBE_FRONTEND_URL` must be a local frontend URL. Backend should remain bound to loopback.

Channel verification needs read permission in addition to upload permission. Google's official [YouTube v3 Discovery document](https://www.googleapis.com/discovery/v1/apis/youtube/v3/rest) lists accepted OAuth scopes per method: `channels.list` accepts `youtube.readonly` but not `youtube.upload`; [`videos.insert`](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert) accepts `youtube.upload` for uploads. YouTube Analytics [`reports.query`](https://developers.google.com/youtube/analytics/reference/reports/query) requires `youtube.readonly`; `yt-analytics.readonly` grants read-only Analytics access. Klipnara requests only these needed capabilities—not broader `youtube`/`youtube.force-ssl` or monetary scopes. Human references: [`channels.list`](https://developers.google.com/youtube/data/reference/rest/v3/channels/list), [`videos.insert`](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert), [Analytics authorization](https://developers.google.com/youtube/analytics/guides/authentication).

Callback redirects contain only a safe error code, never Google error text, authorization code, state, cookie, or token. Codes distinguish state, token exchange, insufficient scope, channel missing/multiple, YouTube API, and token-storage failures. Unexpected callback exceptions map to `oauth_connection_failed`; local logs record only exception type and source location, not exception text or credentials. State is consumed before code exchange. Tokens stay in callback memory until channel lookup succeeds; encrypted persistence happens last. If lookup or persistence fails, no new connected row/token is written. Existing valid stored credentials are not revoked during cleanup, since revocation could invalidate a prior grant; the unpersisted access token is discarded.

Google OAuth external apps in Testing can have limited refresh-token lifetime; reauthorize after `invalid_grant`. If Google returns no refresh token, revoke Klipnara in Google Account settings and connect again with consent. Accounts exposing multiple channels are rejected because no chooser exists; reconnect with grant exposing one intended channel. Account page can verify stored channel ID/title/avatar. Returned video channel ID is checked before `Published`.

Actual grant scopes, not requested scopes, are persisted in `youtube_accounts.granted_scopes_json`. If token exchange omits `scope`, backend verifies access token through Google's token-info endpoint; unverifiable scopes fail closed. Authorization URL uses incremental grants. Analytics consent stores target channel ID and purpose in one-use OAuth state, requests `yt-analytics.readonly` plus `youtube.readonly`, and calls `channels.list(id=stored_channel_id)` before updating the existing row. A channel mismatch, unverifiable grant, or removal of previously recorded scopes leaves stored credentials unchanged. Older accounts with unknown actual scopes must reconnect with upload/read grants before publishing; Analytics cannot rely on unknown scope. Grant omission is never inferred from OAuth request parameters.

Account state map: `connected` after token exchange and channel lookup; `expired` after missing/invalid refresh token (`invalid_grant`); `error` after rejected OAuth client/refreshed auth; `disconnected` after user action clears local ciphertext and revocation is attempted. Reconnect can reuse an existing account row by channel ID. `upload_ready`/`analytics_ready` derive only from persisted actual scopes.

## Credential and callback security

- Google password is never requested or handled by Klipnara.
- Access/refresh tokens and resumable session URI are encrypted in SQLite with Windows user-scoped DPAPI. They can only be decrypted by same Windows user. Data-folder move, Windows account change, or token corruption requires reconnecting.
- OAuth state is 256-bit random, stored as SHA-256 hash, expires after ten minutes, is one-use, and is bound to HttpOnly/SameSite=Lax cookie. Callback validates both values before exchanging code.
- Callback immediately redirects without rendering code-bearing page. Uvicorn access log filter strips callback query string. OAuth client secret remains in backend process environment; tokens never appear in frontend responses.
- Disconnect attempts Google token revocation, then clears local encrypted token and marks account `disconnected`. UI reports if remote revocation was not confirmed.

## Data and API contract

SQLite adds:

- `youtube_oauth_states`: state hash and expiration.
- `oauth_authorizations`: provider-scoped encrypted grant, actual scopes, subject ID, expiry and token status; grants may back multiple provider accounts.
- `youtube_accounts`: channel identity/avatar/verification time, actual granted scopes, default flag, authorization ID, account state, DPAPI ciphertext, token expiry, safe error message.
- `youtube_publications`: manual metadata, content type/ID, immutable `attribution_json` snapshot, category/language/hashtags/native schedule, account/authorization/target-channel snapshot, output path and SHA-256 snapshot, file dimensions/duration, acknowledged bytes, encrypted resumable URI, video ID/URL, attempts, remote status, processing polls, reconciliation flag, and independent publication status.
- `youtube_analytics_cache`: channel ID, canonical report query/key, parsed response, actual date coverage, cache/sync status, timestamps, safe error code/message. Six-hour successful-response reuse; 30-day cleanup; disconnect clears cache rows for that channel.
- `youtube_upload_jobs`: source-less Mood upload queue; Clip upload keeps existing `jobs` row.
- `publishing_metadata_drafts`, `youtube_account_metadata_drafts`, `publishing_metadata_templates`, `publishing_events`, `publishing_thumbnails`: shared and per-channel drafts/templates/lifecycle/thumbnail state.
- `clips.reviewed_render_sha256`: exact MP4 fingerprint captured on approval. Editing or queueing another render clears it; render completion returns clip to `needs_review`. Existing `approved` clips without fingerprint migrate to `needs_review` and need one fresh approval.

Main routes:

| Route | Purpose |
|---|---|
| `GET /api/youtube/config` | Backend credential readiness, current scope, effective redirect URI, local start URL, and safe callback error; never credentials or tokens |
| `GET /api/youtube/oauth/start?account_id={id}` | Optional channel-bound incremental Analytics consent; no new OAuth system |
| `GET /api/youtube/oauth/callback` | Validate state, exchange code, read exact target channel identity and actual scope, then encrypt/store tokens; redirects with safe result/error code only |
| `GET /api/youtube/accounts` | Return account/channel states and actual-scope readiness without credentials |
| `POST /api/youtube/accounts/{id}/default` | Set connected YouTube default destination |
| `POST /api/youtube/accounts/{id}/verify` | Verify stored channel ID and refresh title/avatar |
| `DELETE /api/youtube/accounts/{id}` | Cancel this channel's queued uploads, preserve history, and revoke unshared grant best-effort |
| `GET /api/youtube/analytics?account_id=&scope=channel\|klipnara&start_date=&end_date=&force=` | Channel or linked Klipnara reports, comparison period, coverage, videos, insights and cache state |
| `GET /api/youtube/analytics/publications/{id}` | Daily metrics for one successful local publication |
| `GET /api/youtube/analytics/publications/{id}/retention` | One-video audience-retention report |
| `GET /api/publishing/content` | List Clip/Mood outputs, review eligibility, drafts and thumbnail state |
| `GET/PUT /api/publishing/{clip\|mood_render}/{content_id}/metadata?account_id=` | Read/save shared draft or selected channel override; no upload |
| `GET/POST /api/publishing/metadata-templates`, `DELETE .../{id}` | Manage reusable metadata templates |
| `GET /api/publishing/calendar` / `GET /api/publishing/events` | List schedule and local lifecycle event history |
| `POST /api/publishing/{clip\|mood_render}/{content_id}/youtube` | Validate and independently enqueue selected destination channels |
| `POST/GET /api/publishing/{clip\|mood_render}/{content_id}/thumbnail` | Save/serve render-bound local thumbnail |
| `POST /api/youtube/publications/{id}/thumbnail` | Apply custom thumbnail to existing video |
| `POST /api/clips/{clip_id}/youtube-publications` | Backward-compatible Clip-only route |
| `GET /api/youtube/publications` | Publishing History |
| `GET /api/youtube/publications/{id}` | Current status/progress |
| `POST /api/youtube/publications/{id}/cancel` | Cancel before any media bytes may have been sent |
| `POST /api/youtube/publications/{id}/retry` | Resume a failed, reconcilable upload or recheck known video ID |

Generic `/api/jobs/{id}/retry` and `/cancel` do not control YouTube uploads. Publishing actions go through publication endpoints so duplicate reconciliation and cancellation rules stay enforced.

Publish request requires `confirmed=true`, `account_id`, nonblank `title` (≤100), `made_for_kids`, and `contains_synthetic_media`. Optional fields: description (≤5000 UTF-8 bytes including hashtags), tags (combined ≤500 characters), hashtags, category, video language, and privacy (`private`, `unlisted`, `public`; default `private`). `publish_at` needs ISO 8601 with explicit timezone, Private visibility, and time at least two minutes ahead. Browser-local `datetime-local` is converted to UTC before explicit confirmation. Past schedule is blocked because YouTube may publish it immediately.

Metadata drafts/templates stay local; saving one never enqueues upload. Batch Creator provides links only for individually approved outputs. Each item still needs its own metadata review and final confirmation. Thumbnail uploads accept JPEG/PNG ≤2 MiB, ≥640×360 landscape. Thumbnail state is bound to current output and publication SHA-256; failed `thumbnails.set` stays failed, never successful-looking.

Duplicate protection is per connected account and exact approved-render SHA-256. A new changed render can be published after it is approved again; same bytes cannot be uploaded twice to same account. Clip and Mood review/render states stay separate from publication state. Cancellation requires publication `pending`, worker queued/preparing, and `upload_started=false`; after bytes may have been sent, user must resume/reconcile rather than cancel. Processing/published history remains available separately from render/review states.

## Upload and reconciliation behavior

1. Queue transaction checks account connected, no active render, approved status, render completion, file path, MP4/H.264/AAC, square/portrait ratio, duration ≤180 seconds, and approval SHA-256. It inserts publication and worker job atomically. Clip uses `jobs`; Mood uses source-less `youtube_upload_jobs`.
2. Same serial worker sends both through same `run_upload`. Worker rechecks current approval fingerprint. It creates Google resumable session using `videos.insert?uploadType=resumable&part=snippet,status`; metadata includes privacy/audience declarations, category/tags/language, and optional `status.publishAt`.
3. Session URI is DPAPI encrypted. Worker sends 8 MiB chunks (multiple of 256 KiB) with `Content-Range`. HTTP 308 `Range` determines acknowledged offset; progress never counts bytes merely read locally.
4. Timeout, connection loss, 401, 429, rate-limit 403, and retryable 5xx use bounded retry/backoff and session status probe (`PUT Content-Range: bytes */size`) before resending. Access tokens refresh once on 401; `invalid_grant` marks account `expired`.
5. On interruption/restart, retry probes saved session before sending. Completed session response recovers video ID; incomplete session resumes at acknowledged byte. If session expires after bytes may have been sent and no video ID can be recovered, publication is `failed` with `reconciliation_required`; automatic retry is blocked. User must inspect YouTube Studio. Klipnara does not search by title because title matching cannot prove duplicate identity.
6. Once video ID is saved, state moves to `processing`; existing worker checks `videos.list` when queue is idle. Processing errors/auth loss do not trigger another upload. `Published` requires `uploadStatus=processed`, successful/available processing state, selected channel, requested privacy, and schedule outcome. Future native schedules report `remote_status=scheduled`; worker defers polling until schedule time after YouTube confirms processing. Metadata disclosure fields are checked when YouTube returns them.
7. Custom thumbnail uses official `thumbnails.set` media upload after a video ID exists. Only a successful response containing returned thumbnail resource sets remote state to `applied`.

Processing polling pauses while other worker jobs run. Schedule visibility is owned by YouTube; local app downtime does not cancel or delay schedule.

## YouTube Analytics V3.1

Analytics is an optional tab in the existing Publishing Studio. It uses the same connected channel account and backend OAuth token; it does not add another consent system, uploader, channel chooser, or separate account store. `reports.query` uses the stored `channel_id`; request accepts `account_id`, never arbitrary channel ID. Only read scopes are added. No scraping, earnings/revenue, estimates, or generated metrics.

### Report semantics

- **Channel** scope requests channel-wide official metrics. **Klipnara** scope filters reports to video IDs in successful `youtube_publications` rows for the selected account. These totals remain separate and must not be combined or described as equivalent.
- YouTube Analytics accepts one video ID in the `video` filter, not comma-separated IDs. Klipnara scope queries each linked video separately, combines official daily counts, and view-weights rate metrics. Successful per-video query pages are cached independently for six hours.
- `views` and `engagedViews` are distinct API metrics and stay separate in summary, trend, table, comparison, and CSV. Other available values include watch time, average duration/percentage, likes, comments, shares; subscriber metrics appear only for channel scope.
- The default range is the last 28 complete UTC days. Current UTC day is excluded because reporting can be incomplete. Explicit range allows at most 366 inclusive days. Responses include requested range and actual coverage; YouTube Analytics may report fewer dates than requested.
- Reports page at 200 rows. Date ranges are split into ≤200-day requests; channel video details page through at most 500 rows. Local Klipnara attribution also reads at most 500 newest published records and reports when that cap is reached.
- Dashboard compares an equal-length immediately preceding period. Counts use absolute/percentage deltas; duration/percentage rates use view-weighted averages. Missing/zero previous data has no fabricated percentage delta.
- Per-video detail is available only for local publication IDs. Retention queries `audienceWatchRatio` and `relativeRetentionPerformance` for one video ID per request, mapping elapsed ratios to immutable output duration. New/small videos may return no retention rows.
- Insights are deterministic rules over attributed video reports, grouped by workflow or subtitle type. Each compared group needs at least five videos. UI labels timeframe and sample count; median differences are descriptive, not causal or predictive.
- Local CSV export includes only the selected response's summary, daily rows and video rows. Spreadsheet-formula-like text is escaped before download.

### Cache and errors

Successful canonical report queries are cached by channel/query for six hours. `force=true` bypasses successful cache; failures receive a short retry cooldown, and cache records older than 30 days are deleted. Disconnect clears only that channel's Analytics cache; account history/publications remain. Cache stores query/response/coverage and safe error code/message, never OAuth tokens or media. All report responses stay in local SQLite and browser memory.

FastAPI errors return `detail: {code,message}`. Expected codes include `analytics_scope_required`, `analytics_api_disabled`, `youtube_data_api_disabled`, `analytics_permission_required`, `analytics_quota_exceeded`, `analytics_rate_limited`, `analytics_query_invalid`, `analytics_video_unavailable`, `analytics_date_invalid`, `oauth_reauthorization_required`, and `analytics_temporarily_unavailable`. UI retains a prior successful result with an error notice after forced-refresh failure; initial failure remains an error, not zero metrics. Raw Google response and credentials are not returned.

### Immutable production attribution

New publication creation snapshots compact `attribution_json` inside `youtube_publications`: content/workflow type, render ID/duration/resolution/time, caption type/preset, visual preset, FPS/scenes, optional hook duration, sanitized audio settings, and batch ID/type/fingerprint. Snapshot is written in same local transaction as upload queue row and never reconstructed from mutable drafts. Historical publications created before this migration have null attribution and remain unattributed. YouTube metrics are still the only source for performance counts.

Rules and limits: publication history and channel video detail are capped at 500 records per response; linked video reports require individual API queries and can be quota-limited. No monetization scope is requested. Channel reports can include videos never made in Klipnara; only attributed scope relates records to local production metadata.

## UI flow

1. If OAuth is not configured, open **Akun → Lihat Panduan Setup**. Six collapsible steps cover Google Cloud project/API/consent/client, backend-only environment setup, and channel connection. Callback and requested scope set come from backend config; no Google Cloud step is automatically marked complete. Copy buttons contain the displayed callback or placeholder-only environment values, never actual credentials.
2. Connect/reconnect YouTube from **Akun**; verify channel identity and inspect account status. Backend readiness alone does not create a connected channel.
3. Open **YouTube Studio** or a `Publish this item` link from Batch Creator. Only current approved/completed outputs pass server gate; approve each batch output separately.
4. Preview Clip or Mood render; edit metadata, tags/hashtags, category/language, privacy, optional local-time schedule, and audience declarations. Save local draft or reusable template without uploading.
5. Choose local JPEG/PNG thumbnail if desired. After upload, use History to apply thumbnail; UI reports failure unless YouTube confirms.
6. Review summary and explicit confirmation checkbox, then queue. Private is default; schedule requires Private.
7. Queue, Calendar, and History show upload/processing/scheduled/published/error state, acknowledged-byte progress, retry/cancel affordances, and video link.

## Quota and official references

At documentation check, YouTube lists a separate **100 `videos.insert` calls/day** upload bucket (method cost 1 in that bucket); general project quota defaults to 10,000 units/day, with `channels.list`/`videos.list` cost 1 unit each. Confirm current values in Google Cloud Console before batch use.

- [Videos: insert](https://developers.google.com/youtube/v3/docs/videos/insert)
- [Resumable uploads](https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol)
- [Channels: list](https://developers.google.com/youtube/v3/docs/channels/list)
- [Videos: list](https://developers.google.com/youtube/v3/docs/videos/list)
- [Videos resource and `status.publishAt`](https://developers.google.com/youtube/v3/docs/videos)
- [Thumbnails: set](https://developers.google.com/youtube/v3/docs/thumbnails/set)
- [Google OAuth web-server flow](https://developers.google.com/identity/protocols/oauth2/web-server)
- [YouTube Shorts eligibility](https://support.google.com/youtube/answer/15424877)
- [Quota](https://developers.google.com/youtube/v3/determine_quota_cost)

## Verification and limits

Run mocked integration tests from `backend`:

```powershell
.venv\Scripts\python.exe tests\test_youtube.py
.venv\Scripts\python.exe tests\test_youtube_analytics.py
```

Mocked publishing tests cover DPAPI round-trip, OAuth state/callback/redirect URI/cookie, code exchange, actual required scopes, incremental consent preservation, channel lookup, token-storage failure, multi-channel rejection, channel verification/disconnect, token `invalid_grant`, Clip/Mood approval/fingerprint gates, native schedule payload/lifecycle, metadata/templates/events, source-less worker dispatch, thumbnail confirmation/failure, chunk byte ranges, transient interruption resume, retry endpoint resume, duplicate prevention, cancellation before upload, and unknown-outcome fail-closed reconciliation. Analytics test covers response parsing, separate metrics/scopes, cache reuse, comparison, detail, retention, and structured scope/date errors using mocked reports. Frontend Node test covers OAuth notification states. Google network calls are mocked. Tests and frontend validation are not run for this change; no live OAuth/upload/schedule/thumbnail/Analytics call was performed.

No live OAuth credentials are configured in this checkout; no real upload or video ID has been verified. Before public use, user can run one Private upload and verify video ID, channel, privacy, native schedule, and thumbnail in YouTube Studio. No multi-channel chooser, other social platforms, multi-user auth, or AI captions. YouTube can still reject a valid file for account/channel policy, copyright, content, quota, or API project restrictions.

# YouTube Shorts Publishing — V1.1

Implementation and operations guide for Klipnara's personal, local-first YouTube publisher. Feature uses official YouTube Data API v3 only. No AI caption generation, scheduled posting, or other social platforms.

## Scope and invariants

- OAuth: Google Authorization Code Flow, backend-only client secret, minimum requested scope `https://www.googleapis.com/auth/youtube.upload`.
- Publish eligibility: clip review is `approved`; render status is `completed`; current non-empty MP4 is inside managed clip storage, contains H.264/AAC, is square or portrait, is at most 180 seconds, and matches SHA-256 stored at approval.
- Publication lifecycle is independent of clip review/render lifecycle: `pending`, `uploading`, `processing`, `published`, `failed`, `cancelled`.
- Metadata is manual: title, description, tags, privacy, Made for Kids, synthetic-media disclosure. Privacy default is `private`; user confirms values before enqueue.
- No request is marked `published` until YouTube returns video ID and `videos.list` confirms processed status, expected channel, and requested privacy.
- `videos.insert` upload is resumable. Progress uses server-acknowledged `Range` bytes. Unknown upload outcome fails closed; no blind retry.

## Google Cloud setup

1. Create/select Google Cloud project and enable **YouTube Data API v3**.
2. Configure OAuth consent screen. For personal testing, set audience External/Testing and add the channel's Google account as a test user. Public distribution may require Google's OAuth verification and YouTube API compliance review for the requested scope.
3. Create OAuth Client ID with type **Web application**. Add exact authorized redirect URI:

   ```text
   http://localhost:8000/api/youtube/oauth/callback
   ```

4. Set these values in `backend/.env`; keep real values out of source control:

   ```dotenv
   YOUTUBE_CLIENT_ID=your-client-id.apps.googleusercontent.com
   YOUTUBE_CLIENT_SECRET=your-client-secret
   YOUTUBE_REDIRECT_URI=http://localhost:8000/api/youtube/oauth/callback
   YOUTUBE_FRONTEND_URL=http://localhost:3000/accounts
   ```

5. Start backend with existing `uvicorn ... --env-file .env` command and open **Akun → Hubungkan YouTube**. Consent displays upload access. Connected Accounts shows first channel returned by `channels.list(mine=true)`.

`YOUTUBE_REDIRECT_URI` must use a loopback host, explicit port, and exact callback path. Browser starts OAuth on same host as redirect URI so HttpOnly state cookie returns to callback. `YOUTUBE_FRONTEND_URL` must be a local frontend URL. Backend should remain bound to loopback.

Google OAuth external apps in Testing can have limited refresh-token lifetime; reauthorize after `invalid_grant`. If Google returns no refresh token, revoke Klipnara in Google Account settings and connect again with consent. Accounts exposing multiple channels have no chooser in V1.1; returned video channel ID is checked before `Published`.

## Credential and callback security

- Google password is never requested or handled by Klipnara.
- Access/refresh tokens and resumable session URI are encrypted in SQLite with Windows user-scoped DPAPI. They can only be decrypted by same Windows user. Data-folder move, Windows account change, or token corruption requires reconnecting.
- OAuth state is 256-bit random, stored as SHA-256 hash, expires after ten minutes, is one-use, and is bound to HttpOnly/SameSite=Lax cookie. Callback validates both values before exchanging code.
- Callback immediately redirects without rendering code-bearing page. Uvicorn access log filter strips callback query string. OAuth client secret remains in backend process environment; tokens never appear in frontend responses.
- Disconnect attempts Google token revocation, then clears local encrypted token and marks account `disconnected`. UI reports if remote revocation was not confirmed.

## Data and API contract

SQLite adds:

- `youtube_oauth_states`: state hash and expiration.
- `youtube_accounts`: channel identity, account state, DPAPI ciphertext, token expiry, safe error message.
- `youtube_publications`: manual metadata, account/clip IDs, output path and SHA-256 snapshot, file dimensions/duration, acknowledged bytes, encrypted resumable URI, video ID/URL, attempts, processing polls, reconciliation flag, and independent publication status.
- `clips.reviewed_render_sha256`: exact MP4 fingerprint captured on approval. Editing or queueing another render clears it; render completion returns clip to `needs_review`. Existing `approved` clips without fingerprint migrate to `needs_review` and need one fresh approval.

Main routes:

| Route | Purpose |
|---|---|
| `GET /api/youtube/config` | OAuth readiness, exact redirect URI, and local start URL |
| `GET /api/youtube/oauth/start` | Create state and redirect to Google |
| `GET /api/youtube/oauth/callback` | Validate state, exchange code, read channel identity, encrypt tokens |
| `GET /api/youtube/accounts` | Return account/channel states without credentials |
| `DELETE /api/youtube/accounts/{id}` | Revoke best-effort and disconnect locally |
| `POST /api/clips/{clip_id}/youtube-publications` | Validate approval/render and enqueue manual metadata |
| `GET /api/youtube/publications` | Publishing History |
| `GET /api/youtube/publications/{id}` | Current status/progress |
| `POST /api/youtube/publications/{id}/cancel` | Cancel before any media bytes may have been sent |
| `POST /api/youtube/publications/{id}/retry` | Resume a failed, reconcilable upload or recheck known video ID |

Generic `/api/jobs/{id}/retry` and `/cancel` do not control YouTube uploads. Publishing actions go through publication endpoints so duplicate reconciliation and cancellation rules stay enforced.

Duplicate protection is per connected account and exact approved-render SHA-256. A new changed render can be published after it is approved again; same bytes cannot be uploaded twice to same account. Pending/uploading clips cannot be edited, re-reviewed, rerendered, or deleted. Processing/published history remains available separately from render/review states.

## Upload and reconciliation behavior

1. Queue transaction checks account connected, no active render, approved status, render completion, file path, MP4/H.264/AAC, square/portrait ratio, duration ≤180 seconds, and approval SHA-256. It inserts publication and existing worker job atomically.
2. Worker rechecks current approval fingerprint. It creates Google resumable session using `videos.insert?uploadType=resumable&part=snippet,status`; metadata includes `privacyStatus`, `selfDeclaredMadeForKids`, and `containsSyntheticMedia`.
3. Session URI is DPAPI encrypted. Worker sends 8 MiB chunks (multiple of 256 KiB) with `Content-Range`. HTTP 308 `Range` determines acknowledged offset; progress never counts bytes merely read locally.
4. Timeout, connection loss, 401, 429, rate-limit 403, and retryable 5xx use bounded retry/backoff and session status probe (`PUT Content-Range: bytes */size`) before resending. Access tokens refresh once on 401; `invalid_grant` marks account `expired`.
5. On interruption/restart, retry probes saved session before sending. Completed session response recovers video ID; incomplete session resumes at acknowledged byte. If session expires after bytes may have been sent and no video ID can be recovered, publication is `failed` with `reconciliation_required`; automatic retry is blocked. User must inspect YouTube Studio. Klipnara does not search by title because title matching cannot prove duplicate identity.
6. Once video ID is saved, state moves to `processing`; existing worker checks `videos.list` when queue is idle. Processing errors/auth loss do not trigger another upload. `Published` requires `uploadStatus=processed`, successful/available processing state, selected channel, and requested privacy. Metadata disclosure fields are checked when YouTube returns them.

Processing polling pauses while other worker jobs run. V1.1 supports Post Now only; no scheduler.

## UI flow

1. Connect/reconnect YouTube from **Akun**; inspect channel title, channel ID, and Connected/Expired/Error/Disconnected state.
2. In Clip Editor, **Posting ke YouTube** appears only for approved, completed final render with no unsaved edits.
3. Preview final MP4; manually enter required title, optional description/tags, privacy, explicit Made for Kids Yes/No, and synthetic-content Yes/No.
4. Review summary and press **Konfirmasi & Posting Sekarang**. Private is default.
5. Publishing History shows Pending/Uploading/Processing/Published/Failed/Cancelled, acknowledged-byte progress, retry/cancel affordances, errors, and **Lihat di YouTube** after success.

## Quota and official references

At documentation check, YouTube lists a separate **100 `videos.insert` calls/day** upload bucket (method cost 1 in that bucket); general project quota defaults to 10,000 units/day, with `channels.list`/`videos.list` cost 1 unit each. Confirm current values in Google Cloud Console before batch use.

- [Videos: insert](https://developers.google.com/youtube/v3/docs/videos/insert)
- [Resumable uploads](https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol)
- [Channels: list](https://developers.google.com/youtube/v3/docs/channels/list)
- [Videos: list](https://developers.google.com/youtube/v3/docs/videos/list)
- [Google OAuth web-server flow](https://developers.google.com/identity/protocols/oauth2/web-server)
- [YouTube Shorts eligibility](https://support.google.com/youtube/answer/15424877)
- [Quota](https://developers.google.com/youtube/v3/determine_quota_cost)

## Verification and limits

Run mocked integration tests from `backend`:

```powershell
.venv\Scripts\python.exe tests\test_youtube.py
```

Test covers DPAPI round-trip, OAuth state/callback and account/disconnect lifecycle, token `invalid_grant`, approval/fingerprint/Shorts validation, default Private metadata, chunk byte ranges, transient interruption resume, retry endpoint resume, duplicate prevention, cancellation before upload, and unknown-outcome fail-closed reconciliation. Google network calls are mocked. Frontend validation: `npm run typecheck` and `npm run build`.

No live OAuth credentials are configured in this checkout; no real upload or video ID has been verified. Before public use, run one real Private upload and verify video ID, channel, and privacy in YouTube Studio. No multi-channel chooser, scheduled publishing, other social platforms, multi-user auth, or AI captions. YouTube can still reject a valid file for account/channel policy, copyright, content, quota, or API project restrictions.

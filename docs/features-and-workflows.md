# Features and Workflows

This page describes workflows present in current source. Current primary flow is AI candidate generation followed by human review/edit/render. Timestamp-first Quick Clip and cloud transcription are **planned**, not implemented; see [Roadmap](roadmap.md).

## Source video workflow

1. **Import:** browser submits MP4/MOV upload or direct URL. Backend checks size, free space, file format, codecs, duration and audio via ffprobe. URL ingest requires public HTTPS media response on port 443, resolves/pins public IP, validates each redirect (maximum three), and rejects site pages/private addresses.
2. **Persist:** source file is written under managed source root; `sources` row holds metadata, hash, and later transcript cache. Original media remains separate from generated clips.
3. **Generate:** user chooses count 3/5/10, target duration 15–30/30–60/60–90 seconds, subtitle style, resolution 720/1080, center/manual focus, language auto/Indonesian/English, and provider local/OpenAI/Gemini.
4. **Transcribe and analyze:** if the transcript cache matches language/config/model fingerprint, it is reused. Otherwise FFmpeg extracts normalized mono 16 kHz PCM and whisper.cpp writes timestamped segments. AI chooses candidates, validates time boundaries and deduplicates overlapping candidates. Source and transcript are local. Cloud provider receives transcript/timestamps and job instructions only, after explicit consent.
5. **Review:** candidate cards show rank/title/reason and `review_status=needs_review`. User opens Clip Editor to inspect source, edit and render.

## Clip editing, render, approval

| Concern | Values/state | Meaning |
|---|---|---|
| Clip operational `status` | `ready`, `rendering`, `completed`, `needs_render` | Candidate/render freshness; old MP4 can remain available while marked stale |
| Review `review_status` | `needs_review`, `approved`, `needs_revision` | Human decision, independent of render status |
| Generate job terminal state | `ready_for_review` | Candidates exist; not same as clip review approval |
| Render job terminal state | `completed`, `failed`, `cancelled` | FFmpeg job result |

Render creates portrait H.264/AAC MP4. User can adjust trim, crop, subtitle enable/style/size/color/position and per-segment text overrides. Transcription and candidate analysis are reused; edit/rerender does not rerun AI. Old rendered MP4 remains until replacement succeeds.

Review endpoint accepts `approved` or `needs_revision` only when final render is completed and a nonempty H.264/AAC MP4 passes ffprobe. Approval records SHA-256 of exact output. Changed saved edits or any render request resets approval/fingerprint; render completion remains `needs_review`. A legacy approved record without fingerprint is reset during migration.

## YouTube publishing workflow

1. Connect a YouTube channel from **Akun**. Google grants `youtube.upload`; tokens stay encrypted/server-side.
2. In Clip Editor, approved completed output exposes **Posting ke YouTube**. Backend repeats approval, render, file hash and Shorts eligibility validation.
3. User previews final video; enters title (required), description, tags; chooses privacy (Private default), explicit Made for Kids answer, and explicit synthetic-content answer.
4. A confirmation step enqueues publication in the existing worker.
5. **Publishing History** shows publication status and acknowledged upload bytes. Upload uses resumable sessions; unknown outcome is reconciled before retry. YouTube processing status is polled only when worker queue is idle.

Publication statuses are `pending`, `uploading`, `processing`, `published`, `failed`, `cancelled`; review/render states remain separate. Pending/uploading clip cannot be edited, rerendered, re-reviewed, or deleted. Cancel accepted only before upload may have sent bytes. A known video ID can be rechecked without sending a second upload. Expired session after possible bytes with no recovered ID blocks retry pending manual YouTube Studio reconciliation.

## Privacy and data boundaries

- Local model path: source video → local FFmpeg audio extraction → local whisper.cpp → local Ollama by default → SQLite/local MP4.
- Cloud AI options are explicit per job. OpenAI/Gemini receive transcript-based prompts, not media file/audio. No automatic local/cloud provider fallback.
- YouTube receives video and manually entered metadata through official API only after approval and confirmation.
- No telemetry or product analytics are implemented.

## Current limits relevant to future features

- App currently requires source import and candidate-generation flow; no Quick Clip timestamp form/route exists.
- Whisper and Ollama are required for current default generation path; an AI-free timestamp cut and optional transcription are roadmap work, not current features.
- Highlight subtitles are phrase/segment based; word-level timing is not available.
- Crop is fixed center/manual; no face tracking or timeline editor.
- YouTube V1.1 is Post Now only; no scheduler, platform-wide video search, multi-channel chooser, or other social networks.

See [AI Pipeline](ai-pipeline.md), [Video Processing](video-processing.md), [API and Database](api-and-database.md), and [YouTube Publishing](youtube-shorts-publishing.md) for implementation details.

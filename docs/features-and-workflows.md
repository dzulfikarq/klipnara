# Features and Workflows

This page describes workflows present in current source. **Quick Clip is the default/main mode**; AI Smart Clip remains optional. Cloud transcription is **planned**, not implemented; see [Roadmap](roadmap.md).

## Source selection

1. **Import:** browser submits MP4/MOV upload, selects stored source, or imports direct URL. Backend checks size, free space, file format, video codec, duration and audio metadata via ffprobe. Audio is optional for Quick Clip; AI Smart Clip requires audio when transcription cache misses. URL ingest requires public HTTPS media response on port 443, resolves/pins public IP, validates each redirect (maximum three), and rejects site pages/private addresses.
2. **Persist:** source file is written under managed source root; `sources` row holds metadata, hash, and later transcript cache. Original media remains separate from generated clips.

## Quick Clip (default)

1. Choose uploaded MP4/MOV, direct URL import, or source already in Video Library.
2. Preview original source; enter Start/End in `MM:SS` or `HH:MM:SS`, or capture either value from video playhead.
3. Backend validates finite `0 <= start < end <= source.duration`; there is no product-imposed maximum clip length. User enters title and chooses 720p (default) or 1080p. Output aspect is fixed portrait 9:16; initial subtitle setting is off.
4. `POST /api/sources/{id}/quick-clips` creates a `quick_clip` job and ordinary `clips` row in one SQLite transaction. It does not create a transcript, AI candidate, fake transcript, or AI usage record.
5. Existing single worker sends only selected in/out to FFmpeg; after render user can open same Clip Editor, approve/revise, download or publish through YouTube flow.

Quick Clip never calls `transcribe`, `count_prompt_tokens`, `analyze`, Ollama, OpenAI or Gemini. It works with a silent source. Renderer creates a silent stereo AAC track (`anullsrc`) for silent input so final H.264/AAC review/YouTube contract stays valid. Quick Clip subtitles remain unavailable without a transcript; subtitle toggle is disabled in that case.

## AI Smart Clip (optional)

Choose mode **AI Smart Clip** to use existing workflow. User chooses count 3/5/10, target duration 15–30/30–60/60–90 seconds, subtitle style, 720/1080, center/manual focus, language auto/Indonesian/English, and local/OpenAI/Gemini provider.

If transcript cache matches language/config/model fingerprint, it is reused. Otherwise FFmpeg extracts normalized mono 16 kHz PCM and whisper.cpp writes timestamped segments. AI chooses candidates, validates time boundaries and deduplicates overlaps. Cloud provider receives transcript/timestamps and instructions only after explicit consent.

## Shared review and render

Candidate AI clips and Quick Clips appear with source/candidate labels. Human review uses `review_status=needs_review` initially. User inspects source/final output in shared Clip Editor, changes trim/crop/subtitles where a transcript exists, then renders/approves/revises.

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

- Quick Clip is the default path; current AI Smart Clip still needs Whisper on cache miss and Ollama when local provider is selected.
- Cloud transcription and making Whisper/Ollama optional for other AI workflows remain roadmap work; Quick Clip itself has no such dependency.
- Highlight subtitles are phrase/segment based; word-level timing is not available.
- Crop is fixed center/manual; no face tracking or timeline editor.
- YouTube V1.1 is Post Now only; no scheduler, platform-wide video search, multi-channel chooser, or other social networks.

See [AI Pipeline](ai-pipeline.md), [Video Processing](video-processing.md), [API and Database](api-and-database.md), and [YouTube Publishing](youtube-shorts-publishing.md) for implementation details.

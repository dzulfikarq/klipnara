# Features and Workflows

This page describes workflows present in current source. **Buat Video** is the multi-mode entry point: Quick Clip, AI Smart Clip, AI Mood Quotes, and a disabled YouTube Clip card marked Segera Hadir. Quick Clip remains the default inside the clip workflow. Cloud transcription is **planned**, not implemented; see [Roadmap](roadmap.md).

## Multi-mode create entry

`/create` shows working Quick Clip, AI Smart Clip, and AI Mood Quotes paths. Quick Clip and AI Smart Clip share the source workflow and existing source/editor/review routes. AI Mood Quotes opens its own `/mood` wizard. YouTube Clip is visibly unavailable; no YouTube downloader or active-looking placeholder button is present. Existing OAuth publishing remains separate and applies only to supported source-backed clips.

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

## AI Mood Quotes

1. Choose a data-driven mood group/subcategory, optional custom topic, language, tone, point of view, and target length (5–10, 15–20, or 25–40 seconds). Length is composition guidance, not a word-count guarantee.
2. Choose Gemini (default) or OpenAI and confirm the cloud-data disclosure for **each** generation. The request sends mood/category/topic/style/perspective/length/language and prompt instructions only. No video/image/audio assets or API key are sent. Missing keys, quota errors, or malformed output stop the request; there is no provider fallback or automatic retry.
3. The provider must return exactly five strict-schema quote alternatives with ordered segments, mood/tone IDs, visual keywords, and music mood. Backend checks lengths, exact segment reconstruction, IDs, and pairwise similarity. Rejected output is shown as an error and is not saved.
4. Pick/edit a quote, save favorites, or regenerate. Each generated batch is appended to `mood_generations`; regenerating changes the current batch but does not remove history/favorites. Selection/edit is stored in the draft, so later editor/render steps make no AI call.
5. New drafts use **Sequential Text**: validated provider segments are reused when they fit; otherwise local deterministic sentence/clause splitting and word-weighted timing run without AI. Short opener clauses such as “Terkadang,” merge with following phrase; conjunctions are not selected as unsafe split boundaries. Edit/reorder/add/delete up to eight segments, timing, and per-segment animation; UI warns about gaps, overlap, fast reading, short duration, and long text. **Segmentasi ulang** confirms before replacing text/timing edits. Switch to **Single Text** for one continuous quote. Drafts without `text_mode` load as Single Text to preserve old timing/appearance. Text edits, presets, preview, and render never call AI.
6. **Mood** and **Visual Style** are separate. Mood/subcategory deterministically recommends, but never auto-applies, styles. Ten local presets: Sad Night, Rainy Memories, Happy Sunshine, Golden Hour, Romantic Dream, Motivational Rise, Calm Morning, Minimal Aesthetic, Vintage Memories, Dreamy Pastel. Each sets a different motion/color/atmosphere/typography/animation profile and a music-mood label; no footage or song is bundled or auto-selected.
7. Customize uses expandable Background, Smart Visual Presets, Cinematic Effects, Text Sequence & Typography, and Music sections with two-column controls plus 9:16 preview. Choose local image/video, referenced Source Library video, solid/gradient, and licensed local MP3/WAV/M4A. Effects include None, slow zoom in/out, directional pan, Ken Burns; Subtle/Normal/Strong intensity; brightness, contrast, saturation, temperature, vignette, grain, dark overlay, and gradient overlay. Preset Apply/Undo/Reset changes visual fields only; quote, manual segment/timing, media background asset, and music remain. Presets set palette for solid/gradient backgrounds. Autosave writes stay serialized; Safe Area is editor-only.
8. The collapsible Visual Timeline Editor shows text, background, and music lanes against one shared playhead. Drag/resize text segments without ripple; split/merge/duplicate/reorder/reset timing from selected-segment properties. Drag music clip to set start offset; trim/loop/fades/volume/mute remain editable in Music controls. Zoom and snapping are editor-only; composition edits autosave to the same `composition_json` used by preview/render. No timeline database/schema migration.
9. Live Preview applies browser transforms/filters and follows playhead/segment animation; music preview follows offset, trim, loop, fades, and mute. Video background uses one cached static thumbnail with simulated motion; **Preview Penuh** plays real video/audio. FFmpeg renders the saved composition snapshot through existing renderer; H.264/AAC MP4 at 720p or optional 1080p, stream/duration/resolution/audio checks, progress/cancel/retry, prior output preserved until replacement succeeds. Browser/libass text wrapping and color/grain treatment can differ slightly; compare final MP4 manually. No selected music means background audio or silent AAC; mood/music recommendations never select/download music. Volume zero intentionally permits silence.
10. Review is independent of render state. Approval stores SHA-256 for valid H.264/AAC output; edit changes invalidate approval. Download is available in Mood Quotes and Clip Library; drafts can be reopened/deleted with local uploads.

Mood Quotes uses dedicated project/render tables because it has no source video/clip FK. It does not create a fake source or clip. A Source Library background is referenced with a restricting FK and is never deleted with the Mood Quotes project. Music and uploaded footage remain local; users must have rights to use them. Mood Quotes does not yet expose YouTube publishing; no fake Publish control is shown.

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
- Mood Quotes sends only quote-generation text fields to the selected cloud provider after request-specific consent. Background and music remain local, and render runs offline after quotes are saved.
- YouTube receives video and manually entered metadata through official API only after approval and confirmation.
- No telemetry or product analytics are implemented.

## Current limits relevant to future features

- Quick Clip is the default path; current AI Smart Clip still needs Whisper on cache miss and Ollama when local provider is selected.
- Mood Quotes supports user-owned backgrounds, 10 data-driven cinematic visual presets, local color/motion/atmosphere effects, semantic segmentation, uploaded audio mixing, and system-font rendering. Soft glow is not implemented. Grain, vignette, zoompan and 1080p filters add CPU work; choose Subtle or disable effects on slower machines. No stock-footage/music search, source-clip multi-clip timeline editor, cloud transcription, voiceover, or Mood Quotes YouTube adapter.
- Quote prompts prohibit attribution, famous-quote/song-lyric copying, and generic repetition, but cannot prove internet-wide originality/plagiarism status. Human review remains necessary.
- Cloud transcription and making Whisper/Ollama optional for other AI workflows remain roadmap work; Quick Clip itself has no such dependency.
- Highlight subtitles are phrase/segment based; word-level timing is not available.
- Source-clip crop is fixed center/manual; no face tracking or source-clip timeline editor. Mood Quotes has its own single-composition visual timeline.
- YouTube V1.1 is Post Now only; no scheduler, platform-wide video search, multi-channel chooser, or other social networks.

See [AI Pipeline](ai-pipeline.md), [Video Processing](video-processing.md), [API and Database](api-and-database.md), and [YouTube Publishing](youtube-shorts-publishing.md) for implementation details.

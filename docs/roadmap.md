# Product Roadmap

Roadmap captures latest product direction, not a claim that planned code already exists. Source tree and tests remain implementation authority.

## Product direction

- Keep Klipnara personal, single-user, local-first, Windows-first.
- No cloud hosting or mobile app for now.
- **Quick Clip from user-supplied timestamps is the primary workflow.**
- Whisper/Ollama remain available for AI Smart Clip but are not required by Quick Clip.
- Keep Cloud AI limited to selected features and require explicit user consent per operation.
- Keep FFmpeg as video processing engine.
- Preserve YouTube OAuth/resumable uploader; Publishing Studio supports individually approved Clip and Mood outputs plus native YouTube scheduling and official, publication-attributed Analytics.
- Keep TikTok Inbox/Instagram Reels jobs conditional on verified scopes and provider eligibility. TikTok Direct Post stays disabled; manual export remains universal fallback.
- Keep YouTube preview and media ingest distinct. Optional local segment adapter stays disabled by default and must not be presented as official or universally permitted. Enable only where rights and method permission are clear; retain local-file fallback.

## V2.1 Studio phase status

| Phase | State | Scope/status |
|---|---|---|
| Multi-mode Create Video | **Implemented** | Quick Clip and AI Smart Clip retain existing workflows; YouTube Clip supports preview/timestamp, optional adapter import, and local-file fallback; AI Mood Quotes opens a dedicated workspace. |
| Mood categories and quote generation | **Implemented; live provider not verified in this checkout** | Eight data-driven groups, 61 subcategories, nine writing styles, POV/length/language selection, Gemini default/OpenAI alternative, per-request consent, strict five-quote validation, favorites, history and regenerate preservation. |
| Drafts and editor | **Implemented; runtime recheck pending** | Existing additive tables retained; mode/segments live in `composition_json` without migration. New drafts default to Sequential Text; old drafts stay Single Text. Autosaved editor adds local segment timing/animation, responsive preview, visual/audio controls, and no-AI edits/render. |
| Media composition and FFmpeg | **Implemented; expanded synthetic E2E pending** | Image/video/solid/gradient, segmented ASS text, music trim/resampling/mix/fades/loop, selected-audio signal and MP4 stream/duration/resolution checks, 720p H.264/AAC default and optional 1080p, progress/cancel/retry, review SHA-256/download. Existing 24 Oct results cover earlier cases; new scenarios were not run in this checkout and synthetic media cannot certify arbitrary user footage. |
| Library/review/publishing | **Implemented; V2.11 extends approved-output publishing** | Mood projects retain separate render/review records and publish through YouTube Studio without fake `clips` or source rows. Existing Clip workflow uses same OAuth/resumable uploader. |
| YouTube Analytics V3.1 | **Implemented in source; mocked regression checks added but unrun** | Official `reports.query`, actual-scope persistence and channel-bound incremental consent, separate Channel/Klipnara reports, Views/Engaged Views, comparisons, video/retention detail, local cache/CSV, minimum-sample rule insights, and immutable new-publication attribution. No live YouTube API or OAuth validation. |

## V3.2 Multi-platform publishing

| Phase | State | Scope/status |
|---|---|---|
| Conditional account capability | **Implemented in source; live verification blocked** | TikTok requests `user.info.basic`/`video.upload` only; Instagram requires verified Facebook Login for Business scopes and linked Professional account. Provider app review/eligibility is never inferred. |
| TikTok Inbox | **Implemented in source; mocked checks added but unrun** | Local chunked transfer, provider status, creator-action distinction, and Published only on `PUBLISH_COMPLETE`. No Direct Post/`video.publish`; no scheduling. |
| Instagram Reels | **Implemented in source; mocked checks added but unrun** | Facebook Login for Business local resumable upload, container processing, `media_publish`, status confirmation, token refresh/reconciliation. Instagram Login `video_url` flow is not assumed. |
| Independent history/recovery/manual export | **Implemented in source; runtime QA pending** | Per-platform accounts, metadata, jobs/events, failure/retry/cancel/reconcile, approval SHA-256 checks, explicit rights/duplicate confirmation. Manual export remains available without OAuth. |
| V3.2 QA | **Pending user validation** | Mock test code added; not run. No app credentials, reviewed scopes, eligible provider accounts, tests, typecheck/build, server, browser, live API, or upload performed. |

## V3.2.1 Multi-account destinations

| Phase | State | Scope/status |
|---|---|---|
| Account lifecycle | **Implemented in source; mocked checks added but unrun** | Multiple YouTube/TikTok/Instagram accounts, provider-scoped defaults, per-attempt YouTube OAuth cookies, `prompt=select_account`, shared authorization preservation, account-specific disconnect and queued-job cancellation. |
| Destination-bound publishing | **Implemented in source; mocked checks added but unrun** | Per-account metadata drafts, up to 50 stable account IDs per request, independent result/job per destination, authorization/target identity snapshots, worker identity preflight, retained history on disconnect. |
| Migration and runtime QA | **Pending user validation** | Additive authorization/account/job snapshots and legacy credential backfills; migration/OAuth/fan-out/disconnect assertions added. Google grants exposing multiple YouTube channels still fail closed. No tests/build/provider/OAuth/browser/upload validation performed. |

## V2.3 Mood Quotes cinematic phase

| Phase | State | Scope/status |
|---|---|---|
| Smart Visual Presets | **Implemented in source; validation pending** | Ten typed/versioned data-driven styles, mood recommendations, visual-only application, one-step undo/reset, and no automatic asset/music selection. |
| Motion/color/atmosphere | **Implemented in source; FFmpeg/browser validation pending** | Existing Mood renderer adds bounded zoom/pan/Ken Burns, colorbalance/eq, vignette, grain, dark/gradient overlays; browser previews simulate effects from shared draft settings. No glow or new rendering pipeline. |
| Indonesian semantic segmentation | **Implemented in source; tests not run** | Deterministic clause merge/split rules avoid hanging openers/connectors; manual segments require explicit confirmed re-segmentation. Old Single Text drafts remain supported. |
| V2.3 QA | **Pending user runtime check** | Regression and synthetic-render test code added/updated but not executed. Compare Live Preview, Preview Penuh, and MP4; no build/server/browser/FFmpeg run was performed for this update. |

## V2.4 Mood Quotes visual timeline phase

| Phase | State | Scope/status |
|---|---|---|
| Composition timeline | **Implemented in source; validation pending** | Collapsible text/background/music lanes, shared playhead, zoom/snap, drag/resize, music offset/mute, segment split/merge/duplicate/reorder/reset. Selection/zoom/snap stay UI-only; edits use existing composition JSON. |
| Audio timing and draft safety | **Implemented in source; validation pending** | Backward-compatible offset/mute defaults, asset/span validation, delayed/faded FFmpeg music, preview sync, serialized autosave, immutable render snapshot. No SQLite migration. |
| Regression and manual QA | **Pending** | Frontend helper tests, backend assertions, synthetic offset/mute render cases, and manual checklist added; none run. No typecheck/build/browser/FFmpeg runtime validation performed. |

## V2.5.1 YouTube Clip import phase

| Phase | State | Scope/status |
|---|---|---|
| Strict URL and metadata | **Implemented in source; validation pending** | Exact supported YouTube hosts/paths, 11-character video IDs, canonical URLs, optional `t`/`start`; official Data API metadata is optional, backend-only, bounded and not persisted. |
| Preview and timestamp | **Implemented in source; browser QA pending** | Official IFrame Player API, playhead capture, start/end, replay/stop interval, duration-aware validation and explicit unknown-duration fallback. Embed/private/network limits remain YouTube-controlled. |
| Optional segment adapter | **Implemented in source; validation pending** | Disabled by default; explicit `yt-dlp`/FFmpeg/ffprobe setup, rights attestation, `--download-sections`, caps/validation, persisted import jobs, cancellation/retry/cleanup, managed source, automatic existing Quick Clip handoff. Download is not guaranteed or universally permitted. |
| Local fallback and Quick Clip | **Implemented in source; validation pending** | Source Library/upload fallback remains; successful import enters existing Quick Clip/render/editor/review/publishing pipeline. Imported source association and original timestamps are preserved; no content-identity claim. |
| Security and QA | **Implemented in source; tests/manual QA pending** | No cookies/session, DRM bypass, or access-control workaround. Direct-file importer still rejects YouTube page hosts before DNS. Import regression tests/manual checklist added; none run. |

## V2.6 Clip Editor and Cut Range phase

| Phase | State | Scope/status |
|---|---|---|
| Multi-Scene data and editor | **Implemented in source; validation pending** | Existing `clips.edit_json` stores stable-ID, single-source scenes and source-time subtitles/audio/title/export settings. Single Scene remains default; Multi-Scene supports add/reorder/trim/split/duplicate/delete, Hook/Ending labels, browser ordered-seek preview, and autosave without DB migration. |
| Cut Range / Ripple Delete | **Implemented in source; validation pending** | Output-time selection by drag or Set In/Out; cross-scene delete splits retained source ranges and recomputes contiguous output positions. Undo/Redo bounded to 40 snapshots; shortcuts avoid text controls. Source media remains untouched. |
| FFmpeg scene transitions and export | **Legacy Overlap retained; Transition Slot expanded in V3.2.2** | Existing FIFO renderer now supports frame-counted Insert Slot and Overlap, normalized holds/`xfade`/`concat`, silence or optional audio fades, subtitle ownership, and output signatures. Legacy Zoom Blur remains Overlap-only Crossfade fallback. Validation pending. |
| Regression/manual QA | **Pending user validation** | Frontend mapping/history tests and backend persistence/subtitle/filtergraph assertions added; none run. Browser preview, rendering, sync, output presets, review and publishing regression checklist is in Testing docs. |

## V3.2.2 Transition Slot phase

| Phase | State | Scope/status |
|---|---|---|
| Interactive pair-keyed slots | **Implemented in source; validation pending** | Existing `fromId>toId` records; missing mode remains legacy Overlap. New Crossfade/Dip to Black starts as 0.5s Insert Slot. Add/remove, mode/duration controls, per-boundary preview, Apply to All eligible, undo/redo/autosave; no DB migration. |
| Timeline, subtitle, and audio timing | **Implemented in source; validation pending** | 30/60 FPS frame mapping drives Insert duration, Overlap subtraction, playhead, seek, ripple delete, source/output captions, and composition signatures. Insert uses endpoint holds, silence, optional audio fades; overlap preserves midpoint switch/optional `acrossfade`. |
| FFmpeg and legacy behavior | **Implemented in source; synthetic E2E pending** | Existing renderer normalizes selected scene frames, size, FPS/timebase, and audio before transition composition. Legacy Zoom Blur stays Overlap-only with Crossfade fallback; no new renderer or migration. Tests/docs added; not run. |
| Regression/manual QA | **Pending user validation** | Timeline/API/filtergraph assertion cases and browser/MP4 checklist added. No tests, build, FFmpeg, server, or browser QA run. |

## V2.7 Local Asset Library phase

| Phase | State | Scope/status |
|---|---|---|
| Shared local media | **Implemented in source; validation pending** | Additive `library_assets` registry and backward-compatible source metadata seed. Videos remain canonical `sources`; images/audio live once under managed shared storage. Local uploads dedupe by kind/SHA-256; favorites, mood tags, license/attribution metadata, storage usage, and reference-aware deletion are included. |
| Pexels stock search/import | **Implemented in source; live/provider validation pending** | Official fixed API endpoint, backend-only key, bounded search cache, sanitized preview/media URLs, user-selected single MP4 import, 512 MiB cap, pinned public HTTPS, ffprobe/hash, persisted cancel/retry, one import executor, and ordinary Source Library registration. Mocked tests added but not run; no live request performed. |
| Mood Quotes reuse | **Implemented in source; validation pending** | Mood assets reference shared library/source rows without copying. New Mood uploads enter shared storage; draft delete/detach preserves shared files. Legacy project-scoped assets remain supported and are not migrated. |
| V2.7 QA | **Pending user runtime check** | Mocked API/import test and manual checklist added; not run. No typecheck/build/server/browser/FFmpeg/live Pexels validation. Confirm V2.6/Quick Clip/YouTube/Mood regressions after authorization. |

## V2.9 Batch Creator phase

| Phase | State | Scope/status |
|---|---|---|
| Video Clips batches | **Implemented in source; validation pending** | Up to 10 explicit timestamp drafts, shared export defaults, existing Clip Editor, per-item override, sequential existing renderer/worker scheduling, pause/resume/cancel/retry and individual review/download. |
| Mood Quotes batches | **Implemented in source; validation pending** | Up to 10 saved/manual quote snapshots clone existing drafts and reference shared Asset Library media; no automatic quote generation or media analysis. Legacy project-owned assets must be re-linked before batching. |
| Persistence and recovery | **Implemented in source; validation pending** | Additive SQLite batch/item tables, immutable child snapshots/fingerprints, restart recovery to paused/retryable state, queue-record deletion preserves drafts and outputs. |
| V2.9 regression/UI QA | **Pending** | Backend regression script added but not run. No tests, typecheck/build, server, browser, FFmpeg or runtime checks were performed for this revision. |

## V2.10 Unified Clip Editor workspace

| Phase | State | Scope/status |
|---|---|---|
| Shared clip editor layout | **Implemented in source; manual QA pending** | Quick Clip, AI Smart Clip, and YouTube Clip output retain shared `/clips/[id]` route. Desktop editing controls and sticky 9:16 browser preview use existing editor state; no backend/render rewrite. |
| Preview and timeline access | **Implemented in source; manual QA pending** | Playback/seek/time, preview-only mute, fullscreen, media fallback, preview collapse, timeline collapse, and existing synchronized scene/subtitle timeline are available. Styles update browser composition without remounting video. |
| Draft/render/review status | **Implemented in source; tests and manual QA pending** | Save status and render freshness derive from current edit/PATCH/render state; existing autosave serialization, review fingerprint, approval and publishing gates remain. Node state tests added but not run. |
| Responsive/design QA | **Pending user validation** | Two columns above 1080px; stacked, non-sticky preview at and below 1080px. Mood Quotes remains separate. Existing app has no dark theme. No build, typecheck, browser, or runtime validation performed. |

## V2.12 Word Pop subtitle phase

| Phase | State | Scope/status |
|---|---|---|
| Subtitle type and appearance | **Implemented in source; validation pending** | Adds separate `word_pop` type and Word Pop appearance preset. Existing sentence/phrase/legacy word/karaoke types remain; presets change appearance only. |
| Reviewed/manual word alignment | **Implemented in source; validation pending** | Gemini word timestamps can be used; segment/text-only providers never get inferred timing. Manual word text/time edits, punctuation-aware reconstruction, silence gaps, explicit review, and edit-triggered review invalidation persist in existing `clips.edit_json`; no DB migration. |
| Preview and FFmpeg | **Implemented in source; Preview-vs-MP4 QA pending** | Live one-word preview and per-word ASS events, Pop/Scale/Fade/None, safe placement/long-word sizing, source/output scene-cut mapping, 720p/1080p. Missing, mismatched, unreviewed, overlapping, or sub-10 ms ASS timing fails closed. |
| Regression/manual QA | **Pending user validation** | Backend/frontend regression assertions and Preview-vs-MP4 checklist added; none run. No tests, typecheck/build, server, browser, provider, or FFmpeg validation performed. |

## V2.0 phase status

| Phase | State | Scope/status |
|---|---|---|
| Fase 0 — Audit & Compatibility | **Implemented** | Existing SQLite tables/jobs/render/review/YouTube flow audited. Quick Clip reuses current `jobs`/`clips` schema; no Quick Clip migration or source-file rewrite. Backup/rollback guidance documented. |
| Fase 1 — Lightweight Quick Clip | **Implemented and tested** | Create page defaults to Quick Clip; timestamp form, playhead capture, source Library, direct FFmpeg render, audio-optional input, shared editor/review/approval, and source-origin label. Mocked AI-isolation tests plus real-media and synthetic-silent E2E pass; details in Testing docs. |
| Fase 2 — Lightweight Rendering | **Planned** | Further render latency/CPU optimization. Existing FFmpeg render remains; no stream-copy/Fast Cut optimization is claimed yet. |
| Fase 3 — Simple Editor | **Implemented in source; validation pending** | Shared editor supports Off/Manual/transcription/import subtitle modes, stable-ID tracks, cue/timing edits, autosave/reopen, preview sync, caption controls, and ASS render. |
| Fase 4 — Optional Cloud AI | **Implemented selectively; validation pending** | Existing opt-in OpenAI/Gemini highlight analysis remains. V2.8 subtitle transcription/translation are queued, require per-request consent for cloud audio/text, and keep results as review drafts. |

## Status by feature

| Area | Current source status | Direction |
|---|---|---|
| Clip Editor V2.6 | **Implemented in source; tests, browser, and FFmpeg validation pending.** Single Scene default plus Multi-Scene/Cut Range ripple delete, pair-keyed transitions, 40-entry Undo/Redo, source/output subtitle remapping, optional audio/title/export settings; all saved in existing `edit_json`. Drafts may exceed 180 seconds; final editor renders are capped at 180 seconds. | Run transition-specific manual QA on permitted/synthetic media; compare Live Preview vs MP4 sync. Keep one source, 12 scenes; final output ≤180 seconds. |
| Transition Slots V3.2.2 | **Implemented in source; tests/build/runtime validation pending.** Insert Slot adds frame-counted output time; Overlap subtracts it. Interactive Crossfade/Dip to Black slots drive existing preview, FFmpeg, audio, subtitle mapping, and ripple delete. Legacy missing mode stays Overlap; no migration/new renderer. | Run V3.2.2 manual checklist and compare browser preview against final MP4 after authorization. Verify mixed 30/60 FPS joins, seek/play/pause, subtitles/Word Pop, audio, undo/reload, and failed-render output preservation. |
| Clip Editor V2.10 | **Workspace implemented in source; state test added but unrun; browser/manual QA pending.** Shared desktop two-column controls + sticky preview, responsive stack, collapsible tool groups/timeline, explicit save/render freshness; no backend, DB, or media-processing changes. | Complete V2.10 viewport/playback/autosave/review checklist before claiming verified. Dark theme is not supported by current app. |
| Subtitle & translation V2.8 | **Implemented in source; regression checks added but not run; provider/browser/FFmpeg validation pending.** Queued composition transcription (local Whisper, consented Gemini word timing, consented OpenAI text-only), separate review tracks, text-only translation, SRT/VTT import/export, cue/timeline editing, stale-track protection, and expanded ASS caption styles; no DB migration. | Validate local/cloud consent boundaries, provider limits/response shapes, transcript-only manual timing, translation freshness, import/export edge cases, stale output tracks, preview/render parity, and old editor regression. |
| Word Pop V2.12 | **Implemented in source; regression checks added but not run; browser/FFmpeg validation pending.** Separate subtitle type, reviewed/manual word timing, live preview, per-word ASS animation, scene mapping, long-word fitting, and fail-closed render validation; no DB migration. | Run the Word Pop Preview-vs-MP4 checklist in Testing docs when authorized. Confirm subtitle modes/presets, legacy drafts, timing edits/review, scene cuts/repeats, punctuation, gaps, long words, 720p/1080p, and existing approval gates. |
| Batch Creator V2.9 | **Implemented in source; regression script added but not run; frontend/backend runtime validation pending.** Up to 10 source clips or Mood Quotes items, shared settings, per-item existing editors, serial child scheduling, controls, recovery, review/download, and safe batch-record deletion. | Run `test_batch_studio.py` and manually validate pause races, restart recovery, editor autosave, multiple batches in FIFO queue, Mood shared assets, review/download, and output preservation when authorized. |
| Asset Library V2.7 | **Implemented in source; mocked test and manual/runtime validation pending.** Local video/image/music metadata, favorites, source/license attribution fields, shared Mood reuse, safe deletion, one-at-a-time Pexels MP4 import. | Run mocked test and manual QA only after authorization; review Pexels account/rate limits/license, content rights, cancellation/recovery, hash reuse, reference guards, legacy Mood compatibility. Keep key backend-only and no bulk download. |
| AI Mood Quotes | **V2.4 source implementation; runtime/tests pending** for consented generation, deterministic segmentation, cinematic presets/effects, visual timeline, audio offset/mute, local FFmpeg composition. No V2.4 test/build/live AI/browser/FFmpeg run was performed. | Follow V2.4 manual QA; measure effects on target hardware and validate timeline/audio preview-render parity before calling verified. |
| Quick Clip by timestamp | **Implemented.** Current Create default; accepts `MM:SS`/`HH:MM:SS`, creates clip/job without transcript/candidate/AI, renders selected interval, supports sources without audio. | Keep primary, lightweight path; Fase 2 may optimize FFmpeg latency later. |
| YouTube Clip | **V2.5.1 implemented in source; tests/browser/adapter validation pending.** Official IFrame preview, optional transient metadata, disabled-by-default local section adapter, local fallback, Quick Clip reuse. yt-dlp is not official YouTube tooling; permission/availability are not guaranteed. | Validate adapter only with content/method permitted by rights and platform terms; test restrictions/fallback, cancellation/cleanup, editor handoff, and source preservation. |
| Whisper transcription | **Implemented; used for fresh sources/cache misses** in AI Smart Clip. Local whisper.cpp, `small` recommended, `base` fallback, language auto/Indonesian/English. | Optional for the product's primary Quick Clip flow; retain for AI Smart Clip. |
| Ollama highlight analysis | **Implemented, default** local provider for AI Smart Clip; OpenAI/Gemini can replace it with explicit consent. | Optional for the product's primary Quick Clip flow. |
| Cloud highlight analysis | **Implemented, optional** OpenAI/Gemini provider with per-job transcript-sharing consent. | Continue feature-specific, opt-in cloud use; no fallback without consent. |
| Subtitle speech-to-text | **V2.8 implemented in source; tests/provider validation pending.** Local Whisper segment timing; Gemini `gemini-3.5-transcribe` word timing/speaker labels up to 30 minutes; OpenAI `gpt-transcribe` text-only up to 25 MiB. Existing synchronous `whisper-1` route remains for compatibility. Cloud audio requires explicit consent; tracks remain drafts. | Keep opt-in, no fallback, human review. Never invent timing for text-only output. AI Smart Clip's full-source local transcription remains unchanged. |
| Subtitle translation | **V2.8 implemented in source; provider validation pending.** Consent-gated text-only translation stored separately; source cue fingerprint blocks stale output. | Review language quality and cue-length fit; original captions remain untouched. |
| FFmpeg | **Implemented** for probe/extract/crop/subtitle/render and remains required media engine. | Keep as engine; no replacement planned. |
| YouTube Publishing V1.1 | **Base uploader retained under V2.11 Studio.** OAuth, Clip approval gate, resumable upload and processing confirmation. No live OAuth/upload validation. | Maintain shared uploader; V2.11 adds approved Mood outputs and native YouTube scheduling. |
| YouTube Publishing Studio V2.11 | **Implemented in source; mocked regression assertions added but unrun.** Clip/Mood render fingerprint gates, source-less Mood upload jobs through same uploader, metadata drafts/templates, per-output confirmation, channel verification, native Private schedules, calendar/events, and managed thumbnails. No live OAuth/upload/schedule/thumbnail validation. | Static audit only for this change. After user authorization, run mocked tests/typecheck/build and manual UI review; then optional Private upload, native schedule, and thumbnail validation with user's channel. |
| YouTube Analytics V3.1 | **Implemented in source; mocked parsing/cache/scope assertions added but unrun.** Official channel-bound reports only; no arbitrary channel ID, scraping, monetary scopes, estimates, or second OAuth path. Older publication rows remain unattributed. | Verify mocked tests/typecheck/build and manual charts, CSV, cache expiry, report coverage, consent preservation, permission/quota errors, retention availability, and responsive layout when authorized. Live report validation requires explicit user permission and configured API access. |
| Mobile / hosted SaaS | **Not implemented.** | No near-term work planned. |

## Suggested next sequence

Before continuing legacy validation, complete V2.10 manual editor QA at 1920×1080, 1366×768, tablet/mobile, long transcript/timeline, portrait/landscape, and light theme; dark theme remains unsupported. See [Testing](testing-and-troubleshooting.md).

1. Run V2.9 Batch Creator regression/manual QA: one-at-a-time scheduling, pause/cancel races, restart recovery, retry, pending reorder/remove, editor autosave, shared Mood assets, output review/download and queue-record deletion. Run only when authorized.
2. Run V2.7 Asset Library mocked assertions and manual QA: local dedupe/reuse, Pexels single import/cancel/retry/restart, storage accounting, safe deletion, license metadata, legacy Mood draft preservation, and Quick Clip/Mood reuse. Live Pexels call requires explicit authorization.
3. Run V2.8/V2.12 subtitle QA: local/cloud full-composition timing, explicit audio/text consent, Gemini/OpenAI response/limits, transcript-only manual timing, reviewed manual word alignment, translation freshness, SRT/VTT round trips, stale-track protection, legacy caption modes, and Word Pop Preview-vs-MP4 timing/appearance. Execute tests/build/browser/provider/FFmpeg only when authorized.
4. Run V3.2.2 Transition Slot and V2.6 Clip Editor QA: legacy hard cuts/Overlap, Insert/Overlap duration, mixed joins, output-time drag/Set In/Out, split/trim/reorder/ripple Undo/Redo, autosave/reopen, subtitle/audio/Word Pop timing, synthetic render and review gate. Execute tests/build/browser/FFmpeg only when authorized.
5. Run legacy Quick Clip subtitle QA: Off/Manual persistence, clip/source timebase, playback seek sync, synchronous compatibility route, no-audio/no-speech handling, ASS timing, and existing review/publishing workflow.
6. Run V2.5.1 YouTube Clip manual QA: default-disabled capability, configured adapter only for permitted content/method, IFrame and timestamp behavior, section import/size-duration validation, cancellation/retry/temp cleanup, local fallback, Quick Clip/editor/review handoff. Never test with cookies or access-control workarounds.
7. Run V2.4 Mood Quotes manual QA on target hardware; test timeline interactions and offset/mute audio, compare Live Preview, Preview Penuh, and MP4. Validate live Gemini/OpenAI separately with explicit consent and quota checks.
8. Validate V2.11 publishing, V3.1 Analytics, and V3.2.1 multi-account source changes with mocked tests, typecheck/build, and manual UI QA when authorized; none were run for this checkout.
9. Only after explicit user authorization, configure a personal YouTube OAuth client and verify scope preservation plus one Private upload. Live Analytics report/retention checks are separately optional and use only the authenticated channel.
10. Keep broader YouTube acquisition methods, local upload scheduler, mobile, hosted SaaS, and other social platforms out of scope absent separate requirements and clear permission; current segment adapter remains optional, bounded, and best-effort.

No estimates or release dates assigned. Quick Clip V2.0 subtitle support, Mood Quotes V2.1–V2.4, YouTube Clip V2.5.1, V2.6 Multi-Scene/Cut Range, V2.7 Asset Library, V2.8 subtitle/translation, V2.9 Batch Creator, V2.11 YouTube Publishing Studio, V2.12 Word Pop, V3.1 YouTube Analytics, and V3.2.2 Transition Slots source implementations exist; validation remains pending. General/guaranteed YouTube download, broader hosted transcription, and other listed expansions remain unimplemented.

Current technical structure: [Architecture](architecture.md). Current implemented workflows: [Features and Workflows](features-and-workflows.md).

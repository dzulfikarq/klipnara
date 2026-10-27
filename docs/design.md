# Editor and UI Design

## Clip editor structure

Quick Clip, AI Smart Clip, and YouTube Clip outputs share `frontend/app/clips/[id]/page.tsx`. Existing editor state, callbacks, API routes, validation, keyboard shortcuts, and `clips.edit_json` remain authoritative. Mood Quotes keeps separate preview and project/render flow; no forced migration.

Desktop workspace uses roughly 60/40 columns (`1.55fr` / `1fr`, minimum 320px preview column). Editing panels sit left; one browser composition preview sits right. Workspace width inherits the shell's 1240px maximum. `min-width: 0` prevents grid children from forcing page overflow. Preview is sticky at `74px` below the shell's 62px sticky topbar and stops at the workspace wrapper, before timeline. No overflow-clipping ancestor wraps the sticky item.

Preview preserves 9:16 aspect ratio and caps at 260px width. Short desktop viewports reduce it to 190px; Play/Pause, Replay, output seek/current/total time, preview-only mute, fullscreen, source/render switch, and collapse remain available. Browser overlays reflect current draft without remounting video for style edits. Browser composition preview seeks source ranges and is not final MP4; final render remains FFmpeg. Old rendered MP4 is labeled when draft/render state says outdated. Missing media shows an inline fallback without clearing draft.

At widths `<=1080px`, layout stacks preview before controls and disables sticky positioning. Mobile uses 220px preview cap, collapsible preview, wrapped actions, 38px preview touch controls, and horizontally scrollable timeline. Timeline remains below editor workspace, uses existing `compositionTime`, scene/subtitle selection, seek, trim, cut, reorder, zoom, and undo/redo behavior; a disclosure control collapses the timeline without changing draft.

## Groups and actions

Trim, Crop & Focus, Subtitle & Translation, and Audio/Title/Export use native `<details>/<summary>` disclosures, open by default. All existing controls remain inside their original groups in the left editor column. Timeline follows the full editing workspace. Save/render actions show draft state, review state stays beside approval actions, and existing publish/download gates remain unchanged. No new backend state or schema was introduced.

Save state derives from the current JSON snapshot and existing PATCH flow: **Saving**, **Save failed**, **Unsaved changes**, or **Saved**. “Saved” follows successful response only. Render-required/outdated state derives from dirty draft, existing clip status, and rendered-file availability. Rendering progress still comes from existing job state. Existing serialized autosave and stale-response guard remain in place.

## Word Pop

Word Pop is a caption type, not a preset. Preview shows one timed word at a time and leaves silence gaps empty. Each cue exposes editable word text/start/end, seek, add/remove/split/merge, and explicit review action. Unreviewed or invalid alignments remain editable but cannot activate/render Word Pop; changing cue text or bounds clears review without discarding words. Translated/bilingual display is disabled for this type.

The Word Pop appearance preset sets yellow text, dark outline, centered safe placement, and Pop default; selecting any preset changes appearance only. Pop overshoots slightly, Scale eases to final size, Fade changes opacity, and None skips motion. Preview restarts animation on each word and honors `prefers-reduced-motion`. Font sizing scales with preview/output dimensions and long-word length; final FFmpeg ASS uses one positioned event per word. Controls retain visible labels/focus and word inputs have specific accessible names.

## Visual conventions

- Reuse existing Klipnara tokens: `--ink`, `--muted`, `--line`, `--paper`, `--canvas`, `--green`, `--green-dark`, and `--green-soft`.
- Keep existing compact spacing rhythm: 8–12px control/grid gaps, 12–14px panel padding, and 12px section spacing. Avoid adding nested card borders.
- Keep existing DM Sans body and Manrope heading hierarchy. Editor labels stay compact; clip title remains primary.
- Reuse `.button` variants, panel borders/radii, `lucide-react` icons, and existing status colors. Icon-only controls use `aria-label`, `title`, and visible focus outlines.
- Preserve existing publishing modal and review actions; no new modal/confirmation framework.
- Avoid nested card styling. Timeline alone owns horizontal scrolling; page/workspace remain overflow-visible for sticky behavior.

## Connected Accounts OAuth setup

Connected Accounts keeps channel cards and publishing history in the existing shell. When OAuth is not configured, show a warning with **Lihat Panduan Setup** and a six-step native accordion below it. Each step has a number, title, short summary, and expanded instructions; Google Cloud links open separately. The guide remains available after configuration without claiming any Google Cloud step is complete.

Read OAuth readiness, requested scopes, effective callback URI, and callback-validation error from `GET /api/youtube/config`. Enable connection only when backend detects both credential variables and supplies a valid local start URL. Render callback as read-only and copy only that backend-provided valid URI. If unavailable, explain how to inspect backend `YOUTUBE_REDIRECT_URI`; never substitute a guessed URL. Copyable environment examples use placeholders only. No credential form, Client Secret, or OAuth token belongs in frontend state or output. Read channel-connected state and actual granted scopes from `/api/youtube/accounts` after OAuth and channel lookup; credential presence/requested scopes never imply permission.

When OAuth is configured but no channel exists, keep **Hubungkan YouTube** available and keep the guide discoverable. Show OAuth callback errors with actionable setup hints. Disabled actions retain readable contrast and visible reason text; account-specific disabled actions include a title reason. Use native `<details>/<summary>` semantics, visible keyboard focus, and mobile stacking.

## YouTube Analytics V3.1

Analytics lives in a fourth Publishing Studio tab, not a new navigation route. Keep scope selector explicit: **Channel** means full channel report, **Klipnara** means report filtered to published IDs linked to local records. Never blend their totals or relabel `views` as `engagedViews`. Date inputs exclude current day; show requested range, actual returned coverage, cache/fresh status, and last sync. Refresh explicitly; preserve prior successful response with visible stale/error notice if forced refresh fails. No fake empty chart loading state should look like zero metrics.

Use native responsive SVG/CSS, existing light-theme variables and no chart dependency. Separate Views and Engaged Views charts avoid implying shared scale. Video table offers official YouTube link, local attribution label, and detail action only where publication ID exists. Video details show daily performance, immutable production summary, and audience-retention chart or a clear no-data/error state. Rule insights must show timeframe and sample count and remain descriptive, never causal. CSV exports only returned API data and escapes spreadsheet formulas. Keep controls labeled, focus-visible, touch-usable, and stack on mobile.

No monetary/estimated revenue metrics or arbitrary-channel chooser. Connected Accounts owns channel-bound **Aktifkan Analytics** action; consent outcome updates the same account card without changing channel identity or dropping existing upload scopes. Reports/errors/cache remain local; disconnected account clears report cache.

## Theme and validation boundary

Current frontend defines a light palette only; no app-wide dark theme toggle, `data-theme`, or dark media-query token set exists. New editor surfaces use existing CSS variables and remain consistent with current light UI, but dark-theme compatibility is not claimed. Manual dark-theme QA is therefore blocked until app-level dark theme exists.

No browser test runner is installed. `frontend/lib/clip-editor-state.test.mjs` and `frontend/lib/word-pop.test.mjs` use Node's built-in test runner; visual, sticky, playback, and responsive behavior still requires manual browser QA. Word Pop browser-vs-MP4 parity is unverified. Tests and builds were intentionally not run for this revision.

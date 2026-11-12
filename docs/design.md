# Klipnara UI/UX Design Standards

This document is required reading before creating or changing frontend UI. Keep visual changes within these standards and preserve existing business logic, API contracts, local data, and media-processing behavior.

## Product direction

**Modern Creator Studio — clean, refined, minimal, user-friendly.** Keep the existing emerald accent, neutral surfaces, clear hierarchy, and functional video-workflow density. Prefer readable content and useful grouping over decoration. Avoid nested cards, heavy shadows, decorative gradients, excessive borders, or unexplained whitespace.

## Brand assets

- Use only supplied official Klipnara assets. Never redraw, approximate, crop, recolor, or substitute the official mark.
- Use the K mark at small sizes; use the full logo only where its wordmark remains legible. Preserve source aspect ratio and align artwork optically.
- The supplied assets are installed at `frontend/public/branding/` and `frontend/app/{favicon.ico,icon.png,apple-icon.png}`. Use the K mark in sidebar/mobile header; keep **Klipnara** as accessible HTML text. Use full logo only where wordmark stays legible. Next.js discovers app icons from their file names; keep metadata title/description current.
- Do not redraw, crop, recolor, stretch, or substitute the mark. Do not use Clapperboard as product branding; it remains valid as a video-feature icon.

## Foundations

### Color

Use semantic color, typography, spacing, and radius tokens from `frontend/app/theme.css`:

| Token | Use |
|---|---|
| `--ink` | Main text |
| `--muted` | Secondary text; maintain readable contrast |
| `--line` | Subtle separators and control borders |
| `--paper` / `--surface` / `--canvas` / `--bg` | Surface / app background |
| `--surface` / `--surface-alt` / `--sidebar` | Panels, secondary surfaces, and navigation |
| `--border` / `--text` | Semantic aliases for `--line` / `--ink` |
| `--green` / `--green-dark` / `--green-soft` | Primary action, emphasis, selected state |
| `--primary` / `--primary-soft` / `--on-primary` | Semantic aliases/action contrast |
| `--amber` / `--warning`, `--red` / `--danger` | Warning / destructive or error state |

Use status color with text or an icon; never rely on color alone. Keep cards mostly neutral. Gradients belong only to existing feature illustrations or media previews, not routine UI surfaces.

### Theme behavior

- Dark is the default (`#0C1214` canvas); light is optional (`#F5F8F7`). Use `--surface`, `--surface-alt`, `--sidebar`, `--border`/`--line`, `--text`/`--ink`, `--muted`, `--primary`/`--green`, `--primary-soft`/`--green-soft`, and `--on-primary` consistently.
- `ThemeProvider` persists `dark` or `light` in local storage only. The root-layout initializer applies preference before first paint; never send theme preference to backend.
- Keep quick toggle in topbar and full toggle in Settings. Native controls follow selected `color-scheme`; media and user-selected subtitle/title colors remain unchanged.

### Typography

Use locally hosted Inter Variable from `frontend/app/fonts/InterVariable.woff2`, loaded with `next/font/local` in the root layout. Use `--font-body` and `--font-heading`; no runtime font-network request or remote font import. Do not reintroduce unbundled DM Sans/Manrope references.

| Role | Target |
|---|---:|
| Page title | 28px / 600 (24px on narrow mobile) |
| Section title | 20px / 600 |
| Card title | 16px / 600 |
| Body and input | 14px / 400 |
| Button and sidebar | 14px / 500 (mobile navigation: 12px) |
| Label | 14px / 400–500 |
| Metadata and caption | 12px / 400–500 |
| Primary statistic | 28px / 600 (24px on narrow mobile) |

Use `--type-page-title`, `--type-section-title`, `--type-card-title`, `--type-body`, `--type-control`, `--type-button`, `--type-sidebar`, `--type-label`, `--type-meta`, and `--type-stat`, with `--weight-*` and `--line-height-*` tokens from `frontend/app/theme.css`. Do not add hardcoded UI font sizes or weights when a role token applies. Headings use compact 1.25–1.35 line-height, body uses 1.5, and metadata uses 1.45. Keep letter-spacing subtle; do not tighten body copy. Ordinary UI text must be at least 12px. Only non-interactive ruler ticks and compact timeline lane metadata may use 10px when required by timeline density. Subtitle, title-overlay, and rendered-video typography stay editor-controlled and must not inherit UI typography changes. Never use small-type exceptions for interactive controls, account instructions, diagnostics, or status explanations.

### Spacing and shape

Use spacing tokens `--space-1` (4), `--space-2` (8), `--space-3` (12), `--space-4` (16), `--space-6` (24), `--space-8` (32), and `--space-10` (40). Use 8/12/16px gaps for controls, groups, and cards; 24/32px between major sections. Keep card radius near `--radius-card` and control radius near `--radius-control`. Keep `min-width: 0` on grid/flex children with variable-length content.

## Shared UI patterns

Use existing shared classes before adding page-specific variants: `.button`, `.icon-button`, `.field`, `.panel`, `.notice`, `.page-intro`, `.eyebrow`, `.empty-*`, shared status classes, and `ThemeToggle`. Add a React wrapper only when it removes repeated behavior, not merely to wrap one markup instance. Keep classnames compatible with existing routes.

### Buttons and icons

- Variants: `.button-primary`, `.button-outline` (secondary), `.button-quiet` (ghost), and `.button-danger`; use `.button` as shared base. Use one clear primary action per group. Destructive actions use a solid red button.
- Default button height: 42px; common outline/compact actions: at least 40px. Mobile targets should reach 44px where workflow density permits. Dense timeline actions may stay compact but need visible labels/tooltips and remain keyboard-operable.
- Button text is 14px / 500. Align Lucide icons with text; use 16px for compact controls, 18px for navigation, and 20–24px for section/empty-state symbols.
- Icon-only controls need an accessible name, visible focus, and a comfortable hit area. Keep `.icon-button` hit areas at least 36px except dense editor/timeline controls; small controls are explicit exceptions, not general button style.

### Forms

- Labels remain visible and use 14px. Body/input/select text uses 14px. Helper text uses at least 12px and explains a constraint or next step.
- Standard fields target 44px height, consistent borders, radius, and focus treatment. Group related values; do not use placeholder text as the only label.
- Preserve native input semantics and validation. Use `aria-invalid` and associate actionable error text where appropriate. Do not change trust-boundary validation as a styling shortcut.

### Cards, tables, badges

- Use `.panel` for a meaningful grouping, not every nested element. Keep one primary surface per hierarchy level. Prefer existing `.notice`, `.status-*`, `.review-*`, and `.account-*` classes for alerts/status; pair color with readable text or icon.
- Cards use consistent padding and aligned titles/actions; long filenames, paths, and titles wrap or ellipsize deliberately without expanding grids.
- Tables use readable row/heading hierarchy and may scroll horizontally inside their own wrapper when columns cannot fit. Label status badges and keep text readable; avoid microtype for account or publishing state.

### Dialogs and confirmations

- Use the shared native `<dialog>` confirmation (`ConfirmProvider` / `useConfirm`) for yes/no decisions. `showModal()` provides modal focus containment, Escape cancellation, and focus restoration. State the consequence and label actions specifically; use red for destructive confirmation.
- Existing multi-step dialogs retain their workflow and API success/error behavior, but share overlay, viewport bounds, spacing, headings, footer alignment, and focus treatment.
- Disable close/cancel controls while an irreversible request is in progress when needed. Do not close before success. Keep errors inside the dialog. Do not use `window.alert()` or `window.confirm()` for app flows.

### Loading, empty, and feedback states

- Use existing loading indicators, progress bars, and skeleton styles where present; loading must not look like a successful empty result. Preserve prior successful data and show stale/error status when refresh fails.
- Empty states explain what is absent and give a relevant next action. Keep loading/error/success feedback near the action or affected content; use `role="status"`/`aria-live` when dynamic feedback needs announcement.
- Report success only after the existing backend operation succeeds. Preserve current request, cancellation, and retry semantics.

## App shell and responsive layout

- Main content shares a maximum width of 1380px and aligns with the topbar. Desktop sidebar is about 244px; keep backend status subordinate to navigation.
- Desktop uses a fixed sidebar grouped into Workspace, Distribusi, and Utility, plus a compact sticky topbar. Mobile uses a five-item bottom navigation: Ringkasan, Buat Video, Clip Library, Publishing Studio, and **Lainnya**. Put Asset Library, Batch Creator, Akun Terhubung, and Pengaturan in the accessible More menu; do not remove route access.
- Account for `env(safe-area-inset-bottom)`. Reserve content space for the bottom bar. Keep the More menu reachable by keyboard and expose `aria-expanded`/`aria-controls`.
- Review at 1440px+, 1366px, 1024/768px, 390px, and 320px. Use responsive grids, wrapping toolbars, and `minmax(0,1fr)`. Prevent page-level horizontal overflow; horizontal scrolling is reserved for tables/timelines that need it.
- Dialogs must fit within viewport height and scroll internally. Media previews preserve their aspect ratio. Do not clip ancestors around sticky editor preview.

## Workflow patterns

### Dashboard, creation, library, settings, batches

Keep one clear page title, concise description, and a primary next action. Use consistent statistic cards, form groups, source/file metadata, progress, and empty/error feedback. Settings paths and diagnostic output must wrap safely. Batch progress and item status remain distinct; preserve queue and retry behavior.

### Clip editor

Quick Clip, AI Smart Clip, and YouTube Clip share `frontend/app/clips/[id]/page.tsx`. Existing editor state, callbacks, API routes, validation, keyboard shortcuts, and `clips.edit_json` remain authoritative. Mood Quotes retains its separate preview and project/render flow.

Desktop workspace uses roughly 60/40 columns (`1.55fr` / `1fr`, minimum 320px preview column). Editing panels sit left; one browser composition preview sits right. Preview is sticky below the topbar and stops before timeline. No overflow-clipping ancestor wraps it.

Preview preserves 9:16 aspect ratio and caps at 260px width. Short desktop viewports may reduce it to 190px. Keep Play/Pause, Replay, output seek/current/total time, preview-only mute, fullscreen, source/render switch, and collapse available. Browser overlays reflect the current draft without remounting video for style edits. Browser composition preview is not final MP4; final render remains FFmpeg. Mark old renders when the draft is outdated; missing media shows fallback without clearing draft.

At widths `<=1080px`, stack preview before controls and disable sticky positioning. Mobile uses a 220px preview cap, collapsible preview, wrapped actions, usable touch controls, and horizontally scrollable timeline. Preserve `compositionTime`, scene/subtitle selection, seek, trim, cut, reorder, zoom, undo/redo, and timeline collapse behavior.

Multi-Scene shows a keyboard-accessible Transition Slot at each scene join: active Insert Slot occupies added output time; active Overlap overlays both scene blocks and subtracts time; hard cuts show a compact `+`, never a fake gap. Use lavender slots, selected focus, effect/duration tooltip, and open only selected join settings. Legacy projects remain None/Hard Cut; newly added transitions start as Insert Slots, 0.5s. Keep Crossfade and Dip to Black first; also offer directional Wipe, Slide, and Smooth, Circle Open/Close, Dissolve, Pixelize, Radial, and Fade to White. Keep legacy Zoom Blur disabled with Crossfade-fallback disclosure. Smooth Audio checkbox stays compact. Explain Insert/Overlap in slot settings, not timeline copy. Include From/To, effect, mode, frame-aligned 0.1–2s number/slider, Smooth Audio, Preview, Apply to All eligible, and Remove. Use actual output duration for ruler, playhead, and subtitle lanes. Browser preview is an approximation of FFmpeg; label it. Keep horizontal scrolling, scene reorder, cut, undo/redo, and autosave behavior.

Trim, Crop & Focus, Subtitle & Translation, and Audio/Title/Export use native `<details>/<summary>` disclosures. Save state follows the existing JSON snapshot/PATCH flow: **Saving**, **Save failed**, **Unsaved changes**, or **Saved** only after success. Keep review/render/publish gates and serialized autosave unchanged.

Camera & Reframe stays inside the shared Clip Editor. Keep Dynamic Reframing opt-in so old projects retain their manual crop; show position and camera zoom separately from timeline zoom. Pointer drag works with mouse and touch, while keyframe diamonds stay selectable on the scene-local timeline. Keep Hold/Linear/Smooth under a compact advanced disclosure. Camera keyframes follow stable scene IDs and integer local frames through split, trim, cut, duplicate, reorder, and delete. Source framing moves beneath output-space titles and captions; browser preview is a visual approximation of FFmpeg, not a pixel-match guarantee.

Keep Camera & Reframe and Crop/Audio/Export full-width within the editor controls. Keep camera values beside their sliders, selected-keyframe state visible, Add Keyframe primary, and deletion subdued. Group Crop, Output, Audio, and Title/Overlay with subtle dividers; disabling title overlay disables its controls without clearing values. Composition preview uses centered 9:16 framing, source/render choice, local status, scene/output metadata, accessible transport, and a concise browser-versus-FFmpeg note. Preserve sticky desktop preview.

Word Pop is a caption type, not a preset. Show one timed word at a time and leave silence gaps empty. Keep each cue editable and explicitly reviewed before Word Pop can activate/render. Changing cue text or bounds clears review without discarding words. Presets change appearance only. Preview honors `prefers-reduced-motion`; final FFmpeg ASS uses one positioned event per word.

### Mood Quotes

Group its multi-step workflow into clear stages. Keep template, quote, visual, audio, preview, timeline, render, and approval controls visually distinct; do not give every control equal emphasis. Preserve quote history, project state, preview behavior, and render/approval flow. Timeline alone owns horizontal scrolling.

### Publishing Studio and Connected Accounts

Keep publishing tabs, queue, metadata, calendar, and analytics within the existing route and API contracts. Make destination/account selection explicit, statuses legible, and confirmation content scannable. Analytics remains a fourth Publishing Studio tab with native responsive SVG/CSS and no chart dependency.

OAuth readiness, requested scopes, callback URI, and callback errors come from `GET /api/youtube/config`. Enable connection only when backend provides a valid local start URL. Render/copy only the backend-provided valid callback URI; never guess one. Use placeholders in environment examples; never expose Client Secret or OAuth tokens. Read actual connected state and granted scopes from `/api/youtube/accounts`. Credential presence/requested scopes never imply permission. Keep setup guide discoverable and disabled-action reasons readable.

Analytics scope stays explicit: **Channel** is a full channel report; **Klipnara** filters to published IDs linked to local records. Never blend totals or relabel `views` as `engagedViews`. Exclude the current day from date inputs; show requested/returned coverage and cache/fresh status. Preserve prior successful data with a stale/error notice on refresh failure. Separate Views and Engaged Views charts. Tables may scroll within their wrapper. Rule insights show timeframe/sample count and remain descriptive, never causal. CSV exports returned API data and escapes spreadsheet formulas. No estimated revenue or arbitrary-channel chooser.

## Accessibility and UX writing

- All actions work by keyboard; focus is visible. Use native buttons/links and disclosure semantics. Icon-only actions have an accessible label. Do not hide essential actions behind hover.
- Maintain readable contrast, reduced-motion support, and usable disabled states. Pair color with text/icon for status. Dynamic success/error/loading feedback is announced when appropriate.
- Write concise Indonesian UI copy by default; keep established technical terms when they improve precision. Explain consequences before destructive or cloud/paid actions. Use action labels that say what happens next.

## Manual QA checklist

Before closing a UI change, review at desktop wide, 1366px, 768px, 390px, and 320px:

- Dark default and light option, no preference flash, typography hierarchy, contrast, and no ordinary text below 12px.
- Alignment, spacing, long text/path overflow, and page width.
- Primary/secondary/destructive button hierarchy and touch targets.
- Keyboard tab order, visible focus, accessible names, dialog Escape/focus restoration.
- Loading, empty, error, disabled, and success feedback.
- Safe-area bottom navigation, More-menu access, dialog viewport fit, and video aspect ratio.
- Editor sticky preview and horizontally scrollable timeline; no changes to editor, publishing, or rendering behavior.

Browser QA is a manual step; static inspection does not establish visual correctness or contrast compliance. Existing Node built-in tests are `frontend/lib/clip-editor-state.test.mjs` and `frontend/lib/word-pop.test.mjs`; run them only when explicitly authorized.

# Klipnara UI/UX Design Standards

This document is required reading before creating or changing frontend UI. Keep visual changes within these standards and preserve existing business logic, API contracts, local data, and media-processing behavior.

## Product direction

**Modern Creator Studio — clean, refined, minimal, user-friendly.** Keep the existing emerald accent, neutral surfaces, clear hierarchy, and functional video-workflow density. Prefer readable content and useful grouping over decoration. Avoid nested cards, heavy shadows, decorative gradients, excessive borders, or unexplained whitespace.

## Brand assets

- Use only supplied official Klipnara assets. Never redraw, approximate, crop, recolor, or substitute the official mark.
- Use the K mark at small sizes; use the full logo only where its wordmark remains legible. Preserve source aspect ratio and align artwork optically.
- Apply supplied assets consistently to sidebar, mobile header, favicon, Next.js app icon, and Apple touch icon. Update metadata when assets arrive.
- Until official files exist in the repository, use the **Klipnara** text wordmark only. Do not use Clapperboard as product branding; it remains valid as a video-feature icon.

## Foundations

### Color

Use existing tokens from `frontend/app/globals.css`:

| Token | Use |
|---|---|
| `--ink` | Main text |
| `--muted` | Secondary text; maintain readable contrast |
| `--line` | Subtle separators and control borders |
| `--paper` / `--canvas` | Surface / app background |
| `--green` / `--green-dark` / `--green-soft` | Primary action, emphasis, selected state |
| `--amber` / `--red` | Warning / destructive or error state |

Use status color with text or an icon; never rely on color alone. Keep cards mostly neutral. Gradients belong only to existing feature illustrations or media previews, not routine UI surfaces.

### Typography

Use `--font-body` and `--font-heading`. Both resolve to a system UI stack so local-first installs do not depend on network fonts or fonts incidentally installed on one machine. Do not reintroduce remote font imports or unbundled DM Sans/Manrope references.

| Role | Target |
|---|---:|
| Page title | 26–30px |
| Section title | 20–24px |
| Card/subsection title | 16–18px |
| Body and form control | 14px |
| Button and field label | 13–14px |
| Secondary text | 13–14px |
| Metadata/caption | 12px; 11px only when constrained |

Do not use text below 11px for ordinary UI. The only small-type exceptions are timeline rulers/compact timeline labels and subtitle text rendered inside a video preview, where sizing represents output content. Never use those exceptions for interactive controls, account instructions, diagnostics, or status explanations.

### Spacing and shape

Use spacing tokens `--space-1` (4), `--space-2` (8), `--space-3` (12), `--space-4` (16), `--space-6` (24), `--space-8` (32), and `--space-10` (40). Use 8/12/16px gaps for controls, groups, and cards; 24/32px between major sections. Keep card radius near `--radius-card` and control radius near `--radius-control`. Keep `min-width: 0` on grid/flex children with variable-length content.

## Shared UI patterns

Use existing shared classes before adding page-specific variants: `.button`, `.icon-button`, `.field`, `.panel`, `.notice`, `.page-intro`, `.eyebrow`, `.empty-*`, and shared status classes. Add a React wrapper only when it removes repeated behavior, not merely to wrap one markup instance. Keep classnames compatible with existing routes.

### Buttons and icons

- Variants: primary, outline/secondary, quiet/ghost, and destructive. Use one clear primary action per group. Destructive actions use a solid red button.
- Default button height: 42px; common outline/compact actions: at least 40px. Mobile targets should reach 44px where workflow density permits. Dense timeline actions may stay compact but need visible labels/tooltips and remain keyboard-operable.
- Button text is 13–14px. Align Lucide icons with text; use 16px for compact controls and 18–20px for primary navigation or section markers.
- Icon-only controls need an accessible name, visible focus, and a comfortable hit area. Small editor/timeline controls are documented exceptions, not a general button style.

### Forms

- Labels remain visible and use 13–14px. Body/input/select text uses 14px. Helper text uses at least 12px and explains a constraint or next step.
- Standard fields target 44px height, consistent borders, radius, and focus treatment. Group related values; do not use placeholder text as the only label.
- Preserve native input semantics and validation. Use `aria-invalid` and associate actionable error text where appropriate. Do not change trust-boundary validation as a styling shortcut.

### Cards, tables, badges

- Use `.panel` for a meaningful grouping, not every nested element. Keep one primary surface per hierarchy level.
- Cards use consistent padding and aligned titles/actions; long filenames, paths, and titles wrap or ellipsize deliberately without expanding grids.
- Tables may scroll horizontally inside their own wrapper when columns cannot fit. Label status badges and keep text readable; avoid microtype for account or publishing state.

### Dialogs and confirmations

- Use the shared native `<dialog>` confirmation (`ConfirmProvider` / `useConfirm`) for yes/no decisions. `showModal()` provides modal focus containment, Escape cancellation, and focus restoration. State the consequence and label actions specifically; use red for destructive confirmation.
- Existing multi-step dialogs retain their workflow and API success/error behavior, but share overlay, viewport bounds, spacing, headings, footer alignment, and focus treatment.
- Disable close/cancel controls while an irreversible request is in progress when needed. Do not close before success. Keep errors inside the dialog. Do not use `window.alert()` or `window.confirm()` for app flows.

### Loading, empty, and feedback states

- Loading must not look like a successful empty result. Preserve prior successful data and show stale/error status when refresh fails.
- Empty states explain what is absent and give a relevant next action. Keep loading/error/success feedback near the action or affected content; use `role="status"`/`aria-live` when dynamic feedback needs announcement.
- Report success only after the existing backend operation succeeds. Preserve current request, cancellation, and retry semantics.

## App shell and responsive layout

- Main content shares a maximum width near 1240px and aligns with the topbar. Desktop sidebar is about 232px; keep backend status subordinate to navigation.
- Desktop uses a fixed sidebar and compact sticky topbar. Mobile uses a five-item bottom navigation: Ringkasan, Buat Video, Clip Library, YouTube Studio, and **Lainnya**. Put Asset Library, Akun, and Pengaturan in the accessible More menu; do not remove route access.
- Account for `env(safe-area-inset-bottom)`. Reserve content space for the bottom bar. Keep the More menu reachable by keyboard and expose `aria-expanded`/`aria-controls`.
- Review at 1440px+, 1366px, 900/768px, 390px, and 320px. Use responsive grids, wrapping toolbars, and `minmax(0,1fr)`. Prevent page-level horizontal overflow; horizontal scrolling is reserved for tables/timelines that need it.
- Dialogs must fit within viewport height and scroll internally. Media previews preserve their aspect ratio. Do not clip ancestors around sticky editor preview.

## Workflow patterns

### Dashboard, creation, library, settings, batches

Keep one clear page title, concise description, and a primary next action. Use consistent statistic cards, form groups, source/file metadata, progress, and empty/error feedback. Settings paths and diagnostic output must wrap safely. Batch progress and item status remain distinct; preserve queue and retry behavior.

### Clip editor

Quick Clip, AI Smart Clip, and YouTube Clip share `frontend/app/clips/[id]/page.tsx`. Existing editor state, callbacks, API routes, validation, keyboard shortcuts, and `clips.edit_json` remain authoritative. Mood Quotes retains its separate preview and project/render flow.

Desktop workspace uses roughly 60/40 columns (`1.55fr` / `1fr`, minimum 320px preview column). Editing panels sit left; one browser composition preview sits right. Preview is sticky below the topbar and stops before timeline. No overflow-clipping ancestor wraps it.

Preview preserves 9:16 aspect ratio and caps at 260px width. Short desktop viewports may reduce it to 190px. Keep Play/Pause, Replay, output seek/current/total time, preview-only mute, fullscreen, source/render switch, and collapse available. Browser overlays reflect the current draft without remounting video for style edits. Browser composition preview is not final MP4; final render remains FFmpeg. Mark old renders when the draft is outdated; missing media shows fallback without clearing draft.

At widths `<=1080px`, stack preview before controls and disable sticky positioning. Mobile uses a 220px preview cap, collapsible preview, wrapped actions, usable touch controls, and horizontally scrollable timeline. Preserve `compositionTime`, scene/subtitle selection, seek, trim, cut, reorder, zoom, undo/redo, and timeline collapse behavior.

Trim, Crop & Focus, Subtitle & Translation, and Audio/Title/Export use native `<details>/<summary>` disclosures. Save state follows the existing JSON snapshot/PATCH flow: **Saving**, **Save failed**, **Unsaved changes**, or **Saved** only after success. Keep review/render/publish gates and serialized autosave unchanged.

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

- Typography hierarchy, contrast, and no ordinary text below 11px.
- Alignment, spacing, long text/path overflow, and page width.
- Primary/secondary/destructive button hierarchy and touch targets.
- Keyboard tab order, visible focus, accessible names, dialog Escape/focus restoration.
- Loading, empty, error, disabled, and success feedback.
- Safe-area bottom navigation, More-menu access, dialog viewport fit, and video aspect ratio.
- Editor sticky preview and horizontally scrollable timeline; no changes to editor, publishing, or rendering behavior.

The app is light-theme only. Do not claim dark-theme compatibility. Browser QA is a manual step; static inspection does not establish visual correctness. Existing Node built-in tests are `frontend/lib/clip-editor-state.test.mjs` and `frontend/lib/word-pop.test.mjs`; run them only when explicitly authorized.

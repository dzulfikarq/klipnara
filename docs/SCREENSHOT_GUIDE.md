# Portfolio Screenshot Guide

Use screenshots only when they show a real Klipnara screen and can be published safely. Never fabricate UI, seed the primary user database, or capture private media/accounts for the portfolio.

## Capture standard

- Use a dedicated browser profile and the locally running application; do not reuse a signed-in personal browser profile.
- Set viewport to **1600 × 900** at normal browser zoom. Wait for the page and API data to settle before capture.
- Save reviewed captures as WebP in `docs/screenshots/`, named `NN-feature.webp`. Keep text crisp and target roughly **150–500 KB** when practical.
- Remove cursor, tooltip, menu, loading state, and framework debug overlay. Do not crop or alter app content to imply a feature state that did not exist.
- Inspect each final image at full size. Check alt text, README relative paths, dimensions, file size, and visible UI text before adding it to the gallery.

## Privacy and rights

- Prefer synthetic or demo media created for public use, or footage the project owner has explicitly approved and has rights to publish.
- Inspect each route before capture. Exclude source names, transcripts, quote drafts, file paths, hardware-specific diagnostics, account/channel names, OAuth state, credentials, and unpublished content.
- Use test accounts only with explicit permission. Never click upload, publish, OAuth, import, delete, or render actions for a screenshot.
- If the active workspace contains user data and no isolated, approved demo dataset is available, skip that screen. Do not change or clear the primary workspace to make a screenshot.
- Opening `/mood` without an `id` creates a new local Mood draft. Avoid that route during a read-only capture unless using an isolated demo database.

## Refresh workflow

1. Start the app manually by following [Getting Started](getting-started.md); this guide does not authorize an agent to start or restart services.
2. Inspect the target screen and its visible data in a dedicated browser profile. Confirm media rights and privacy before capture.
3. Capture the genuine viewport at 1600 × 900. Keep original app layout and text; only remove browser/framework chrome and transient overlays.
4. Save only approved WebP files under `docs/screenshots/`, then update `README.md` captions, alt text, and relative links.
5. Review every image and the README diff. Do not publish captures containing unapproved media or account information.

Current published files use these names:

- `01-workflow-selector.webp`
- `02-quick-clip-setup.webp`
- `03-youtube-clip-setup.webp`
- `04-batch-creator-empty.webp`

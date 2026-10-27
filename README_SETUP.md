# How to install these Git standards in Klipnara

1. Place `docs/GIT_WORKFLOW.md` in the repository's `docs/` directory.
2. If a root `AGENTS.md` already exists, **merge** the included `AGENTS.md` rules without removing existing project guidance. Otherwise place the supplied file at the repository root.
3. Optionally merge `"docs/GIT_WORKFLOW.md"` into the existing `instructions` array of `opencode.json` / `opencode.jsonc` if used. Do **not** replace other entries or create competing config files.
4. Add a brief reference to `docs/GIT_WORKFLOW.md` in `README.md` or contributor guidance.
5. Review these changes. Request a **local commit** specifically if you want the agent to create one, and request a **push** separately.

This package contains only documentation. It does not edit your local Git repository, create commits, or push anything.

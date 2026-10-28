# Klipnara — Coding Agent Instructions

These project-wide rules apply to all coding-agent sessions. If a root `AGENTS.md` already exists, **merge** these rules into it rather than replacing existing instructions.

## Git workflow is mandatory

- **Before every `git add`, `git commit`, or `git push` operation, explicitly read `docs/GIT_WORKFLOW.md` again.** Do not rely solely on memory or earlier reads.
- Follow the Conventional Commits naming and logical-change requirements in that document.
- Before staging, inspect the working tree and relevant diff; stage only reviewed, task-related files or hunks. Review staged content before each commit.
- Before proposing a commit, inspect actual changes and provide a **logical commit plan** (files and messages). A feature may warrant multiple commits, but never create filler commits to increase the count.
- **Never execute `git commit` unless the user has explicitly authorized committing for the current task.**
- **Never execute `git push` unless the user has explicitly authorized pushing.** Commit approval is not push approval. An instruction explicitly authorizing both covers both actions.
- Never force-push, amend/rewrite existing history, delete branches, or alter tags without separate explicit authorization.
- Do not assume the target branch or remote; inspect them and follow the user's instructions.

## Environment and data safety

- Never start, stop, restart, or kill development processes; do not use `taskkill`, `Stop-Process`, or other PID-management commands.
- Never run dev servers, build commands, tests, FFmpeg, browser automation, or external API uploads unless the user explicitly authorizes that exact category of action.
- Do not commit secrets, `.env` files, OAuth tokens, API keys, media exports, virtual environments, local databases, generated outputs, or machine-specific artifacts.
- Review changes to files such as `frontend/next-env.d.ts` and directories such as `backend/.venv_old/` instead of staging them automatically.
- Do not modify user data, credentials, or unrelated files without a task-specific reason and approval where needed.

## Documentation and reporting

- Update applicable product documentation (`README.md`, relevant `docs/*`) when implementing features.
- When finishing a task, report what changed, what was not run, any risks, and the proposed commit grouping. Do not claim tests or runtime checks passed when they were not run.

## Frontend UI/UX

- Before creating or changing frontend UI, read and follow `docs/design.md`. Treat its brand, typography, spacing, responsive, accessibility, and workflow rules as required standards.
- Preserve existing route behavior, API contracts, local data, and media-processing logic while refining presentation.

**Detailed required standard:** `docs/GIT_WORKFLOW.md`.

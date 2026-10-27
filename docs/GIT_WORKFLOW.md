# Klipnara — Git Workflow & Commit Standards

**Status:** Mandatory repository standard  
**Applies to:** Coding agents, contributors, and all Git commit/push operations  
**Purpose:** Maintain a useful, honest, reviewable history as Klipnara grows.

## 1. Core principles

1. Prefer **many meaningful, logically scoped commits** over one enormous commit for a substantial feature.
2. **Do not target an arbitrary commit count.** A small fix may need one commit; a large feature may warrant several. Never create filler commits merely to make the contribution graph look busy.
3. A commit should represent one coherent change that can be understood and, where practical, reviewed or reverted independently.
4. Commit messages and timestamps must accurately reflect work actually done. Never backdate, fabricate history, or create empty commits for appearance.
5. Keep code, tests, and documentation synchronized; separate commits only when doing so keeps each commit coherent.
6. Preserve existing history; never force-push, rewrite commits, or rebase shared branches without explicit authorization.

## 2. Mandatory reading and permission gates

Before **each** `git add`, `git commit`, and `git push`, the agent must re-open this document and check its requirements.

- **Read-only Git inspections** (`git status`, `git diff`, `git log`) are allowed for review.
- **Staging and local commits** are not automatically authorized by a request to implement a feature. Get explicit user approval to commit for that task.
- **Pushing** requires its own explicit approval. Approval to commit does **not** imply approval to push.
- If the user explicitly says, for example, “commit and push the changes,” that authorizes both for that stated task, subject to the checks below.
- If permission or the intended branch/remote is uncertain, stop and ask. Never silently push.

## 3. Conventional Commits

Use the format:

```text
<type>(<scope>): <short imperative description>
```

Allowed examples of `type`:

| Type | Use for |
| --- | --- |
| `feat` | New user-facing functionality |
| `fix` | Bug or correctness repair |
| `refactor` | Internal improvement without intentional behavior changes |
| `perf` | Performance improvement |
| `test` | Tests or test infrastructure |
| `docs` | Documentation-only changes |
| `chore` | Maintenance unrelated to product behavior |
| `build` | Build system and dependencies |
| `ci` | CI/workflow changes |

Use short, concrete English descriptions. Choose scopes that match the affected module (`auth`, `youtube`, `tiktok`, `instagram`, `publish`, `analytics`, `editor`, `subtitle`, `mood`, `db`, `ui`). Scope is optional if it adds no clarity.

Good examples:

```text
feat(db): support multiple connected accounts
feat(auth): persist provider grants per account
feat(youtube): add multi-channel selection
feat(publish): create destination-specific upload jobs
fix(publish): reject wrong-account upload targets
test(publish): cover multi-account retry isolation
docs: document account connection workflow
```

Avoid vague messages such as `update`, `fix stuff`, `changes`, `wip`, or `final`.

## 4. How to split a substantial feature

Plan commits based on **real implementation boundaries**, for example:

1. Database model and backward-compatible migration.
2. Provider/OAuth logic.
3. Backend API and queue integration.
4. Frontend UI and interactions.
5. Targeted bug fixes or performance changes.
6. Relevant regression tests.
7. Documentation updates.

This is a **planning example, not a fixed quota or mandatory sequence**. Related code and tests may be combined when splitting would create a broken or confusing commit. Avoid combining unrelated work just to save commits.

For changes already piled up in the working tree, reconstruct commits **only from actual file differences**. Do not invent intermediate states or claim an old feature was independently completed if the current diff does not support that claim.

## 5. Before staging: mandatory preflight

1. Re-read this file.
2. Inspect the current branch, remote, working tree, and recent commits using read-only Git commands.
3. Identify which changes belong to the current task and which existed beforehand.
4. Propose a commit plan listing **message, purpose, and files/hunks** for each planned commit.
5. Explicitly exclude secrets and non-source artifacts.
6. State verification status accurately: **not run** for any test/build/runtime action the user has not authorized.
7. Wait for the appropriate authorization before staging/committing.

Useful read-only commands:

```bash
git status --short
git branch --show-current
git remote -v
git log -5 --oneline
git diff --stat
git diff --check
```

Only run commands appropriate to the user's current permission and environment. `git diff --check` checks whitespace issues; it is **not** a substitute for tests.

## 6. Staging rules

- Prefer explicit paths or intentional patch/hunk staging instead of `git add .` or `git add -A`.
- Check `git diff --cached --stat` and `git diff --cached` **before every commit**.
- Confirm the staged content matches the proposed commit message.
- Do not mix unrelated feature work into the same commit.
- Do not stage files just because they are untracked.
- If changes are intertwined and cannot be separated safely, disclose this and use a coherent larger commit rather than a contrived sequence.

### Never commit by default

- `.env`, `.env.*` containing real values, OAuth tokens, API secrets, credentials, private keys.
- `node_modules/`, `.next/`, `dist/`, `build/`, `.venv/`, `.venv_old/`, caches and logs.
- User SQLite databases, local state, private account records, or runtime files.
- Source media exports, rendered MP4 files, large thumbnails, temporary assets, or downloaded music/footage unless the user explicitly requested specific legally reusable fixtures.
- Machine-generated or machine-specific changes without review (for example `frontend/next-env.d.ts`).

Use the repository's `.gitignore`; if missing necessary patterns, propose/implement targeted additions without hiding legitimate source files.

## 7. Before each commit

Confirm all of the following:

- The user explicitly approved committing for the task.
- This document has been re-read.
- The staged diff is reviewed and free from credentials/unrelated files.
- The commit is a coherent logical unit with a Conventional Commit message.
- Applicable documentation and tests were updated or omissions explained.
- No forbidden runtime operation was performed.
- Verification status is reported honestly.

Then create **only the authorized local commit(s)**. Do not automatically push afterward unless separately authorized.

## 8. Before each push

Confirm all of the following:

- The user explicitly approved pushing.
- This document has been re-read.
- The exact remote and destination branch are known.
- The intended commit range has been reviewed, including any pre-existing local commits that would also be pushed.
- The repository contains no known secrets or unintended large artifacts in those commits.
- You can state which commit hashes/branch will be pushed.
- No `--force`, `--force-with-lease`, history rewrite, branch deletion, or tags unless **separately** requested.

Only push the approved branch/commits to the approved remote. If the remote has diverged or permissions fail, stop and report the issue rather than improvising a history rewrite.

## 9. Required final report format

At task completion, include:

```text
Implementation: <what changed>
Documentation: <files updated>
Verification: <read-only checks performed; tests/build/runtime not run unless authorized>
Proposed commits:
  1. feat(...): ... — affected files
  2. test(...): ... — affected files
  3. docs: ... — affected files
Git state: <branch, working tree, committed/not committed>
Push state: not pushed (unless explicitly approved and completed)
Warnings: <unrelated changes, credentials, migration risks, known limitations>
```

If commits were authorized and created, list their **actual** hashes and messages. If push was authorized, report the actual target branch/remote and outcome. Do not fabricate hashes, tests, or success statuses.

## 10. Relationship to coding-agent rules

The project root `AGENTS.md` must link to this document and require a fresh read before every Git-changing action. For OpenCode, the project instruction configuration may additionally include `docs/GIT_WORKFLOW.md` in its `instructions` array to keep the full standard available throughout the session. Preserve existing configuration and merge rather than overwrite.

**Default policy: plan and recommend commits; execute local commit/push only upon explicit user instruction.**

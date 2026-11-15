# PLAN: Fork release hardening

## Goal
Make the fork's release flow match how established forks work (Git for Windows,
microsoft/git, swiftlang/llvm-project): `main` only changes through pull requests,
stable releases are immutable and versioned instead of one moving `fork-stable` tag,
promotion needs an explicit approval, and a scheduled job reports when upstream
has moved ahead, so syncing no longer depends on someone remembering.

## Context
- Repo / worktree: `/home/disorder/Projects/Github/chunkhound/.claude/worktrees/release-hardening`
- Branch: `ci/fork-release-hardening` (from `origin/main` 767c5b0c), one PR against the fork's `main`.
- Project rules: read `AGENTS.md` and `FORK.md` before starting. `FORK.md` wins where they disagree.
- Already done on GitHub by Claude (not part of any phase):
  - Ruleset `main: PR only` on the default branch: PR required (0 approvals),
    required checks `tests (<os>, 3.14, <1|2|3>)` for ubuntu/macos/windows,
    no force push, no deletion. Admins may bypass only through a PR.
  - Tag ruleset `fork release tags immutable` on `refs/tags/fork-v*`: no deletion,
    no update, no non-fast-forward.
  - Environment `fork-stable`: required reviewer Cubical6 (self-review allowed),
    deployments only from branch `main`.
- Versioning today: hatch-vcs / setuptools-scm 10.x derives the version from the
  last upstream `v*` tag (`6.1.1.dev198+g767c5b0c6`). setuptools-scm's default
  describe uses `--match *[0-9]*`, so any fork tag with a digit would currently
  change the version. That is why fork tags have no digits so far.
- Release workflows: `.github/workflows/fork-release.yml` (rolling prerelease
  `fork-latest` on every push to `main`) and `.github/workflows/fork-promote.yml`
  (manual; today moves tag `fork-stable` and its release). Release notes:
  `scripts/fork_release_notes.py`. No `fork-stable` release exists yet, so no
  migration of an existing stable release is needed.

## Constraints (apply to every phase)
- Only change files listed in the phase, unless strictly needed; mention any extra file in the report.
- Do NOT commit, push, create tags/releases, or call GitHub APIs that change anything. Do not start other phases.
- Keep the fork's diff with upstream small: do not reformat or move upstream code; never edit version strings or `CHANGELOG.md`.
- Never put URLs to upstream (`chunkhound/chunkhound`) issues or PRs, or `chunkhound/chunkhound#N` references, in anything the workflows write to GitHub.
- Workflows: least-privilege `permissions` per job, no `pull_request_target`, no `${{ }}` interpolation of untrusted text inside `run:` scripts (pass through `env:`).
- Keep context small: search with `rg`, read only relevant line ranges, run targeted tests with
  `-q --tb=short`, and pipe long output through `| tail -n 40`.
- Do not run the full test suite; Claude runs it.

## Final report format (every phase)
At most ~15 lines:
1. Files changed (one line each, with a short reason)
2. Tests run, with results
3. Deviations from the plan and open issues

---

## Phase 1: Version derivation ignores fork tags
- [x] Done
- **Depends on:** none
- **Model:** `openai-codex/gpt-6.1-sol` / `medium`
- **Goal:** Tags named `fork-*` (for example `fork-v6.1.1.dev198`) never influence the derived version, locally or in CI, so stable releases can get versioned tags.
- **Files:** `pyproject.toml` (only the `[tool.hatch.version]` table), `.github/workflows/fork-release.yml` (only the `version` job), `tests/unit/test_fork_version_tags.py` (new)
- **Steps:**
  1. In `[tool.hatch.version]` add `raw-options` that make setuptools-scm describe only upstream-style tags and exclude `fork-*`, e.g. a git describe command `git describe --dirty --tags --long --match "v[0-9]*" --exclude "fork-*"`. Use the option name that setuptools-scm 10.x accepts without a deprecation warning (check its docs/source in the uv cache; `scm.git.describe_command` vs `git_describe_command`).
  2. In the `version` job of `fork-release.yml`, after deriving the version, assert that the result is unchanged when a `fork-v<version>` tag points at HEAD (create the tag locally on the runner only, then delete it), so a regression fails the build.
  3. Add `tests/unit/test_fork_version_tags.py`: build a temp git repo with the project's `[tool.hatch.version]` settings (read from `pyproject.toml`, not copied), tag `v6.1.0`, add commits, tag `fork-v6.1.1.dev2` on a later commit, and assert the version from setuptools-scm is still based on `v6.1.0` (`6.1.1.devN`). Skip if `git` is missing.
- **Acceptance criteria:**
  - In this worktree, `uv run --no-project --with hatch-vcs python -c "from setuptools_scm import get_version; print(get_version())"` prints the same version before and after a temporary local `git tag fork-v9.9.9` on HEAD (delete the tag afterwards).
  - New test passes; no deprecation warning from setuptools-scm for the chosen option.
- **Verify:** `uv run pytest tests/unit/test_fork_version_tags.py -q --tb=short`
- **Notes:** Upstream `v*` tags are fetched on the runner only (`git fetch --no-tags ... refs/tags/v*`); keep that. Do not change anything else in `pyproject.toml`.

## Phase 2: Immutable versioned stable releases
- [x] Done
- **Depends on:** Phase 1
- **Model:** `openai-codex/gpt-6.1-sol` / `medium`
- **Goal:** Promotion creates a new, immutable release `fork-v<public version>` (e.g. `fork-v6.1.1.dev198`) from the checked `fork-latest` build, behind the `fork-stable` environment, and marks it as the repository's Latest release. Rolling `fork-latest` is unchanged.
- **Files:** `.github/workflows/fork-promote.yml`, `.github/workflows/fork-release.yml` (only the release-notes / previous-stable lookup in the publish step), `scripts/fork_release_notes.py`, `tests/unit/test_fork_release_notes.py` (new)
- **Steps:**
  1. `fork-promote.yml`: add `environment: fork-stable` to the promote job. Keep the existing checks (commit input equals `fork-latest` commit, manifest commit, ancestor of `main`).
  2. Derive the public version from the downloaded manifest (strip the `+local` part). Tag `fork-v<public version>` at the expected commit; fail clearly if that tag or release already exists (never move or delete it).
  3. Create the release for that tag: not a prerelease, `--latest`, title `Fork stable <public version>`, notes from `fork_release_notes.py --channel stable`, upload the same assets (manifest last, as today). Remove all code that creates or moves the `fork-stable` tag/release.
  4. Previous stable for release notes (both workflows): the commit of the most recent `fork-v*` release (e.g. `gh api repos/$GH_REPO/releases/latest` → `tag_name`, only if it starts with `fork-v`, then resolve the tag's commit). Empty when none exists.
  5. `fork_release_notes.py`: accept an optional `--previous-name` (tag name) and use it in the headings instead of the generic "fork-stable" wording; keep current behaviour when absent. Keep it network-free.
  6. Test: unit tests for `fork_release_notes.py` heading/entry logic using a temp git repo with two commits of a minimal `CHANGELOG.fork.md`.
- **Acceptance criteria:**
  - No remaining reference to moving a `fork-stable` tag; `rg -n 'fork-stable' .github scripts` only shows the environment name and wording that is still correct.
  - Workflows are valid YAML; `actionlint` passes if available (`uvx actionlint` or skip and say so).
  - New tests pass.
- **Verify:** `uv run pytest tests/unit/test_fork_release_notes.py tests/unit/test_fork_version_tags.py -q --tb=short`
- **Notes:** Assets and integrity checks of the promote job stay as they are. `GITHUB_TOKEN` creating a tag via the API is allowed by the tag ruleset (it only blocks update/delete).

## Phase 3: Scheduled upstream watch
- [x] Done
- **Depends on:** none
- **Model:** `openai-codex/gpt-6.1-terra` / `medium`
- **Goal:** A daily workflow tells the maintainer, through one fork issue, how far `main` is behind upstream and which upstream releases are not merged yet; it closes that issue when the fork has caught up.
- **Files:** `.github/workflows/fork-upstream-watch.yml` (new), `scripts/fork_upstream_watch.py` (new), `tests/unit/test_fork_upstream_watch.py` (new)
- **Steps:**
  1. Workflow: `schedule` (daily, e.g. `17 5 * * *`) + `workflow_dispatch`; `if: github.repository != 'chunkhound/chunkhound'`; permissions `contents: read`, `issues: write`. Checkout with `fetch-depth: 0`, then `git fetch --no-tags https://github.com/chunkhound/chunkhound.git +refs/heads/main:refs/remotes/upstream/main '+refs/tags/v*:refs/tags/v*'`.
  2. `scripts/fork_upstream_watch.py` (stdlib only) computes from git: commits behind (`origin/main..upstream/main`), upstream `v*` tags not contained in `origin/main`, and a first-parent one-line log of what came in (max 30 lines). It renders the issue title and body as plain text. It rewrites `#123` to `upstream PR 123` and contains no URLs to the upstream repo.
  3. The workflow uses `gh` to find the one open issue with label `upstream-sync` (create the label if missing): behind > 0 → create it or edit title/body; behind == 0 → close it with a short comment. Title e.g. `Upstream sync: 12 commits behind (new release v6.2.0)`.
  4. Tests for the script's rendering and parsing (pure functions; feed fake git output), including the `#123` rewrite and the no-URL rule.
- **Acceptance criteria:**
  - Tests pass; workflow is valid YAML and passes `actionlint` if available.
  - No `pull_request_target`, no untrusted interpolation in `run:`.
- **Verify:** `uv run pytest tests/unit/test_fork_upstream_watch.py -q --tb=short`
- **Notes:** Do not open sync PRs automatically: merges can conflict and need a human (see `FORK.md`, Syncing upstream).

## Phase 4: Docs (Claude)
- [x] Done
- **Depends on:** Phases 1-3
- **Goal:** `FORK.md` describes the new rules: no direct pushes, the rulesets, the `fork-stable` environment approval, `fork-v*` stable releases, the upstream-watch issue. Add a `CHANGELOG.fork.md` entry under `## Changed` for the new stable release naming.
- **Files:** `FORK.md`, `CHANGELOG.fork.md`

---

## Final verification (Claude, after all phases)
- [ ] Targeted tests of all phases, plus the smoke suite from `AGENTS.md` (background task)
- [ ] `actionlint` on the changed workflows
- [ ] Review the complete diff against the Goal
- [ ] PR opened with an "Upstream check" section; `Fork rolling release` PR run green
- [ ] `.pi-handoff/` removed; nothing from it committed

## Progress log
| Date | Phase | sessionId | Commit | Notes |
|---|---|---|---|---|
| 2026-11-15 | GitHub settings | – | – | Rulesets 27308867 (main) and 27308868 (fork-v* tags), environment fork-stable created |
| 2026-11-15 | 1 | 01a1deaa-0a1f-73b8-ba81-120ea2013aa0 | c070f534 | describe_command via raw-options; CI asserts fork-v tag invariance |
| 2026-11-15 | 3 | 01a1deab-df15-73b8-ba81-12119f5618f6 | 71c4305e | Review fix: neutralise @-mentions, checkout v6 |
| 2026-11-15 | 2 | 01a1deae-6d1a-73b8-ba81-1212aa787949 | (this commit) | Review fixes: keep fork #N, draft-then-publish, verify tag commit |
| 2026-11-15 | 4 | – | (this commit) | FORK.md and CHANGELOG.fork.md by Claude |

---

## Prompts (for Claude, copy per phase)

**Start a phase** (new session, model from the phase):
> Read `AGENTS.md`, `FORK.md` and `docs/fork/plans/2026-11-15-release-hardening.md` in `<cwd>`. Implement only Phase N. Follow the Constraints and the
> Final report format in the plan. Do not start other phases.

**Feedback within a phase** (same `sessionId`, while context < ~200k):
> Review feedback on Phase N: <concrete problem, file:line, expected behaviour>. Fix only this and report.

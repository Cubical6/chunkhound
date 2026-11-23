# Fork workflow

This repository is `Cubical6/chunkhound`, a fork of `chunkhound/chunkhound`.
This file holds the fork's own rules for git, GitHub and releases. Where it
disagrees with `AGENTS.md` (VERSION_MANAGEMENT, and the rule to run the full
suite before pushing) or `RELEASING.md`, which both describe upstream, this
file wins.

## Remotes and branches

- `origin` is the fork. `upstream` is `chunkhound/chunkhound` and is read-only.
- `main` on the fork is upstream's `main` plus the fork's changes. Never rebase
  or force-push it, and never push to it directly: every change, also a sync
  or a one-line docs fix, goes through a pull request.
- GitHub enforces this with the ruleset `main: PR only`: a pull request is
  required (no approval needed), force pushes and deletion are blocked, and
  the checks of the `CI` workflow must pass (see "Tests" below). Do not change
  or disable the ruleset without the user's approval.

## Tests

The full suite runs on GitHub Actions in the `CI` workflow (`ci.yml`), on
every pull request and every push to `main`: Linux, macOS and Windows, each in
three shards, plus the Rust checks, the Watchman runtime validation and the
site build. The shards are balanced by the durations in `.test_durations`
(pytest-split). The workflows that stay on are `CI` and the fork's own
`Fork rolling release`, `Fork stable promotion` and `Fork upstream watch`.
`Minimal`, `Deprecate`, `Release` and `RC Release` are disabled. Do not delete
`ci.yml` or the other upstream workflows: they are upstream files, and deleting
them conflicts at the next sync. Do not enable or disable a workflow without
the user's approval.

- Locally, before every commit: the smoke suite, plus the tests of what you
  changed (`make rust-test` when Rust code or the native extension changed).
  Do not run the full suite locally as a gate; CI does that.
- The ruleset `main: PR only` requires the `CI` checks, so a pull request
  with red CI cannot be merged. Find the cause in the failed run
  (`gh run view <id> -R Cubical6/chunkhound --log-failed`), fix it and push
  again. Rerun a failed job only when the failure is a runner problem
  unrelated to the code, and say so in the pull request.
- Put the results in the pull request under a "Tests" heading: the CI run
  (link) for the last commit, every job rerun and why, every failure that
  passed through a `# flaky:` annotation, and the local tests you ran.
- When `.test_durations` no longer matches the suite (many tests added or one
  shard much slower than the others), regenerate it serially:
  `uv run pytest tests/ --store-durations -q`.
- Work on a branch cut from `origin/main` (`feat/…`, `fix/…`, `docs/…`,
  `ci/…`) and open the pull request against `main` of the fork.
- Pass `-R Cubical6/chunkhound` to every `gh` command that creates or changes
  something. In a fork `gh` can resolve to the parent repository.
- A plan with several phases merges its phase branches into one integration
  branch. Once the integration branch contains a phase branch, delete that
  branch (local and on `origin`) and remove its worktree.
- After a pull request is merged, delete its branch on both sides and remove
  its worktree.

## Nothing goes to upstream

- Do not create issues, pull requests, comments, reviews or reactions on
  `chunkhound/chunkhound`, unless the user asks for that specific item.
- A bug found in ChunkHound becomes an issue in the fork.
- Do not link to upstream items from the fork. A URL or a
  `chunkhound/chunkhound#123` reference in a fork issue, pull request, comment
  or commit message adds a public "mentioned this" entry to the upstream item.
  Write `upstream PR 523` or `upstream issue 516` as plain words instead.

## Check upstream before you start

Upstream is active: it usually has dozens of open pull requests, many of them
in the areas the fork also changes. Before you design a fix or a feature:

```bash
git fetch upstream
# Open upstream pull requests that touch these files or directories:
scripts/fork_upstream_check.sh chunkhound/services/realtime/ chunkhound/core/config/
# With no arguments: the files changed on the current branch.
scripts/fork_upstream_check.sh
# Upstream issues and pull requests about a topic, open and closed:
scripts/fork_upstream_check.sh --search "relative imports"
```

Then decide:

| What you find | What to do |
|---|---|
| Upstream already merged a fix | Sync upstream (below) instead of fixing it here. |
| An open upstream pull request solves it | Adopt it unchanged: `git fetch upstream pull/<N>/head` and merge or cherry-pick those commits. Do not write a competing implementation. |
| An open upstream pull request touches the same files for another reason | Keep the fork change small and local in those files, and expect a conflict at the next sync. |
| Only an upstream issue, no pull request | Fix it in the fork and note the upstream issue number in the fork issue, so the next sync can check whether upstream fixed it. |
| Nothing | Carry on. |

Put the outcome in the fork pull request under an "Upstream check" heading,
also when you found nothing. For an adopted pull request, name its number and
the commit you took.

## Keep the difference with upstream small

Every line the fork changes in an upstream file can conflict at a later sync.

- Robustness comes first. Keep the difference small through where you put
  code (fork-only files, one shared hook in an upstream file), never by
  picking a weaker design or a workaround. When the robust fix needs many
  upstream lines, make them, and name the expected sync conflicts and the
  open upstream pull requests on those files in the pull request under
  "Upstream check".
- Put fork-only code, tooling and docs in files that do not exist upstream.
- Do not reformat, rename or move upstream code.
- Do not edit `CHANGELOG.md`. It stays as upstream wrote it; the fork's
  changes go in `CHANGELOG.fork.md` (below).
- Never edit version strings.

## Fork changelog

`CHANGELOG.fork.md` lists what the fork changes on top of upstream. The release
notes of both fork releases are built from it, so a change without an entry is
invisible at release.

- Every pull request with a change a user of the fork notices (a `feat`, a
  `fix`, a changed default, a removed option) adds one entry, in that pull
  request. Tests, refactors and internal docs need none.
- An entry is one line under `## Added`, `## Changed`, `## Fixed` or
  `## Removed`, at the top of its heading, and starts with a bold title:
  `- **Title** — what changed, in terms of what the user sees`.
- Do not rename the title of an existing entry: the release notes use titles
  to tell new entries from old ones.
- During a sync, remove an entry when upstream now ships the same change. The
  release notes then list it as no longer fork-specific.

## Syncing upstream

Check how far behind the fork is:

```bash
git fetch upstream --tags
git rev-list --count origin/main..upstream/main
```

Sync when that count is above zero and one of these holds: upstream published
a release, upstream merged a fix for an open fork issue or for an area you are
about to work on, or you are about to start work that spans several days.

```bash
git switch -c sync/upstream-YYYYMMDD origin/main
git merge upstream/main
```

1. Resolve conflicts. Upstream's version wins for code the fork did not change
   on purpose. Where upstream fixed the same thing as a fork patch, take
   upstream's implementation, drop the fork's and remove its entry from
   `CHANGELOG.fork.md`.
2. Read what came in (`git log --oneline --first-parent origin/main..upstream/main`
   before the merge). For each open fork issue and fork branch, check whether
   upstream now covers it; close the issue or drop the branch if it does.
3. Run the smoke suite locally and let CI run the full suite (see "Tests").
   When a test fails, check whether it also fails on upstream's `main` (its
   own CI runs, or the test run locally there): a failure that also occurs
   there belongs in a fork issue, not in the sync. Because the ruleset
   requires green CI, ask the user how to proceed with such a failure; do not
   change the ruleset to get around it.
4. Open a pull request against the fork's `main` and merge it with a merge
   commit: `gh pr merge <N> -R Cubical6/chunkhound --merge`. Never squash or
   rebase a sync: that discards the link to upstream's history, and the next
   sync then conflicts on everything again.
5. Delete the sync branch and its worktree.

Upstream's `v*` tags stay local. They are needed there to derive the version,
but must not reach `origin`: never run `git push --tags` or
`git push --follow-tags`, and never push a `v*` tag.

## Releases

Upstream's release process does not apply here. In the fork:

- Do not run `scripts/update_version.py` and do not create tags by hand.
- Do not create or publish a GitHub Release by hand or with a personal token.
  That fires upstream's `release.yml`, which publishes to PyPI. Releases are
  only made by the two fork workflows below, which use `GITHUB_TOKEN`.
- The `Release` and `RC Release` workflows are disabled in the fork. Leave
  them disabled.

The version comes from the last upstream tag plus the commits since, for
example `6.1.1.dev187+g221d109fe`. Only upstream-style `v<digit>…` tags count:
`pyproject.toml` (`[tool.hatch.version] raw-options`) excludes `fork-*` tags,
and `fork-release.yml` fails if a `fork-v…` tag would change the version.

| Channel | Made by | Contents |
|---|---|---|
| `fork-latest` | `fork-release.yml`, on every push to `main` | The newest build of `main`, a prerelease that moves with every merge. |
| `fork-v<version>` (stable) | `fork-promote.yml`, started by hand and approved in the `fork-stable` environment | A copy of a checked `fork-latest` build. Each promotion adds a new release; the newest is the repository's Latest release. |

Stable tags look like `fork-v6.1.1.dev198`: the public version of the build,
without the `+g…` part. The ruleset `fork release tags immutable` blocks moving
or deleting `fork-v*` tags, so every stable release stays available. To find
the current stable release:

```bash
gh release view -R Cubical6/chunkhound --json tagName,name --jq '.tagName, .name'
```

Each release's notes list the `CHANGELOG.fork.md` entries and the merges that
are new since the last stable release (`scripts/fork_release_notes.py`).

### Upstream watch

`fork-upstream-watch.yml` runs every day. When `main` is behind upstream's
`main`, it keeps one open issue labelled `upstream-sync` up to date with the
number of commits behind, the upstream releases not merged yet and what came
in. It closes the issue once the fork has caught up. The issue is a reminder,
not a decision: sync according to "Syncing upstream" above.

### `fork-latest`: every merge to `main`

There is nothing to start. Because every merge is published, merge only what
can be installed: CI is green and no phase of a larger plan is half done.
After a merge, check that the `Fork rolling release` run and the `CI` run on
`main` succeeded. If one failed, repairing it comes before other work.

### Stable: when to promote

Propose a promotion to the user when all of these hold:

1. There is a reason: an upstream release was synced into `main`, a fix for a
   fork issue labelled `bug` was merged, or a feature the user asked for is
   complete.
2. The `Fork rolling release` run and the `CI` run for that commit
   succeeded. A failure that was let through (a `# flaky:` annotation, a
   rerun job) also fails on upstream at the upstream commit last merged.
   Upstream's `main` is sometimes red itself; compare, do not ignore.
3. The `fork-latest` build was installed and used on a real repository:
   `chunkhound --version` shows the expected version, and indexing, search and
   the MCP server work.
4. No open fork issue has the label `release-blocker`.
5. No sync pull request is open and no integration branch is partly merged.

State the version, the commit and what changed since the last stable
release. The notes of the `fork-latest` release already list that:

```bash
gh release view fork-latest -R Cubical6/chunkhound --json name,body --jq '.name, .body'
```

If a merged change is missing there, add its `CHANGELOG.fork.md` entry first.

Promote only after the user agrees:

```bash
gh workflow run fork-promote.yml -R Cubical6/chunkhound -f commit=<full sha of fork-latest>
```

The run waits for approval in the `fork-stable` environment: approve it in
the run's page on GitHub (Review deployments) or with `gh run view <id> -R
Cubical6/chunkhound --web`. The workflow refuses when `commit` is not the
commit `fork-latest` was built from, and when a release for that version
already exists, so a build that arrived in the meantime is never promoted by
accident and a stable release is never overwritten.

Older `fork-latest` builds are not kept, but every stable release is. To go
back, point users at an earlier `fork-v…` release, revert on `main`, and
promote the build that follows.

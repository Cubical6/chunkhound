# Fork workflow

This repository is `Cubical6/chunkhound`, a fork of `chunkhound/chunkhound`.
This file holds the fork's own rules for git, GitHub and releases. Where it
disagrees with `AGENTS.md` (VERSION_MANAGEMENT) or `RELEASING.md`, which both
describe upstream, this file wins.

## Remotes and branches

- `origin` is the fork. `upstream` is `chunkhound/chunkhound` and is read-only.
- `main` on the fork is upstream's `main` plus the fork's changes. Never rebase
  or force-push it.
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
3. Run the smoke suite and the full suite from `AGENTS.md`.
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
example `6.1.1.dev187+g221d109fe`. Any tag that contains a digit changes that
calculation, so the fork's tags have no digits.

| Channel | Made by | Contents |
|---|---|---|
| `fork-latest` | `fork-release.yml`, on every push to `main` | The newest build of `main`. |
| `fork-stable` | `fork-promote.yml`, started by hand | A copy of a `fork-latest` build that was checked. |

Each release's notes list the `CHANGELOG.fork.md` entries and the merges that
are new since the current `fork-stable` (`scripts/fork_release_notes.py`).

### `fork-latest`: every merge to `main`

There is nothing to start. Because every merge is published, merge only what
can be installed: the tests from `AGENTS.md` pass and no phase of a larger
plan is half done. After a merge, check that the `Fork rolling release` run
succeeded. If it failed, repairing it comes before other work.

### `fork-stable`: when to promote

Propose a promotion to the user when all of these hold:

1. There is a reason: an upstream release was synced into `main`, a fix for a
   fork issue labelled `bug` was merged, or a feature the user asked for is
   complete.
2. The `Fork rolling release` run for that commit succeeded, and `CI` on that
   commit has no failing job that passes on upstream at the upstream commit
   last merged. Upstream's `main` is sometimes red itself; compare, do not
   ignore.
3. The `fork-latest` build was installed and used on a real repository:
   `chunkhound --version` shows the expected version, and indexing, search and
   the MCP server work.
4. No open fork issue has the label `release-blocker`.
5. No sync pull request is open and no integration branch is partly merged.

State the version, the commit and what changed since the current
`fork-stable`. The notes of the `fork-latest` release already list that:

```bash
gh release view fork-latest -R Cubical6/chunkhound --json name,body --jq '.name, .body'
```

If a merged change is missing there, add its `CHANGELOG.fork.md` entry first.

Promote only after the user agrees:

```bash
gh workflow run fork-promote.yml -R Cubical6/chunkhound -f commit=<full sha of fork-latest>
```

The workflow refuses when `commit` is not the commit `fork-latest` was built
from, so a build that arrived in the meantime is never promoted by accident.
Older builds are not kept. To go back, revert on `main` and promote the build
that follows.

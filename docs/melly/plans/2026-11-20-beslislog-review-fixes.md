# PLAN: decision log review follow-ups (tests and docs)

## Goal
Fix the small, local findings from the cross-review of PR #86 (decision log) in one follow-up PR. The PR only tightens tests and docs; the decision log's runtime behaviour does not change. Findings that need a design decision went to fork issues #89 (path guard), #90 (lock without timeout) and #91 (tool/source field) and are out of scope here.

## Context
- Repo / worktree: `/home/disorder/Projects/Github/chunkhound/.claude/worktrees/decision-log-followups`
- Branch: `fix/decision-log-review-followups` (from `origin/main` df6c3af7)
- Project rules: read `AGENTS.md` and `FORK.md` before starting.
- Background: cross-review report `~/.claude/jobs/adhoc/tmp/cross-review/chunkhound-86-delta/report.md` (item numbers below refer to it; "old item" refers to the first review run `~/.claude/jobs/adhoc/tmp/cross-review/chunkhound-86/verdicts.md`).
- Out of scope on purpose: the parsing of `CHUNKHOUND_DECISION_LOG__ENABLED` (`on` becomes False, an invalid `MAX_SIZE_MB` is ignored silently, old item 5). The same `lower() in ("true", "1", "yes")` pattern is used in `analytics_config.py` and `research_config.py`; changing only the decision log would be inconsistent.
- Native extension: a fresh worktree has no built `chunkhound_native`. If imports fail, build it first (`make` native build) or run the tests in the main checkout with identical code.
- Native extension, as set up in this worktree: the main checkout's wheel (`target/wheels/*.whl`) was copied in and installed with `scripts/install_native.py`. Run Python only with `uv run --no-sync …`; a plain `uv run` re-syncs the locked PyPI wheel and breaks the import.
- Mutation checks: copy `chunkhound/`, `tests/` and `pyproject.toml` (not `chunkhound_native/`) to a temp dir, mutate there and run `<worktree>/.venv/bin/python -m pytest …` from that dir. `PYTHONPATH` does not work: the worktree's `chunkhound/` wins.

## Constraints (apply to every phase)
- Only change files listed in the phase, unless strictly needed; mention any extra file in the report.
- No production code changes (`chunkhound/**`). If a test cannot be fixed without one, stop and report.
- Follow `AGENTS.md` TESTING_PHILOSOPHY: test contracts, not private helpers.
- Do NOT commit, push, or start other phases. No network, no real LLM calls.
- Keep context small: search with `rg`, read only relevant line ranges, run targeted tests with `-q --tb=short`, and pipe long output through `| tail -n 40`.
- Do not run the full test suite; Claude runs it.

## Final report format (every phase)
At most ~15 lines:
1. Files changed (one line each, with a short reason)
2. Tests run, with results (including the mutation check where the phase asks for one)
3. Deviations from the plan and open issues

---

## Phase 1: decision log unit tests (items 10, 11, 14)
- [x] Done
- **Depends on:** none
- **Model:** `openai-codex/gpt-6.1-terra` / `medium`
- **Goal:** Make three tests in `tests/unit/test_decision_log.py` prove what they claim.
- **Files:** `tests/unit/test_decision_log.py`
- **Steps:**
  1. Item 11: in `test_unwritable_path_does_not_fail_or_print` (~:112-119) and `test_symlinked_lock_cannot_create_file_outside_log_directory` (~:267-279), assert `decision_log.is_enabled()` right after `enable(...)`, so the tests fail when `configure()` refuses the path.
  2. Item 14: add a test (or parametrize the symlinked-lock test) where the log file `.chunkhound/decisions.jsonl` itself is replaced by a symlink to an outside file **after** enable; `record()` must leave the outside file byte-for-byte unchanged and must not raise or print.
  3. Item 10: in `test_process_writers_retain_generation_and_every_record` (~:150-215), raise the waits for events that normally happen (child start-up, `rotating.wait`, `started[1].wait`, child A's `release.wait` inside the patched `Path.replace`) from 3 s to 30 s. Keep the short negative check (B must not finish within 0.2 s while A holds the lock) and give it a clear assert message.
- **Acceptance criteria:**
  - All tests in the file pass.
  - Mutation check (do it in a scratch copy, never in the worktree's `chunkhound/`): with `flags |= getattr(os, "O_NOFOLLOW", 0)` removed from the append open in `decision_log.py`, the new item-14 test fails. Report the result.
- **Verify:** `uv run pytest tests/unit/test_decision_log.py -q --tb=short | tail -n 40`
- **Notes:** Do not change the locking code. Issue #90 may later replace the blocking lock; this phase only removes the start-up flakiness.

## Phase 2: research decision log tests and usage fixtures (item 12, item 2, old item 18)
- [x] Done
- **Depends on:** none
- **Model:** `openai-codex/gpt-6.1-sol` / `medium`
- **Goal:** The usage-isolation test counts records; test fixtures count usage like real providers; the trace test goes through public methods.
- **Files:** `tests/unit/research/test_research_decision_log.py`, `tests/fixtures/fake_providers.py`, `tests/fixtures/scripted_structured.py`, `tests/code_mapper/c4/conftest.py`
- **Steps:**
  1. Item 12: in `test_research_runs_log_only_their_own_usage` (~:206-224), assert there are exactly two `research_run` records (one per query) before building the per-query dict.
  2. Item 2: replace every `self._requests_made += 1` in the test fixtures (`fake_providers.py` ~:364 and ~:542, `scripted_structured.py:54`, `tests/code_mapper/c4/conftest.py:42`) with `self._record_usage(requests=1)`, so fake requests also reach the per-run usage scope. Check that `_requests_made` totals stay the same for the tests that read them.
  3. Old item 18: `test_decisions_share_run_trace_and_preserve_selections` (~:290-345) builds its own `QuestionGenerator`/`GapDetectionService` and calls the private `selector._select_gaps_by_elbow(gaps)` (~:335). Replace the private call with the public method that performs gap selection and records `gap_selection`, keeping the assertions on trace id and kept items. If no public path can run with the fake LLM in under ~40 lines of setup, keep the test as is and report why.
- **Acceptance criteria:**
  - Targeted tests pass; mutation check: with the `research_run` record written twice for one query (scratch copy), the item-12 test fails.
  - No `_requests_made += 1` left under `tests/`.
- **Verify:** `uv run pytest tests/unit/research/test_research_decision_log.py tests/unit/llm/test_llm_usage_scope.py tests/code_mapper/c4 -q --tb=short | tail -n 40`, plus the test files that import `ScriptedStructuredLLM` or the changed fakes (`rg -l 'ScriptedStructuredLLM|scripted_structured|fake_providers' tests`).
- **Notes:** Item 2 is a nit (no test observes it today); do not widen it beyond the four lines.

## Phase 3: chunk selection test fixtures (old items 17 and 19)
- [ ] Done
- **Depends on:** none
- **Model:** `openai-codex/gpt-6.1-terra` / `medium`
- **Goal:** `tests/unit/research/test_chunk_selection_decision_log.py` uses normal pytest fixtures and its "disabled" test detects a missing `is_enabled()` guard.
- **Files:** `tests/unit/research/test_chunk_selection_decision_log.py`, `tests/unit/research/conftest.py` (only if a shared fixture moves there)
- **Steps:**
  1. Old item 19: drop the `_ParallelTests.mock_strategy.__wrapped__(None)` call (~:25) and the `reset_decision_log  # noqa: F401` import (~:18). Get the strategy and the log isolation from proper fixtures: move them to `tests/unit/research/conftest.py` or define them locally.
  2. Old item 17: `test_disabled_records_do_not_build_payload_or_create_file` (~:171-189) passes `None` for every input, so removing the `is_enabled()` guards in `chunkhound/services/research/shared/decision_records.py` does not fail it. Pass realistic inputs (a few chunk dicts with scores) and patch the payload builders or `decision_log.record` to fail when called, so the test proves that nothing is built while the log is disabled.
- **Acceptance criteria:**
  - Tests in the file pass, and the file has no `__wrapped__` and no `noqa: F401`.
  - Mutation check (scratch copy): with the `is_enabled()` guard removed from `record_chunk_rerank` and from `record_elbow_filter`, the disabled test fails.
- **Verify:** `uv run pytest tests/unit/research/test_chunk_selection_decision_log.py tests/unit/research -q --tb=short | tail -n 40`
- **Notes:** If the moved fixture is used by the class `_ParallelTests` elsewhere, keep that class working.

## Phase 4: docs for the lock file (item 9) — Claude, not pi-bolt
- [x] Done
- **Depends on:** none
- **Goal:** Users learn that the log creates a `<filename>.lock` file next to it that stays.
- **Files:** `site/src/pages/docs/configuration.md` (~:787, "Rotation" paragraph), `CHANGELOG.fork.md` (existing **Decision log** entry; keep its title)
- **Steps:** mention the `<filename>.lock` sidecar (created owner-only, used to serialize rotation and appends across processes, never removed, safe to delete when no ChunkHound process runs). Optionally move the containment sentence out from under "Rotation" into its own sentence or paragraph.
- **Verify:** `uv run pytest tests/site -q --tb=short | tail -n 20` (serial; the site build is slow).

---

## Final verification (Claude, after all phases)
- [ ] Smoke: `uv run pytest tests/test_smoke.py -v -n auto`
- [ ] Full test suite: `uv run pytest tests/ -v -n auto` (background task); compare failures with issues #80 and #81 (known `-n auto` failures)
- [ ] Lint / typecheck: `uv run ruff check chunkhound tests/unit/test_decision_log.py tests/unit/research`, `uv run mypy chunkhound` (totals unchanged: no production code changes)
- [ ] Review the complete diff against the Goal; no files under `chunkhound/` changed
- [ ] `.pi-handoff/` removed; nothing from it committed
- [ ] PR against `main` of `Cubical6/chunkhound` with "Tests" and "Upstream check" headings (decision log is fork-only; nothing upstream); references #89, #90, #91 as out of scope

## After each phase (Claude)
1. Review the diff, run the phase's Verify command, tick its box, add a Progress log line, commit (smoke suite first).
2. If Claude's own context is over ~100k: don't start the next phase here. Write a handoff with the `handoff` skill that points to this PLAN.md, the next phase, running pi-bolt sessionIds and the last commit, then follow its hand-over step.

Phases 1, 2 and 3 are independent. Run them in sequence in this worktree, or in parallel each in its own git worktree (branch off `fix/decision-log-review-followups`, merge back after review).

## Progress log
| Date | Phase | sessionId | Commit | Notes |
|---|---|---|---|---|
| 2026-11-20 | 1 | 01a1fa6b-211d-737f-ae4f-f0a0233039d6 | `test(decision-log): …` | 66 passed; mutation (append without O_NOFOLLOW) fails only the new symlinked-log test, checked by Claude in a scratch copy; smoke 14 passed |
| 2026-11-20 | 2 | 01a1fa6c-d20c-737f-ae4f-f0a28367dd6d | `test(research): …` | Verify 624 passed; importers 549 passed, 1 skipped; mutation (duplicate `research_run`) fails the item-12 test. Deviations: the two `_requests_made += 1` left in `fake_providers.py` belong to `FakeEmbeddingProvider`, which has no LLM usage scope (the plan's premise was wrong there). Old item 18 kept as is: the public path `detect_and_fill_gaps` needs clustering, shard gap detection, gap embeddings and unification before it selects, far over the ~40-line setup limit |
| 2026-11-20 | 4 | Claude | `docs(decision-log): …` | Containment moved to its own "Location" paragraph, new "Lock file" paragraph; changelog entry extended (title kept). Site tests 73 passed (needed `npm ci --prefix site` in the worktree first) |

---

## Prompts (for Claude, copy per phase)

**Start a phase** (new session, model from the phase):
> Read `AGENTS.md` and `docs/melly/plans/2026-11-20-beslislog-review-fixes.md` in `<cwd>`. Implement only Phase N. Follow the Constraints and the Final report format in the plan. Do not start other phases.

**Feedback within a phase** (same `sessionId`):
> Review feedback on Phase N: <concrete problem, file:line, expected behaviour>. Fix only this and report.

**After a timeout or cancel** (same `sessionId`):
> You were interrupted. Check `git status` and `git diff`, then finish Phase N and report.

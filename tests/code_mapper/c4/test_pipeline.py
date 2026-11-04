"""End-to-end C4 cost, recovery, replay, and persistence contracts."""

import json
import shutil
import subprocess

import pytest

from chunkhound.code_mapper.c4.documented import TopicSources
from chunkhound.code_mapper.c4.llm import C4Llm, RetryQueue
from chunkhound.code_mapper.c4.lockfile import read_scope_lock, write_scope_lock
from chunkhound.code_mapper.c4.pipeline import analyze_c4, finish_c4
from chunkhound.code_mapper.c4.summaries import summary_key
from chunkhound.providers.llm.codex_cli_provider import CodexCLIProvider


def payload(prompt):
    return json.loads(prompt.split("\nInput:\n", 1)[1])


def classify_answer(prompt):
    items = json.loads(prompt.split("\nItems:\n", 1)[1])
    return {
        "classifications": [
            {
                "key": item["key"],
                "value": "external_system"
                if item["question"] == "dependency"
                else "yes",
            }
            for item in items
        ]
    }


def merge_answer(prompt):
    data = payload(prompt)
    return {
        "components": [
            {
                # Root and same-named directory groups share a name, not an id.
                "name": group["id"],
                "description": "Domain responsibility.",
                "groups": [group["id"]],
            }
            for group in data["groups"]
        ],
        "direct": [],
        "titles": [],
    }


@pytest.fixture
def pipeline_answers(scripted, monkeypatch):
    monkeypatch.setenv("CHUNKHOUND_USE_RUST", "0")
    scripted.answers.update(
        {
            "classify": classify_answer,
            "merge": merge_answer,
            "titles": lambda prompt: {
                "titles": [
                    {"fingerprint": row["fingerprint"], "title": "gebruikt via API"}
                    for row in payload(prompt)["relations"]
                ]
            },
            "summaries": lambda prompt: {
                "labels": [
                    {"key": row["key"], "label": "gebruikt diensten"}
                    for row in payload(prompt)["arrows"]
                ]
            },
        }
    )
    return scripted


def head_sha(repo):
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def commit(repo, message):
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=C4 Fixture",
            "-c",
            "user.email=c4@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-m",
            message,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def write_sources(repo, sources):
    for file, source in sources.items():
        path = repo / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)


def owner_of(build_result, group):
    return next(
        id
        for id, component in build_result.lock.components.items()
        if group in component.groups
    )


def removed_ids(build_result):
    return {e.from_id for e in build_result.model.history if e.kind == "removed"}


async def build(repo, manager, *, lock=None, trial=False, **inputs):
    llm = C4Llm(manager, concurrency=4, trial=trial)
    retries = RetryQueue()
    draft = await analyze_c4(
        project_root=repo,
        scope_path=inputs.get("scope_path", repo),
        scope_label=inputs.get("scope_label", "shop"),
        config=inputs.get("config"),
        llm=llm,
        lock=lock,
        retries=retries,
    )
    return await finish_c4(
        draft=draft,
        topics=inputs.get("topics", [TopicSources("orders", ("shop/orders.py",))]),
        llm=llm,
        lock=lock,
        retries=retries,
        head_sha=head_sha(repo),
        kind="trial" if trial else "full",
    )


@pytest.mark.parametrize("origin", ["answer", "cache", "trial", "fallback"])
async def test_documented_terms_require_their_own_literal_span(
    fixture_repo, c4_llm_manager, pipeline_answers, tmp_path, origin
):
    citation = {
        "file": "README.md",
        "start_line": 3,
        "end_line": 3,
        "quote": "Een beheerder gebruikt de\twebwinkel via Stripe.",
    }
    valid = [
        {"kind": "person", "term": "beheerder", "citation": citation},
        {"kind": "external", "term": "de webwinkel", "citation": citation},
    ]
    # Absent entirely, present only outside the span, and a nonliteral case variant.
    unsupported = [
        {"kind": "external", "term": term, "citation": citation}
        for term in ("Invented Payment Authority", "Shop", "Beheerder")
    ]
    pipeline_answers.answers["documented"] = {"elements": valid, "relations": []}
    lock = None
    if origin != "answer":
        previous = await build(fixture_repo, c4_llm_manager)
        assert previous.lock.transition is not None
        lock = previous.lock
        for item in unsupported:
            lock.documented.elements.append(
                {
                    **item,
                    "citation": dict(lock.documented.elements[0]["citation"]),
                }
            )
        write_scope_lock(tmp_path / "cache", "shop", lock)
        lock = read_scope_lock(tmp_path / "cache", "shop")
        pipeline_answers.calls.clear()
        if origin in {"trial", "fallback"}:
            with (fixture_repo / "README.md").open("a") as readme:
                readme.write("\n")
    pipeline_answers.answers["documented"] = {
        "elements": unsupported if origin == "fallback" else valid + unsupported,
        "relations": [],
    }
    result = await build(
        fixture_repo, c4_llm_manager, lock=lock, trial=origin == "trial"
    )
    ids = {element.id for element in result.model.elements}
    assert not {
        "extern:invented-payment-authority",
        "extern:shop",
        "extern:beheerder",
    }.intersection(ids)
    assert {"persoon:beheerder", "extern:de-webwinkel"} <= ids
    assert all(
        any(
            citation.target == id
            and citation.source == "documentation"
            and citation.verified
            for citation in result.evidence.citations
        )
        for id in ("persoon:beheerder", "extern:de-webwinkel")
    )
    if origin == "fallback":
        assert pipeline_answers.calls["documented"] == 2
        assert result.lock.documented is None
        assert result.lock.transition is None
        assert result.fallback_count > 0
    elif origin == "trial":
        assert not pipeline_answers.calls
        assert result.lock is None
    else:
        assert pipeline_answers.calls["documented"] == (1 if origin == "answer" else 0)
        assert {item["term"] for item in result.lock.documented.elements} == {
            "beheerder",
            "de webwinkel",
        }


@pytest.mark.parametrize(
    "answer_kind",
    ["valid", "duplicate", "missing", "extra", "blank", "empty", "overlong", "legacy"],
)
async def test_summary_labels_validate_before_persisting(
    fixture_repo, c4_llm_manager, pipeline_answers, monkeypatch, tmp_path, answer_kind
):
    # Separate components reach the same external system with distinct titles.
    billing = fixture_repo / "billing"
    billing.mkdir()
    (billing / "client.py").write_text(
        "import requests\n\ndef charge(): return requests.post('https://example.invalid')\n"
    )
    pipeline_answers.answers["titles"] = lambda prompt: {
        "titles": [
            {"fingerprint": row["fingerprint"], "title": f"verwerkt via API {index}"}
            for index, row in enumerate(payload(prompt)["relations"])
        ]
    }
    summary_keys = set()

    async def run_cli(prompt, system, max_completion_tokens, timeout):
        request = prompt.split("User request: ", 1)[1].rsplit(
            "\n\nRespond with JSON only", 1
        )[0]
        step = request.split("C4 step: ", 1)[1].splitlines()[0]
        if step != "summaries":
            answer = pipeline_answers.answers[step]
            return json.dumps(answer(request) if callable(answer) else answer)
        keys = [row["key"] for row in payload(request)["arrows"]]
        summary_keys.update(keys)
        rows = [{"key": key, "label": "verwerkt en bewaart"} for key in keys]
        if answer_kind == "duplicate":
            rows.append(dict(rows[0]))
        elif answer_kind == "missing":
            rows.pop()
        elif answer_kind == "extra":
            rows.append({"key": "unexpected", "label": "ongewenst"})
        elif answer_kind in {"blank", "empty", "overlong"}:
            rows[0]["label"] = {"blank": "   ", "empty": "", "overlong": "x" * 61}[
                answer_kind
            ]
        elif answer_kind == "legacy":
            return json.dumps({"labels": {row["key"]: row["label"] for row in rows}})
        return json.dumps({"labels": rows})

    # Only external discovery/execution are replaced. Both production validators run.
    monkeypatch.setattr(CodexCLIProvider, "_codex_available", lambda self: True)
    provider = CodexCLIProvider(model="contract-test")
    monkeypatch.setattr(provider, "_run_cli_command", run_cli)
    monkeypatch.setattr(c4_llm_manager, "get_utility_provider", lambda: provider)
    monkeypatch.setattr(c4_llm_manager, "get_synthesis_provider", lambda: provider)
    result = await build(fixture_repo, c4_llm_manager)
    titles = {relation.id: relation.title for relation in result.model.relations}
    summarized = [
        arrow
        for arrow in result.model.merged
        if summary_key((id, titles[id]) for id in arrow.underlying) in summary_keys
    ]
    assert summarized, "The fixture must exercise nonempty multi-title summaries"
    write_scope_lock(tmp_path / "cache", "shop", result.lock)
    restored = read_scope_lock(tmp_path / "cache", "shop")
    if answer_kind == "valid":
        assert all(arrow.label == "verwerkt en bewaart" for arrow in summarized)
        assert all("fallback" not in arrow.markers for arrow in summarized)
        assert {key: restored.summaries[key] for key in summary_keys} == {
            key: "verwerkt en bewaart" for key in summary_keys
        }
    else:
        assert all("fallback" in arrow.markers for arrow in summarized)
        assert not summary_keys.intersection(restored.summaries)


async def test_failed_merge_invents_no_components(
    fixture_repo, c4_llm_manager, pipeline_answers
):
    pipeline_answers.answers["merge"] = TimeoutError("temporarily unavailable")
    result = await build(fixture_repo, c4_llm_manager)
    assert not [e for e in result.model.elements if e.kind == "component"]
    # Each failed container stays locked and owns its files for this run.
    failed = {e.id for e in result.model.elements if "fallback" in e.markers}
    assert failed == {"container:shop", "container:web", "container:acme-admin"}
    assert result.fallback_count == len(failed)
    assert failed == set(result.lock.containers.values())
    assert {"shop/orders.py", "shop/cli.py"} <= set(
        result.evidence.element_files["container:shop"]
    )
    assert "web/src/api.ts" in result.evidence.element_files["container:web"]
    assert any(
        (c.target, c.file, c.source) == ("container:shop", "shop/orders.py", "code")
        for c in result.evidence.citations
    )
    # Nothing about this run's placement becomes permanent.
    assert result.lock.components == {}
    assert not any(result.lock.direct_groups.values())
    assert result.lock.transition is None
    # Relations of a failed container vanish on recovery, so their titles do too.
    relations = [r for r in result.model.relations if r.status == "found"]
    assert relations and all("fallback" in r.markers for r in relations)
    assert not result.lock.relations
    pipeline_answers.answers["classify"] = ValueError("bad config")
    with pytest.raises(ValueError, match="bad config"):
        await build(fixture_repo, c4_llm_manager)


async def test_rerun_unchanged_zero_calls_stable_output(
    fixture_repo, c4_llm_manager, pipeline_answers, tmp_path
):
    first = await build(fixture_repo, c4_llm_manager)
    assert first.fallback_count == 0
    assert first.lock.components
    write_scope_lock(tmp_path / "cache", "shop", first.lock)
    restored = read_scope_lock(tmp_path / "cache", "shop")
    pipeline_answers.calls.clear()
    second = await build(fixture_repo, c4_llm_manager, lock=restored)
    assert not pipeline_answers.calls
    assert second.model == first.model
    assert second.evidence == first.evidence
    assert second.lock == first.lock


async def test_new_file_in_known_directory_needs_no_merge_call(
    fixture_repo, c4_llm_manager, pipeline_answers
):
    first = await build(fixture_repo, c4_llm_manager)
    owner, before = next(
        (id, c)
        for id, c in first.lock.components.items()
        if "shop/orders.py" in c.files
    )
    (fixture_repo / "shop/refunds.py").write_text("class Refund: pass\n")
    pipeline_answers.calls.clear()
    second = await build(fixture_repo, c4_llm_manager, lock=first.lock)
    assert pipeline_answers.calls["merge"] == 0
    assert second.fallback_count == 0
    after = second.lock.components[owner]
    assert after.groups == before.groups == ["container:shop/shop"]
    assert set(after.files) == {*before.files, "shop/refunds.py"}
    assert set(second.lock.components) == set(first.lock.components)


@pytest.mark.parametrize(
    ("directory", "group"),
    [
        ("billing", "container:shop/billing"),
        # A directory below a claimed one is still its own, unclaimed group.
        ("shop/billing", "container:shop/shop/billing"),
    ],
)
async def test_new_directory_needs_one_merge_call(
    fixture_repo, c4_llm_manager, pipeline_answers, directory, group
):
    first = await build(fixture_repo, c4_llm_manager)
    (fixture_repo / directory).mkdir()
    (fixture_repo / directory / "invoice.py").write_text("class Invoice: pass\n")
    (fixture_repo / directory / "credit.py").write_text("class Credit: pass\n")
    sent = []

    def merge(prompt):
        sent.append([row["id"] for row in payload(prompt)["groups"]])
        return merge_answer(prompt)

    pipeline_answers.answers["merge"] = merge
    pipeline_answers.calls.clear()
    second = await build(fixture_repo, c4_llm_manager, lock=first.lock)
    assert pipeline_answers.calls["merge"] == 1
    assert sent == [[group]]
    assert second.fallback_count == 0
    assert set(first.lock.components) < set(second.lock.components)
    new = set(second.lock.components) - set(first.lock.components)
    assert [second.lock.components[id].groups for id in new] == [[group]]


async def test_trial_names_root_group_after_container(
    fixture_repo, c4_llm_manager, pipeline_answers
):
    result = await build(fixture_repo, c4_llm_manager, trial=True)
    root = next(
        e
        for e in result.model.elements
        if e.kind == "component"
        and "pyproject.toml" in result.evidence.element_files[e.id]
    )
    assert root.name == "shop"
    assert "component:topic" not in {e.id for e in result.model.elements}
    assert "." not in {e.name for e in result.model.elements}


async def test_trial_run_uses_lock_only(fixture_repo, c4_llm_manager, pipeline_answers):
    first = await build(fixture_repo, c4_llm_manager)
    original = first.lock.model_copy(deep=True)
    pipeline_answers.calls.clear()
    result = await build(fixture_repo, c4_llm_manager, lock=first.lock, trial=True)
    assert not pipeline_answers.calls
    assert result.model.run.kind == "trial"
    assert result.lock is None
    assert first.lock == original
    assert all(
        e.coverage.status in {"not_computed", "none"} for e in result.model.elements
    )


async def test_direct_groups_replay_without_merge(
    fixture_repo, c4_llm_manager, pipeline_answers
):
    pipeline_answers.answers["merge"] = lambda prompt: {
        "components": [],
        "direct": [g["id"] for g in payload(prompt)["groups"]],
        "titles": [],
    }
    first = await build(fixture_repo, c4_llm_manager)
    assert not first.lock.components
    assert first.lock.direct_groups["container:shop"] == [
        "container:shop/.",
        "container:shop/shop",
        "container:shop/templates",
    ]
    pipeline_answers.calls.clear()
    second = await build(fixture_repo, c4_llm_manager, lock=first.lock)
    assert not pipeline_answers.calls
    assert second.evidence.element_files == first.evidence.element_files
    assert not any(e.kind == "component" for e in second.model.elements)


async def test_deferred_classification_precedes_final_runtime(
    fixture_repo, c4_llm_manager, pipeline_answers
):
    (fixture_repo / "templates/package.json").write_text('{"name":"templates"}')
    attempts = 0

    def delayed(prompt):
        nonlocal attempts
        attempts += 1
        if attempts <= 3:
            raise TimeoutError("first voting batch unavailable")
        return classify_answer(prompt)

    pipeline_answers.answers["classify"] = delayed
    result = await build(fixture_repo, c4_llm_manager)
    assert result.fallback_count == 0
    assert any(e.id == "container:templates" for e in result.model.elements)
    assert result.lock.classifications["templates/package.json"].value == "yes"


async def test_title_failure_is_not_cached(
    fixture_repo, c4_llm_manager, pipeline_answers
):
    pipeline_answers.answers["titles"] = TimeoutError("unavailable")
    result = await build(fixture_repo, c4_llm_manager)
    relations = [r for r in result.model.relations if r.status == "found"]
    assert relations and all("fallback" in r.markers for r in relations)
    assert not result.lock.relations
    assert result.lock.components  # Title failure does not discard successful grouping.
    assert result.lock.transition is None


async def test_removed_container_identity_is_reserved(
    fixture_repo, c4_llm_manager, pipeline_answers
):
    first = await build(fixture_repo, c4_llm_manager)
    old_id = first.lock.containers["web/package.json"]
    (fixture_repo / "web/package.json").unlink()
    second = await build(fixture_repo, c4_llm_manager, lock=first.lock)
    assert second.lock.tombstones["web/package.json"] == old_id
    (fixture_repo / "web/package.json").write_text(
        '{"name":"web", "scripts":{"start":"node src/index.ts"}}'
    )
    third = await build(fixture_repo, c4_llm_manager, lock=second.lock)
    assert third.lock.containers["web/package.json"] != old_id
    assert third.lock.tombstones["web/package.json"] == old_id


async def test_failed_merge_is_retried_next_run(
    fixture_repo, c4_llm_manager, pipeline_answers, tmp_path
):
    pipeline_answers.answers["merge"] = TimeoutError("unavailable")
    first = await build(fixture_repo, c4_llm_manager)
    # Without a previous lock there is nothing to keep but the current commit.
    assert first.lock.base_sha == head_sha(fixture_repo)
    write_scope_lock(tmp_path / "cache", "shop", first.lock)
    restored = read_scope_lock(tmp_path / "cache", "shop")
    pipeline_answers.answers["merge"] = merge_answer
    pipeline_answers.calls.clear()
    second = await build(fixture_repo, c4_llm_manager, lock=restored)
    assert pipeline_answers.calls["merge"] == 3
    assert owner_of(second, "container:shop/shop") in {
        e.id for e in second.model.elements if e.kind == "component"
    }
    assert "shop/orders.py" in second.lock.components[
        owner_of(second, "container:shop/shop")
    ].files
    assert second.fallback_count == 0
    assert second.lock.transition is not None


async def test_failed_merge_keeps_locked_component_with_vanished_directory(
    fixture_repo, c4_llm_manager, pipeline_answers, tmp_path
):
    write_sources(fixture_repo, {"legacy/old.py": "class Old: pass\n"})
    commit(fixture_repo, "add legacy")
    first = await build(fixture_repo, c4_llm_manager)
    gone = owner_of(first, "container:shop/legacy")
    living = owner_of(first, "container:shop/shop")
    shutil.rmtree(fixture_repo / "legacy")
    write_sources(fixture_repo, {"billing/invoice.py": "class Invoice: pass\n"})
    commit(fixture_repo, "replace legacy with billing")
    pipeline_answers.answers["merge"] = TimeoutError("unavailable")
    pipeline_answers.calls.clear()
    failed = await build(fixture_repo, c4_llm_manager, lock=first.lock)
    assert pipeline_answers.calls["merge"] == 2
    # The vanished component keeps its id and record, but is not in this output.
    assert failed.lock.components[gone] == first.lock.components[gone]
    assert gone not in failed.lock.tombstones
    assert gone not in removed_ids(failed)
    assert gone not in {e.id for e in failed.model.elements}
    # A component that still has its directory appears as usual.
    assert living in {e.id for e in failed.model.elements}
    assert failed.lock.components[living] == first.lock.components[living]
    # The unplaced directory is cited on the container and is not permanent.
    assert "billing/invoice.py" in failed.evidence.element_files["container:shop"]
    assert "container:shop/billing" not in failed.lock.direct_groups["container:shop"]
    assert not any(
        "container:shop/billing" in c.groups for c in failed.lock.components.values()
    )
    # With the merge recovered, the directory is simply gone.
    write_scope_lock(tmp_path / "cache", "shop", failed.lock)
    restored = read_scope_lock(tmp_path / "cache", "shop")
    pipeline_answers.answers["merge"] = merge_answer
    recovered = await build(fixture_repo, c4_llm_manager, lock=restored)
    assert gone not in recovered.lock.components
    assert recovered.lock.tombstones[gone] == gone
    assert gone in removed_ids(recovered)
    assert owner_of(recovered, "container:shop/billing")


async def test_failed_merge_does_not_carry_inherited_or_living_components(
    fixture_repo, c4_llm_manager, pipeline_answers
):
    write_sources(
        fixture_repo,
        {
            "alpha/one.py": "class AlphaOne: pass\n",
            "alpha/two.py": "class AlphaTwo: pass\n",
            "alpha/three.py": "class AlphaThree: pass\n",
            "beta/only.py": "class BetaOnly: pass\n",
            "gamma/first.py": "class GammaFirst: pass\n",
            "gamma/second.py": "class GammaSecond: pass\n",
        },
    )
    commit(fixture_repo, "add alpha, beta and gamma")
    first = await build(fixture_repo, c4_llm_manager)
    alpha = owner_of(first, "container:shop/alpha")
    beta = owner_of(first, "container:shop/beta")
    gamma = owner_of(first, "container:shop/gamma")
    # Most of beta's files are now alpha's: beta's group inherits alpha's id.
    for name in ("one", "two", "three"):
        (fixture_repo / "alpha" / f"{name}.py").rename(
            fixture_repo / "beta" / f"{name}.py"
        )
    # Gamma's directory lives on with entirely new files: its id is not inherited.
    shutil.rmtree(fixture_repo / "gamma")
    write_sources(
        fixture_repo,
        {
            "gamma/fresh.py": "VALUE = 1\n",
            "billing/invoice.py": "class Invoice: pass\n",
        },
    )
    commit(fixture_repo, "move alpha into beta, rewrite gamma, add billing")
    pipeline_answers.answers["merge"] = TimeoutError("unavailable")
    failed = await build(fixture_repo, c4_llm_manager, lock=first.lock)
    # Inherited: the old record must not overwrite the one built in this run.
    assert failed.lock.components[alpha].groups == ["container:shop/beta"]
    assert set(failed.lock.components[alpha].files) >= {"beta/one.py", "beta/only.py"}
    assert alpha not in failed.lock.tombstones
    # Living: carrying these would give their groups two owners on the next run.
    assert beta not in failed.lock.components
    assert failed.lock.tombstones[beta] == beta
    assert gamma not in failed.lock.components
    assert failed.lock.tombstones[gamma] == gamma
    fresh = owner_of(failed, "container:shop/gamma")
    assert fresh != gamma
    pipeline_answers.answers["merge"] = merge_answer
    recovered = await build(fixture_repo, c4_llm_manager, lock=failed.lock)
    assert recovered.fallback_count == 0
    assert owner_of(recovered, "container:shop/beta") == alpha
    assert owner_of(recovered, "container:shop/gamma") == fresh


async def test_failed_merge_keeps_base_sha(
    fixture_repo, c4_llm_manager, pipeline_answers
):
    first = await build(fixture_repo, c4_llm_manager)
    write_sources(fixture_repo, {"billing/invoice.py": "class Invoice: pass\n"})
    commit(fixture_repo, "add billing")
    pipeline_answers.answers["merge"] = TimeoutError("unavailable")
    failed = await build(fixture_repo, c4_llm_manager, lock=first.lock)
    assert failed.model.run.head_sha == head_sha(fixture_repo) != first.lock.base_sha
    assert failed.lock.base_sha == first.lock.base_sha
    pipeline_answers.answers["merge"] = merge_answer
    recovered = await build(fixture_repo, c4_llm_manager, lock=failed.lock)
    assert recovered.lock.base_sha == head_sha(fixture_repo)


async def test_other_container_is_still_locked(
    fixture_repo, c4_llm_manager, pipeline_answers
):
    write_sources(
        fixture_repo,
        {
            "legacy/old.py": "class Old: pass\n",
            "web/legacy/old.ts": "export const old = 1;\n",
        },
    )
    commit(fixture_repo, "add legacy directories")
    first = await build(fixture_repo, c4_llm_manager)
    shop_gone = owner_of(first, "container:shop/legacy")
    web_gone = owner_of(first, "container:web/legacy")
    shutil.rmtree(fixture_repo / "legacy")
    shutil.rmtree(fixture_repo / "web/legacy")
    write_sources(
        fixture_repo,
        {
            "billing/invoice.py": "class Invoice: pass\n",
            "web/lib/client.ts": "export const client = 1;\n",
        },
    )
    commit(fixture_repo, "replace legacy directories")
    attempted = []

    def merge(prompt):
        attempted.append(payload(prompt)["container"])
        if attempted[-1] == "container:web":
            raise TimeoutError("unavailable")
        return merge_answer(prompt)

    pipeline_answers.answers["merge"] = merge
    result = await build(fixture_repo, c4_llm_manager, lock=first.lock)
    assert sorted(attempted) == ["container:shop", "container:web", "container:web"]
    markers = {e.id: e.markers for e in result.model.elements}
    assert "fallback" in markers["container:web"]
    assert "fallback" not in markers["container:shop"]
    assert result.fallback_count == 1
    assert set(result.lock.containers.values()) >= {"container:shop", "container:web"}
    # The healthy container is updated, tombstone and removed edge included.
    assert owner_of(result, "container:shop/billing")
    assert shop_gone not in result.lock.components
    assert result.lock.tombstones[shop_gone] == shop_gone
    assert shop_gone in removed_ids(result)
    # The failed one keeps its record and leaves its new directory unplaced.
    assert result.lock.components[web_gone] == first.lock.components[web_gone]
    assert web_gone not in result.lock.tombstones
    assert web_gone not in removed_ids(result)
    assert "web/lib/client.ts" in result.evidence.element_files["container:web"]
    assert not any(
        "container:web/lib" in c.groups for c in result.lock.components.values()
    )
    # base_sha is per scope, so one failed container holds it for all.
    assert result.lock.base_sha == first.lock.base_sha
    assert result.lock.transition is None


async def test_failure_then_rename_keeps_component_id(
    fixture_repo, c4_llm_manager, pipeline_answers
):
    write_sources(
        fixture_repo,
        {
            "alpha/one.py": "class AlphaOne: pass\n",
            "alpha/two.py": "class AlphaTwo: pass\n",
        },
    )
    commit(fixture_repo, "add alpha")
    first = await build(fixture_repo, c4_llm_manager)
    alpha = owner_of(first, "container:shop/alpha")
    (fixture_repo / "alpha").rename(fixture_repo / "omega")
    commit(fixture_repo, "rename alpha to omega")
    pipeline_answers.answers["merge"] = TimeoutError("unavailable")
    failed = await build(fixture_repo, c4_llm_manager, lock=first.lock)
    assert failed.lock.components[alpha] == first.lock.components[alpha]
    assert failed.lock.base_sha == first.lock.base_sha
    pipeline_answers.answers["merge"] = merge_answer
    recovered = await build(fixture_repo, c4_llm_manager, lock=failed.lock)
    assert owner_of(recovered, "container:shop/omega") == alpha
    assert set(recovered.lock.components[alpha].files) == {
        "omega/one.py",
        "omega/two.py",
    }
    assert alpha not in recovered.lock.tombstones
    assert alpha not in removed_ids(recovered)
    assert any(
        e.from_id == alpha and e.to_id == alpha and e.kind == "continuation"
        for e in recovered.model.history
    )


async def test_recovered_merge_titles_use_final_identity_without_titles_call(
    fixture_repo, c4_llm_manager, pipeline_answers
):
    for file, source in {
        "orders/create.py": (
            "from payments.charge import ChargePayment\n"
            "class CreateOrder:\n    def run(self): return ChargePayment()\n"
        ),
        "orders/submit.py": "class SubmitOrder: pass\n",
        "payments/charge.py": "class ChargePayment: pass\n",
        "payments/refund.py": "class RefundPayment: pass\n",
    }.items():
        path = fixture_repo / file
        path.parent.mkdir(exist_ok=True)
        path.write_text(source)
    seen = set()
    supplied = []

    def recover(prompt):
        data = payload(prompt)
        if data["container"] not in seen:
            seen.add(data["container"])
            raise TimeoutError("retry after other containers")
        answer = merge_answer(prompt)
        answer["titles"] = [
            {
                "from": "group:" + link["from"],
                "to": "group:" + link["to"],
                "title": "importeert via domein",
            }
            for link in data["links"]
        ]
        supplied.extend(answer["titles"])
        return answer

    pipeline_answers.answers["classify"] = lambda prompt: {
        "classifications": [
            {
                "key": item["key"],
                "value": "library" if item["question"] == "dependency" else "yes",
            }
            for item in json.loads(prompt.split("\nItems:\n", 1)[1])
        ]
    }
    pipeline_answers.answers["merge"] = recover
    result = await build(fixture_repo, c4_llm_manager)
    assert supplied
    assert pipeline_answers.calls["titles"] == 0
    relation = next(
        r for r in result.model.relations if r.title == "importeert via domein"
    )
    assert relation.from_id.startswith("component:")
    assert relation.to_id.startswith("component:")
    assert result.lock.relations[relation.id].title == relation.title
    assert result.fallback_count == 0


async def test_successful_fallback_wording_is_cached(
    fixture_repo, c4_llm_manager, pipeline_answers
):
    pipeline_answers.answers["titles"] = lambda prompt: {
        "titles": [
            {"fingerprint": row["fingerprint"], "title": "importeert"}
            for row in payload(prompt)["relations"]
        ]
    }
    result = await build(fixture_repo, c4_llm_manager)
    assert result.lock.relations
    assert all("fallback" not in r.markers for r in result.model.relations)
    assert all(r.title == "importeert" for r in result.lock.relations.values())


async def test_nested_containers_retain_unbound_root_references(
    fixture_repo, c4_llm_manager, pipeline_answers
):
    (fixture_repo / "pyproject.toml").unlink()
    (fixture_repo / "Dockerfile").unlink()
    (fixture_repo / "root.py").write_text(
        "from shop.orders import place_order\nplace_order('one', 10)\n"
    )
    result = await build(fixture_repo, c4_llm_manager)
    assert {e.id for e in result.model.elements if e.kind == "container"} == {
        "container:web",
        "container:acme-admin",
    }
    references = [r for r in result.evidence.references if r.from_file == "root.py"]
    assert any(r.to == "shop/orders.py" and r.status == "counts" for r in references)
    assert all(r.relation is None for r in references)


async def test_changed_transition_survives_json_lock_replay(
    fixture_repo, c4_llm_manager, pipeline_answers, tmp_path
):
    first = await build(fixture_repo, c4_llm_manager)
    shutil.rmtree(fixture_repo / "admin")
    commit(fixture_repo, "remove admin runtime")
    changed = await build(fixture_repo, c4_llm_manager, lock=first.lock)
    assert any(edge.kind == "removed" for edge in changed.model.history)
    assert changed.model.history != first.model.history
    assert changed.model.run.renames
    write_scope_lock(tmp_path / "cache", "shop", changed.lock)
    restored = read_scope_lock(tmp_path / "cache", "shop")
    pipeline_answers.calls.clear()
    replay = await build(fixture_repo, c4_llm_manager, lock=restored)
    assert not pipeline_answers.calls
    assert replay.model == changed.model
    assert replay.evidence == changed.evidence
    assert replay.lock == changed.lock


async def test_dirty_input_same_head_is_new_transition(
    fixture_repo, c4_llm_manager, pipeline_answers
):
    first = await build(fixture_repo, c4_llm_manager)
    (fixture_repo / "billing").mkdir()
    (fixture_repo / "billing/invoice.py").write_text("class Invoice: pass\n")
    (fixture_repo / "billing/credit.py").write_text("class Credit: pass\n")
    changed = await build(fixture_repo, c4_llm_manager, lock=first.lock)
    assert changed.model.run.head_sha == first.model.run.head_sha
    assert (
        changed.lock.transition.input_fingerprint
        != first.lock.transition.input_fingerprint
    )
    assert changed.model.history != first.model.history
    assert any(
        e.kind == "new" and e.to_id not in {old.to_id for old in first.model.history}
        for e in changed.model.history
    )
    pipeline_answers.calls.clear()
    replay = await build(fixture_repo, c4_llm_manager, lock=changed.lock)
    assert not pipeline_answers.calls
    assert replay.model == changed.model
    assert replay.evidence == changed.evidence
    assert replay.lock == changed.lock


@pytest.mark.parametrize("change", ["topics", "configuration", "overrides"])
async def test_analysis_inputs_invalidate_transition(
    fixture_repo, c4_llm_manager, pipeline_answers, change
):
    from chunkhound.core.config.config import Config

    first = await build(fixture_repo, c4_llm_manager)
    kwargs = {}
    if change == "topics":
        kwargs["topics"] = [TopicSources("payments", ("shop/payments.py",))]
    elif change == "configuration":
        kwargs["config"] = Config(debug=True)
    else:
        first.lock.overrides.names["container:web"] = "Browser runtime"
    changed = await build(fixture_repo, c4_llm_manager, lock=first.lock, **kwargs)
    assert (
        changed.lock.transition.input_fingerprint
        != first.lock.transition.input_fingerprint
    )
    assert changed.model.history != first.model.history
    assert changed.model.run.renames
    if change == "topics":
        assert changed.model.elements != first.model.elements
    if change == "overrides":
        assert (
            next(e.name for e in changed.model.elements if e.id == "container:web")
            == "Browser runtime"
        )


async def test_direct_placements_survive_independent_new_merge_failure(
    fixture_repo, c4_llm_manager, pipeline_answers
):
    pipeline_answers.answers["merge"] = lambda prompt: {
        "components": [],
        "direct": [g["id"] for g in payload(prompt)["groups"]],
        "titles": [],
    }
    first = await build(fixture_repo, c4_llm_manager)
    (fixture_repo / "billing").mkdir()
    (fixture_repo / "billing/invoice.py").write_text("class Invoice: pass\n")
    (fixture_repo / "billing/credit.py").write_text("class Credit: pass\n")
    pipeline_answers.answers["merge"] = TimeoutError("new grouping unavailable")
    failed = await build(fixture_repo, c4_llm_manager, lock=first.lock)
    assert failed.fallback_count > 0
    assert failed.lock.direct_groups == first.lock.direct_groups
    assert failed.lock.transition is None
    assert not failed.lock.components
    assert "billing/invoice.py" in failed.evidence.element_files["container:shop"]
    pipeline_answers.answers["merge"] = merge_answer
    pipeline_answers.calls.clear()
    recovered = await build(fixture_repo, c4_llm_manager, lock=failed.lock)
    assert pipeline_answers.calls["merge"] == 1
    assert recovered.lock.direct_groups == first.lock.direct_groups
    assert recovered.lock.components
    assert recovered.lock.transition is not None
    assert recovered.fallback_count == 0


async def test_changed_bytes_not_timestamps_invalidate_replay(
    fixture_repo, c4_llm_manager, pipeline_answers
):
    import os

    first = await build(fixture_repo, c4_llm_manager)
    path = fixture_repo / "shop/orders.py"
    before = path.stat()
    source = path.read_text()
    changed_source = source.replace("order_id", "order_no")
    assert source != changed_source and len(source) == len(changed_source)
    path.write_text(changed_source)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    changed = await build(fixture_repo, c4_llm_manager, lock=first.lock)
    assert changed.model.run.head_sha == first.model.run.head_sha
    assert (
        changed.lock.transition.input_fingerprint
        != first.lock.transition.input_fingerprint
    )
    assert changed.model.history != first.model.history


@pytest.mark.parametrize("initial_exists", [False, True], ids=["appearance", "removal"])
async def test_outside_scope_resolution_changes_transition(
    fixture_repo, c4_llm_manager, pipeline_answers, tmp_path, initial_exists
):
    scope = fixture_repo / "services/api"
    scope.mkdir(parents=True)
    (scope / "pyproject.toml").write_text(
        '[project]\nname = "api"\n[project.scripts]\napi = "main:run"\n'
    )
    source = scope / "main.py"
    source.write_text("import shared\n\ndef run():\n    return shared.work()\n")
    source_bytes = source.read_bytes()
    target = fixture_repo / "shared.py"
    if initial_exists:
        target.write_text("def work(): return 1\n")
    inputs = {"scope_path": scope, "scope_label": "services/api", "topics": []}
    first = await build(fixture_repo, c4_llm_manager, **inputs)
    before_target, after_target = (
        ("shared.py", "package:shared")
        if initial_exists
        else ("package:shared", "shared.py")
    )
    assert any(r.to == before_target for r in first.evidence.references)
    if initial_exists:
        target.unlink()
    else:
        target.write_text("def work(): return 1\n")
    changed = await build(fixture_repo, c4_llm_manager, lock=first.lock, **inputs)
    assert changed.model.run.head_sha == first.model.run.head_sha
    assert source.read_bytes() == source_bytes
    assert any(r.to == after_target for r in changed.evidence.references)
    assert changed.evidence.references != first.evidence.references
    assert changed.model.history != first.model.history
    assert changed.model.run.renames and not first.model.run.renames
    assert (
        changed.lock.transition.input_fingerprint
        != first.lock.transition.input_fingerprint
    )
    write_scope_lock(tmp_path / "cache", "services/api", changed.lock)
    restored = read_scope_lock(tmp_path / "cache", "services/api")
    pipeline_answers.calls.clear()
    replay = await build(fixture_repo, c4_llm_manager, lock=restored, **inputs)
    assert not pipeline_answers.calls
    assert replay.model == changed.model
    assert replay.evidence == changed.evidence
    assert replay.lock == changed.lock


def test_new_limit_fields_do_not_change_input_fingerprint(tmp_path):
    """Upgrading must not reset lock history: request limits are cost settings."""
    from chunkhound.code_mapper.c4.pipeline import _input_fingerprint
    from chunkhound.core.config.config import Config
    from chunkhound.core.config.llm_config import LLMConfig

    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    plain = Config(target_dir=tmp_path, llm=LLMConfig(provider="codex-cli"))
    limited = Config(
        target_dir=tmp_path,
        llm=LLMConfig(
            provider="codex-cli",
            utility_max_input_chars=50_000,
            utility_max_input_tokens=10_000,
        ),
    )
    assert _input_fingerprint(tmp_path, ["app.py"], plain, tmp_path) == (
        _input_fingerprint(tmp_path, ["app.py"], limited, tmp_path)
    )


async def test_fallback_fragment_without_lock_items_blocks_lock(
    fixture_repo, c4_llm_manager, pipeline_answers
):
    """A first run whose only document keeps failing: no lock items to fall
    back on, yet neither documentation nor a transition may be locked."""
    citation = {"file": "README.md", "start_line": 3, "end_line": 3}
    pipeline_answers.answers["documented"] = {
        "elements": [
            {
                "kind": "person",
                "term": "beheerder",
                "citation": {**citation, "quote": "Verzonnen citaat"},
            }
        ],
        "relations": [],
    }

    result = await build(fixture_repo, c4_llm_manager)

    assert pipeline_answers.calls["documented"] == 2
    assert result.model.run.kind == "full"
    assert result.model.run.fallback_fragments == 1
    assert result.lock.documented is None
    assert result.lock.transition is None
    assert not any(
        c.source == "documentation" and c.verified for c in result.evidence.citations
    )


async def test_old_cache_entries_are_pruned_only_after_non_trial_run(
    fixture_repo, c4_llm_manager, pipeline_answers
):
    import os
    import time

    from chunkhound.code_mapper.c4.documented import EXTRACTION_CACHE

    directory = fixture_repo / EXTRACTION_CACHE / "documented"
    directory.mkdir(parents=True)
    old = directory / ("0" * 64 + ".json")
    old.write_text("{}", encoding="utf-8")
    month_ago = time.time() - 31 * 86_400
    os.utime(old, (month_ago, month_ago))

    await build(fixture_repo, c4_llm_manager, trial=True)
    assert old.exists()

    await build(fixture_repo, c4_llm_manager)
    assert not old.exists()
    assert list(directory.glob("*.json"))  # this run's bundle stays

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
                "name": group["name"],
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
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return await finish_c4(
        draft=draft,
        topics=inputs.get("topics", [TopicSources("orders", ("shop/orders.py",))]),
        llm=llm,
        lock=lock,
        retries=retries,
        head_sha=head,
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


async def test_llm_failure_contract(fixture_repo, c4_llm_manager, pipeline_answers):
    pipeline_answers.answers["merge"] = TimeoutError("temporarily unavailable")
    result = await build(fixture_repo, c4_llm_manager)
    components = [e for e in result.model.elements if e.kind == "component"]
    assert components and all("fallback" in e.markers for e in components)
    assert result.fallback_count == sum(
        "fallback" in e.markers for e in result.model.elements
    )
    assert result.fallback_count > 0
    assert result.lock.components == {}
    assert not any(result.lock.direct_groups.values())
    assert result.lock.transition is None
    assert {f for e in components for f in result.evidence.element_files[e.id]} >= {
        "shop/orders.py",
        "web/src/api.ts",
    }
    pipeline_answers.answers["classify"] = ValueError("bad config")
    with pytest.raises(ValueError, match="bad config"):
        await build(fixture_repo, c4_llm_manager)


async def test_rerun_unchanged_zero_calls_stable_output(
    fixture_repo, c4_llm_manager, pipeline_answers, tmp_path
):
    first = await build(fixture_repo, c4_llm_manager)
    assert first.fallback_count == 0
    assert first.lock.group_membership
    write_scope_lock(tmp_path / "cache", "shop", first.lock)
    restored = read_scope_lock(tmp_path / "cache", "shop")
    pipeline_answers.calls.clear()
    second = await build(fixture_repo, c4_llm_manager, lock=restored)
    assert not pipeline_answers.calls
    assert second.model == first.model
    assert second.evidence == first.evidence
    assert second.lock == first.lock


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
    assert first.lock.group_membership
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


async def test_failed_merge_is_attempted_again_on_next_run(
    fixture_repo, c4_llm_manager, pipeline_answers
):
    pipeline_answers.answers["merge"] = TimeoutError("unavailable")
    first = await build(fixture_repo, c4_llm_manager)
    pipeline_answers.answers["merge"] = merge_answer
    pipeline_answers.calls.clear()
    second = await build(fixture_repo, c4_llm_manager, lock=first.lock)
    assert pipeline_answers.calls["merge"] > 0
    assert second.lock.components
    assert second.fallback_count == 0
    assert second.lock.transition is not None


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
    subprocess.run(["git", "add", "-A"], cwd=fixture_repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=C4 Fixture",
            "-c",
            "user.email=c4@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            "remove admin runtime",
        ],
        cwd=fixture_repo,
        check=True,
        capture_output=True,
    )
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
    assert "billing/invoice.py" in failed.lock.group_membership["container:shop"]
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

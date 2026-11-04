"""Whole-group placement, cached identities, relation evidence and recovery."""

import json
from collections import Counter
from pathlib import Path

import pytest

from chunkhound.code_mapper.c4.grouping import Group
from chunkhound.code_mapper.c4.llm import AnswerRejectedError, C4Llm, RetryQueue
from chunkhound.code_mapper.c4.merge import (
    MergeAnswer,
    check_merge_answer,
    fallback_title,
    merge_container,
    relation_fingerprint,
    title_relations,
)
from chunkhound.code_mapper.c4.model import LockedComponent
from chunkhound.code_mapper.c4.runtime import RuntimeUnit
from chunkhound.llm_manager import LLMManager
from chunkhound.services.extraction.budget import ENVELOPE_MARGIN_CHARS, schema_text

CONTAINER = RuntimeUnit("container:shop", "shop", "pyproject.toml", ".", False, (), ())
GROUPS = [
    Group("container:shop/1", CONTAINER.id, "orders", "orders", ("orders/api.py",)),
    Group("container:shop/2", CONTAINER.id, "db", "db", ("db/store.py",)),
    Group("container:shop/3", CONTAINER.id, "common", "common", ("common/types.py",)),
]
# These groups name files that do not exist; a parser failure costs only symbols.
NO_FILES = Path("/nonexistent")


def answer(components=(), direct=(), titles=()):
    return {
        "components": list(components),
        "direct": list(direct),
        "titles": list(titles),
    }


def component(name, groups):
    return {"name": name, "description": "Domain responsibility.", "groups": groups}


@pytest.mark.parametrize(
    "placement",
    [
        answer([component("Orders", [GROUPS[0].id, "unknown"])]),
        answer([component("Orders", [GROUPS[0].id, GROUPS[0].id])]),
        answer([component("Orders", ["container:other/1"])]),
        answer(),
        answer([component("Empty", [])], [GROUPS[0].id]),
    ],
)
def test_merge_rejects_invalid_placement(placement):
    with pytest.raises(AnswerRejectedError):
        check_merge_answer(
            MergeAnswer.model_validate(placement), GROUPS[:1], CONTAINER.id
        )


def test_merge_rejects_foreign_container_even_with_matching_id():
    foreign = Group(GROUPS[0].id, "container:other", "other", "other", ("other.py",))
    with pytest.raises(AnswerRejectedError):
        check_merge_answer(
            MergeAnswer.model_validate(answer(direct=[foreign.id])),
            [foreign],
            CONTAINER.id,
        )


async def test_merge_direct_group_has_no_component(c4_llm_manager, scripted):
    scripted.answers["merge"] = answer(direct=["G1", "G2", "G3"])
    queue = RetryQueue()
    result = await merge_container(
        container=CONTAINER,
        project_root=NO_FILES,
        references=[],
        groups=GROUPS,
        group_links={},
        existing={},
        placements={},
        llm=C4Llm(c4_llm_manager, concurrency=1, trial=False),
        retries=queue,
    )
    assert result.components == []
    assert result.direct_groups == [g.id for g in GROUPS]
    assert not result.fallback
    assert await queue.drain() == 0


async def test_merge_fallback_leaves_groups_pending(c4_llm_manager, scripted):
    scripted.answers["merge"] = TimeoutError("temporarily unavailable")
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    queue = RetryQueue()
    locked = LockedComponent(
        name="Orders",
        description="Orders API",
        container=CONTAINER.id,
        groups=[GROUPS[0].id],
        files=[],
    )
    result = await merge_container(
        container=CONTAINER,
        project_root=NO_FILES,
        references=[],
        groups=GROUPS,
        group_links={},
        existing={"component:orders": locked},
        placements={},
        llm=llm,
        retries=queue,
    )
    assert not result.fallback  # Deferred, not yet a fallback.
    assert await queue.drain() == 1
    assert llm.calls == 2
    assert result.fallback
    assert [(c.key, c.groups) for c in result.components] == [
        ("component:orders", (GROUPS[0].id,))
    ]
    assert result.direct_groups == []
    assert result.pending_groups == [GROUPS[1].id, GROUPS[2].id]
    assert result.failure_reason == "tijdelijke fout"


async def test_merge_trial_has_no_calls_or_deferred_work():
    queue = RetryQueue()
    llm = C4Llm(None, concurrency=1, trial=False)
    result = await merge_container(
        container=CONTAINER,
        project_root=NO_FILES,
        references=[],
        groups=GROUPS,
        group_links={},
        existing={},
        placements={},
        llm=llm,
        retries=queue,
    )
    assert not result.fallback
    assert llm.calls == await queue.drain() == 0
    assert all(
        set(c.markers) == {"trial", "not_merged", "provisional"}
        for c in result.components
    )


async def test_known_placements_and_override_win_without_calls(c4_llm_manager):
    locked = LockedComponent(
        name="Orders",
        description="Orders API",
        container=CONTAINER.id,
        groups=[GROUPS[0].id, GROUPS[1].id],
        files=[],
    )
    other = LockedComponent(
        name="Storage",
        description=None,
        container=CONTAINER.id,
        groups=[GROUPS[2].id],
        files=[],
    )
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    result = await merge_container(
        container=CONTAINER,
        project_root=NO_FILES,
        references=[],
        groups=GROUPS,
        group_links={},
        existing={"component:orders": locked, "component:storage": other},
        placements={GROUPS[1].id: "component:storage"},
        llm=llm,
        retries=RetryQueue(),
    )
    assert {c.key: c.groups for c in result.components} == {
        "component:orders": (GROUPS[0].id,),
        "component:storage": (GROUPS[1].id, GROUPS[2].id),
    }
    assert llm.calls == 0


async def test_merge_titles_survive_and_only_unclaimed_groups_are_sent(
    c4_llm_manager, scripted
):
    locked = LockedComponent(
        name="Orders",
        description="API",
        container=CONTAINER.id,
        groups=[GROUPS[0].id],
        files=[],
    )
    seen = []

    def respond(prompt):
        seen.append(json.loads(prompt.split("\nInput:\n", 1)[1]))
        return answer(
            [component("Storage", ["G1"])],
            ["G2"],
            [{"from": "component:E1", "to": "group:G1", "title": "bewaart via"}],
        )

    scripted.answers["merge"] = respond
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    result = await merge_container(
        container=CONTAINER,
        project_root=NO_FILES,
        references=[],
        groups=GROUPS,
        group_links={(GROUPS[0].id, GROUPS[1].id): Counter({"call": 2})},
        existing={"component:orders": locked},
        placements={},
        llm=llm,
        retries=RetryQueue(),
    )
    target = next(c.key for c in result.components if c.name == "Storage")
    assert result.titles == {("component:orders", target): "bewaart via"}
    assert [(g["id"], g["dir"]) for g in seen[0]["groups"]] == [
        ("G1", "db"),
        ("G2", "common"),
    ]
    assert seen[0]["existing"] == [
        {"id": "E1", "name": "Orders", "description": "API", "dirs": ["orders"]}
    ]
    # The caller removes already supplied pairs before requesting remaining titles.
    assert (
        await title_relations(
            container=CONTAINER.id, pending={}, llm=llm, retries=RetryQueue()
        )
        == {}
    )
    assert scripted.calls == {"merge": 1}


@pytest.mark.parametrize(
    "endpoint", ["group:G99", "group:G3", "component:E1", f"group:{GROUPS[1].id}"]
)
async def test_merge_retries_unsupported_title_endpoints(
    c4_llm_manager, scripted, endpoint
):
    scripted.answers["merge"] = answer(
        [component("Orders", ["G1"]), component("Storage", ["G2"])],
        ["G3"],
        [{"from": "group:G1", "to": endpoint, "title": "uses"}],
    )
    queue = RetryQueue()
    result = await merge_container(
        container=CONTAINER,
        project_root=NO_FILES,
        references=[],
        groups=GROUPS,
        group_links={(GROUPS[0].id, GROUPS[1].id): Counter({"call": 1})},
        existing={},
        placements={},
        llm=C4Llm(c4_llm_manager, concurrency=1, trial=False),
        retries=queue,
    )
    assert await queue.drain() == 1
    assert result.fallback and not result.titles


async def test_rejected_merge_can_recover_on_delayed_retry(c4_llm_manager, scripted):
    # A real id is not an alias of this call, so it counts as an unknown group.
    responses = iter(
        [answer(direct=[g.id for g in GROUPS]), answer(direct=["G1", "G2", "G3"])]
    )
    scripted.answers["merge"] = lambda _: next(responses)
    queue = RetryQueue()
    result = await merge_container(
        container=CONTAINER,
        project_root=NO_FILES,
        references=[],
        groups=GROUPS,
        group_links={},
        existing={},
        placements={},
        llm=C4Llm(c4_llm_manager, concurrency=1, trial=False),
        retries=queue,
    )
    assert await queue.drain() == 0
    assert result.direct_groups == [g.id for g in GROUPS]
    assert not result.fallback


async def test_fatal_merge_error_propagates(c4_llm_manager, scripted):
    scripted.answers["merge"] = ValueError("bad config")
    with pytest.raises(ValueError, match="bad config"):
        await merge_container(
            container=CONTAINER,
            project_root=NO_FILES,
            references=[],
            groups=GROUPS,
            group_links={},
            existing={},
            placements={},
            llm=C4Llm(c4_llm_manager, concurrency=1, trial=False),
            retries=RetryQueue(),
        )


@pytest.mark.parametrize(
    ("kinds", "title"),
    [
        ({"import"}, "importeert"),
        ({"call", "import"}, "roept aan"),
        ({"inherit", "call", "import"}, "erft van"),
    ],
)
def test_fallback_titles(kinds, title):
    assert fallback_title(kinds) == title


def test_fingerprint_tracks_pair_kind_target_but_not_order_or_duplicates():
    refs = [("call", "db/store.py"), ("import", "db/types.py")]
    fingerprint = relation_fingerprint("a", "b", refs)
    assert fingerprint == relation_fingerprint("a", "b", [*reversed(refs), refs[0]])
    assert len(fingerprint) == 64
    assert fingerprint != relation_fingerprint("b", "a", refs)
    assert fingerprint != relation_fingerprint(
        "a", "b", [("import", "db/store.py"), refs[1]]
    )
    assert fingerprint != relation_fingerprint(
        "a", "b", [("call", "other.py"), refs[1]]
    )


async def test_titles_validate_all_fingerprints_and_retry(c4_llm_manager, scripted):
    responses = iter(
        [
            {"titles": [{"fingerprint": "unknown", "title": "uses"}]},
            {"titles": [{"fingerprint": "fp", "title": "bewaart via"}]},
        ]
    )
    scripted.answers["titles"] = lambda _: next(responses)
    queue = RetryQueue()
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    result = await title_relations(
        container=CONTAINER.id,
        pending={"fp": Counter({"call": 1})},
        llm=llm,
        retries=queue,
    )
    assert result == {}
    assert await queue.drain() == 0
    assert result == {"fp": "bewaart via"}
    assert llm.calls == 2


async def test_titles_timeout_fallback_and_trial(c4_llm_manager, scripted):
    scripted.answers["titles"] = TimeoutError("unavailable")
    queue = RetryQueue()
    pending = {"fp": Counter({"import": 2, "inherit": 1})}
    result = await title_relations(
        container=CONTAINER.id,
        pending=pending,
        llm=C4Llm(c4_llm_manager, concurrency=1, trial=False),
        retries=queue,
    )
    assert await queue.drain() == 1
    assert result == {"fp": "erft van"}
    trial_queue = RetryQueue()
    assert (
        await title_relations(
            container=CONTAINER.id,
            pending=pending,
            llm=C4Llm(None, concurrency=1, trial=True),
            retries=trial_queue,
        )
        == result
    )
    assert await trial_queue.drain() == 0


async def test_merge_attaches_new_group_to_existing_component(c4_llm_manager, scripted):
    locked = LockedComponent(
        name="Orders",
        description="Keep this description",
        container=CONTAINER.id,
        groups=[GROUPS[0].id],
        files=[],
    )
    scripted.answers["merge"] = answer(
        [component("Orders", ["G1"])],
        ["G2"],
        [{"from": "component:E1", "to": "container", "title": "importeert"}],
    )
    result = await merge_container(
        container=CONTAINER,
        project_root=NO_FILES,
        references=[],
        groups=GROUPS,
        group_links={(GROUPS[0].id, GROUPS[2].id): Counter({"import": 1})},
        existing={"component:orders": locked},
        placements={},
        llm=C4Llm(c4_llm_manager, concurrency=1, trial=False),
        retries=RetryQueue(),
    )
    assert len(result.components) == 1
    merged = result.components[0]
    assert merged.key == "component:orders"
    assert merged.groups == (GROUPS[0].id, GROUPS[1].id)
    assert merged.description == "Keep this description"
    assert result.titles == {("component:orders", CONTAINER.id): "importeert"}


@pytest.mark.parametrize("mode", ["reverse", "self", "duplicate"])
async def test_merge_rejects_unsupported_normalized_pairs(
    c4_llm_manager, scripted, mode
):
    row = {"from": "group:G1", "to": "group:G2", "title": "uses"}
    if mode == "reverse":
        row["from"], row["to"] = row["to"], row["from"]
    elif mode == "self":
        row["to"] = row["from"]
    titles = [row, dict(row)] if mode == "duplicate" else [row]
    scripted.answers["merge"] = answer(
        [component("Orders", ["G1"]), component("Storage", ["G2"])],
        ["G3"],
        titles,
    )
    queue = RetryQueue()
    result = await merge_container(
        container=CONTAINER,
        project_root=NO_FILES,
        references=[],
        groups=GROUPS,
        group_links={(GROUPS[0].id, GROUPS[1].id): Counter({"call": 1})},
        existing={},
        placements={},
        llm=C4Llm(c4_llm_manager, concurrency=1, trial=False),
        retries=queue,
    )
    assert await queue.drain() == 1
    assert result.fallback and not result.titles


async def test_proposed_keys_are_stable_across_group_order(c4_llm_manager, scripted):
    scripted.answers["merge"] = answer([component("Orders", ["G1", "G2", "G3"])])
    results = [
        await merge_container(
            container=CONTAINER,
            project_root=NO_FILES,
            references=[],
            groups=groups,
            group_links={},
            existing={},
            placements={},
            llm=C4Llm(c4_llm_manager, concurrency=1, trial=False),
            retries=RetryQueue(),
        )
        for groups in (GROUPS, list(reversed(GROUPS)))
    ]
    assert results[0].components == results[1].components


async def test_merge_aliases_round_trip_to_real_ids(c4_llm_manager, scripted):
    locked = LockedComponent(
        name="Orders",
        description="API",
        container=CONTAINER.id,
        groups=[GROUPS[0].id],
        files=[],
    )
    prompts = []

    def respond(prompt):
        prompts.append(prompt.split("\nInput:\n", 1)[1])
        return answer(
            [component("Storage", ["G1"])],
            ["G2"],
            [
                {"from": "component:E1", "to": "group:G1", "title": "bewaart via"},
                {"from": "container", "to": "component:E1", "title": "levert aan"},
            ],
        )

    scripted.answers["merge"] = respond
    result = await merge_container(
        container=CONTAINER,
        project_root=NO_FILES,
        references=[],
        groups=GROUPS,
        group_links={
            (GROUPS[0].id, GROUPS[1].id): Counter({"call": 1}),
            (GROUPS[2].id, GROUPS[0].id): Counter({"import": 1}),
        },
        existing={"component:orders": locked},
        placements={},
        llm=C4Llm(c4_llm_manager, concurrency=1, trial=False),
        retries=RetryQueue(),
    )
    storage = next(c for c in result.components if c.name == "Storage")
    assert storage.groups == (GROUPS[1].id,)
    assert result.direct_groups == [GROUPS[2].id]
    assert result.titles == {
        ("component:orders", storage.key): "bewaart via",
        (CONTAINER.id, "component:orders"): "levert aan",
    }
    assert not result.fallback
    assert "container:shop" not in prompts[0]


async def test_oversized_prompt_makes_no_call_and_reports(
    tmp_path, c4_llm_manager, scripted
):
    source = tmp_path / "orders/api.py"
    source.parent.mkdir()
    source.write_text("class OrderApi:\n    def run(self): return 1\n")
    group = Group(
        "container:shop/orders", CONTAINER.id, "orders", "orders", ("orders/api.py",)
    )
    room = len(schema_text(MergeAnswer.model_json_schema())) + ENVELOPE_MARGIN_CHARS
    prompts = []

    def respond(prompt):
        prompts.append(prompt)
        return answer(direct=["G1"])

    scripted.answers["merge"] = respond

    async def merge_within(limit):
        config = {"provider": "fake", "model": "fake-gpt"}
        manager = LLMManager(
            utility_config=config,
            synthesis_config={**config, "max_input_chars": limit},
        )
        return await merge_container(
            container=CONTAINER,
            project_root=tmp_path,
            references=[],
            groups=[group],
            group_links={},
            existing={},
            placements={},
            llm=C4Llm(manager, concurrency=1, trial=False),
            retries=RetryQueue(),
        )

    await merge_within(1_000_000)
    with_symbols = prompts[-1]
    assert "OrderApi" in with_symbols

    # One character too large: symbols go first and the call still happens.
    await merge_within(len(with_symbols) + room - 1)
    without_symbols = prompts[-1]
    assert "OrderApi" not in without_symbols
    assert scripted.calls["merge"] == 2

    limit = len(without_symbols) + room - 1
    result = await merge_within(limit)
    assert scripted.calls["merge"] == 2
    assert result.fallback
    assert result.components == result.direct_groups == []
    assert result.pending_groups == [group.id]
    assert str(limit) in result.failure_reason
    assert str(limit + 1) in result.failure_reason


async def test_merge_sends_public_symbols_and_places_unparseable_files(
    tmp_path, c4_llm_manager, scripted
):
    directory = tmp_path / "orders"
    directory.mkdir()
    (directory / "api.py").write_text(
        "class OrderApi:\n    def run(self): return 1\n\n"
        "class _Hidden:\n    def run(self): return 2\n"
    )
    (directory / "broken.py").write_text("class Broken(:\n  def (\n")
    group = Group(
        "container:shop/orders",
        CONTAINER.id,
        "orders",
        "orders",
        ("orders/api.py", "orders/broken.py", "orders/gone.py"),
    )
    seen = {}

    def respond(prompt):
        files = json.loads(prompt.split("\nInput:\n", 1)[1])["groups"][0]["files"]
        seen.update({row["name"]: row["symbols"] for row in files})
        return answer(direct=["G1"])

    scripted.answers["merge"] = respond
    result = await merge_container(
        container=CONTAINER,
        project_root=tmp_path,
        references=[],
        groups=[group],
        group_links={},
        existing={},
        placements={},
        llm=C4Llm(c4_llm_manager, concurrency=1, trial=False),
        retries=RetryQueue(),
    )
    assert set(seen) == {"api.py", "broken.py", "gone.py"}
    assert "OrderApi" in seen["api.py"]
    assert "_Hidden" not in seen["api.py"]
    assert seen["gone.py"] == []
    assert result.direct_groups == [group.id]
    assert not result.fallback

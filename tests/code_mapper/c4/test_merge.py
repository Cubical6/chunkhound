"""Whole-group placement, cached identities, relation evidence and recovery."""

import json
from collections import Counter
from pathlib import Path

import pytest

from chunkhound.code_mapper.c4 import merge as merge_module
from chunkhound.code_mapper.c4.grouping import Group
from chunkhound.code_mapper.c4.llm import C4Llm, RetryQueue
from chunkhound.code_mapper.c4.merge import (
    MergeAnswer,
    TitleRequest,
    fallback_title,
    merge_container,
    relation_fingerprint,
    title_relations,
)
from chunkhound.code_mapper.c4.model import LockedComponent, Reference
from chunkhound.code_mapper.c4.runtime import RuntimeUnit
from chunkhound.llm_manager import LLMManager
from chunkhound.services.extraction.budget import (
    ENVELOPE_MARGIN_CHARS,
    InputLimit,
    schema_text,
)

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


def title_request(kinds, targets=("db/store.py",)):
    return TitleRequest(
        from_name="Orders",
        from_description="Handles orders.",
        to_name="Storage",
        to_description="Keeps data.",
        kinds=Counter(kinds),
        targets=targets,
    )


def component(name, groups):
    return {"name": name, "description": "Domain responsibility.", "groups": groups}


async def merge(llm, queue, *, groups=GROUPS, **overrides):
    return await merge_container(
        **{
            "container": CONTAINER,
            "project_root": NO_FILES,
            "references": [],
            "groups": groups,
            "group_links": {},
            "existing": {},
            "placements": {},
            "llm": llm,
            "retries": queue,
            **overrides,
        }
    )


def sequence(*responses):
    """Answer each call in turn; an Exception is raised, a callable gets the prompt."""
    remaining = iter(responses)

    def respond(prompt):
        response = next(remaining)
        if isinstance(response, Exception):
            raise response
        return response(prompt) if callable(response) else response

    return respond


def data(prompt):
    return json.loads(prompt.split("\nInput:\n", 1)[1])


def alias_of(prompt, name):
    return next(row["id"] for row in data(prompt)["existing"] if row["name"] == name)


def place_first(prompt):
    return answer(direct=[data(prompt)["groups"][0]["id"]])


@pytest.mark.parametrize(
    ("placement", "removed"),
    [
        (answer([component("Orders", ["G1", "G99"])]), 1),
        (answer([component("Orders", ["G1", "G1"])]), 1),
        (answer([component("Orders", ["G1"])], ["G1"]), 1),
        (answer([component("Empty", []), component("Orders", ["G1"])]), 0),
        (answer([component("Ghost", ["G99"]), component("Orders", ["G1"])]), 1),
    ],
)
async def test_merge_repairs_invalid_placement(
    c4_llm_manager, scripted, placement, removed
):
    scripted.answers["merge"] = placement
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    queue = RetryQueue()
    result = await merge(llm, queue, groups=GROUPS[:1])
    assert [(c.name, c.groups) for c in result.components] == [
        ("Orders", (GROUPS[0].id,))
    ]
    assert result.direct_groups == []
    assert (result.placed_groups, result.removed_placements) == (1, removed)
    assert await queue.drain() == 0
    assert llm.calls == 1
    assert not result.fallback


async def test_merge_refuses_foreign_input_group(c4_llm_manager):
    foreign = Group(GROUPS[0].id, "container:other", "other", "other", ("other.py",))
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    with pytest.raises(ValueError, match="foreign input group"):
        await merge(llm, RetryQueue(), groups=[foreign])
    assert llm.calls == 0


async def test_partial_answer_is_repaired_and_leftovers_retry_narrowly(
    c4_llm_manager, scripted
):
    groups = [
        *GROUPS,
        Group("container:shop/4", CONTAINER.id, "search", "search", ("search/a.py",)),
        Group("container:shop/5", CONTAINER.id, "web", "web", ("web/b.py",)),
    ]
    ids = [group.id for group in groups]
    prompts = []

    def first(prompt):
        return answer(
            [
                component("Orders", ["G1", "G99", "G1"]),  # unknown and repeat
                component("Orders", ["G2"]),  # same name
                component("Storage", ["G3"]),
                component("Ghost", ["G98"]),  # nothing remains
                component("", ["G4"]),  # no name
            ],
            ["G1"],  # repeat: the component row was first
            [
                {"from": "group:G1", "to": "group:G3", "title": "bewaart via"},
                {"from": "group:G1", "to": "group:G99", "title": "onbekend"},
                {"from": "group:G2", "to": "group:G3", "title": "zelfde paar"},
                {"from": "group:G4", "to": "group:G5", "title": "nog niet geplaatst"},
            ],
        )

    def second(prompt):
        orders = alias_of(prompt, "Orders")
        storage = alias_of(prompt, "Storage")
        return answer(
            [component("Orders", ["G1"]), component("Zoeken", ["G2"])],
            titles=[
                {
                    "from": f"component:{orders}",
                    "to": f"component:{storage}",
                    "title": "tweede wint niet",
                },
                {
                    "from": f"component:{storage}",
                    "to": "group:G2",
                    "title": "levert aan",
                },
            ],
        )

    answers = sequence(first, second)

    def respond(prompt):
        prompts.append(prompt)
        return answers(prompt)

    scripted.answers["merge"] = respond
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    queue = RetryQueue()
    result = await merge(
        llm,
        queue,
        groups=groups,
        group_links={
            (ids[0], ids[2]): Counter({"call": 1}),
            (ids[1], ids[2]): Counter({"call": 1}),
            (ids[2], ids[4]): Counter({"import": 1}),
        },
        references=[
            Reference(
                relation=None,
                from_file=source,
                line=1,
                to=target,
                kind="import",
                status="counts",
            )
            for source, target in (
                ("orders/api.py", "orders/api.py"),
                ("orders/api.py", "db/store.py"),
            )
        ],
    )
    assert llm.calls == 1
    orders_key = next(c.key for c in result.components if c.name == "Orders")
    assert await queue.drain() == 0
    assert llm.calls == 2

    # A file referring to itself is never evidence for a placement.
    assert data(prompts[0])["file_links"] == [[0, 1, 1]]
    # The narrow prompt holds only what is left, beside what was just chosen.
    narrow = data(prompts[1])
    assert [row["dir"] for row in narrow["groups"]] == ["search", "web"]
    assert {row["name"]: row["dirs"] for row in narrow["existing"]} == {
        "Orders": ["db", "orders"],
        "Storage": ["common"],
    }

    by_name = {c.name: c for c in result.components}
    assert set(by_name) == {"Orders", "Storage", "Zoeken"}
    assert by_name["Orders"].key == orders_key
    assert by_name["Orders"].groups == (ids[0], ids[1], ids[3])
    assert by_name["Storage"].groups == (ids[2],)
    assert by_name["Zoeken"].groups == (ids[4],)
    assert result.direct_groups == []
    assert result.titles == {
        (orders_key, by_name["Storage"].key): "bewaart via",
        (by_name["Storage"].key, by_name["Zoeken"].key): "levert aan",
    }
    assert result.placed_groups == 5
    assert result.removed_placements == 4  # G99, G98, and two repeats of G1
    assert result.pending_groups == []
    assert not result.fallback
    assert result.failure_reason is None


async def test_ambiguous_existing_name_makes_its_groups_leftover(
    c4_llm_manager, scripted
):
    groups = [
        *GROUPS,
        Group("container:shop/4", CONTAINER.id, "search", "search", ("search/a.py",)),
    ]
    locked = {
        f"component:orders-{index}": LockedComponent(
            name="Orders",
            description=None,
            container=CONTAINER.id,
            groups=[GROUPS[index].id],
            files=[],
        )
        for index in range(2)
    }
    # The name stays ambiguous on the narrow retry, which then places nothing.
    scripted.answers["merge"] = sequence(
        answer([component("Orders", ["G1"]), component("Zoeken", ["G2"])]),
        answer([component("Orders", ["G1"])]),
    )
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    queue = RetryQueue()
    result = await merge(llm, queue, groups=groups, existing=locked)
    assert await queue.drain() == 1
    assert llm.calls == 2
    assert {c.name: c.groups for c in result.components if c.name != "Orders"} == {
        "Zoeken": (groups[3].id,)
    }
    assert {c.key: c.groups for c in result.components if c.name == "Orders"} == {
        "component:orders-0": (GROUPS[0].id,),
        "component:orders-1": (GROUPS[1].id,),
    }
    assert result.pending_groups == [GROUPS[2].id]
    assert result.fallback


@pytest.mark.parametrize(
    "nothing",
    [
        answer(),
        answer([component("Empty", [])]),
        answer([component("Orders", ["G99"])]),
        answer([component("", ["G1"])]),
        answer(direct=[GROUPS[0].id]),  # a real id is no alias of this call
    ],
)
@pytest.mark.parametrize("recovers", [True, False])
async def test_answer_placing_nothing_is_rejected_and_retried_once(
    c4_llm_manager, scripted, nothing, recovers
):
    prompts = []
    answers = sequence(
        nothing, answer(direct=["G1", "G2", "G3"]) if recovers else nothing
    )

    def respond(prompt):
        prompts.append(prompt)
        return answers(prompt)

    scripted.answers["merge"] = respond
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    queue = RetryQueue()
    result = await merge(llm, queue)
    assert await queue.drain() == (0 if recovers else 1)
    assert llm.calls == 2
    assert prompts[0] == prompts[1]
    if recovers:
        assert result.direct_groups == [g.id for g in GROUPS]
        assert not result.fallback
    else:
        assert result.components == result.direct_groups == []
        assert result.pending_groups == [g.id for g in GROUPS]
        assert result.fallback
        assert result.failure_reason == "rejected (answer places no group)"


@pytest.mark.parametrize(
    "unreadable",
    [
        RuntimeError("Structured output truncated by the provider"),
        RuntimeError("Invalid JSON in structured output: quoted input_too_large"),
        ValueError("Incomplete - token limit reached"),
    ],
)
@pytest.mark.parametrize("recovers", [True, False])
async def test_truncated_answer_does_not_end_the_run(
    c4_llm_manager, scripted, unreadable, recovers
):
    scripted.answers["merge"] = sequence(
        unreadable, answer(direct=["G1", "G2", "G3"]) if recovers else unreadable
    )
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    queue = RetryQueue()
    result = await merge(llm, queue)
    assert await queue.drain() == (0 if recovers else 1)
    assert llm.calls == 2
    assert result.fallback is not recovers
    if not recovers:
        assert result.pending_groups == [g.id for g in GROUPS]
        assert result.failure_reason == "rejected (invalid answer schema)"


@pytest.mark.parametrize(
    "refusal",
    [
        RuntimeError("provider said input_too_large for secret payload"),
        TimeoutError("input_too_large after a timeout"),
    ],
)
async def test_input_refusal_goes_to_fallback_without_retry(
    c4_llm_manager, scripted, refusal
):
    scripted.answers["merge"] = refusal
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    queue = RetryQueue()
    result = await merge(llm, queue)
    assert await queue.drain() == 0
    assert llm.calls == 1
    assert result.fallback
    assert result.components == result.direct_groups == []
    assert result.pending_groups == [g.id for g in GROUPS]
    assert result.failure_reason == "input refused"
    report = "\n".join(llm.report_lines())
    assert "input refused, fallback" in report
    assert "secret" not in report

    # Refused on the narrow retry: what the first call placed stays placed.
    scripted.answers["merge"] = sequence(place_first, refusal)
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    queue = RetryQueue()
    result = await merge(llm, queue)
    await queue.drain()
    assert llm.calls == 2
    assert result.fallback
    assert result.direct_groups == [GROUPS[0].id]
    assert result.pending_groups == [GROUPS[1].id, GROUPS[2].id]
    assert result.failure_reason == "input refused"


@pytest.mark.parametrize(
    ("responses", "placed", "reason"),
    [
        ((place_first, place_first), 2, "incomplete answer"),
        ((TimeoutError("busy"), place_first), 1, "incomplete answer"),
        ((answer(), place_first), 1, "incomplete answer"),
        ((place_first, TimeoutError("busy")), 1, "transient error"),
        ((place_first, answer()), 1, "rejected (answer places no group)"),
        ((TimeoutError("busy"), TimeoutError("busy")), 0, "transient error"),
    ],
)
async def test_at_most_two_merge_calls_per_container(
    c4_llm_manager, scripted, responses, placed, reason
):
    # A third call would exhaust the sequence and fail the test.
    scripted.answers["merge"] = sequence(*responses)
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    queue = RetryQueue()
    result = await merge(llm, queue)
    await queue.drain()
    assert await queue.drain() == 0
    assert llm.calls == 2
    assert result.fallback
    assert result.failure_reason == reason
    assert result.placed_groups == len(result.direct_groups) == placed
    assert result.direct_groups == [g.id for g in GROUPS[:placed]]
    assert result.pending_groups == [g.id for g in GROUPS[placed:]]


async def test_narrow_retry_that_does_not_fit_makes_no_call(c4_llm_manager, scripted):
    prompts = []

    def respond(prompt):
        prompts.append(prompt)
        # The description makes the narrow prompt larger than the first one.
        return answer([{"name": "Orders", "description": "x" * 5000, "groups": ["G1"]}])

    scripted.answers["merge"] = respond

    async def merge_within(limit):
        config = {"provider": "fake", "model": "fake-gpt"}
        manager = LLMManager(
            utility_config=config,
            synthesis_config={**config, "max_input_chars": limit},
        )
        llm = C4Llm(manager, concurrency=1, trial=False)
        queue = RetryQueue()
        result = await merge(llm, queue, groups=GROUPS)
        await queue.drain()
        return result

    await merge_within(1_000_000)
    assert len(prompts) == 2
    room = len(schema_text(MergeAnswer.model_json_schema())) + ENVELOPE_MARGIN_CHARS
    limit = len(prompts[0]) + room
    assert len(prompts[1]) + room > limit

    prompts.clear()
    result = await merge_within(limit)
    assert len(prompts) == 1
    assert result.fallback
    assert [(c.name, c.groups) for c in result.components] == [
        ("Orders", (GROUPS[0].id,))
    ]
    assert result.pending_groups == [GROUPS[1].id, GROUPS[2].id]
    assert result.failure_reason.startswith("input too large")
    assert str(limit) in result.failure_reason


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
    assert result.failure_reason == "transient error"


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
async def test_merge_drops_unsupported_title_endpoints(
    c4_llm_manager, scripted, endpoint
):
    scripted.answers["merge"] = answer(
        [component("Orders", ["G1"]), component("Storage", ["G2"])],
        ["G3"],
        [{"from": "group:G1", "to": endpoint, "title": "uses"}],
    )
    queue = RetryQueue()
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    result = await merge(
        llm, queue, group_links={(GROUPS[0].id, GROUPS[1].id): Counter({"call": 1})}
    )
    assert await queue.drain() == 0
    assert llm.calls == 1
    assert not result.fallback and not result.titles
    assert {c.name for c in result.components} == {"Orders", "Storage"}
    assert result.direct_groups == [GROUPS[2].id]


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
        ({"import"}, "imports"),
        ({"call", "import"}, "calls"),
        ({"inherit", "call", "import"}, "inherits from"),
    ],
)
def test_fallback_titles(kinds, title):
    assert fallback_title(kinds) == title


def test_fingerprint_follows_the_titles_prompt(monkeypatch):
    refs = [("call", "db/store.py")]
    before = relation_fingerprint("a", "b", refs)
    assert before == relation_fingerprint("a", "b", refs)
    monkeypatch.setattr(merge_module, "load_c4_prompt", lambda step: "another prompt")
    assert before != relation_fingerprint("a", "b", refs)


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
        pending={"fp": title_request({"call": 1})},
        llm=llm,
        retries=queue,
    )
    assert result == {}
    assert await queue.drain() == 0
    assert result == {"fp": "bewaart via"}
    assert llm.calls == 2


async def test_titles_prompt_names_what_the_relation_connects(
    c4_llm_manager, scripted
):
    seen = []

    def respond(prompt):
        seen.append(data(prompt))
        return {"titles": [{"fingerprint": "fp", "title": "bewaart bestellingen in"}]}

    scripted.answers["titles"] = respond
    result = await title_relations(
        container=CONTAINER.id,
        pending={"fp": title_request({"call": 2})},
        llm=C4Llm(c4_llm_manager, concurrency=1, trial=False),
        retries=RetryQueue(),
    )
    assert result == {"fp": "bewaart bestellingen in"}
    assert seen[0]["relations"] == [
        {
            "fingerprint": "fp",
            "from": {"name": "Orders", "description": "Handles orders."},
            "to": {"name": "Storage", "description": "Keeps data."},
            "kinds": {"call": 2},
            "targets": ["db/store.py"],
        }
    ]


async def test_titles_prompt_too_large_or_refused_falls_back_and_goes_on(
    c4_llm_manager, scripted, monkeypatch
):
    pending = {"fp": title_request({"call": 1})}
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    scripted.answers["titles"] = RuntimeError("input_too_large")
    queue = RetryQueue()
    result = await title_relations(
        container=CONTAINER.id, pending=pending, llm=llm, retries=queue
    )
    assert await queue.drain() == 1
    assert result == {"fp": "calls"}
    assert llm.calls == 1

    # Too large even without targets: no call at all, with the reason in the report.
    monkeypatch.setattr(
        llm, "input_limit", lambda role: InputLimit(max_chars=10, max_tokens=None)
    )
    queue = RetryQueue()
    result = await title_relations(
        container=CONTAINER.id, pending=pending, llm=llm, retries=queue
    )
    assert await queue.drain() == 1
    assert result == {"fp": "calls"}
    assert llm.calls == 1
    assert "input too large" in "\n".join(llm.report_lines())


async def test_titles_timeout_fallback_and_trial(c4_llm_manager, scripted):
    scripted.answers["titles"] = TimeoutError("unavailable")
    queue = RetryQueue()
    pending = {"fp": title_request({"import": 2, "inherit": 1})}
    result = await title_relations(
        container=CONTAINER.id,
        pending=pending,
        llm=C4Llm(c4_llm_manager, concurrency=1, trial=False),
        retries=queue,
    )
    assert await queue.drain() == 1
    assert result == {"fp": "inherits from"}
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
        [{"from": "component:E1", "to": "container", "title": "imports"}],
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
    assert result.titles == {("component:orders", CONTAINER.id): "imports"}


@pytest.mark.parametrize("mode", ["reverse", "self", "blank", "duplicate"])
async def test_merge_drops_unsupported_normalized_pairs(c4_llm_manager, scripted, mode):
    row = {"from": "group:G1", "to": "group:G2", "title": "uses"}
    if mode == "reverse":
        row["from"], row["to"] = row["to"], row["from"]
    elif mode == "self":
        row["to"] = row["from"]
    elif mode == "blank":
        row["title"] = ""
    titles = [row, {**row, "title": "second"}] if mode == "duplicate" else [row]
    scripted.answers["merge"] = answer(
        [component("Orders", ["G1"]), component("Storage", ["G2"])],
        ["G3"],
        titles,
    )
    queue = RetryQueue()
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    result = await merge(
        llm, queue, group_links={(GROUPS[0].id, GROUPS[1].id): Counter({"call": 1})}
    )
    assert await queue.drain() == 0
    assert llm.calls == 1
    assert not result.fallback
    keys = {c.name: c.key for c in result.components}
    assert result.titles == (
        {(keys["Orders"], keys["Storage"]): "uses"} if mode == "duplicate" else {}
    )


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

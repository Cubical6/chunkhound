"""Classification voting, cost boundaries and delayed failure recovery."""

import asyncio
import json
import random
from typing import Any

import pytest
from pydantic import BaseModel

from chunkhound.code_mapper.c4.classify import ClassifyItem, classify, tally
from chunkhound.code_mapper.c4.llm import C4Llm, RetryQueue, TransientStepError
from chunkhound.code_mapper.c4.model import LockedClassification
from chunkhound.llm_manager import LLMManager
from tests.code_mapper.c4.conftest import ScriptedLLM
from tests.code_mapper.c4.test_lockfile import sample_lock


def answer(**values: str) -> dict[str, Any]:
    return {
        "classifications": [
            {"key": key, "value": value} for key, value in values.items()
        ]
    }


def items_from_prompt(prompt: str) -> list[dict[str, Any]]:
    return json.loads(prompt.split("\nItems:\n", 1)[1])


@pytest.mark.parametrize(
    ("votes", "expected", "markers"),
    [
        (["storage_driver"] * 3, "storage_driver", ()),
        (["library", "library", "storage_driver"], "library", ("disputed",)),
        (["library", "external_system", "storage_driver"], "library", ("disputed",)),
        (["library", None, "external_system"], "library", ("disputed",)),
        (["storage_driver", None, "storage_driver"], "storage_driver", ()),
        (["external_system", "storage_driver", None], "library", ("disputed",)),
    ],
)
def test_dependency_vote_tally(votes, expected, markers) -> None:
    assert tally(votes, default="library") == (expected, markers)


async def test_override_wins(c4_llm_manager: LLMManager, scripted: ScriptedLLM) -> None:
    lock = sample_lock()
    lock.classifications["requests"] = LockedClassification(
        value="external_system", votes=["external_system"] * 3, markers=[]
    )
    lock.overrides.classifications["requests"] = "storage_driver"
    llm = C4Llm(c4_llm_manager, concurrency=3, trial=False)
    result = await classify(
        [ClassifyItem("requests", "dependency", {})],
        llm=llm,
        lock=lock,
        retries=RetryQueue(),
    )
    assert result["requests"].value == "storage_driver"
    assert result["requests"].votes == ()
    assert llm.calls == 0
    assert not scripted.calls


async def test_locked_classification_skips_call(c4_llm_manager: LLMManager) -> None:
    lock = sample_lock()
    lock.classifications["requests"] = LockedClassification(
        value="library",
        votes=["library", "storage_driver", "library"],
        markers=["disputed"],
    )
    llm = C4Llm(c4_llm_manager, concurrency=3, trial=False)
    result = await classify(
        [ClassifyItem("requests", "dependency", {})],
        llm=llm,
        lock=lock,
        retries=RetryQueue(),
    )
    assert result["requests"].value == "library"
    assert result["requests"].votes == ("library", "storage_driver", "library")
    assert result["requests"].markers == ("disputed",)
    assert not result["requests"].fallback
    assert llm.calls == 0


@pytest.mark.parametrize("manager_present", [True, False])
async def test_classify_trial_makes_no_calls(c4_llm_manager, manager_present) -> None:
    llm = C4Llm(
        c4_llm_manager if manager_present else None,
        concurrency=3,
        trial=manager_present,
    )
    queue = RetryQueue()
    result = await classify(
        [
            ClassifyItem("requests", "dependency", {}),
            ClassifyItem("web", "container", {}),
            ClassifyItem("db", "storage", {}),
        ],
        llm=llm,
        lock=None,
        retries=queue,
    )
    assert {key: value.value for key, value in result.items()} == {
        "requests": "library",
        "web": "no",
        "db": "no",
    }
    assert all(
        value.markers == ("not_classified", "trial") for value in result.values()
    )
    assert all(not value.fallback for value in result.values())
    assert await queue.drain() == 0
    assert llm.calls == 0
    with pytest.raises(RuntimeError, match="trial"):
        await llm.call("classify", BaseModel, "unused", provider="utility")


async def test_three_bundled_shuffled_rounds(c4_llm_manager, scripted) -> None:
    items = [
        ClassifyItem(str(i), "dependency", {"description": f"Package {i}"})
        for i in range(6)
    ]
    seen = []

    def respond(prompt):
        batch = items_from_prompt(prompt)
        seen.append(batch)
        return answer(**{item["key"]: "storage_driver" for item in batch})

    scripted.answers["classify"] = respond
    llm = C4Llm(c4_llm_manager, concurrency=3, trial=False)
    queue = RetryQueue()
    result = await classify(items, llm=llm, lock=None, retries=queue, seed=12)
    assert llm.calls == 3
    for round_index, batch in enumerate(seen):
        expected = list(items)
        random.Random(12 + round_index).shuffle(expected)
        assert [item["key"] for item in batch] == [item.key for item in expected]
        assert {item["key"]: item["facts"] for item in batch} == {
            item.key: item.facts for item in items
        }
    assert all(
        value.value == "storage_driver"
        and value.votes == ("storage_driver",) * 3
        and not value.markers
        for value in result.values()
    )
    assert await queue.drain() == 0


async def test_failed_round_uses_remaining_votes(c4_llm_manager, scripted) -> None:
    replies = iter(
        [answer(requests="storage_driver"), TimeoutError(), answer(requests="library")]
    )

    def respond(prompt):
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    scripted.answers["classify"] = respond
    queue = RetryQueue()
    result = await classify(
        [ClassifyItem("requests", "dependency", {})],
        llm=C4Llm(c4_llm_manager, concurrency=3, trial=False),
        lock=None,
        retries=queue,
    )
    assert result["requests"].value == "library"
    assert result["requests"].votes == ("storage_driver", None, "library")
    assert result["requests"].markers == ("disputed",)
    assert await queue.drain() == 0


async def test_delayed_retry_repeats_bundled_vote_operation(
    c4_llm_manager, scripted
) -> None:
    scripted.answers["classify"] = TimeoutError()
    llm = C4Llm(c4_llm_manager, concurrency=3, trial=False)
    queue = RetryQueue()
    result = await classify(
        [ClassifyItem("requests", "dependency", {}), ClassifyItem("db", "storage", {})],
        llm=llm,
        lock=None,
        retries=queue,
    )
    assert llm.calls == 3  # Delayed until the rest of the pipeline has run.
    scripted.answers["classify"] = answer(requests="storage_driver", db="yes")
    assert await queue.drain() == 0
    assert llm.calls == 6  # Three bundled retry rounds, not three per candidate.
    assert result["requests"].value == "storage_driver"
    assert result["requests"].votes == ("storage_driver",) * 3
    assert result["db"].value == "yes"
    assert result["db"].votes == ("yes",) * 3
    assert all(not item.fallback for item in result.values())
    assert await queue.drain() == 0
    assert llm.calls == 6


@pytest.mark.parametrize(
    "bad_answer",
    [
        {"classifications": []},
        {"classifications": [{"key": "requests", "value": "library"}] * 2},
        answer(requests="library", extra="library"),
        answer(requests="yes"),
        answer(requests="invented"),
        {"unexpected": []},
    ],
)
async def test_invalid_rounds_retry_then_fall_back(
    c4_llm_manager, scripted, bad_answer
) -> None:
    scripted.answers["classify"] = bad_answer
    llm = C4Llm(c4_llm_manager, concurrency=3, trial=False)
    queue = RetryQueue()
    result = await classify(
        [ClassifyItem("requests", "dependency", {})], llm=llm, lock=None, retries=queue
    )
    assert llm.calls == 3
    assert await queue.drain() == 1
    assert llm.calls == 6
    assert result["requests"].value == "library"
    assert result["requests"].votes == (None,) * 3
    assert result["requests"].markers == ("not_classified", "fallback")
    assert result["requests"].fallback


async def test_all_timeouts_fallback_per_item(c4_llm_manager, scripted) -> None:
    scripted.answers["classify"] = TimeoutError()
    queue = RetryQueue()
    llm = C4Llm(c4_llm_manager, concurrency=3, trial=False)
    result = await classify(
        [ClassifyItem("requests", "dependency", {}), ClassifyItem("db", "storage", {})],
        llm=llm,
        lock=None,
        retries=queue,
    )
    assert await queue.drain() == 2
    assert result["requests"].value == "library"
    assert result["db"].value == "no"
    assert all(item.fallback for item in result.values())
    assert llm.calls == 6


@pytest.mark.parametrize("delayed", [False, True])
async def test_non_transient_errors_propagate(
    c4_llm_manager, scripted, delayed
) -> None:
    scripted.answers["classify"] = (
        TimeoutError() if delayed else ValueError("bad config")
    )
    llm = C4Llm(c4_llm_manager, concurrency=3, trial=False)
    queue = RetryQueue()
    if delayed:
        await classify(
            [ClassifyItem("requests", "dependency", {})],
            llm=llm,
            lock=None,
            retries=queue,
        )
        scripted.answers["classify"] = ValueError("bad config")
        with pytest.raises(ValueError, match="bad config"):
            await queue.drain()
    else:
        with pytest.raises(ValueError, match="bad config"):
            await classify(
                [ClassifyItem("requests", "dependency", {})],
                llm=llm,
                lock=None,
                retries=queue,
            )


async def test_retry_queue_applies_once_and_only_recovers_transient_errors() -> None:
    queue = RetryQueue()
    applied = []

    async def recover():
        return "recovered"

    async def fail():
        raise TransientStepError("timeout")

    queue.defer(
        "good",
        recover,
        lambda: "wrong",
        lambda result, fallback: applied.append((result, fallback)),
    )
    queue.defer(
        "bad",
        fail,
        lambda: "fallback",
        lambda result, fallback: applied.append((result, fallback)),
    )
    assert await queue.drain() == 1
    assert applied == [("recovered", False), ("fallback", True)]
    assert await queue.drain() == 0
    assert len(applied) == 2


async def test_llm_jobs_limit_is_shared_across_steps(
    c4_llm_manager, scripted, monkeypatch
) -> None:
    class Response(BaseModel):
        value: str

    active = 0
    peak = 0

    async def respond(**kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"value": "ok"}

    monkeypatch.setattr(scripted, "complete_structured", respond)
    llm = C4Llm(c4_llm_manager, concurrency=2, trial=False)
    await asyncio.gather(
        *(
            llm.call("classify", Response, "prompt", provider=provider)
            for provider in ("utility", "synthesis") * 3
        )
    )
    assert peak == 2
    assert llm.calls == 6


async def test_mixed_candidates_only_send_unknown_keys(
    c4_llm_manager, scripted
) -> None:
    lock = sample_lock()
    lock.overrides.classifications["requests"] = "storage_driver"
    seen = []
    replies = iter(
        [
            answer(web="yes", db="yes"),
            answer(web="no", db="yes"),
            answer(web="no", db="yes"),
        ]
    )

    def respond(prompt):
        seen.append({item["key"] for item in items_from_prompt(prompt)})
        return next(replies)

    scripted.answers["classify"] = respond
    llm = C4Llm(c4_llm_manager, concurrency=3, trial=False)
    result = await classify(
        [
            ClassifyItem("requests", "dependency", {}),
            ClassifyItem("web", "container", {}),
            ClassifyItem("db", "storage", {}),
        ],
        llm=llm,
        lock=lock,
        retries=RetryQueue(),
    )
    assert seen == [{"web", "db"}] * 3
    assert result["requests"].value == "storage_driver"
    assert result["db"].value == "yes"
    assert not result["db"].markers
    assert result["web"].value == "no"
    assert result["web"].markers == ("disputed",)


async def test_trial_reuses_lock_and_overrides(c4_llm_manager) -> None:
    lock = sample_lock()
    lock.classifications["requests"] = LockedClassification(
        value="external_system", votes=["external_system"] * 3, markers=[]
    )
    lock.overrides.classifications["db"] = "yes"
    llm = C4Llm(c4_llm_manager, concurrency=3, trial=True)
    result = await classify(
        [
            ClassifyItem("requests", "dependency", {}),
            ClassifyItem("db", "storage", {}),
            ClassifyItem("web", "container", {}),
        ],
        llm=llm,
        lock=lock,
        retries=RetryQueue(),
    )
    assert result["requests"].value == "external_system"
    assert result["requests"].votes == ("external_system",) * 3
    assert result["db"].value == "yes"
    assert not result["db"].markers
    assert result["web"].value == "no"
    assert result["web"].markers == ("not_classified", "trial")
    assert llm.calls == 0

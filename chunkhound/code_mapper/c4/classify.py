"""Three bundled votes classify only candidates absent from the scope lock."""

import asyncio
import json
import random
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from chunkhound.code_mapper.c4.llm import (
    AnswerRejectedError,
    C4Llm,
    RetryQueue,
    StepReport,
    TransientStepError,
    load_c4_prompt,
)
from chunkhound.code_mapper.c4.model import Marker, ScopeLock


@dataclass(frozen=True)
class ClassifyItem:
    key: str
    question: Literal["dependency", "container", "storage"]
    facts: dict[str, Any]


@dataclass(frozen=True)
class Classification:
    value: str
    votes: tuple[str | None, ...]
    markers: tuple[Marker, ...]
    fallback: bool


class _Vote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    value: Literal["library", "external_system", "storage_driver", "yes", "no"]


class _ClassifyAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classifications: list[_Vote]


def tally(
    votes: Sequence[str | None], *, default: str
) -> tuple[str, tuple[Marker, ...]]:
    """Ignore failed rounds; ties use the question's conservative default."""
    counts = Counter(vote for vote in votes if vote is not None)
    if not counts:
        return default, ()
    leaders = [
        value for value, count in counts.items() if count == max(counts.values())
    ]
    value = leaders[0] if len(leaders) == 1 else default
    return value, ("disputed",) if len(counts) > 1 else ()


def _default(item: ClassifyItem, *, trial: bool = False) -> Classification:
    return Classification(
        value="library" if item.question == "dependency" else "no",
        votes=(None, None, None),
        markers=("not_classified", "trial" if trial else "fallback"),
        fallback=not trial,
    )


def _known(item: ClassifyItem, lock: ScopeLock | None) -> Classification | None:
    if lock is None:
        return None
    if item.key in lock.overrides.classifications:
        return Classification(lock.overrides.classifications[item.key], (), (), False)
    if item.key in lock.classifications:
        cached = lock.classifications[item.key]
        return Classification(
            cached.value, tuple(cached.votes), tuple(cached.markers), False
        )
    return None


def _validate(answer: _ClassifyAnswer, items: Sequence[ClassifyItem]) -> dict[str, str]:
    counts = Counter(vote.key for vote in answer.classifications)
    if counts != Counter(item.key for item in items):
        raise AnswerRejectedError(
            "classify: every candidate key must occur exactly once"
        )
    values: dict[str, str] = {vote.key: vote.value for vote in answer.classifications}
    for item in items:
        allowed = (
            {"library", "external_system", "storage_driver"}
            if item.question == "dependency"
            else {"yes", "no"}
        )
        if values[item.key] not in allowed:
            raise AnswerRejectedError("classify: invalid candidate vote")
    return values


async def _round(
    items: Sequence[ClassifyItem],
    llm: C4Llm,
    template: str,
    seed: int,
    report: StepReport,
) -> dict[str, str]:
    shuffled = list(items)
    random.Random(seed).shuffle(shuffled)
    prompt = template + "\nItems:\n" + json.dumps([asdict(item) for item in shuffled])
    try:
        with report.attempt():
            answer = await llm.call(
                "classify", _ClassifyAnswer, prompt, provider="utility"
            )
            return _validate(answer, items)
    except TransientStepError:
        return {}


async def _vote(
    items: Sequence[ClassifyItem], llm: C4Llm, seed: int, report: StepReport
) -> dict[str, Classification]:
    template = load_c4_prompt("classify")
    rounds = await asyncio.gather(
        *(_round(items, llm, template, seed + index, report) for index in range(3))
    )
    if not any(rounds):
        raise TransientStepError("classify: all three voting rounds failed")
    result = {}
    for item in items:
        votes = tuple(round_result.get(item.key) for round_result in rounds)
        value, markers = tally(
            votes, default="library" if item.question == "dependency" else "no"
        )
        result[item.key] = Classification(value, votes, markers, False)
    return result


def _defer_item(
    item: ClassifyItem,
    batch: Callable[[], Awaitable[dict[str, Classification]]],
    result: dict[str, Classification],
    retries: RetryQueue,
    report: StepReport,
) -> None:
    async def attempt() -> Classification:
        return (await batch())[item.key]

    def apply(value: Classification, fallback: bool) -> None:
        result[item.key] = value

    retries.defer(
        f"classify:{item.key}", attempt, lambda: _default(item), apply, report=report
    )


def _defer_batch(
    items: Sequence[ClassifyItem],
    llm: C4Llm,
    seed: int,
    result: dict[str, Classification],
    retries: RetryQueue,
    report: StepReport,
) -> None:
    # One retry operation retains three bundled rounds, shared by all candidates.
    task: asyncio.Task[dict[str, Classification]] | None = None

    async def batch() -> dict[str, Classification]:
        nonlocal task
        if task is None:
            task = asyncio.create_task(_vote(items, llm, seed, report))
        return await task

    for item in items:
        _defer_item(item, batch, result, retries, report)


async def classify(
    items: Sequence[ClassifyItem],
    *,
    llm: C4Llm,
    lock: ScopeLock | None,
    retries: RetryQueue,
    seed: int = 0,
) -> dict[str, Classification]:
    """Return known/voted outcomes; drain retries to populate any deferred keys."""
    result: dict[str, Classification] = {}
    pending = []
    for item in items:
        known = _known(item, lock)
        if known is not None:
            result[item.key] = known
        elif llm.trial:
            result[item.key] = _default(item, trial=True)
        else:
            pending.append(item)
    if pending:
        report = llm.report("classify", f"{len(pending)} nieuwe kandidaten")
        try:
            result.update(await _vote(pending, llm, seed, report))
        except TransientStepError:
            _defer_batch(pending, llm, seed, result, retries, report)
    return result

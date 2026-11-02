"""Run one extraction goal over fragments in bounded, reusable bundles."""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, create_model

from chunkhound.services.extraction.budget import (
    InputLimit,
    effective_target,
    fits,
    measure_request,
)
from chunkhound.services.extraction.bundles import pack, select_reusable, split_to_fit
from chunkhound.services.extraction.errors import (
    InputRejectedError,
    ProviderInputRefusedError,
    TransientCallError,
    UnreadableAnswerError,
)
from chunkhound.services.extraction.fragments import MEASURE_FID, Fragment, Numbering
from chunkhound.services.extraction.provider_call import StructuredCall
from chunkhound.services.extraction.store import (
    ExtractionStore,
    ProviderIdentity,
    StoredBundle,
    bundle_key_parts,
    key_from_parts,
)

PartT = TypeVar("PartT")

FRAGMENTS_HEADING = "\n\nFragments:\n\n"


@dataclass(frozen=True)
class Rejected:
    rule: str


class ExtractionGoal(Protocol[PartT]):
    """Application-owned meaning: instructions, schema, validation, storage form."""

    name: str
    version: str  # sha256 over instructions, part schema and validator version
    line_numbering: Numbering

    def instructions(self) -> str: ...

    def part_model(self) -> type[BaseModel]: ...

    def max_completion_tokens(self, bundle_chars: int) -> int: ...

    def validate(self, fragment: Fragment, part: Any) -> PartT | Rejected: ...

    def dump(self, fragment: Fragment, part: PartT) -> dict[str, Any]: ...

    def recheck(
        self, fragment: Fragment, stored: dict[str, Any]
    ) -> PartT | Rejected: ...


@dataclass(frozen=True)
class Valid(Generic[PartT]):
    part: PartT
    from_cache: bool


@dataclass(frozen=True)
class Failed:
    kind: Literal["transient", "rejected"]
    rule: str | None = None


@dataclass
class ExtractionCounts:
    reused: int = 0
    new: int = 0
    split: int = 0


@dataclass(frozen=True)
class AttemptRecord:
    bundle_key: str
    fragments: int
    outcome: Literal["accepted", "rejected", "unreadable", "transient"]
    rule: str | None = None


@dataclass
class ExtractionResult(Generic[PartT]):
    parts: dict[int, Valid[PartT] | Failed] = field(default_factory=dict)
    # Packed (or supplied) bundle key -> indices that failed within it.
    failed_bundles: dict[str, tuple[int, ...]] = field(default_factory=dict)
    counts: ExtractionCounts = field(default_factory=ExtractionCounts)


_ANSWER_MODELS: dict[tuple[str, str], type[BaseModel]] = {}


def answer_model(goal: ExtractionGoal[Any]) -> type[BaseModel]:
    """Fixed per goal: one part per fragment id, part schema owned by the goal."""
    cache_key = (goal.name, goal.version)
    if cache_key not in _ANSWER_MODELS:
        strict = ConfigDict(extra="forbid")
        item = create_model(
            f"{goal.name.title()}FragmentAnswer",
            __config__=strict,
            id=(str, ...),
            part=(goal.part_model(), ...),
        )
        _ANSWER_MODELS[cache_key] = create_model(
            f"{goal.name.title()}BundleAnswer",
            __config__=strict,
            fragments=(list[item], ...),  # type: ignore[valid-type]
        )
    return _ANSWER_MODELS[cache_key]


def build_prompt(goal: ExtractionGoal[Any], fragments: Sequence[Fragment]) -> str:
    rendered = [
        fragment.render(f"F{number}", goal.line_numbering)
        for number, fragment in enumerate(fragments, 1)
    ]
    return goal.instructions() + FRAGMENTS_HEADING + "\n\n".join(rendered)


async def run_extraction(
    goal: ExtractionGoal[PartT],
    fragments: Sequence[Fragment],
    *,
    call: StructuredCall,
    provider: ProviderIdentity,
    limit: InputLimit,
    store: ExtractionStore | None,
    concurrency: int,
    bundles: Sequence[Sequence[int]] | None = None,
    order_hint: Callable[[Fragment], float] | None = None,
    on_attempt: Callable[[AttemptRecord], None] | None = None,
) -> ExtractionResult[PartT]:
    """Reuse first, then pack; validate per fragment; store valid bundles at once.

    Fatal errors cancel running bundles and propagate; bundles validated
    before that moment stay stored.
    """
    if concurrency < 1:
        raise ValueError("Extraction concurrency must be at least one")
    model = answer_model(goal)
    schema = model.model_json_schema()
    instructions = goal.instructions()
    target = effective_target(limit)
    result: ExtractionResult[PartT] = ExtractionResult()

    def measure(indices: Sequence[int]) -> int:
        rendered = [
            fragments[index].render(MEASURE_FID, goal.line_numbering)
            for index in indices
        ]
        return measure_request(instructions + FRAGMENTS_HEADING, schema, rendered)

    if store is not None:
        candidates = [
            bundle
            for bundle in store.candidates()
            if _same_goal(bundle, goal, provider)
        ]
        for reuse in select_reusable(fragments, candidates):
            used = False
            for index, stored in sorted(reuse.assigned.items()):
                checked = goal.recheck(fragments[index], stored)
                if not isinstance(checked, Rejected):
                    result.parts[index] = Valid(checked, from_cache=True)
                    used = True
            if used:
                result.counts.reused += 1
                store.touch(reuse.bundle.key)

    remaining = [index for index in range(len(fragments)) if index not in result.parts]
    if bundles is None:
        groups = pack(remaining, target, measure)
    else:
        wanted = set(remaining)
        groups = [
            piece
            for supplied in bundles
            if (kept := [index for index in supplied if index in wanted])
            for piece in split_to_fit(kept, target, measure)
        ]
    if order_hint is not None:
        hint = order_hint
        groups.sort(key=lambda group: -max(hint(fragments[index]) for index in group))

    semaphore = asyncio.Semaphore(concurrency)
    # After a fatal error no bundle may start a new call or store an outcome.
    stopped = asyncio.Event()

    def key_for(group: Sequence[int], max_tokens: int) -> tuple[str, dict[str, Any]]:
        parts = bundle_key_parts(
            goal=goal.name,
            goal_version=goal.version,
            provider=provider,
            max_completion_tokens=max_tokens,
            members=[fragments[index].identity() for index in group],
        )
        return key_from_parts(parts), parts

    def record(outcome: AttemptRecord) -> None:
        if on_attempt is not None:
            on_attempt(outcome)

    def fail(origin: str, group: Sequence[int], failure: Failed) -> None:
        for index in group:
            result.parts[index] = failure
        result.failed_bundles[origin] = (
            *result.failed_bundles.get(origin, ()),
            *group,
        )

    async def attempt(group: list[int], origin: str | None) -> None:
        members = [fragments[index] for index in group]
        prompt = build_prompt(goal, members)
        max_tokens = goal.max_completion_tokens(len(prompt))
        key, key_parts = key_for(group, max_tokens)
        origin = origin or key
        if not fits(prompt, schema, limit, call.estimate_tokens):
            raise AssertionError(f"Bundle {key} exceeds the input limit after packing")
        bisect = False
        try:
            async with semaphore:
                if stopped.is_set():
                    return
                answer = await call(prompt, model, max_tokens)
        except ProviderInputRefusedError as exc:
            raise InputRejectedError(
                provider.provider, len(prompt), limit.max_chars
            ) from exc
        except UnreadableAnswerError as exc:
            record(AttemptRecord(key, len(group), "unreadable", exc.rule))
            if len(group) == 1:
                fail(origin, group, Failed("rejected", exc.rule))
                return
            bisect = True
        except TransientCallError:
            record(AttemptRecord(key, len(group), "transient"))
            fail(origin, group, Failed("transient"))
            return

        if bisect:
            # Outside the except block: otherwise every later provider error
            # chains to this one and is classified as unreadable too.
            result.counts.split += 1
            middle = len(group) // 2
            await attempt(group[:middle], origin)
            await attempt(group[middle:], origin)
            return
        if stopped.is_set():
            return
        result.counts.new += 1
        by_id: dict[str, list[Any]] = {}
        parsed: Any = answer
        for item in parsed.fragments:
            by_id.setdefault(item.id, []).append(item.part)
        stored: dict[int, dict[str, Any]] = {}
        rejected: list[int] = []
        first_rule: str | None = None
        for position, index in enumerate(group):
            answers = by_id.get(f"F{position + 1}", [])
            if len(answers) != 1:
                checked: Any = Rejected("every fragment id must occur exactly once")
            else:
                checked = goal.validate(fragments[index], answers[0])
            if isinstance(checked, Rejected):
                rejected.append(index)
                first_rule = first_rule or checked.rule
                result.parts[index] = Failed("rejected", checked.rule)
            else:
                result.parts[index] = Valid(checked, from_cache=False)
                stored[position] = goal.dump(fragments[index], checked)
        if store is not None:
            store.put(StoredBundle(key, key_parts, _identities(members), stored))
        if rejected:
            result.failed_bundles[origin] = (
                *result.failed_bundles.get(origin, ()),
                *rejected,
            )
            record(AttemptRecord(key, len(group), "rejected", first_rule))
        else:
            record(AttemptRecord(key, len(group), "accepted"))

    async def guarded(group: list[int]) -> None:
        try:
            await attempt(group, None)
        except BaseException:
            stopped.set()
            raise

    tasks = [asyncio.create_task(guarded(group)) for group in groups]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        stopped.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return result


def _identities(members: Sequence[Fragment]) -> tuple[Any, ...]:
    return tuple(member.identity() for member in members)


def _same_goal(
    bundle: StoredBundle, goal: ExtractionGoal[Any], provider: ProviderIdentity
) -> bool:
    expected = bundle_key_parts(
        goal=goal.name,
        goal_version=goal.version,
        provider=provider,
        max_completion_tokens=0,
        members=(),
    )
    return all(
        bundle.key_parts.get(part) == expected[part]
        for part in ("notation", "goal", "goal_version", "provider")
    )

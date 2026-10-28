"""View projection and bounded, cached, batched labels."""

import json

import pytest

from chunkhound.code_mapper.c4.llm import AnswerRejectedError, C4Llm, RetryQueue
from chunkhound.code_mapper.c4.model import Coverage, Element, MergedArrow, Relation
from chunkhound.code_mapper.c4.summaries import (
    derive_views,
    fallback_label,
    label_arrows,
    summary_key,
)


def element(id, kind, parent=None):
    return Element(
        id=id,
        kind=kind,
        name=id,
        description=None,
        status="found",
        parent=parent,
        markers=[],
        coverage=Coverage(status="none", topics=[]),
    )


def relation(source, target, title="gebruikt"):
    return Relation(
        id=f"{source}->{target}",
        from_id=source,
        to_id=target,
        title=title,
        status="found",
        reference_counts={"call": 1},
        markers=[],
    )


def arrow(id="context:s->x", underlying=None):
    return MergedArrow(
        id=id,
        from_id="s",
        to_id="x",
        view="context",
        label="",
        underlying=underlying or ["r1", "r2"],
        markers=[],
    )


def test_views_preserve_direct_and_nested_relations():
    elements = [
        element("s", "system"),
        element("c", "container", "s"),
        element("d", "container", "s"),
        element("a", "component", "c"),
        element("b", "component", "c"),
        element("e", "component", "d"),
        element("x", "external"),
        element("p", "person"),
        element("store", "storage", "s"),
    ]
    relations = [
        relation("a", "x"),
        relation("s", "x"),
        relation("b", "a"),
        relation("a", "e"),
        relation("p", "c"),
        relation("a", "store"),
    ]
    arrows = {a.id: a for a in derive_views(elements, relations)}
    assert arrows["context:s->x"].underlying == ["a->x", "s->x"]
    assert arrows["containers:c->d"].underlying == ["a->e"]
    assert arrows["components:c:b->a"].underlying == ["b->a"]
    assert arrows["components:c:a->d"].underlying == ["a->e"]
    assert arrows["containers:c->store"].underlying == ["a->store"]
    assert arrows["context:p->s"].underlying == ["p->c"]
    assert "context:s->s" not in arrows
    assert not any(
        a.view == "components:d" and a.from_id == "b" for a in arrows.values()
    )
    assert all(a.label == "" for a in arrows.values())
    assert derive_views(elements[::-1], relations[::-1]) == list(arrows.values())


async def test_merged_arrow_labels(c4_llm_manager, scripted):
    llm = C4Llm(c4_llm_manager, concurrency=2, trial=False)
    single = await label_arrows(
        [arrow(underlying=["r1"])],
        titles_by_relation={"r1": "gebruikt"},
        locked={},
        overrides={},
        llm=llm,
        retries=RetryQueue(),
    )
    assert single[0].label == "gebruikt"
    assert llm.calls == 0

    def answer(prompt):
        data = json.loads(prompt.split("\nInput:\n")[1])
        return {
            "labels": {item["key"]: "verwerkt en bewaart" for item in data["arrows"]}
        }

    scripted.answers["summaries"] = answer
    titles = {"r1": "verwerkt", "r2": "bewaart"}
    arrows = [arrow(), arrow("containers:c->x")]
    result = await label_arrows(
        arrows,
        titles_by_relation=titles,
        locked={},
        overrides={},
        llm=llm,
        retries=RetryQueue(),
    )
    assert [a.label for a in result] == ["verwerkt en bewaart"] * 2
    assert llm.calls == 1
    key = summary_key(titles.items())
    assert key == summary_key(reversed(list(titles.items())))
    assert key != summary_key([("r1", "anders"), ("r2", "bewaart")])
    cached = await label_arrows(
        [arrow()],
        titles_by_relation=titles,
        locked={key: "cache"},
        overrides={},
        llm=llm,
        retries=RetryQueue(),
    )
    assert cached[0].label == "cache"
    assert llm.calls == 1
    manual = await label_arrows(
        [arrow()],
        titles_by_relation=titles,
        locked={key: "cache"},
        overrides={"context:s->x": "handmatig"},
        llm=llm,
        retries=RetryQueue(),
    )
    assert manual[0].label == "handmatig"
    assert llm.calls == 1
    assert fallback_label(["b", "a", "a"]) == "a; b"
    assert len(fallback_label(["a" * 80, "b"])) <= 60


@pytest.mark.parametrize("length", [60, 61, 100])
async def test_single_title_label_is_bounded_without_model_calls(
    c4_llm_manager, length
):
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    title = "a" * length
    relations = [relation("s", "x", title), relation("c", "x", title)]
    titles = {item.id: item.title for item in relations}
    queue = RetryQueue()
    result = await label_arrows(
        [arrow(underlying=list(titles))],
        titles_by_relation=titles,
        locked={},
        overrides={},
        llm=llm,
        retries=queue,
    )
    assert result[0].label == title[:60]
    assert all(item.title == title for item in relations)
    assert all(value == title for value in titles.values())
    assert await queue.drain() == 0
    assert llm.calls == 0


async def test_long_label_rejected_then_retried(c4_llm_manager, scripted):
    seen = []

    def answer(prompt):
        data = json.loads(prompt.split("\nInput:\n")[1])
        seen.append(data)
        return {"labels": {item["key"]: "x" * 61 for item in data["arrows"]}}

    scripted.answers["summaries"] = answer
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    queue = RetryQueue()
    result = await label_arrows(
        [arrow()],
        titles_by_relation={"r1": "a", "r2": "b"},
        locked={},
        overrides={},
        llm=llm,
        retries=queue,
    )
    assert await queue.drain() == 1
    assert result[0].label == "a; b"
    assert result[0].markers == ["fallback"]
    assert llm.calls == 2
    # The step's schema rejects overlong labels at the public LLM boundary.
    from chunkhound.code_mapper.c4.summaries import SummariesAnswer

    with pytest.raises(AnswerRejectedError):
        await llm.call(
            "summaries",
            SummariesAnswer,
            "C4 step: summaries\nInput:\n" + json.dumps(seen[0]),
            provider="utility",
        )


async def test_trial_labels_make_no_calls_or_deferred_retries():
    queue = RetryQueue()
    llm = C4Llm(None, concurrency=1, trial=True)
    result = await label_arrows(
        [arrow()],
        titles_by_relation={"r1": "a", "r2": "b"},
        locked={},
        overrides={},
        llm=llm,
        retries=queue,
    )
    assert result[0].label == "a; b"
    assert result[0].markers == ["trial"]
    assert await queue.drain() == 0
    assert llm.calls == 0

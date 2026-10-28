"""Documentation evidence must be literal, scoped and reusable without a model."""

import hashlib
from dataclasses import asdict

import pytest

from chunkhound.code_mapper.c4.documented import (
    DocumentedAnswer,
    TopicSources,
    check_documented_answer,
    doc_files_for,
    extract_documented,
    verify_quote,
)
from chunkhound.code_mapper.c4.llm import AnswerRejectedError, C4Llm, RetryQueue
from chunkhound.code_mapper.c4.model import LockedDocumented

QUOTE = "Een beheerder gebruikt de webwinkel via Stripe."


def citation(quote=QUOTE, file="README.md", start_line=3, end_line=3):
    return dict(file=file, start_line=start_line, end_line=end_line, quote=quote)


def answer(quote=QUOTE):
    return {
        "elements": [dict(kind="person", term="beheerder", citation=citation(quote))],
        "relations": [
            dict(
                from_term="beheerder",
                to_term="webwinkel",
                title="gebruikt",
                citation=citation(quote),
            )
        ],
    }


def test_documented_quote_must_exist(fixture_repo):
    with pytest.raises(AnswerRejectedError):
        check_documented_answer(
            DocumentedAnswer.model_validate(answer("Webdashboard")),
            fixture_repo,
            ["README.md"],
        )
    elements, relations = check_documented_answer(
        DocumentedAnswer.model_validate(answer()), fixture_repo, ["README.md"]
    )
    assert [(item.kind, item.term) for item in elements] == [("person", "beheerder")]
    assert elements[0].citation.verified
    assert elements[0].citation.source == "documentation"
    assert elements[0].citation.target is None  # Identity is assigned after extraction.
    assert [(item.from_term, item.to_term, item.title) for item in relations] == [
        ("beheerder", "webwinkel", "gebruikt")
    ]
    assert relations[0].citation.verified
    assert relations[0].citation.source == "documentation"


async def test_documented_discards_invalid_items(
    fixture_repo, c4_llm_manager, scripted
):
    payload = answer()
    payload["elements"].append(
        dict(kind="external", term="Webdashboard", citation=citation("Webdashboard"))
    )
    payload["relations"].append(
        dict(
            from_term="beheerder",
            to_term="Webdashboard",
            title="gebruikt",
            citation=citation("Webdashboard"),
        )
    )
    scripted.answers["documented"] = payload
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    retries = RetryQueue()
    result = await extract_documented(
        project_root=fixture_repo,
        doc_files=["README.md"],
        locked=None,
        llm=llm,
        retries=retries,
    )
    assert [item.term for item in result.elements] == ["beheerder"]
    assert [item.to_term for item in result.relations] == ["webwinkel"]
    assert not result.fallback
    assert await retries.drain() == 0
    assert llm.calls == 1


async def test_documented_reuses_on_same_hashes(fixture_repo, c4_llm_manager, scripted):
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    first = await extract_documented(
        project_root=fixture_repo,
        doc_files=["README.md"],
        locked=None,
        llm=llm,
        retries=RetryQueue(),
    )
    assert {item.term for item in first.elements} == {"beheerder", "Stripe"}
    assert first.hashes == {
        "README.md": hashlib.sha256(
            (fixture_repo / "README.md").read_bytes()
        ).hexdigest()
    }
    locked = LockedDocumented(
        hashes=first.hashes,
        elements=[asdict(item) for item in first.elements],
        relations=[asdict(item) for item in first.relations],
    )
    # Citation is a Pydantic model nested in the dataclass.
    locked = LockedDocumented.model_validate_json(locked.model_dump_json())
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    cached = await extract_documented(
        project_root=fixture_repo,
        doc_files=["README.md"],
        locked=locked,
        llm=llm,
        retries=RetryQueue(),
    )
    assert llm.calls == 0
    assert cached == first
    (fixture_repo / "README.md").write_text("# Changed\n", encoding="utf-8")
    scripted.answers["documented"] = {"elements": [], "relations": []}
    changed = await extract_documented(
        project_root=fixture_repo,
        doc_files=["README.md"],
        locked=locked,
        llm=llm,
        retries=RetryQueue(),
    )
    assert llm.calls == 1
    assert changed.elements == changed.relations == []
    assert changed.hashes != first.hashes
    removed = await extract_documented(
        project_root=fixture_repo,
        doc_files=[],
        locked=locked,
        llm=llm,
        retries=RetryQueue(),
    )
    assert removed.elements == removed.relations == []
    assert removed.hashes == {}


@pytest.mark.parametrize("has_lock", [False, True])
async def test_documented_fallback_after_retry(
    fixture_repo, c4_llm_manager, scripted, has_lock
):
    elements, relations = check_documented_answer(
        DocumentedAnswer.model_validate(answer()), fixture_repo, ["README.md"]
    )
    locked = (
        LockedDocumented(
            hashes={"README.md": "previous-hash"},
            elements=[asdict(item) for item in elements],
            relations=[asdict(item) for item in relations],
        )
        if has_lock
        else None
    )
    scripted.answers["documented"] = answer("Webdashboard")
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    retries = RetryQueue()
    result = await extract_documented(
        project_root=fixture_repo,
        doc_files=["README.md"],
        locked=locked,
        llm=llm,
        retries=retries,
    )
    assert not result.fallback
    assert await retries.drain() == 1
    assert llm.calls == 2
    assert result.fallback
    assert result.elements == (elements if has_lock else [])
    assert result.relations == (relations if has_lock else [])


async def test_documented_retry_can_recover(fixture_repo, c4_llm_manager, scripted):
    scripted.answers["documented"] = TimeoutError("temporarily unavailable")
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    retries = RetryQueue()
    result = await extract_documented(
        project_root=fixture_repo,
        doc_files=["README.md"],
        locked=None,
        llm=llm,
        retries=retries,
    )
    scripted.answers["documented"] = answer()
    assert await retries.drain() == 0
    assert [item.term for item in result.elements] == ["beheerder"]
    assert not result.fallback
    assert llm.calls == 2


async def test_documented_trial_and_no_documents_make_no_calls(fixture_repo):
    llm = C4Llm(None, concurrency=1, trial=True)
    retries = RetryQueue()
    for files in (["README.md"], []):
        result = await extract_documented(
            project_root=fixture_repo,
            doc_files=files,
            locked=None,
            llm=llm,
            retries=retries,
        )
        assert result.elements == result.relations == []
    assert llm.calls == await retries.drain() == 0


def test_doc_files_for_uses_scope_readmes_and_topic_markdown(tmp_path):
    for file in (
        "README.md",
        "scope/README",
        "scope/README.md",
        "scope/docs/guide.md",
        "scope/docs/unrelated.md",
        "scope/code.py",
        "scope/docs/README.md",
    ):
        path = tmp_path / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content", encoding="utf-8")
    (tmp_path / "scope/README-directory").mkdir()
    topics = [
        TopicSources("Usage", ("scope/docs/guide.md", "scope/code.py", "missing.md")),
        TopicSources("Repeated", ("scope/docs/guide.md",)),
    ]
    assert doc_files_for(tmp_path, tmp_path / "scope", topics) == [
        "scope/README",
        "scope/README.md",
        "scope/docs/guide.md",
    ]


def test_verify_quote_normalizes_whitespace_but_respects_lines(tmp_path):
    (tmp_path / "README.md").write_text(
        "Heading\nEen  beheerder\n gebruikt Stripe.\n", encoding="utf-8"
    )
    assert verify_quote(tmp_path, "README.md", 2, 3, "Een beheerder gebruikt\tStripe.")
    for start, end, quote in (
        (1, 1, "Een beheerder"),
        (2, 2, "gebruikt Stripe."),
        (0, 3, "Heading"),
        (3, 2, "Stripe."),
        (1, 4, "Heading"),
        (1, 3, " \t"),
    ):
        assert not verify_quote(tmp_path, "README.md", start, end, quote)
    assert not verify_quote(tmp_path, "missing.md", 1, 1, "Heading")


def test_documented_cannot_cite_unprovided_or_outside_files(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (tmp_path / "outside.md").write_text(QUOTE, encoding="utf-8")
    (root / "unprovided.md").write_text(QUOTE, encoding="utf-8")
    (root / "linked.md").symlink_to(tmp_path / "outside.md")
    for file in ("../outside.md", "linked.md", str(tmp_path / "outside.md")):
        assert not verify_quote(root, file, 1, 1, QUOTE)
    payload = answer()
    payload["elements"][0]["citation"] = citation(
        file="unprovided.md", start_line=1, end_line=1
    )
    payload["relations"] = []
    with pytest.raises(AnswerRejectedError):
        check_documented_answer(
            DocumentedAnswer.model_validate(payload), root, ["README.md"]
        )
    assert (
        doc_files_for(
            root, root, [TopicSources("Escapes", ("../outside.md", "linked.md"))]
        )
        == []
    )

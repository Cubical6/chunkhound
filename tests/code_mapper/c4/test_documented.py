"""Documentation evidence must be literal, scoped and reusable without a model."""

import hashlib
import json
from dataclasses import asdict

import jsonschema
import pytest

from chunkhound.code_mapper.c4.documented import (
    EXTRACTION_CACHE,
    DocElement,
    DocRelation,
    TopicSources,
    doc_files_for,
    extract_documented,
    report_lines,
    verify_quote,
)
from chunkhound.code_mapper.c4.llm import C4Llm, RetryQueue
from chunkhound.code_mapper.c4.model import Citation, LockedDocumented
from chunkhound.core.config.c4_config import C4Config
from chunkhound.core.config.config import Config
from chunkhound.llm_manager import LLMManager
from chunkhound.services.extraction.errors import InputRejectedError
from tests.code_mapper.c4.conftest import (
    component_answer,
    documented_fragments,
    write_sections,
)

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


def verified_citation():
    return Citation(
        target=None,
        file="README.md",
        start_line=3,
        end_line=3,
        source="documentation",
        verified=True,
    )


async def test_documented_citations_are_verified_documentation_evidence(
    fixture_repo, c4_llm_manager, scripted
):
    scripted.answers["documented"] = answer()
    llm = C4Llm(c4_llm_manager, concurrency=1, trial=False)
    outcome = await extract_documented(
        project_root=fixture_repo,
        doc_files=["README.md"],
        locked=None,
        llm=llm,
        retries=RetryQueue(),
    )
    assert outcome.elements == [
        DocElement("person", "beheerder", verified_citation())
    ]
    assert outcome.relations == [
        DocRelation("beheerder", "webwinkel", "gebruikt", verified_citation())
    ]
    # Identity is assigned after extraction.
    assert outcome.elements[0].citation.target is None


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
    elements = [DocElement("person", "beheerder", verified_citation())]
    relations = [DocRelation("beheerder", "webwinkel", "gebruikt", verified_citation())]
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
    assert doc_files_for(tmp_path, tmp_path / "scope", topics, None) == [
        "scope/README",
        "scope/README.md",
        "scope/docs/guide.md",
    ]


def test_changelog_and_hidden_directories_are_no_documentation_source(tmp_path):
    kept = ["docs/guide.md", "docs/news-site/Overview.md"]
    history = [
        "CHANGELOG.md",
        "docs/Changes.md",
        "docs/history.md",
        "docs/NEWS.md",
        "docs/release_notes_4.md",
        "docs/releases.md",
        "docs/migration-guide.md",
        "docs/Upgrading.md",
    ]
    hidden = [".superpowers/design.md", "docs/.drafts/idea.md"]
    test_docs = ["tests/guide.md", "docs/fixtures/guide.md"]
    files = [*kept, *history, *hidden, *test_docs]
    for file in files:
        path = tmp_path / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content", encoding="utf-8")
    topics = [TopicSources("All", tuple(files))]
    assert doc_files_for(tmp_path, tmp_path, topics, None) == sorted(kept)
    # Only the test rules have a switch.
    config = Config.model_construct(c4=C4Config(exclude_test_code=False))
    assert doc_files_for(tmp_path, tmp_path, topics, config) == sorted(
        [*kept, *test_docs]
    )


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


def test_documented_sources_stay_inside_the_project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (tmp_path / "outside.md").write_text(QUOTE, encoding="utf-8")
    (root / "linked.md").symlink_to(tmp_path / "outside.md")
    for file in ("../outside.md", "linked.md", str(tmp_path / "outside.md")):
        assert not verify_quote(root, file, 1, 1, QUOTE)
    assert (
        doc_files_for(
            root,
            root,
            [TopicSources("Escapes", ("../outside.md", "linked.md"))],
            None,
        )
        == []
    )


# --- Bounded, resumable extraction over fragments (shared extraction layer) ---


@pytest.fixture
def limited_manager(monkeypatch, scripted):
    """A low input limit forces several bundles for one document."""
    monkeypatch.setattr(LLMManager, "_create_provider", lambda self, config: scripted)
    config = {"provider": "fake", "model": "fake-gpt", "max_input_chars": 16_000}
    return LLMManager(utility_config=config, synthesis_config=config)


async def run_documented(repo, manager, files, *, locked=None, trial=False):
    llm = C4Llm(manager, concurrency=1, trial=trial)
    retries = RetryQueue()
    outcome = await extract_documented(
        project_root=repo, doc_files=files, locked=locked, llm=llm, retries=retries
    )
    fallbacks = await retries.drain()
    return outcome, llm, fallbacks


def cited_lines(repo, outcome):
    lines = (repo / "docs/arch.md").read_text(encoding="utf-8").splitlines()
    return {
        element.term: (
            element.citation.start_line,
            lines[element.citation.start_line - 1],
        )
        for element in outcome.elements
    }


async def test_documented_covers_every_line_or_marks_fallback(
    fixture_repo, limited_manager, scripted
):
    write_sections(fixture_repo / "docs/arch.md")
    scripted.answers["documented"] = lambda prompt: component_answer(prompt, reject=3)

    outcome, llm, fallbacks = await run_documented(
        fixture_repo, limited_manager, ["docs/arch.md"]
    )

    assert llm.calls >= 4  # several bundles, then one recovery attempt
    assert fallbacks == 1
    assert {e.term for e in outcome.elements} == {
        f"Component{n}" for n in range(12) if n != 3
    }
    [(path, start, end)] = outcome.fallback_fragments
    lines = (fixture_repo / "docs/arch.md").read_text().splitlines()
    assert path == "docs/arch.md"
    assert any("Component3 " in line for line in lines[start - 1 : end])
    assert outcome.fallback and not outcome.fallback_citations


async def test_insert_at_top_reuses_and_shifts_citations(
    fixture_repo, limited_manager, scripted
):
    doc = fixture_repo / "docs/arch.md"
    write_sections(doc)
    scripted.answers["documented"] = component_answer
    first, first_llm, _ = await run_documented(
        fixture_repo, limited_manager, ["docs/arch.md"]
    )
    before = cited_lines(fixture_repo, first)
    lines = doc.read_text(encoding="utf-8").splitlines()
    heading = lines.index("## Sectie 1")
    lines.insert(heading + 1, "Een nieuwe zin bovenaan sectie 1.")
    doc.write_text("\n".join(lines) + "\n", encoding="utf-8")

    second, second_llm, _ = await run_documented(
        fixture_repo, limited_manager, ["docs/arch.md"]
    )

    after = cited_lines(fixture_repo, second)
    assert first_llm.calls >= 3
    assert 1 <= second_llm.calls < first_llm.calls
    assert second.counts is not None and second.counts.reused >= 1
    assert set(after) == set(before)
    for term, (line, text) in after.items():
        assert term in text  # every citation points at its own sentence
        expected = before[term][0] + (1 if term != "Component0" else 0)
        assert line == expected


async def test_cached_outcome_with_stale_quote_is_not_reused(
    fixture_repo, c4_llm_manager
):
    first, _, _ = await run_documented(fixture_repo, c4_llm_manager, ["README.md"])
    [entry] = (fixture_repo / EXTRACTION_CACHE / "documented").glob("*.json")
    data = json.loads(entry.read_text())
    for part in data["parts"].values():
        for item in [*part["elements"], *part["relations"]]:
            item["citation"]["quote"] = "Verzonnen citaat"
    entry.write_text(json.dumps(data), encoding="utf-8")

    second, llm, _ = await run_documented(fixture_repo, c4_llm_manager, ["README.md"])

    assert llm.calls == 1
    assert second.elements == first.elements
    assert second.relations == first.relations


async def test_trial_makes_no_calls_and_no_cache_writes(fixture_repo, c4_llm_manager):
    await run_documented(fixture_repo, c4_llm_manager, ["README.md"])
    cache = fixture_repo / EXTRACTION_CACHE
    before = {p: p.stat().st_mtime_ns for p in cache.rglob("*") if p.is_file()}
    (fixture_repo / "README.md").write_text("# Changed\n", encoding="utf-8")

    _, llm, fallbacks = await run_documented(
        fixture_repo, c4_llm_manager, ["README.md"], trial=True
    )

    assert llm.calls == fallbacks == 0
    after = {p: p.stat().st_mtime_ns for p in cache.rglob("*") if p.is_file()}
    assert after == before


async def test_duplicate_items_are_merged_once(fixture_repo, c4_llm_manager, scripted):
    payload = answer()
    payload["elements"] *= 2
    payload["relations"] *= 2
    scripted.answers["documented"] = payload

    outcome, _, _ = await run_documented(fixture_repo, c4_llm_manager, ["README.md"])

    assert [e.term for e in outcome.elements] == ["beheerder"]
    assert [r.to_term for r in outcome.relations] == ["webwinkel"]


def invalid_json_error():
    try:
        json.loads("geen json")
    except json.JSONDecodeError as exc:
        return RuntimeError(f"Invalid JSON in structured output: {exc}")
    raise AssertionError("unreachable")


def fails_first_with(error, then=component_answer):
    """The first call raises `error`; later calls answer through `then`."""
    state = {"calls": 0}

    def handler(prompt):
        state["calls"] += 1
        if state["calls"] == 1:
            raise error
        return then(prompt)

    return handler


@pytest.mark.parametrize(
    "error",
    [
        invalid_json_error(),
        RuntimeError("Structured output truncated - increase max_completion_tokens"),
        RuntimeError("LLM response truncated - token limit exceeded"),
        RuntimeError("LLM structured completion truncated - token limit exceeded"),
        RuntimeError("Gemini response truncated - token limit exceeded"),
        RuntimeError("Gemini structured completion truncated - token limit exceeded"),
        RuntimeError("LLM response incomplete - token limit exceeded"),
    ],
)
async def test_unreadable_answer_halves_and_reports_the_split(
    fixture_repo, limited_manager, scripted, error
):
    write_sections(fixture_repo / "docs/arch.md")
    scripted.answers["documented"] = fails_first_with(error)

    outcome, _, fallbacks = await run_documented(
        fixture_repo, limited_manager, ["docs/arch.md"]
    )

    assert fallbacks == 0 and not outcome.fallback
    assert {e.term for e in outcome.elements} == {f"Component{n}" for n in range(12)}
    assert "1 gesplitst" in report_lines(outcome)[0]


@pytest.mark.parametrize(
    "text",
    [
        "codex exec failed (exit 1): error: input_too_large max_chars: 1048576",
        "LLM structured completion failed: input_too_large",
    ],
)
async def test_input_refusal_stops_with_size_and_limit(
    fixture_repo, c4_llm_manager, scripted, text
):
    scripted.answers["documented"] = RuntimeError(text)

    with pytest.raises(InputRejectedError, match="opgegeven grens"):
        await run_documented(fixture_repo, c4_llm_manager, ["README.md"])

    assert scripted.calls["documented"] == 1


async def test_fatal_error_after_a_split_stops_the_run(
    fixture_repo, limited_manager, scripted
):
    write_sections(fixture_repo / "docs/arch.md")
    state = {"calls": 0}

    def handler(prompt):
        state["calls"] += 1
        if state["calls"] == 1:
            raise invalid_json_error()
        raise RuntimeError("codex exec failed (exit 1): 401 unauthorized")

    scripted.answers["documented"] = handler

    with pytest.raises(RuntimeError, match="401"):
        await run_documented(fixture_repo, limited_manager, ["docs/arch.md"])

    assert state["calls"] == 2


async def test_input_refusal_after_a_split_stays_a_refusal(
    fixture_repo, limited_manager, scripted
):
    write_sections(fixture_repo / "docs/arch.md")
    state = {"calls": 0}

    def handler(prompt):
        state["calls"] += 1
        if state["calls"] == 1:
            raise invalid_json_error()
        raise RuntimeError("codex exec failed (exit 1): error: input_too_large")

    scripted.answers["documented"] = handler

    with pytest.raises(InputRejectedError):
        await run_documented(fixture_repo, limited_manager, ["docs/arch.md"])


async def test_temporary_error_after_a_split_is_reported_as_temporary(
    fixture_repo, limited_manager, scripted
):
    write_sections(fixture_repo / "docs/arch.md")
    state = {"calls": 0}

    def handler(prompt):
        state["calls"] += 1
        if state["calls"] == 1:
            raise invalid_json_error()
        if state["calls"] == 2:
            raise RuntimeError("rate limit 429")
        return component_answer(prompt)

    scripted.answers["documented"] = handler

    outcome, llm, fallbacks = await run_documented(
        fixture_repo, limited_manager, ["docs/arch.md"]
    )

    report = next(line for line in llm.report_lines() if "C4 documented" in line)
    assert "#2 tijdelijke fout" in report
    assert fallbacks == 0 and not outcome.fallback


def schema_failure_quoting_document(prompt):
    """The real text of a CLI provider's schema failure, which quotes the answer."""
    try:
        jsonschema.validate(
            {"quote": "Codex geeft input_too_large bij te grote aanvragen."},
            {"type": "object", "required": ["end_line"]},
        )
    except jsonschema.ValidationError as exc:
        raise RuntimeError(f"LLM structured completion failed: {exc}") from exc
    raise AssertionError("unreachable")


def pydantic_failure_quoting_document(prompt):
    return {
        "fragments": [
            {
                "id": "F1",
                "part": {
                    "elements": [
                        {
                            "kind": "input_too_large",
                            "term": "x",
                            "citation": {
                                "start_line": 1,
                                "end_line": 1,
                                "quote": "input_too_large",
                            },
                        }
                    ],
                    "relations": [],
                },
            }
        ]
    }


@pytest.mark.parametrize(
    "handler", [schema_failure_quoting_document, pydantic_failure_quoting_document]
)
async def test_marker_in_model_output_is_no_input_refusal(
    fixture_repo, c4_llm_manager, scripted, handler
):
    (fixture_repo / "docs").mkdir(exist_ok=True)
    (fixture_repo / "docs/limit.md").write_text(
        "# Limiet\n\nCodex geeft input_too_large bij te grote aanvragen.\n",
        encoding="utf-8",
    )
    scripted.answers["documented"] = handler

    outcome, _, fallbacks = await run_documented(
        fixture_repo, c4_llm_manager, ["docs/limit.md"]
    )

    assert fallbacks == 1 and outcome.fallback
    assert scripted.calls["documented"] == 2


async def test_citation_must_lie_inside_its_own_fragment(
    fixture_repo, limited_manager, scripted
):
    """A quote that exists elsewhere in the document does not count."""
    write_sections(fixture_repo / "docs/arch.md")
    neighbour = "Component1 verwerkt verzoeken."

    def handler(prompt):
        fragments = []
        for fid, (_path, lines) in documented_fragments(prompt).items():
            forged = any("Component0 " in line for line in lines)
            elements = [
                {
                    "kind": "component",
                    "term": "Component1",
                    "citation": {
                        "start_line": 1,
                        "end_line": len(lines),
                        "quote": neighbour,
                    },
                }
            ]
            fragments.append(
                {
                    "id": fid,
                    "part": {
                        "elements": elements if forged else [],
                        "relations": [],
                    },
                }
            )
        return {"fragments": fragments}

    scripted.answers["documented"] = handler

    outcome, _, fallbacks = await run_documented(
        fixture_repo, limited_manager, ["docs/arch.md"]
    )

    assert outcome.elements == []
    assert fallbacks == 1
    [(_, start, end)] = outcome.fallback_fragments
    lines = (fixture_repo / "docs/arch.md").read_text().splitlines()
    assert any("Component0 " in line for line in lines[start - 1 : end])


async def test_non_utf8_source_passes_trial_and_fails_clearly_in_a_real_run(
    fixture_repo, c4_llm_manager
):
    (fixture_repo / "README.rst").write_bytes(b"caf\xe9\n")

    outcome, llm, _ = await run_documented(
        fixture_repo, c4_llm_manager, ["README.rst"], trial=True
    )
    assert llm.calls == 0
    assert outcome.hashes == {"README.rst": hashlib.sha256(b"caf\xe9\n").hexdigest()}

    with pytest.raises(ValueError, match="not valid UTF-8: README.rst"):
        await run_documented(fixture_repo, c4_llm_manager, ["README.rst"])

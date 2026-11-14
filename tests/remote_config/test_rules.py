"""Public-contract unit tests for the remote-config rules module.

Scope kept narrow per AGENTS.md `TESTING_PHILOSOPHY`: only the two public
contracts the pipeline (and reviewers) depend on directly are locked here.

- ENCLOSING_SUB_MODEL: the path→BaseModel map. Its correctness is invisible
  from higher-level tests, but the `X | None` unwrapping bug it protects
  against would silently break per-rule sub-model validation for
  ``embedding.*``, ``llm.*``, and ``remote_config.*``.
- ``parse_path``: user-facing rule authoring accepts multiple syntaxes;
  a regression here silently changes rule matching.
"""

from __future__ import annotations

import typing

import pytest
from pydantic import BaseModel

from chunkhound.core.config.config import Config
from chunkhound.core.config.embedding_config import EmbeddingConfig
from chunkhound.core.config.llm_config import LLMConfig
from chunkhound.core.config.mcp_config import MCPConfig
from chunkhound.core.config.remote.rules import (
    ENCLOSING_SUB_MODEL,
    _check_payload_keys,
    _predicate_matches,
    _resolve_path_model,
    _unwrap_optional_basemodel,
    parse_path,
)
from chunkhound.core.config.remote_config import RemoteConfig


class TestEnclosingSubModelMap:
    def test_optional_fields_unwrap_to_basemodel(self) -> None:
        # The bug-prone cases: `X | None` must resolve to `X`, not `UnionType`.
        assert ENCLOSING_SUB_MODEL["embedding"] is EmbeddingConfig
        assert ENCLOSING_SUB_MODEL["llm"] is LLMConfig
        assert ENCLOSING_SUB_MODEL["remote_config"] is RemoteConfig

    def test_required_field_binds_directly(self) -> None:
        assert ENCLOSING_SUB_MODEL["mcp"] is MCPConfig

    def test_scalar_fields_omitted(self) -> None:
        # `debug: bool` etc. are not BaseModels and must not appear here.
        assert "debug" not in ENCLOSING_SUB_MODEL
        assert "target_dir" not in ENCLOSING_SUB_MODEL


class TestParsePath:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("a.b.c", ["a", "b", "c"]),
            ("a/b/c", ["a", "b", "c"]),
            (".a.b", ["a", "b"]),
            ("/a/b", ["a", "b"]),
            ("mcp.host", ["mcp", "host"]),
            ("embedding.api_key", ["embedding", "api_key"]),
        ],
    )
    def test_accepted_forms(self, text: str, expected: list[str]) -> None:
        assert parse_path(text) == expected

    @pytest.mark.parametrize("bad", ["", "..a", "a..b", "/", "."])
    def test_rejects_empty_or_double_separators(self, bad: str) -> None:
        with pytest.raises(ValueError):
            parse_path(bad)


class TestPredicateMatches:
    def test_none_predicates_match(self) -> None:
        assert _predicate_matches(None, Config()) == (True, None)

    def test_unknown_key_returns_schema_error(self) -> None:
        # Typo like "wehn" or "existng" must produce an operator-visible
        # signal, not a silent skip — see module docstring rationale.
        matches, err = _predicate_matches({"wehn": "linux"}, Config())
        assert matches is False
        assert err is not None
        assert "wehn" in err

    def test_os_mismatch_is_silent_miss(self) -> None:
        matches, err = _predicate_matches(
            {"os": "definitely-not-a-real-platform"}, Config()
        )
        assert (matches, err) == (False, None)


def test_config_tree_is_validated_at_every_model_depth() -> None:
    """Tripwire for depth-agnostic rule-id and payload-key validation.

    Every real nested BaseModel must be reachable, accept its known fields,
    and reject an unknown key via both rule ids and ancestor payloads.
    If the config tree gains an unsupported shape:
    1. Extend both walkers without treating arbitrary dict keys as fields.
    2. Add a pipeline_e2e contract test for that shape before relaxing this
       guard (including operator-visible schema_error and no mutation).
    """

    def walk(model: type[BaseModel], prefix: list[str]) -> None:
        assert _resolve_path_model(prefix) == (model, None)
        typo = "__unknown_config_field__"
        assert typo not in model.model_fields
        bad_path = [*prefix, typo]
        assert _resolve_path_model(bad_path)[1] == ".".join(bad_path)

        # Exercise payload traversal from every ancestor, not just the target.
        payload: typing.Any = {typo: None}
        for depth in range(len(prefix), -1, -1):
            ancestor, error = _resolve_path_model(prefix[:depth])
            assert error is None and ancestor is not None
            assert _check_payload_keys(ancestor, payload, prefix[:depth]) == (
                ".".join(bad_path)
            )
            if depth:
                payload = {prefix[depth - 1]: payload}

        for name, info in model.model_fields.items():
            nested = _unwrap_optional_basemodel(info.annotation)
            path = [*prefix, name]
            assert _resolve_path_model(path) == (nested, None)
            assert _check_payload_keys(model, {name: None}, prefix) is None
            if nested is not None:
                walk(nested, path)

    walk(Config, [])


def test_config_has_no_ambiguous_basemodel_unions() -> None:
    """Tripwire for ambiguous ``BaseModel`` unions in the Config tree.

    ``_unwrap_optional_basemodel`` and ``_build_enclosing_map`` both pick
    the *first* ``BaseModel`` candidate in a union. That's safe only while
    no field is typed as ``A | B`` where both are ``BaseModel`` subclasses
    — if one appears, per-rule sub-model validation silently binds to one
    schema and ignores the other. If this test fails, extend the walker
    in ``remote/rules.py`` to refuse ambiguous unions rather than
    silently picking a candidate.
    """
    violations: list[str] = []

    def walk(model: type[BaseModel], prefix: str) -> None:
        for name, info in model.model_fields.items():
            candidates = typing.get_args(info.annotation) or (info.annotation,)
            models = [
                c
                for c in candidates
                if isinstance(c, type) and issubclass(c, BaseModel)
            ]
            if len(models) > 1:
                violations.append(f"{prefix}{name}: {[m.__name__ for m in models]}")
            elif len(models) == 1:
                walk(models[0], f"{prefix}{name}.")

    walk(Config, "")

    assert not violations, (
        "Config tree gained an ambiguous BaseModel union — the walker in "
        "remote/rules.py silently picks the first candidate and would "
        "validate rules against the wrong schema. Extend the walker to "
        f"reject rather than pick: {violations}"
    )

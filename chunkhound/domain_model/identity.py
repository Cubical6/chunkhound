"""Stable ASCII identities for domain elements and derived role constraints."""

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Literal

from chunkhound.domain_model.model import GroundValue
from chunkhound.utils.text import slugify_kebab


class EmptyKeyError(ValueError):
    code = "empty_key"


class InvalidReferenceError(ValueError):
    code = "invalid_reference"


def key_segment(text: str) -> str:
    normalized = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )
    key = slugify_kebab(normalized, ascii_only=True, fallback="")
    if not key:
        raise EmptyKeyError(f"Expected a nonempty ASCII key from {text!r}")
    return key


def repository_key(repository: str) -> str:
    return "root" if repository == "." else key_segment(repository)


def concept_id(repository: str, term: str) -> str:
    return f"concept:{repository_key(repository)}/{key_segment(term)}"


def fact_type_id(repository: str, name: str) -> str:
    return f"fact_type:{repository_key(repository)}/{key_segment(name)}"


def _fact_key(fact_type: str) -> str:
    kind, repository, segments = parse_id(fact_type)
    if kind != "fact_type":
        raise InvalidReferenceError(f"Expected a fact_type id, got {fact_type!r}")
    return f"{repository}/{segments[0]}"


def role_id(fact_type: str, name: str) -> str:
    return f"role:{_fact_key(fact_type)}/{key_segment(name)}"


def validation_rule_id(
    fact_type: str,
    rule_kind: Literal["uniqueness", "subset", "value", "other"],
    roles: Iterable[str] = (),
    *,
    name: str | None = None,
) -> str:
    """Build a rule id from role names (not role ids)."""
    if rule_kind == "other":
        suffix = key_segment(name or "")
    elif rule_kind in {"uniqueness", "subset", "value"}:
        keys = sorted(key_segment(role) for role in roles)
        if not keys or (rule_kind == "value" and len(keys) != 1):
            raise ValueError(f"Invalid roles for {rule_kind}: {keys!r}")
        suffix = "+".join(keys)
    else:
        raise ValueError(f"Unsupported stored rule kind: {rule_kind!r}")
    return f"validation_rule:{_fact_key(fact_type)}/{rule_kind}/{suffix}"


def mandatory_rule_id(fact_type: str, role: str) -> str:
    return f"validation_rule:{_fact_key(fact_type)}/mandatory/{key_segment(role)}"


def datatype_rule_id(fact_type: str, role: str) -> str:
    return f"validation_rule:{_fact_key(fact_type)}/datatype/{key_segment(role)}"


def derivation_rule_id(repository: str, name: str) -> str:
    return f"derivation_rule:{repository_key(repository)}/{key_segment(name)}"


def exchange_rule_id(repository: str, name: str) -> str:
    return f"exchange_rule:{repository_key(repository)}/{key_segment(name)}"


def event_rule_id(repository: str, name: str) -> str:
    return f"event_rule:{repository_key(repository)}/{key_segment(name)}"


def ground_fact_hash(
    values: Mapping[str, GroundValue], violates: Iterable[str] = ()
) -> str:
    payload = json.dumps(
        {"values": dict(values), "violates": sorted(violates)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def ground_fact_id(
    fact_type: str,
    values: Mapping[str, GroundValue],
    violates: Iterable[str] = (),
) -> str:
    return f"ground_fact:{_fact_key(fact_type)}/{ground_fact_hash(values, violates)}"


def parse_id(identifier: str) -> tuple[str, str, tuple[str, ...]]:
    """Parse a canonical §6.2 id, including derived role constraints."""
    kind, separator, key = identifier.partition(":")
    parts = key.split("/")
    arities = {
        "concept": 2,
        "fact_type": 2,
        "role": 3,
        "validation_rule": 4,
        "derivation_rule": 2,
        "exchange_rule": 2,
        "event_rule": 2,
        "ground_fact": 3,
    }
    valid = bool(separator) and len(parts) == arities.get(kind, 0)
    segment_pattern = r"[a-z0-9]+(?:-[a-z0-9]+)*"
    if valid:
        ordinary = parts[:-1] if kind == "validation_rule" else parts
        valid = all(re.fullmatch(segment_pattern, part) for part in ordinary)
    if valid and kind == "ground_fact":
        valid = re.fullmatch(r"[0-9a-f]{12}", parts[-1]) is not None
    if valid and kind == "validation_rule":
        rule_kind, suffix = parts[-2:]
        if rule_kind in {"uniqueness", "subset", "value"}:
            roles = suffix.split("+")
            valid = (
                all(re.fullmatch(segment_pattern, role) for role in roles)
                and roles == sorted(roles)
                and (rule_kind != "value" or len(roles) == 1)
            )
        else:
            valid = rule_kind in {"other", "mandatory", "datatype"} and bool(
                re.fullmatch(segment_pattern, suffix)
            )
    if not valid:
        raise InvalidReferenceError(
            f"Expected a canonical domain id, got {identifier!r}"
        )
    return kind, parts[0], tuple(parts[1:])

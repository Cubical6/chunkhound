"""Strict, path-addressed loading and deterministic domain contract serialization."""

import json
import re
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from types import UnionType
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel, ValidationError

from chunkhound.domain_model import identity
from chunkhound.domain_model.issues import Issue, ModelLoadError
from chunkhound.domain_model.model import (
    SCHEMA_VERSION,
    Concept,
    DerivationRule,
    DomainModel,
    EventRule,
    ExchangeRule,
    FactType,
    GroundFact,
    Role,
    ValidationRule,
)

Element = (
    Concept
    | FactType
    | Role
    | ValidationRule
    | DerivationRule
    | ExchangeRule
    | EventRule
    | GroundFact
)
COLLECTIONS = (
    "concepts",
    "fact_types",
    "roles",
    "validation_rules",
    "derivation_rules",
    "exchange_rules",
    "event_rules",
    "ground_facts",
)


def _json_path(loc: tuple[str | int, ...]) -> str:
    """Follow the contract types so union branch labels are not JSON keys."""
    annotation: Any = DomainModel
    path = ""
    for part in loc:
        origin = get_origin(annotation)
        if origin in (UnionType, Union):
            choices = [
                choice for choice in get_args(annotation) if choice is not type(None)
            ]
            if len(choices) > 1:
                annotation = next(
                    (
                        choice
                        for choice in choices
                        if getattr(choice, "__name__", None) == part
                    ),
                    Any,
                )
                continue
            annotation = choices[0]
            origin = get_origin(annotation)
        path += f"[{part}]" if isinstance(part, int) else ("." if path else "") + part
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            field = annotation.model_fields.get(str(part))
            annotation = field.annotation if field else Any
        elif origin in (tuple, list):
            annotation = get_args(annotation)[0]
        elif origin in (dict, Mapping):
            annotation = get_args(annotation)[1]
        else:
            annotation = Any
    return path


def parse_model(data: object) -> DomainModel:
    """Validate schema first, then shape, then all cross-element invariants."""
    if (
        not isinstance(data, dict)
        or type(data.get("schema_version")) is not int
        or data["schema_version"] != SCHEMA_VERSION
    ):
        raise ModelLoadError(
            (
                Issue(
                    "schema_version",
                    "unsupported_schema_version",
                    f"Expected schema_version {SCHEMA_VERSION}",
                ),
            )
        )
    try:
        model = DomainModel.model_validate(data)
    except ValidationError as exc:
        issues = []
        seen: set[tuple[str, str]] = set()
        for error in exc.errors():
            loc = error["loc"]
            code = {"missing": "missing_field", "extra_forbidden": "unknown_field"}.get(
                error["type"], "invalid_value"
            )
            if (
                loc
                and loc[-1] == "rule_kind"
                and error.get("input") in ("mandatory", "datatype")
            ):
                code = "derived_rule_kind"
            path = _json_path(loc)
            if (path, code) not in seen:
                issues.append(Issue(path, code, error["msg"]))
                seen.add((path, code))
        raise ModelLoadError(issues) from exc
    issues = _model_issues(model)
    if issues:
        raise ModelLoadError(issues)
    return model


def load_model(path: Path) -> DomainModel:
    """Read UTF-8 JSON, translating file and decoding failures to load issues."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ModelLoadError((Issue("", "invalid_json", str(exc)),)) from exc
    return parse_model(data)


def _model_issues(model: DomainModel) -> list[Issue]:
    issues: list[Issue] = []
    entries: list[tuple[str, Element]] = [
        (f"{collection}[{index}]", element)
        for collection in COLLECTIONS
        for index, element in enumerate(getattr(model, collection))
    ]
    by_id = {element.id: element for _, element in entries}
    seen: set[str] = set()
    derived = {
        function(role.fact_type, role.name)
        for role in model.roles
        for function, enabled in (
            (identity.mandatory_rule_id, role.mandatory is True),
            (identity.datatype_rule_id, role.datatype is not None),
        )
        if enabled and _valid_fact_reference(role.fact_type) and _has_key(role.name)
    }

    def add(path: str, code: str, message: str) -> None:
        issues.append(Issue(path, code, message))

    def reference(
        path: str, value: str, kinds: set[str], *, allow_derived: bool = False
    ) -> None:
        try:
            kind, _, _ = identity.parse_id(value)
        except identity.InvalidReferenceError as exc:
            add(path, "invalid_reference", str(exc))
            return
        if kind not in kinds:
            add(
                path,
                "invalid_reference",
                f"Expected one of {sorted(kinds)}, got {kind}",
            )
        elif value not in by_id and not (allow_derived and value in derived):
            add(path, "dangling_reference", f"No element with id {value!r}")

    for path, element in entries:
        issue_start = len(issues)
        id_failure: str | None = None
        if element.id in seen:
            add(path + ".id", "duplicate_id", f"Duplicate id {element.id!r}")
        seen.add(element.id)
        try:
            expected = _expected_id(element)
        except identity.EmptyKeyError as exc:
            field = "term" if isinstance(element, Concept) else "name"
            try:
                identity.repository_key(element.repository)
            except identity.EmptyKeyError:
                field = "repository"
            add(path + "." + field, "empty_key", str(exc))
        except ValueError as exc:
            # Prefer the specific reference/shape issue below, but never lose a failure.
            id_failure = str(exc)
        else:
            if element.id != expected:
                add(path + ".id", "id_mismatch", f"Expected {expected!r}")
        try:
            _, repository, _ = identity.parse_id(element.id)
        except identity.InvalidReferenceError:
            add(path + ".id", "id_mismatch", "Expected a canonical element id")
        else:
            if repository != element.repository:
                add(
                    path + ".repository",
                    "id_mismatch",
                    f"Expected repository {repository!r}",
                )
        if not element.citations and not element.human_sources:
            add(
                path, "missing_source", "Expected at least one citation or human source"
            )
        if element.status == "confirmed" and not any(
            source.op == "confirm"
            or (source.op == "put" and source.put_status == "confirmed")
            for source in element.human_sources
        ):
            add(
                path + ".status",
                "confirmed_without_human_source",
                "Expected a confirm or confirmed put human source",
            )
        citations = [
            (f"{path}.citations[{i}]", c) for i, c in enumerate(element.citations)
        ]
        if isinstance(element, (FactType, Role)):
            for i, binding in enumerate(element.bindings):
                binding_path = f"{path}.bindings[{i}].citation"
                citations.append((binding_path, binding.citation))
                if binding.citation not in element.citations:
                    add(
                        binding_path,
                        "binding_citation_missing",
                        "Binding citation must also occur in citations",
                    )
        for citation_path, citation in citations:
            if citation.start_line < 1 or citation.end_line < citation.start_line:
                add(
                    citation_path,
                    "invalid_line_range",
                    "Expected 1 <= start_line <= end_line",
                )

        single_refs: dict[str, set[str]] = {}
        list_refs: dict[str, set[str]] = {}
        if isinstance(element, (Role, ValidationRule, GroundFact)):
            single_refs["fact_type"] = {"fact_type"}
        if isinstance(element, FactType):
            single_refs["identifies"] = {"concept"}
            list_refs["roles"] = {"role"}
            role_names = [
                role.name
                for role_id in element.roles
                if isinstance(role := by_id.get(role_id), Role)
            ]
            for i, template in enumerate(element.templates):
                placeholders = re.findall(r"<([^<>]*)>", template)
                if Counter(placeholders) != Counter(role_names) or len(
                    set(placeholders)
                ) != len(placeholders):
                    add(
                        f"{path}.templates[{i}]",
                        "template_role_mismatch",
                        f"Expected each role exactly once: {role_names!r}",
                    )
            for i, role_id in enumerate(element.roles):
                role = by_id.get(role_id)
                if isinstance(role, Role) and role.fact_type != element.id:
                    add(
                        f"{path}.roles[{i}]",
                        "role_mismatch",
                        "Role must belong to this fact type",
                    )
            if element.status == "confirmed" and not any(
                fact.fact_type == element.id and not fact.violates
                for fact in model.ground_facts
            ):
                add(
                    path + ".status",
                    "confirmed_without_ground_fact",
                    "Expected a valid ground fact for confirmed fact type",
                )
        if isinstance(element, Role):
            single_refs["concept"] = {"concept"}
            parent = by_id.get(element.fact_type)
            if isinstance(parent, FactType) and element.id not in parent.roles:
                add(
                    path + ".fact_type",
                    "role_mismatch",
                    "Fact type must list this role",
                )
            if any(char in element.name for char in "<>\r\n"):
                add(
                    path + ".name",
                    "invalid_value",
                    "Role names cannot contain angle brackets or newlines",
                )
        if isinstance(element, ValidationRule):
            single_refs["superset_fact_type"] = {"fact_type"}
            list_refs.update(roles={"role"}, superset_roles={"role"})
            malformed = (
                (element.rule_kind == "uniqueness" and not element.roles)
                or (element.rule_kind == "value" and len(element.roles) != 1)
                or (
                    element.rule_kind == "subset"
                    and (
                        not element.roles
                        or not element.superset_fact_type
                        or len(element.roles) != len(element.superset_roles)
                    )
                )
                or (
                    element.rule_kind == "other"
                    and (not element.name or not element.statement)
                )
            )
            if malformed:
                add(
                    path,
                    "rule_shape",
                    "Expected roles for uniqueness, one role for value, matching "
                    "subset roles and superset, or name and statement for other",
                )
        if isinstance(element, DerivationRule):
            list_refs["derives"] = {"fact_type", "role"}
            list_refs["uses"] = {
                "concept",
                "fact_type",
                "role",
                "validation_rule",
                "derivation_rule",
                "exchange_rule",
                "event_rule",
                "ground_fact",
            }
        if isinstance(element, ExchangeRule):
            list_refs["fact_types"] = {"fact_type"}
        if isinstance(element, EventRule):
            list_refs["starts"] = {"exchange_rule", "derivation_rule"}
        if isinstance(element, GroundFact):
            list_refs["violates"] = {"validation_rule"}
            parent = by_id.get(element.fact_type)
            if isinstance(parent, FactType):
                names = {r.name for r in model.roles if r.id in parent.roles}
                for name in element.values:
                    if name not in names:
                        add(
                            path + ".values." + name,
                            "unknown_role",
                            f"Expected a role name from {sorted(names)!r}",
                        )
        for field, kinds in single_refs.items():
            value = getattr(element, field)
            if value is not None:
                reference(path + "." + field, value, kinds)
        for field, kinds in list_refs.items():
            for i, value in enumerate(getattr(element, field)):
                reference(
                    f"{path}.{field}[{i}]",
                    value,
                    kinds,
                    allow_derived=field == "violates",
                )
        if id_failure is not None and len(issues) == issue_start:
            add(path + ".id", "id_mismatch", id_failure)
    return issues


def _valid_fact_reference(value: str) -> bool:
    try:
        return identity.parse_id(value)[0] == "fact_type"
    except identity.InvalidReferenceError:
        return False


def _has_key(value: str) -> bool:
    try:
        identity.key_segment(value)
        return True
    except identity.EmptyKeyError:
        return False


def _expected_id(element: Element) -> str:
    if isinstance(element, Concept):
        return identity.concept_id(element.repository, element.term)
    if isinstance(element, FactType):
        return identity.fact_type_id(element.repository, element.name)
    if isinstance(element, Role):
        return identity.role_id(element.fact_type, element.name)
    if isinstance(element, ValidationRule):
        names = []
        for role in element.roles:
            kind, _, segments = identity.parse_id(role)
            if kind != "role":
                raise identity.InvalidReferenceError("Expected a role id")
            names.append(segments[-1])
        return identity.validation_rule_id(
            element.fact_type, element.rule_kind, names, name=element.name
        )
    if isinstance(element, GroundFact):
        return identity.ground_fact_id(
            element.fact_type, element.values, element.violates
        )
    functions = {
        DerivationRule: identity.derivation_rule_id,
        ExchangeRule: identity.exchange_rule_id,
        EventRule: identity.event_rule_id,
    }
    return functions[type(element)](element.repository, element.name)


def dump_model(model: DomainModel) -> str:
    """Serialize in contract field order without reordering positional lists."""
    data: dict[str, Any] = {"schema_version": model.schema_version}
    base_fields = {"id", "repository", "status", "citations", "human_sources"}
    for collection in COLLECTIONS:
        serialized = []
        for element in sorted(getattr(model, collection), key=lambda item: item.id):
            raw = element.model_dump(mode="json")
            own_fields = [
                field
                for field in type(element).model_fields
                if field not in base_fields
            ]
            ordered = {
                field: raw[field]
                for field in (
                    "id",
                    "repository",
                    *own_fields,
                    "status",
                    "citations",
                    "human_sources",
                )
            }
            if "values" in ordered:
                ordered["values"] = dict(sorted(ordered["values"].items()))
            serialized.append(ordered)
        data[collection] = serialized
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"

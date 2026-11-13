"""Append-only human input: request contract, final-state checks and replay."""

import json
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Annotated, Any, Literal, Protocol, TypeAlias
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from chunkhound.domain_model import identity
from chunkhound.domain_model.issues import Issue
from chunkhound.domain_model.loader import (
    COLLECTIONS,
    rule_shape_issues,
    template_issues,
    validation_issues,
)
from chunkhound.domain_model.model import (
    Concept,
    DerivationRule,
    DomainModel,
    EntryPoint,
    EventRule,
    ExchangeRule,
    FactType,
    GroundFact,
    GroundValue,
    HumanSource,
    Role,
    ValidationRule,
)

PutStatus: TypeAlias = Literal["proposed", "confirmed"]

# Serialize read/validate/append across all in-process write callers.
_WRITE_LOCK = Lock()


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class _PutBody(_FrozenModel):
    status: PutStatus = "proposed"


class _RepositoryBody(_PutBody):
    repository: str = "."


class PutConcept(_RepositoryBody):
    kind: Literal["concept"]
    term: str
    plural: str | None = None
    definition: str | None = None
    synonyms: tuple[str, ...] = ()


class InlineRole(_FrozenModel):
    name: str
    concept: str | None = None
    datatype: str | None = None
    mandatory: bool | None = None


class PutFactType(_RepositoryBody):
    kind: Literal["fact_type"]
    name: str
    templates: tuple[str, ...] = Field(min_length=1)
    roles: tuple[InlineRole, ...]
    identifies: str | None = None


class PutValidationRule(_PutBody):
    kind: Literal["validation_rule"]
    fact_type: str
    rule_kind: Literal["uniqueness", "subset", "value", "other"]
    roles: tuple[str, ...] = ()
    superset_fact_type: str | None = None
    superset_roles: tuple[str, ...] = ()
    allowed_values: tuple[str, ...] = ()
    name: str | None = None
    statement: str | None = None


class PutDerivationRule(_RepositoryBody):
    kind: Literal["derivation_rule"]
    name: str
    statement: str
    derives: tuple[str, ...] = ()
    uses: tuple[str, ...] = ()


class PutExchangeRule(_RepositoryBody):
    kind: Literal["exchange_rule"]
    name: str
    statement: str
    operations: tuple[Literal["add", "change", "remove"], ...] = Field(min_length=1)
    fact_types: tuple[str, ...] = ()


class PutEventRule(_RepositoryBody):
    kind: Literal["event_rule"]
    name: str
    statement: str
    event: str = ""
    starts: tuple[str, ...] = ()


class PutGroundFact(_PutBody):
    kind: Literal["ground_fact"]
    fact_type: str
    values: dict[str, GroundValue]
    violates: tuple[str, ...] = ()


PutBody: TypeAlias = Annotated[
    PutConcept
    | PutFactType
    | PutValidationRule
    | PutDerivationRule
    | PutExchangeRule
    | PutEventRule
    | PutGroundFact,
    Field(discriminator="kind"),
]


class PutOp(_FrozenModel):
    op: Literal["put"]
    element: PutBody


class ConfirmOp(_FrozenModel):
    op: Literal["confirm"]
    id: str


class UnconfirmOp(_FrozenModel):
    op: Literal["unconfirm"]
    id: str


class DeleteOp(_FrozenModel):
    op: Literal["delete"]
    id: str


Operation: TypeAlias = Annotated[
    PutOp | ConfirmOp | UnconfirmOp | DeleteOp, Field(discriminator="op")
]


class WriteRequest(_FrozenModel):
    operations: list[Operation] = Field(min_length=1, max_length=500)


class Author(_FrozenModel):
    name: str
    email: str | None = None


class ElementResult(_FrozenModel):
    id: str
    kind: str
    status: PutStatus


class WriteResult(_FrozenModel):
    batch_id: str
    dry_run: bool
    records: tuple[int, ...]
    elements: tuple[ElementResult, ...]
    warnings: tuple[Issue, ...]


class Judgement(_FrozenModel):
    id: str
    confirmed: bool
    human_sources: tuple[HumanSource, ...]


class HumanInputView(_FrozenModel):
    model: DomainModel
    judgements: tuple[Judgement, ...]


class DomainInputRejected(ValueError):  # noqa: N818 - public contract name (§9.1)
    def __init__(self, issues: Iterable[Issue]) -> None:
        self.issues = tuple(issues)
        super().__init__(f"{len(self.issues)} issues; nothing was written")


class DomainInputProvider(Protocol):
    def load_domain_input(self) -> list[dict[str, Any]]: ...

    def append_domain_input(self, rows: list[dict[str, Any]]) -> list[int]: ...


@dataclass
class _Entry:
    body: dict[str, Any] | None = None
    confirmed: bool = False
    sources: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class HumanInputState:
    records: tuple[dict[str, Any], ...] = ()
    entries: dict[str, _Entry] = field(default_factory=dict)


def _role_ids(identifier: str, body: dict[str, Any] | None) -> list[str]:
    if body is None or body["kind"] != "fact_type":
        return []
    return [identity.role_id(identifier, role["name"]) for role in body["roles"]]


def _apply_record(state: HumanInputState, record: dict[str, Any]) -> None:
    identifier = record["element_id"]
    op = record["op"]
    entry = state.entries.setdefault(identifier, _Entry())
    old_roles = _role_ids(identifier, entry.body)
    if op == "delete":
        for target in [identifier, *old_roles]:
            state.entries.pop(target, None)
        return
    if op == "put":
        body = json.loads(record["payload"])
        entry.body = body
        entry.confirmed = body["status"] == "confirmed"
        new_roles = _role_ids(identifier, body)
        for removed in set(old_roles) - set(new_roles):
            state.entries.pop(removed, None)
        for role_id, role in zip(new_roles, body.get("roles", ())):
            child = state.entries.setdefault(role_id, _Entry())
            # A newly introduced role inherits the entire surviving parent history.
            if child.body is None:
                child.sources = sorted(
                    {
                        row["seq"]: row for row in [*entry.sources, *child.sources]
                    }.values(),
                    key=lambda row: row["seq"],
                )
            child.body = {"kind": "role", "fact_type": identifier, **role}
    else:
        entry.confirmed = op == "confirm"
    entry.sources.append(record)
    for role_id in _role_ids(identifier, entry.body):
        child = state.entries.setdefault(role_id, _Entry())
        child.confirmed = entry.confirmed
        child.sources.append(record)


def replay(records: Iterable[dict[str, Any]]) -> HumanInputState:
    """Replay in seq order; a parent operation also applies to its inline roles."""
    ordered = tuple(sorted(deepcopy(list(records)), key=lambda row: row["seq"]))
    state = HumanInputState(records=ordered)
    for record in ordered:
        _apply_record(state, record)
    return state


def _put_id(body: dict[str, Any]) -> str:
    kind = body["kind"]
    if kind == "concept":
        return identity.concept_id(body["repository"], body["term"])
    if kind == "fact_type":
        return identity.fact_type_id(body["repository"], body["name"])
    if kind == "validation_rule":
        return identity.validation_rule_id(
            body["fact_type"], body["rule_kind"], body["roles"], name=body["name"]
        )
    if kind == "ground_fact":
        return identity.ground_fact_id(
            body["fact_type"], body["values"], body["violates"]
        )
    functions = {
        "derivation_rule": identity.derivation_rule_id,
        "exchange_rule": identity.exchange_rule_id,
        "event_rule": identity.event_rule_id,
    }
    return functions[kind](body["repository"], body["name"])


def _references(body: dict[str, Any]) -> Iterable[tuple[str, str, set[str]]]:
    """References in request form; rule role names are checked separately."""
    single = {
        "fact_type": {"fact_type"},
        "concept": {"concept"},
        "identifies": {"concept"},
        "superset_fact_type": {"fact_type"},
    }
    multiple = {
        "derives": {"fact_type", "role"},
        "uses": {
            "concept",
            "fact_type",
            "role",
            "validation_rule",
            "derivation_rule",
            "exchange_rule",
            "event_rule",
            "ground_fact",
        },
        "fact_types": {"fact_type"},
        "starts": {"exchange_rule", "derivation_rule"},
        "violates": {"validation_rule"},
    }
    for name, kinds in single.items():
        if body.get(name) is not None:
            yield name, body[name], kinds
    for name, kinds in multiple.items():
        for index, value in enumerate(body.get(name, ())):
            yield f"{name}[{index}]", value, kinds
    if body["kind"] == "fact_type":
        for index, role in enumerate(body["roles"]):
            if role["concept"] is not None:
                yield f"roles[{index}].concept", role["concept"], {"concept"}


def _reference_issue(value: str, kinds: set[str], path: str) -> Issue | None:
    try:
        kind, _, _ = identity.parse_id(value)
        if kind not in kinds:
            raise identity.InvalidReferenceError(
                f"Expected one of {sorted(kinds)}, got {kind}"
            )
    except identity.InvalidReferenceError as exc:
        return Issue(path, "invalid_reference", str(exc))
    return None


def _body_issues(body: dict[str, Any], path: str) -> list[Issue]:
    issues = []
    for name in ("repository", "term", "name"):
        if body.get(name) is not None:
            try:
                (
                    identity.repository_key
                    if name == "repository"
                    else identity.key_segment
                )(body[name])
            except identity.EmptyKeyError as exc:
                issues.append(Issue(f"{path}.{name}", "empty_key", str(exc)))
    for suffix, value, kinds in _references(body):
        issue = _reference_issue(value, kinds, f"{path}.{suffix}")
        if issue:
            issues.append(issue)
    if body["kind"] == "fact_type":
        seen = set()
        names = [role["name"] for role in body["roles"]]
        for index, name in enumerate(names):
            role_path = f"{path}.roles[{index}].name"
            if any(char in name for char in "<>\r\n"):
                issues.append(
                    Issue(
                        role_path,
                        "invalid_value",
                        "Role names cannot contain angle brackets or newlines",
                    )
                )
            try:
                key = identity.key_segment(name)
            except identity.EmptyKeyError as exc:
                issues.append(Issue(role_path, "empty_key", str(exc)))
            else:
                if key in seen:
                    issues.append(
                        Issue(
                            role_path,
                            "duplicate_id",
                            "Role names must have distinct keys",
                        )
                    )
                seen.add(key)
        for index, template in enumerate(body["templates"]):
            issues.extend(
                template_issues(template, names, f"{path}.templates[{index}]")
            )
    if body["kind"] == "validation_rule":
        # Shape is independent of whether roles are names (input) or ids (contract).
        issues.extend(rule_shape_issues(ValidationRule.model_construct(**body), path))
        if body["superset_roles"] and not body["superset_fact_type"]:
            issues.append(
                Issue(path, "rule_shape", "superset_roles require superset_fact_type")
            )
        for name in ("roles", "superset_roles"):
            for index, role in enumerate(body[name]):
                try:
                    identity.key_segment(role)
                except identity.EmptyKeyError as exc:
                    issues.append(
                        Issue(f"{path}.{name}[{index}]", "empty_key", str(exc))
                    )
    return issues


def _parse_request(
    request: WriteRequest | dict[str, Any],
) -> tuple[WriteRequest | None, list[Issue]]:
    try:
        return WriteRequest.model_validate(request), []
    except ValidationError as exc:
        issues = validation_issues(exc, WriteRequest)
        for index, issue in enumerate(issues):
            if issue.path == "operations" and any(
                error["type"] == "too_long" for error in exc.errors()
            ):
                issues[index] = Issue(
                    issue.path,
                    "too_many_operations",
                    "At most 500 operations are allowed",
                )
            elif issue.code == "unknown_field" and issue.path.rsplit(".", 1)[-1] in {
                "author",
                "author_name",
                "author_email",
                "entry_point",
                "recorded_at",
            }:
                issues[index] = Issue(
                    issue.path,
                    issue.code,
                    "ChunkHound fills this field itself; callers cannot supply it",
                )
        return None, issues


def validate(
    state: HumanInputState, request: WriteRequest | dict[str, Any]
) -> tuple[list[dict[str, Any]], list[Issue], list[Issue]]:
    """Plan a whole batch on a copy, checking references and B14 on its end state."""
    body: dict[str, Any] | None
    parsed, issues = _parse_request(request)
    if parsed is None:
        return [], issues, []
    working = replay(state.records)
    planned: list[dict[str, Any]] = []
    warnings: list[Issue] = []
    paths: dict[str, str] = {}
    status_paths: dict[str, str] = {}
    fact_paths: dict[str, str] = {}
    deleted: dict[str, str] = {}
    put_ids: set[str] = set()
    next_seq = max((row["seq"] for row in state.records), default=0) + 1
    for index, operation in enumerate(parsed.operations):
        path = f"operations[{index}]"
        if isinstance(operation, PutOp):
            body = operation.element.model_dump(mode="json")
            body_path = path + ".element"
            body_issues = _body_issues(body, body_path)
            issues.extend(body_issues)
            try:
                identifier = _put_id(body)
            except ValueError as exc:
                # Prefer precise diagnostics, but never silently drop an operation.
                if not body_issues:
                    issues.append(Issue(body_path, "invalid_value", str(exc)))
                continue
            if identifier in put_ids:
                issues.append(
                    Issue(body_path, "duplicate_id", f"Two puts have id {identifier}")
                )
            put_ids.add(identifier)
            if any(
                issue.code in {"empty_key", "duplicate_id"} for issue in body_issues
            ):
                continue
            paths[identifier] = body_path
            status_paths[identifier] = body_path + ".status"
            if body["kind"] == "ground_fact":
                fact_paths[body["fact_type"]] = body_path
            for role_index, role_id in enumerate(_role_ids(identifier, body)):
                paths[role_id] = f"{body_path}.roles[{role_index}]"
            payload = json.dumps(
                body,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        else:
            identifier = operation.id
            issue = _reference_issue(
                identifier,
                {
                    "concept",
                    "fact_type",
                    "role",
                    "validation_rule",
                    "derivation_rule",
                    "exchange_rule",
                    "event_rule",
                    "ground_fact",
                },
                path + ".id",
            )
            if issue:
                issues.append(issue)
                continue
            entry = working.entries.get(identifier)
            if isinstance(operation, DeleteOp) and (
                entry is None or entry.body is None
            ):
                issues.append(
                    Issue(
                        path + ".id",
                        "unknown_element",
                        f"{identifier} has no put in the human input",
                    )
                )
                continue
            if isinstance(operation, UnconfirmOp) and entry is None:
                issues.append(
                    Issue(
                        path + ".id",
                        "unknown_element",
                        f"{identifier} is not in the human input",
                    )
                )
                continue
            if isinstance(operation, (ConfirmOp, UnconfirmOp)):
                if entry is not None and entry.confirmed == isinstance(
                    operation, ConfirmOp
                ):
                    warnings.append(
                        Issue(
                            path + ".id",
                            "no_change",
                            f"{identifier} already has this confirmation state",
                        )
                    )
                status_paths[identifier] = path + ".id"
            if isinstance(operation, DeleteOp):
                if entry and entry.body and entry.body["kind"] == "ground_fact":
                    fact_paths[entry.body["fact_type"]] = path + ".id"
                for target in [
                    identifier,
                    *_role_ids(identifier, entry.body if entry else None),
                ]:
                    deleted[target] = path + ".id"
            payload = None
        record = {
            "seq": next_seq + len(planned),
            "op": operation.op,
            "element_id": identifier,
            "payload": payload,
            "payload_version": 1,
        }
        planned.append(record)
        _apply_record(working, record)

    # Fall back to a real submitted field for invariants involving existing input.
    cause_path = f"operations[{len(parsed.operations) - 1}]" + (
        ".element" if isinstance(parsed.operations[-1], PutOp) else ".id"
    )
    referenced_by: dict[str, set[str]] = {}
    derived = set()
    for identifier, entry in working.entries.items():
        body = entry.body
        if body and body["kind"] == "role":
            if body["mandatory"] is True:
                derived.add(identity.mandatory_rule_id(body["fact_type"], body["name"]))
            if body["datatype"] is not None:
                derived.add(identity.datatype_rule_id(body["fact_type"], body["name"]))
    for identifier, entry in working.entries.items():
        body = entry.body
        if body is None:
            continue
        path = paths.get(identifier, cause_path)
        refs = list(_references(body))
        if body["kind"] == "fact_type":
            refs.extend(
                (f"roles[{i}]", role_id, {"role"})
                for i, role_id in enumerate(_role_ids(identifier, body))
            )
        for suffix, target, kinds in refs:
            if _reference_issue(target, kinds, f"{path}.{suffix}"):
                # Already reported at the submitted put.
                continue
            referenced_by.setdefault(target, set()).add(identifier)
            if (
                target not in working.entries
                and target not in derived
                and target not in deleted
                and identifier in paths
            ):
                warnings.append(
                    Issue(
                        f"{path}.{suffix}",
                        "unresolved_reference",
                        f"{target} is not in the human input; it may be a found "
                        "element. Section 6 checks it on the full model.",
                    )
                )
        if body["kind"] in {"validation_rule", "ground_fact"}:
            groups = [
                (
                    "values" if body["kind"] == "ground_fact" else "roles",
                    body["fact_type"],
                )
            ]
            if body["kind"] == "validation_rule" and body["superset_fact_type"]:
                groups.append(("superset_roles", body["superset_fact_type"]))
            for name, parent_id in groups:
                parent = working.entries.get(parent_id)
                if parent and parent.body and parent.body["kind"] == "fact_type":
                    names = {role["name"] for role in parent.body["roles"]}
                    for role_index, name_value in enumerate(body[name]):
                        if name_value not in names:
                            suffix = (
                                f"values.{name_value}"
                                if name == "values"
                                else f"{name}[{role_index}]"
                            )
                            issues.append(
                                Issue(
                                    f"{path}.{suffix}"
                                    if identifier in paths
                                    else paths.get(parent_id, cause_path),
                                    "unknown_role",
                                    f"{name_value!r} in {identifier} is not a role "
                                    f"of {parent_id}",
                                )
                            )
    for identifier, path in deleted.items():
        remaining = working.entries.get(identifier)
        if (
            remaining is None or remaining.body is None
        ) and identifier in referenced_by:
            issues.append(
                Issue(
                    path,
                    "still_referenced",
                    f"{identifier} is still referenced by "
                    f"{', '.join(sorted(referenced_by[identifier]))}",
                )
            )
    valid_facts = {
        entry.body["fact_type"]
        for entry in working.entries.values()
        if entry.body
        and entry.body["kind"] == "ground_fact"
        and not entry.body["violates"]
    }
    for identifier, entry in working.entries.items():
        if (
            identifier.startswith("fact_type:")
            and entry.confirmed
            and identifier not in valid_facts
        ):
            issues.append(
                Issue(
                    status_paths.get(
                        identifier, fact_paths.get(identifier, cause_path)
                    ),
                    "confirmed_without_ground_fact",
                    f"{identifier} would be confirmed without a valid ground fact; "
                    "add a ground_fact put for it in the same request",
                )
            )
    return planned, list(dict.fromkeys(issues)), list(dict.fromkeys(warnings))


def _source(record: dict[str, Any]) -> HumanSource:
    timestamp = record["recorded_at"]
    if isinstance(timestamp, datetime):
        timestamp = (
            timestamp.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        )
    return HumanSource(
        record=record["seq"],
        op=record["op"],
        put_status=json.loads(record["payload"])["status"]
        if record["op"] == "put"
        else None,
        author_name=record["author_name"],
        author_email=record["author_email"],
        entry_point=record["entry_point"],
        recorded_at=timestamp,
    )


def load_human_input(provider: DomainInputProvider) -> HumanInputView:
    """Project surviving puts and judgements without requiring extracted elements."""
    state = replay(provider.load_domain_input())
    classes: dict[str, type[BaseModel]] = {
        "concept": Concept,
        "fact_type": FactType,
        "role": Role,
        "validation_rule": ValidationRule,
        "derivation_rule": DerivationRule,
        "exchange_rule": ExchangeRule,
        "event_rule": EventRule,
        "ground_fact": GroundFact,
    }
    collections: dict[str, list[Any]] = {name: [] for name in COLLECTIONS}
    judgements = []
    for identifier, entry in sorted(state.entries.items()):
        sources = tuple(
            _source(record)
            for record in sorted(entry.sources, key=lambda row: row["seq"])
        )
        if entry.body is None:
            judgements.append(
                Judgement(
                    id=identifier, confirmed=entry.confirmed, human_sources=sources
                )
            )
            continue
        body = deepcopy(entry.body)
        kind = body.pop("kind")
        body.pop("status", None)
        body.pop("repository", None)
        repository = identity.parse_id(identifier)[1]
        if kind == "fact_type":
            body["roles"] = tuple(_role_ids(identifier, entry.body))
        if kind == "validation_rule":
            body["roles"] = tuple(
                identity.role_id(body["fact_type"], name) for name in body["roles"]
            )
            body["superset_roles"] = tuple(
                identity.role_id(body["superset_fact_type"], name)
                for name in body["superset_roles"]
            )
        if kind in {"fact_type", "role"}:
            body["bindings"] = ()
        # Request shape was checked before writing; this partial model may still
        # reference extracted elements, so do not run full-model loader checks.
        for name, value in body.items():
            if isinstance(value, list):
                body[name] = tuple(value)
        element = classes[kind].model_construct(
            id=identifier,
            repository=repository,
            status="confirmed" if entry.confirmed else "proposed",
            citations=(),
            human_sources=sources,
            **body,
        )
        collections[kind + "s"].append(element)
    model = DomainModel(
        schema_version=1, **{key: tuple(value) for key, value in collections.items()}
    )
    return HumanInputView(model=model, judgements=tuple(judgements))


def apply_write(
    request: WriteRequest | dict[str, Any],
    *,
    provider: DomainInputProvider,
    author: Author,
    entry_point: EntryPoint,
    dry_run: bool = False,
) -> WriteResult:
    """Validate atomically and append exactly one batch, or nothing on rejection."""
    with _WRITE_LOCK:
        state = replay(provider.load_domain_input())
        planned, issues, warnings = validate(state, request)
        if issues:
            raise DomainInputRejected(issues)
        batch_id = str(uuid4())
        recorded_at = datetime.now(timezone.utc).replace(tzinfo=None)
        rows = [
            {
                **{key: value for key, value in record.items() if key != "seq"},
                "batch_id": batch_id,
                "author_name": author.name,
                "author_email": author.email,
                "entry_point": entry_point,
                "recorded_at": recorded_at,
            }
            for record in planned
        ]
        records = () if dry_run else tuple(provider.append_domain_input(rows))
    end_state = replay([*state.records, *planned])
    touched: dict[str, None] = {}
    for record in planned:
        identifier = record["element_id"]
        touched[identifier] = None
        if record["op"] == "put":
            for role_id in _role_ids(identifier, json.loads(record["payload"])):
                touched[role_id] = None
        elif identifier in end_state.entries:
            for role_id in _role_ids(identifier, end_state.entries[identifier].body):
                touched[role_id] = None
    elements = tuple(
        ElementResult(
            id=identifier,
            kind=identity.parse_id(identifier)[0],
            status="confirmed"
            if end_state.entries[identifier].confirmed
            else "proposed",
        )
        for identifier in touched
        if identifier in end_state.entries
    )
    return WriteResult(
        batch_id=batch_id,
        dry_run=dry_run,
        records=records,
        elements=elements,
        warnings=tuple(warnings),
    )

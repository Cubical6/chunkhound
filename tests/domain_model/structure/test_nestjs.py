"""NestJS public extraction contracts for routes, resolver merging, and DTO hints."""

import shutil
from pathlib import Path

import pytest

from chunkhound.domain_model.structure.anchors import anchor_id
from chunkhound.domain_model.structure.contract import (
    RepositoryRef,
    StructureExtraction,
)
from chunkhound.domain_model.structure.extract import build_structure

FIXTURE = Path(__file__).parent / "fixtures" / "nestjs"
REPOSITORIES = (RepositoryRef(key="root", path=".", commit="1" * 40, dirty=False),)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root)
    return root


def extract(project: Path) -> StructureExtraction:
    return build_structure(project, REPOSITORIES)


@pytest.mark.parametrize(
    ("controller", "route", "method", "expected"),
    [
        ("'teams'", "Get(':id')", "GET", ["/teams/:id"]),
        ("{ path: '/teams/' }", "Post()", "POST", ["/teams"]),
        ("", "Put", "PUT", ["/"]),
        ("'teams'", "Patch(['/one/', 'two'])", "PATCH", ["/teams/one", "/teams/two"]),
        ("'teams'", "Delete('')", "DELETE", ["/teams"]),
        ("'teams'", "Options()", "OPTIONS", ["/teams"]),
        ("'teams'", "Head()", "HEAD", ["/teams"]),
        ("'teams'", "All()", "ANY", ["/teams"]),
        ("prefix", "Get()", "GET", []),
        ("{ path: prefix }", "Get()", "GET", []),
        ("'teams'", "Get(path)", "GET", []),
        ("'teams'", "Get(['one', path])", "GET", []),
        ("['a', 'b']", "Get('x')", "GET", ["/a/x", "/b/x"]),
        ("{ path: ['a', 'b'] }", "Get('x')", "GET", ["/a/x", "/b/x"]),
        (
            "['a', 'b', 'a']",
            "Get(['x', 'y', 'x'])",
            "GET",
            ["/a/x", "/a/y", "/b/x", "/b/y"],
        ),
        ("['a', prefix]", "Get('x')", "GET", []),
        ("/* prefix */ 't'", "Get(/* path */ 'x' /* end */)", "GET", ["/t/x"]),
        ("`t`", "Get(`x`)", "GET", ["/t/x"]),
        ("`t${prefix}`", "Get('x')", "GET", []),
        ("'t'", "Get(`x${path}`)", "GET", []),
        ("{ ...options, path: 't', unrelated() {} }", "Get('x')", "GET", ["/t/x"]),
        ("{ unrelated() {}, path: 't', ...options }", "Get('x')", "GET", ["/t/x"]),
        ("{ ...options }", "Get('x')", "GET", []),
        ("{ unrelated() {} }", "Get('x')", "GET", ["/x"]),
    ],
)
def test_controller_prefix_and_method_path_are_joined(
    project: Path, controller: str, route: str, method: str, expected: list[str]
) -> None:
    baseline = extract(project)
    assert {(a.method, a.path) for a in baseline.anchors if a.kind == "http"} == {
        ("GET", "/teams/:id"),
        ("POST", "/teams"),
        ("PATCH", "/teams/:id"),
        ("DELETE", "/teams/:id"),
    }
    source = (
        "import { Controller as C, Get, Post, Put, Patch, Delete, Options, Head, All } "
        "from '@nestjs/common';\n"
        f"@C({controller})\nexport class TestController {{\n"
        f"  @{route}\n  handle() {{}}\n}}\n"
    )
    (project / "teams.controller.ts").write_text(source)
    # Other packages, declarations, and dependency files are ignored.
    (project / "unrelated.ts").write_text(source.replace("@nestjs/common", "other"))
    for path in ("hidden.d.ts", "node_modules/hidden.ts", "vendor/hidden.ts"):
        file = project / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(source.replace("TestController", "HiddenController"))
    result = extract(project)
    anchors = [a for a in result.anchors if a.kind == "http"]
    assert sorted(a.path for a in anchors) == sorted(expected)
    for anchor in anchors:
        assert anchor.method == method
        assert anchor.handler and anchor.handler.symbol == "TestController.handle"
        assert anchor.handler.citation and anchor.handler.citation.start_line == 5
        assert anchor.source == "nestjs"
    dynamic = [f for f in result.findings if f.reason == "dynamic_registration"]
    assert len(dynamic) == (0 if expected else 1)
    assert all(f.kind == "unresolved" and f.subject is None for f in dynamic)


@pytest.mark.parametrize(
    "variant",
    [
        "enum",
        "object",
        "local_enum",
        "cycle",
        "mapped",
        "typed_nested",
        "transformer_type",
        "same_file",
        "enum_alias",
        "object_alias",
        "comments",
    ],
)
def test_dto_validators_become_input_hints(project: Path, variant: str) -> None:
    dto = project / "team.dto.ts"
    if variant in {"object", "object_alias"}:
        (project / "status.ts").write_text(
            "export const Status = { Active: 'active', "
            "Archived: 'archived' } as const;\n"
        )
    elif variant == "local_enum":
        dto.write_text(
            dto.read_text().replace(
                "import { Status } from './status';",
                (project / "status.ts").read_text(),
            )
        )
    elif variant == "same_file":
        controller = project / "teams.controller.ts"
        controller.write_text(
            controller.read_text().replace(
                "import { CreateTeamDto } from './team.dto';", dto.read_text()
            )
        )
    elif variant == "transformer_type":
        dto.write_text(
            dto.read_text().replace("address: AddressDto", "address: unknown")
        )
    elif variant == "cycle":
        dto.write_text(
            dto.read_text().replace(
                "class BaseDto {", "class BaseDto extends CreateTeamDto {"
            )
        )
    elif variant == "mapped":
        dto.write_text(
            dto.read_text().replace("extends BaseDto", "extends PartialType(BaseDto)")
        )
    elif variant == "typed_nested":
        dto.write_text(
            dto.read_text().replace(
                "  @ValidateNested()\n  @Type(() => AddressDto)\n", ""
            )
        )
    if variant in {"enum_alias", "object_alias"}:
        dto.write_text(
            dto.read_text()
            .replace("import { Status }", "import { Status as St }")
            .replace("@IsEnum(Status)", "@IsEnum(St)")
        )
    elif variant == "comments":
        dto.write_text(
            dto.read_text()
            .replace("@IsEnum(Status)", "@IsEnum(/* enum */ Status /* end */)")
            .replace("@Type(() => AddressDto)", "@Type(/* type */ () => AddressDto)")
        )
    result = extract(project)
    anchor = next(a for a in result.anchors if a.method == "POST")
    hints = anchor.hints
    types = {h.name for h in hints if h.kind == "input_type"}
    if variant == "mapped":
        assert not types
        assert not any(h.kind == "input_rule" for h in hints)
    else:
        assert types == {"CreateTeamDto", "AddressDto"}
        rules = {(h.name, h.value) for h in hints if h.kind == "input_rule"}
        assert {
            ("email", "@Length(1, 20)"),
            ("email", "@IsEmail()"),
            (
                "status",
                "@IsEnum(St)"
                if variant in {"enum_alias", "object_alias"}
                else "@IsEnum(/* enum */ Status /* end */)"
                if variant == "comments"
                else "@IsEnum(Status)",
            ),
            ("label", "@IsString()"),
        } <= rules
        assert not any(name == "city" for name, _ in rules)
        enum = next(h for h in hints if h.kind == "enum")
        assert enum.name == "Status" and enum.values == ("active", "archived")
        assert all(
            h.citation.path
            == ("teams.controller.ts" if variant == "same_file" else "team.dto.ts")
            for h in hints
            if h.kind == "input_rule"
        )
    assert not any("dto" in f.name.lower() for f in result.model.fact_types)
    assert not any(f.reason == "unreadable_source" for f in result.findings)


@pytest.mark.parametrize("named_missing", [False, True])
def test_resolver_fills_handler_of_schema_anchor(
    project: Path, named_missing: bool
) -> None:
    if named_missing:
        (project / "schema.graphql").write_text(
            'type Mutation { addTeam: Boolean @field(resolver: "Missing@run") }\n'
        )
    result = extract(project)
    matches = [a for a in result.anchors if a.path == "Mutation.addTeam"]
    assert len(matches) == 1
    anchor = matches[0]
    assert anchor.id == anchor_id("root", "graphql", "mutation", "Mutation.addTeam")
    assert anchor.source == "graphql"
    assert anchor.handler and anchor.handler.symbol == "TeamsResolver.add"
    assert (
        anchor.handler.citation and anchor.handler.citation.path == "teams.resolver.ts"
    )
    assert len(anchor.citations) == 2
    assert {c.path for c in anchor.citations} == {"schema.graphql", "teams.resolver.ts"}
    findings = [
        f
        for f in result.findings
        if f.subject == anchor.id and f.reason == "handler_not_found"
    ]
    assert bool(findings) == named_missing
    assert all(f.detail is not None for f in findings)


@pytest.mark.parametrize(
    ("decorator", "method", "path"),
    [
        ("Query({ name: 'teamCount' })", "query", "Query.teamCount"),
        ("Query(() => Number, { name: 'total' })", "query", "Query.total"),
        ("Query()", "query", "Query.count"),
        ("Mutation('rename')", "mutation", "Mutation.rename"),
        ("Subscription({ name: 'events' })", "subscription", "Subscription.events"),
        ("Query(() => [Team])", "query", "Query.count"),
        (
            "Query(/* type */ () => [Team], /* options */ { name: 'total' })",
            "query",
            "Query.total",
        ),
        ("Query(/* name */ 'named')", "query", "Query.named"),
        ("Query(`tpl`)", "query", "Query.tpl"),
        (
            "Query({ ...options, name: 'named', unrelated() {} })",
            "query",
            "Query.named",
        ),
        (
            "Query({ unrelated() {}, name: 'named', ...options })",
            "query",
            "Query.named",
        ),
        ("Query({ unrelated() {} })", "query", "Query.count"),
        ("Query(QUERY_NAME)", "query", None),
        ("Mutation(names.create)", "mutation", None),
        ("Subscription(getName())", "subscription", None),
        ("Query(`tpl${name}`)", "query", None),
        ("Query({ name: NAME })", "query", None),
        ("Query(() => [Team], { name: NAME })", "query", None),
        ("Query({ ...options })", "query", None),
        ("Query(() => [Team], { ...options })", "query", None),
    ],
)
def test_code_first_resolver_is_its_own_anchor(
    project: Path, decorator: str, method: str, path: str | None
) -> None:
    resolver = project / "teams.resolver.ts"
    resolver.write_text(
        resolver.read_text().replace("Query({ name: 'teamCount' })", decorator)
    )
    result = extract(project)
    if path is None:
        assert not any(
            a.handler and a.handler.symbol == "CodeFirstResolver.count"
            for a in result.anchors
        )
        findings = [f for f in result.findings if f.reason == "dynamic_registration"]
        assert len(findings) == 1
        assert findings[0].kind == "unresolved" and findings[0].subject is None
        return
    anchor = next(a for a in result.anchors if a.path == path)
    assert anchor.method == method and anchor.source == "nestjs"
    assert anchor.handler and anchor.handler.symbol == "CodeFirstResolver.count"
    assert len(anchor.citations) == 1
    assert [h.value for h in anchor.hints if h.kind == "operation"] == (
        ["read"] if method == "query" else []
    )
    assert not any(a.path.endswith(".ignored") for a in result.anchors)
    assert any(a.path == "Subscription.teamChanged" for a in result.anchors)
    assert not any(f.subject == anchor.id for f in result.findings)


def test_entity_parameter_links_hint_to_fact_type(project: Path) -> None:
    result = extract(project)
    anchor = next(a for a in result.anchors if a.method == "POST")
    model = next(h for h in anchor.hints if h.kind == "model")
    fact = next(f for f in result.model.fact_types if f.name == "teams")
    assert model.name == "Team" and model.fact_type == fact.id
    role = next(
        r for r in result.model.roles if r.fact_type == fact.id and r.name == "email"
    )
    email = [h for h in anchor.hints if h.kind == "input_rule" and h.name == "email"]
    assert email and all(h.role == role.id for h in email)
    assert all(
        h.role is None
        for h in anchor.hints
        if h.kind == "input_rule" and h.name == "status"
    )
    assert [h.value for h in anchor.hints if h.kind == "operation"] == ["add"]


@pytest.mark.parametrize("form", ["star", "named", "alias", "cycle", "first_match"])
def test_relative_reexports_preserve_dto_and_entity_hints(
    project: Path, form: str
) -> None:
    dto_exports = {
        "star": "export * from '../team.dto';\n",
        "named": "export { CreateTeamDto } from '../team.dto';\n",
        "alias": "export { CreateTeamDto as CreateDto } from '../team.dto';\n",
        "cycle": "export * from './cycle';\nexport * from '../team.dto';\n",
        "first_match": "export * from '../team.dto';\nexport * from './other';\n",
    }
    (project / "dto").mkdir()
    (project / "dto/index.ts").write_text(dto_exports[form])
    (project / "dto/cycle.ts").write_text("export * from './index';\n")
    (project / "dto/other.ts").write_text(
        "import { IsString } from 'class-validator';\n"
        "export class CreateTeamDto { @IsString() other: string; }\n"
    )
    entity_exports = (
        "export { Team as Entity } from '../team.entity';\n"
        if form == "alias"
        else "export * from '../team.entity';\n"
    )
    (project / "models").mkdir()
    (project / "models/index.ts").write_text(entity_exports)
    for filename in ("teams.controller.ts", "teams.resolver.ts"):
        file = project / filename
        source = (
            file.read_text()
            .replace("'./team.dto'", "'./dto'")
            .replace("'./team.entity'", "'./models'")
        )
        if form == "alias":
            source = (
                source.replace("CreateTeamDto", "CreateDto")
                .replace("{ Team }", "{ Entity }")
                .replace(": Team", ": Entity")
            )
        file.write_text(source)
    result = extract(project)
    for anchor in result.anchors:
        if anchor.method == "POST" or anchor.path == "Mutation.addTeam":
            assert {h.name for h in anchor.hints if h.kind == "input_type"} == {
                "CreateTeamDto",
                "AddressDto",
            }
            rules = [h for h in anchor.hints if h.kind == "input_rule"]
            assert any(h.name == "email" and h.value == "@IsEmail()" for h in rules)
            assert all(h.citation.path == "team.dto.ts" for h in rules)
    post = next(a for a in result.anchors if a.method == "POST")
    model = next(h for h in post.hints if h.kind == "model")
    fact = next(f for f in result.model.fact_types if f.name == "teams")
    assert model.name == "Team" and model.fact_type == fact.id
    assert not any(f.reason == "unreadable_source" for f in result.findings)


@pytest.mark.parametrize(
    ("type_expression", "resolved"),
    [
        ("CreateTeamDto[]", True),
        ("CreateTeamDto | null", True),
        ("CreateTeamDto | undefined", True),
        ("CreateTeamDto[] | null | undefined", True),
        ("Array<CreateTeamDto>", False),
        ("dto.CreateTeamDto", False),
        ("CreateTeamDto | OtherDto", False),
    ],
)
def test_array_and_nullable_dto_parameters_keep_input_hints(
    project: Path, type_expression: str, resolved: bool
) -> None:
    for filename in ("teams.controller.ts", "teams.resolver.ts"):
        file = project / filename
        file.write_text(
            file.read_text().replace(": CreateTeamDto", f": {type_expression}")
        )
    result = extract(project)
    for anchor in result.anchors:
        if anchor.method == "POST" or anchor.path == "Mutation.addTeam":
            inputs = [h for h in anchor.hints if h.kind == "input_type"]
            rules = [h for h in anchor.hints if h.kind == "input_rule"]
            assert bool(inputs) == resolved
            assert bool(rules) == resolved
            if resolved:
                assert any(h.name == "CreateTeamDto" for h in inputs)
                assert any(h.name == "email" and h.value == "@IsEmail()" for h in rules)


@pytest.mark.parametrize("kind", ["http", "graphql"])
@pytest.mark.parametrize("name", ["'quoted'", "['x']", "[expr]"])
def test_quoted_handler_names_are_unquoted_and_computed_names_are_dynamic(
    project: Path, kind: str, name: str
) -> None:
    if kind == "http":
        source = (
            "import { Controller, Get } from '@nestjs/common';\n"
            "@Controller('t') export class Names {\n"
            f" @Get('x') {name}() {{}}\n}}\n"
        )
    else:
        source = (
            "import { Resolver, Query } from '@nestjs/graphql';\n"
            "@Resolver() export class Names {\n"
            f" @Query() {name}() {{}}\n}}\n"
        )
    (project / "names.ts").write_text(source)
    result = extract(project)
    anchors = [
        a for a in result.anchors if any(c.path == "names.ts" for c in a.citations)
    ]
    if name == "'quoted'":
        assert len(anchors) == 1
        assert anchors[0].path == ("/t/x" if kind == "http" else "Query.quoted")
        assert anchors[0].handler and anchors[0].handler.symbol == "Names.quoted"
    else:
        assert not anchors
        findings = [
            f for f in result.findings if any(c.path == "names.ts" for c in f.citations)
        ]
        assert len(findings) == 1
        assert (
            findings[0].kind == "unresolved"
            and findings[0].reason == "dynamic_registration"
        )
        assert findings[0].subject is None


def test_abstract_decorated_classes_register_anchors(project: Path) -> None:
    for filename in ("teams.controller.ts", "teams.resolver.ts"):
        file = project / filename
        file.write_text(
            file.read_text().replace("export class", "export abstract class")
        )
    result = extract(project)
    assert {(a.kind, a.path) for a in result.anchors} == {
        ("http", "/teams/:id"),
        ("http", "/teams"),
        ("graphql", "Mutation.addTeam"),
        ("graphql", "Query.teamCount"),
        ("graphql", "Subscription.teamChanged"),
    }
    assert all(a.handler and a.handler.citation for a in result.anchors)

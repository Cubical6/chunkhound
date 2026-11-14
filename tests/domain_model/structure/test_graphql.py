"""GraphQL acceptance contracts across Magento, Lighthouse, and plain schemas."""

import shutil
from pathlib import Path

import pytest

from chunkhound.domain_model.structure.contract import RepositoryRef
from chunkhound.domain_model.structure.extract import build_structure

FIXTURES = Path(__file__).parent / "fixtures"
REPOSITORIES = (RepositoryRef(key="root", path=".", commit="1" * 40, dirty=False),)


def project(tmp_path: Path, name: str) -> Path:
    destination = tmp_path / "project"
    shutil.copytree(FIXTURES / name, destination)
    for path in destination.rglob("dot-gitignore"):
        path.rename(path.with_name(".gitignore"))
    return destination


@pytest.mark.parametrize("encoding", ["escaped", "unicode", "block"])
@pytest.mark.parametrize("missing", [None, "class", "method", "trait"])
def test_magento_resolver_with_escaped_namespace_is_found(
    tmp_path: Path, encoding: str, missing: str | None
) -> None:
    root = project(tmp_path, "graphql_magento")
    schema = root / "app/code/Acme/Notes/etc/schema.graphqls"
    resolver = root / "app/code/Acme/Notes/Model/Resolver/AddNote.php"
    text = schema.read_text()
    if encoding == "unicode":
        text = text.replace("Acme", r"\u0041cme")
    elif encoding == "block":
        text = text.replace(
            '"Acme\\\\Notes\\\\Model\\\\Resolver\\\\AddNote"',
            '"""\n\n    Acme\\Notes\\Model\\Resolver\\AddNote\n    \n"""',
        )
    schema.write_text(text)
    if missing == "class":
        resolver.unlink()
    elif missing == "method":
        resolver.write_text(
            resolver.read_text().replace("function resolve", "function other")
        )
    elif missing == "trait":
        resolver.write_text(
            "<?php\nnamespace Acme\\Notes\\Model\\Resolver;\n"
            "class AddNote { use Resolves; }\n"
        )
        resolver = resolver.with_name("Resolves.php")
        resolver.write_text(
            "<?php\nnamespace Acme\\Notes\\Model\\Resolver;\n"
            "trait Resolves { public function resolve() {} }\n"
        )
    # Only own module schemas count in a Magento repository, without relying on ignores.
    for relative in (
        "dev/tests/stray.graphqls",
        "stray.gql",
        "app/code/Acme/Notes/node_modules/hidden.graphql",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("extend type Mutation { hidden: String }\n")
    (root / ".gitignore").unlink()
    result = build_structure(root, REPOSITORIES)
    assert len(result.anchors) == 1
    anchor = result.anchors[0]
    assert anchor.path == "Mutation.addNote" and anchor.method == "mutation"
    assert anchor.source == "graphql" and anchor.kind == "graphql"
    assert anchor.handler is not None
    assert anchor.handler.symbol == "Acme\\Notes\\Model\\Resolver\\AddNote@resolve"
    assert not [h for h in anchor.hints if h.kind == "operation"]
    if missing in {"class", "method"}:
        assert anchor.handler.citation is None
        assert [(f.reason, f.subject) for f in result.findings] == [
            ("handler_not_found", anchor.id)
        ]
    else:
        citation = anchor.handler.citation
        assert citation and citation.path == resolver.relative_to(root).as_posix()
        assert (
            "function resolve"
            in resolver.read_text().splitlines()[citation.start_line - 1]
        )
        assert not result.findings


def test_lighthouse_create_directive_needs_no_handler(tmp_path: Path) -> None:
    root = project(tmp_path, "graphql_lighthouse")
    result = build_structure(root, REPOSITORIES)
    anchors = {a.path: a for a in result.anchors}
    expected = {
        "Query.teams": ("all", "read"),
        "Query.team": ("find", "read"),
        "Query.firstTeam": ("first", "read"),
        "Query.pagedTeams": ("paginate", "read"),
        "Query.database": ("find", "read"),
        "Query.search": ("all", "read"),
        "Mutation.createTeam": ("create", "add"),
        "Mutation.updateTeam": ("update", "change"),
        "Mutation.upsertTeam": ("upsert", "change"),
        "Mutation.deleteTeam": ("delete", "remove"),
    }
    for path, (directive, operation) in expected.items():
        anchor = anchors[path]
        assert anchor.handler and anchor.handler.symbol == "@" + directive
        assert anchor.handler.citation is None
        assert [h.value for h in anchor.hints if h.kind == "operation"] == [operation]
        models = [h for h in anchor.hints if h.kind == "model"]
        model_name = {
            "Query.pagedTeams": "TeamPaginator",
            "Query.database": "DatabaseConnection",
        }.get(path, "Team")
        assert [(h.name, h.fact_type) for h in models] == [
            (
                "App\\Models\\" + model_name,
                "fact_type:root/teams" if model_name == "Team" else None,
            )
        ]
    create = anchors["Mutation.createTeam"]
    assert {h.name for h in create.hints if h.kind == "input_type"} == {
        "TeamInput",
        "AddressInput",
    }
    rules = {h.name: h for h in create.hints if h.kind == "input_rule"}
    assert rules["name"].value == '["required", "min:2"]'
    assert rules["name"].role == "role:root/teams/name"
    assert rules["state"].value == "State"
    assert rules["state"].role == "role:root/teams/state"
    assert "city" not in rules and "secret" not in rules
    assert [(h.name, h.values) for h in create.hints if h.kind == "enum"] == [
        ("State", ("OPEN", "CLOSED"))
    ]
    for path, symbol in {
        "Query.custom": "Custom@handle",
        "Query.invoked": "Custom@__invoke",
        "Query.defaultTeam": "App\\GraphQL\\Queries\\DefaultTeam@__invoke",
        "Mutation.defaultTeam": "App\\GraphQL\\Mutations\\DefaultTeam@__invoke",
        "Mutation.hello": "DefaultTeam@__invoke",
        "Subscription.changes": "App\\GraphQL\\Queries\\Custom@__invoke",
    }.items():
        handler = anchors[path].handler
        assert handler and handler.symbol == symbol and handler.citation
    assert not [
        h for h in anchors["Subscription.changes"].hints if h.kind == "operation"
    ]
    assert not [
        h for h in anchors["Mutation.defaultTeam"].hints if h.kind == "operation"
    ]
    search_rules = {
        h.name: h.value for h in anchors["Query.search"].hints if h.kind == "input_rule"
    }
    assert search_rules == {
        "name": '["required", "min:2"]',
        "title": '["required"]',
        "state": "State",
        "address": "AddressInput",
        "limit": "Int",
    }
    assert not result.findings
    assert {f.name for f in result.model.fact_types} == {
        "teams",
        "team_members",
        "composite_members",
        "Membership",
    }
    assert any(
        r.rule_kind == "value" and r.allowed_values == ("OPEN", "CLOSED")
        for r in result.model.validation_rules
    )


@pytest.mark.parametrize(
    "resolver",
    [
        None,
        '"Missing@handle"',
        r'"\ud800"',
        '"""\n    Missing\\"""\n      nested\n\n"""',
    ],
)
def test_schema_without_resolvers_reports_handler_not_found(
    tmp_path: Path, resolver: str | None
) -> None:
    root = project(tmp_path, "graphql_plain")
    if resolver:
        schema = root / "schema.graphql"
        schema.write_text(
            schema.read_text().replace(
                "addInvoice: Invoice",
                f"addInvoice: Invoice @field(resolver: {resolver})",
            )
        )
    broken = root / "000_broken.gql"
    broken.write_text("type Broken { invalid(\n")
    ignored = root / "ignored.graphql"
    ignored.write_text("extend type RootQuery { ignored: String }\n")
    (root / ".gitignore").write_text("ignored.graphql\n")
    (root / "node_modules").mkdir()
    (root / "node_modules/hidden.gql").write_text(
        "extend type RootQuery { hidden: String }\n"
    )
    (root / "vendor").mkdir()
    (root / "vendor/hidden.graphqls").write_text(
        "extend type RootQuery { vendorHidden: String }\n"
    )
    result = build_structure(root, REPOSITORIES)
    failures = [f for f in result.findings if f.reason == "unreadable_source"]
    assert len(failures) == 1 and failures[0].citations[0].path == broken.name
    assert len(result.anchors) == 4
    for anchor in result.anchors:
        assert any(
            f.reason == "handler_not_found" and f.subject == anchor.id
            for f in result.findings
        )
        if resolver and anchor.path == "RootMutation.addInvoice":
            expected_symbol = (
                r"\ud800@__invoke"
                if resolver == r'"\ud800"'
                else 'Missing"""\n  nested@__invoke'
                if resolver.startswith('"""')
                else "Missing@handle"
            )
            assert anchor.handler and anchor.handler.symbol == expected_symbol
            assert anchor.handler.citation is None
        else:
            assert anchor.handler is None
        assert [h.value for h in anchor.hints if h.kind == "operation"] == (
            ["read"] if anchor.method == "query" else []
        )
    query = next(a for a in result.anchors if a.path == "RootQuery.team")
    assert {h.name for h in query.hints if h.kind == "input_type"} == {
        "TeamFilter",
        "NestedInput",
    }
    assert {h.name: h.value for h in query.hints if h.kind == "input_rule"} == {
        "name": "String!",
        "state": "State",
        "nested": "NestedInput",
    }
    assert all(h.values == ("OPEN", "CLOSED") for h in query.hints if h.kind == "enum")
    assert len([h for h in query.hints if h.kind == "enum"]) == 2


@pytest.mark.parametrize("declaration", ["schema", "extend schema"])
def test_extend_type_fields_are_anchors(tmp_path: Path, declaration: str) -> None:
    root = project(tmp_path, "graphql_plain")
    schema = root / "schema.graphql"
    schema.write_text(
        schema.read_text().replace("schema { query:", declaration + " { query:")
    )
    extension = root / "extend.gql"
    extension.write_text(
        extension.read_text()
        + "extend type RootQuery { team(filter: TeamFilter, state: State): Team }\n"
    )
    result = build_structure(root, REPOSITORIES)
    query = next(a for a in result.anchors if a.path == "RootQuery.invoices")
    assert query.kind == "graphql" and query.method == "query"
    assert query.citations[0].path == "extend.gql"
    duplicate = next(a for a in result.anchors if a.path == "RootQuery.team")
    assert {c.path for c in duplicate.citations} == {"schema.graphql", "extend.gql"}
    assert len(result.anchors) == 4
    assert "Query" in {f.name for f in result.model.fact_types}
    assert not any(a.path.startswith("Query.") for a in result.anchors)


def test_type_matching_a_table_adds_citation_or_divergent_claim(tmp_path: Path) -> None:
    root = project(tmp_path, "graphql_plain")
    result = build_structure(root, REPOSITORIES)
    roles = {r.id: r for r in result.model.roles}
    name = roles["role:root/team/name"]
    assert {c.path for c in name.citations} == {"tables.sql", "schema.graphql"}
    assert name.datatype == "varchar(80)" and name.mandatory is True
    assert any(
        c.subject == "role:root/team/state"
        and c.property == "mandatory"
        and c.value is True
        and c.source == "graphql"
        for c in result.divergent_claims
    )
    assert any(
        c.property == "allowed_values"
        and c.value == ("OPEN", "CLOSED")
        and c.source == "graphql"
        for c in result.divergent_claims
    )
    assert roles["role:root/team/state"].mandatory is False
    assert "role:root/team/extra" not in roles
    assert any(
        f.reason == "column_only_in_lower_source"
        and f.detail == "extra"
        and f.subject == "fact_type:root/team"
        for f in result.findings
    )
    assert len([f for f in result.model.fact_types if f.name == "Team"]) == 1
    # Equal terms in a different repository must not absorb this API shape.
    (root / "storage").mkdir()
    (root / "tables.sql").rename(root / "storage/tables.sql")
    repositories = (
        *REPOSITORIES,
        RepositoryRef(key="storage", path="storage", commit="1" * 40, dirty=False),
    )
    separate = build_structure(root, repositories)
    assert "role:root/team/extra" in {r.id for r in separate.model.roles}
    assert not separate.divergent_claims
    assert {f.repository for f in separate.model.fact_types if f.name == "Team"} == {
        "root",
        "storage",
    }
    # No singular/plural inference: a table's term must actually match.
    (root / "storage/tables.sql").rename(root / "tables.sql")
    sql = root / "tables.sql"
    sql.write_text(sql.read_text().replace("TABLE Team", "TABLE teams"))
    unmatched = build_structure(root, REPOSITORIES)
    assert {f.name for f in unmatched.model.fact_types} >= {"Team", "teams"}
    assert "role:root/team/extra" in {r.id for r in unmatched.model.roles}
    lighthouse = build_structure(
        project(tmp_path / "lighthouse", "graphql_lighthouse"), REPOSITORIES
    )
    member = next(f for f in lighthouse.model.fact_types if f.name == "team_members")
    assert member.identifies == "concept:root/team-member"
    assert "TeamMember" not in {f.name for f in lighthouse.model.fact_types}
    for role in (r for r in lighthouse.model.roles if r.fact_type == member.id):
        assert {c.path for c in role.citations} >= {
            "members.sql",
            "graphql/schema.graphql",
        }
    assert not lighthouse.findings


@pytest.mark.parametrize("id_type", ["ID", "ID!"])
def test_type_without_table_becomes_fact_type(tmp_path: Path, id_type: str) -> None:
    root = project(tmp_path, "graphql_plain")
    schema = root / "schema.graphql"
    schema.write_text(
        schema.read_text().replace(
            "type Invoice { id: ID!", "type Invoice { id: " + id_type
        )
    )
    result = build_structure(root, REPOSITORIES)
    invoice = next(f for f in result.model.fact_types if f.name == "Invoice")
    assert invoice.identifies == "concept:root/invoice"
    assert invoice.roles[0] == "role:root/invoice/id"
    roles = {r.name: r for r in result.model.roles if r.fact_type == invoice.id}
    assert roles["id"].mandatory is True and roles["id"].datatype == id_type
    assert roles["total"].datatype == "Float!" and roles["total"].mandatory is True
    assert roles["issued"].datatype == "Date" and roles["issued"].mandatory is False
    assert roles["issued"].citations[0].path == "extend.gql"
    assert roles["team"].concept == "concept:root/team"
    assert "teams" not in roles
    assert roles["parent"].concept == "concept:root/invoice"
    assert roles["state"].datatype == "State" and roles["state"].mandatory is False
    assert any(
        r.rule_kind == "value"
        and r.roles == (roles["state"].id,)
        and r.allowed_values == ("OPEN", "CLOSED")
        for r in result.model.validation_rules
    )
    assert any(
        r.rule_kind == "subset"
        and r.fact_type == invoice.id
        and r.superset_fact_type == "fact_type:root/team"
        and r.superset_roles == ("role:root/team/id",)
        for r in result.model.validation_rules
    )
    assert {f.name for f in result.model.fact_types} == {
        "Team",
        "Invoice",
        "TeamConnection",
        "Query",
    }
    assert any(
        f.reason == "key_collision" and f.subject is None and f.detail == "_"
        for f in result.findings
    )
    lighthouse = build_structure(
        project(tmp_path / "lighthouse", "graphql_lighthouse"), REPOSITORIES
    )
    membership = next(f for f in lighthouse.model.fact_types if f.name == "Membership")
    member_rules = [
        r
        for r in lighthouse.model.validation_rules
        if r.fact_type == membership.id and r.rule_kind == "subset"
    ]
    assert [(r.superset_fact_type, r.superset_roles) for r in member_rules] == [
        ("fact_type:root/team-members", ("role:root/team-members/member-key",))
    ]
    assert {r.name for r in lighthouse.model.roles if r.fact_type == membership.id} == {
        "id",
        "member",
    }
    assert not [f for f in lighthouse.findings if f.kind == "external_reference"]


def test_connection_types_are_technical(tmp_path: Path) -> None:
    result = build_structure(project(tmp_path, "graphql_plain"), REPOSITORIES)
    assert any(
        f.kind == "technical"
        and f.reason == "framework_table"
        and f.detail == "graphql"
        and f.subject == "fact_type:root/teamconnection"
        for f in result.findings
    )

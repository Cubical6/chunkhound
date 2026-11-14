"""Laravel entry points expose cited input hints, never inferred exchange rules."""

import hashlib
import re
import shutil
from pathlib import Path

import pytest

from chunkhound.domain_model.identity import key_segment
from chunkhound.domain_model.structure.contract import (
    RepositoryRef,
    StructureExtraction,
)
from chunkhound.domain_model.structure.extract import build_structure

FIXTURE = Path(__file__).parent / "fixtures/laravel_routes"
RESOURCE_PARAMETERS = {
    "houses": "house",
    "courses": "course",
    "expenses": "expense",
    "purchases": "purchase",
    "licenses": "license",
    "movies": "movie",
    "categories": "category",
    "boxes": "box",
    "churches": "church",
    "statuses": "status",
    "addresses": "address",
    "team-members": "team_member",
    "people": "people",
    "buses": "bus",
    "glass": "glass",
    "status": "status",
}
SHALLOW_ACTIONS = {
    ("GET", "/teams/{group}/team-members", "index"),
    ("POST", "/teams/{group}/team-members", "store"),
    ("GET", "/teams/{group}/team-members/create", "create"),
    ("GET", "/team-members/{person}", "show"),
    ("GET", "/team-members/{person}/edit", "edit"),
    ("PUT", "/team-members/{person}", "update"),
    ("PATCH", "/team-members/{person}", "update"),
    ("DELETE", "/team-members/{person}", "destroy"),
}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    shutil.copytree(FIXTURE, tmp_path, dirs_exist_ok=True)
    return tmp_path


def extract(project: Path) -> StructureExtraction:
    repo = RepositoryRef(key="root", path=".", commit="1" * 40, dirty=False)
    return build_structure(project, (repo,))


@pytest.mark.parametrize("aliases", [False, True])
def test_every_literal_route_is_an_anchor(project: Path, aliases: bool) -> None:
    if aliases:
        for path in project.rglob("*.php"):
            source = path.read_text()
            for facade, alias in (
                ("Route", "Router"),
                ("Artisan", "Console"),
                ("Validator", "Checks"),
            ):
                source = source.replace(
                    f"Facades\\{facade};", f"Facades\\{facade} as {alias};"
                )
                source = source.replace(f"{facade}::", f"{alias}::")
            path.write_text(source)
    result = extract(project)
    assert len(result.anchors) == 73
    expected = {
        ("POST", "/teams/{team}/members"),
        ("GET", "/teams/{team}/members"),
        ("GET", "/health"),
        ("HEAD", "/health"),
        ("POST", "/literal"),
        ("PUT", "/members/{member}"),
        ("PATCH", "/members/{member}"),
        ("DELETE", "/members/{member}"),
        ("OPTIONS", "/options"),
        ("GET", "/matched"),
        ("POST", "/matched"),
        ("ANY", "/anything"),
        ("GET", "/invoke"),
        ("GET", "/missing"),
        ("GET", "/missing-method"),
        ("GET", "/duplicate"),
        ("GET", "/notes"),
        ("GET", "/notes/{note}"),
        ("GET", "/teams"),
        ("POST", "/teams"),
        ("GET", "/teams/{team}"),
        ("PUT", "/teams/{team}"),
        ("PATCH", "/teams/{team}"),
        ("GET", "/teams/create"),
        ("GET", "/teams/{team}/edit"),
        ("GET", "/all"),
        ("POST", "/all"),
        ("GET", "/all/{all}"),
        ("PUT", "/all/{all}"),
        ("PATCH", "/all/{all}"),
        ("DELETE", "/all/{all}"),
        ("GET", "/limited"),
        ("GET", "/limited/create"),
        ("GET", "/except"),
        ("GET", "/except/{except}"),
        ("DELETE", "/except/{except}"),
    }
    expected |= {
        ("GET", "/invoke-string"),
        ("GET", "/match-string"),
        ("GET", "/legacy"),
        ("GET", "/admin/users"),
        ("GET", "/v1/admin/users"),
        ("GET", "/"),
        ("GET", "/trait"),
        ("GET", "/libraries/create"),
        ("GET", "/libraries/{library}/edit"),
        ("GET", "/v1.0/teams/{team}/team-members"),
        ("GET", "/v1.0/teams/{team}/team-members/{team_member}"),
    }
    expected |= {
        ("GET", f"/{name}/{{{parameter}}}")
        for name, parameter in RESOURCE_PARAMETERS.items()
    }
    expected |= {(method, path) for method, path, _ in SHALLOW_ACTIONS}
    http = [a for a in result.anchors if a.kind == "http"]
    assert len(http) == len(expected) == 71
    assert {(a.method, a.path) for a in http} == expected
    assert {a.source for a in result.anchors} == {"laravel_routes"}
    operations = {
        "GET": "read",
        "HEAD": "read",
        "POST": "add",
        "PUT": "change",
        "PATCH": "change",
        "DELETE": "remove",
    }
    for anchor in http:
        assert {h.value for h in anchor.hints if h.kind == "operation"} == (
            {operations[anchor.method]} if anchor.method in operations else set()
        )
        assert anchor.handler is not None
        if not anchor.path.startswith("/missing"):
            assert anchor.handler.citation is not None
    invoke = next(a for a in http if a.path == "/invoke")
    assert (
        invoke.handler.symbol == "App\\Http\\Controllers\\TeamMemberController@__invoke"
    )
    assert (
        next(
            a for a in http if a.path == "/health" and a.method == "GET"
        ).handler.symbol
        == "closure"
    )
    string_invoke = next(a for a in http if a.path == "/invoke-string")
    assert string_invoke.handler == invoke.handler
    trait = next(a for a in http if a.path == "/trait")
    assert trait.handler.symbol.endswith("TeamMemberController@fromTrait")
    assert trait.handler.citation.path.endswith("Concerns/SharedMemberActions.php")
    assert (trait.handler.citation.start_line, trait.handler.citation.end_line) == (
        6,
        6,
    )
    assert {h.fact_type for h in trait.hints if h.kind == "model"} == {
        "fact_type:root/team-user"
    }
    assert not result.model.exchange_rules


@pytest.mark.parametrize("options_array", [False, True])
def test_api_resource_expands_to_listed_actions(
    project: Path, options_array: bool
) -> None:
    if options_array:
        for path in (project / "routes").rglob("*.php"):
            source = re.sub(
                r"\)->(only|except)\((\[[^\n]*?\]|\$actions)\)",
                r", ['\1' => \2])",
                path.read_text(),
            )
            path.write_text(source)
    result = extract(project)
    notes = [a for a in result.anchors if a.path.startswith("/notes")]
    assert {(a.method, a.path, a.handler.symbol.rsplit("@", 1)[-1]) for a in notes} == {
        ("GET", "/notes", "index"),
        ("GET", "/notes/{note}", "show"),
    }
    all_actions = [a for a in result.anchors if a.path.startswith("/all")]
    assert len(all_actions) == 6
    assert {a.handler.symbol.rsplit("@", 1)[-1] for a in all_actions} == {
        "index",
        "store",
        "show",
        "update",
        "destroy",
    }
    actions = {
        (a.method, a.path, a.handler.symbol.rsplit("@", 1)[-1])
        for a in result.anchors
        if a.kind == "http"
    }
    assert SHALLOW_ACTIONS <= actions
    for resource, parameter in RESOURCE_PARAMETERS.items():
        assert ("GET", f"/{resource}/{{{parameter}}}", "show") in actions
    assert ("GET", "/libraries/create", "create") in actions
    assert ("GET", "/libraries/{library}/edit", "edit") in actions
    assert ("GET", "/v1.0/teams/{team}/team-members", "index") in actions
    assert ("GET", "/v1.0/teams/{team}/team-members/{team_member}", "show") in actions
    assert not any(a.path.startswith("/dynamic-") for a in result.anchors)
    assert {
        f.detail for f in result.findings if f.reason == "non_literal_argument"
    } == {"only", "except", "validation rules"}


def test_same_route_twice_is_one_anchor_with_two_citations(project: Path) -> None:
    first = extract(project)
    anchors = [a for a in first.anchors if a.path == "/duplicate"]
    assert len(anchors) == 1
    anchor = anchors[0]
    assert len(anchor.citations) == 2
    assert [c.start_line for c in anchor.citations] == [24, 25]
    assert {h.name for h in anchor.hints if h.kind == "model"} == {
        "App\\Models\\TeamUser"
    }
    assert {h.name for h in anchor.hints if h.kind == "input_rule"} == {
        "email",
        "invite_code",
        "nickname",
        "age",
    }
    teams = [a for a in first.anchors if a.method == "GET" and a.path == "/teams"]
    assert len(teams) == 1
    assert len(teams[0].citations) == 5
    team_digest = hashlib.sha256(b"GET /teams").hexdigest()[:8]
    assert teams[0].id == f"anchor:root/http/get-teams-{team_digest}"
    root = next(a for a in first.anchors if a.path == "/")
    assert root.method == "GET"
    assert len(root.citations) == 2
    assert all(
        a.path == "/" or (a.path.startswith("/") and not a.path.endswith("/"))
        for a in first.anchors
        if a.kind == "http"
    )
    source = "GET /duplicate"
    digest = hashlib.sha256(source.encode()).hexdigest()[:8]
    assert anchor.id == f"anchor:root/http/{key_segment(source)}-{digest}"
    route_file = project / "routes/api.php"
    with route_file.open("a") as stream:
        stream.write(
            "Route::get('/a/b', fn () => null);\nRoute::get('/a-b', fn () => null);\n"
        )
    second = extract(project)
    assert next(a for a in second.anchors if a.path == "/duplicate") == anchor
    collisions = [a.id for a in second.anchors if a.path in {"/a/b", "/a-b"}]
    assert len(set(collisions)) == 2


@pytest.mark.parametrize("case", ["unique", "ambiguous", "non_psr4"])
def test_form_request_rules_become_input_hints(project: Path, case: str) -> None:
    ambiguous = case == "ambiguous"
    if case == "non_psr4":
        model = project / "app/Models/TeamUser.php"
        model.rename(model.with_name("Records.php"))
    if ambiguous:
        controller = project / "app/Http/Controllers/TeamMemberController.php"
        controller.write_text(
            controller.read_text().replace(
                "TeamUser $member)", r"TeamUser $member, \App\Models\Team $team)"
            )
        )
    result = extract(project)
    anchor = next(
        a
        for a in result.anchors
        if a.method == "POST" and a.path == "/teams/{team}/members"
    )
    models = [h for h in anchor.hints if h.kind == "model"]
    assert {h.name for h in models} == (
        {"App\\Models\\TeamUser", "App\\Models\\Team"}
        if ambiguous
        else {"App\\Models\\TeamUser"}
    )
    assert {h.fact_type for h in models} == (
        {"fact_type:root/team-user", "fact_type:root/teams"}
        if ambiguous
        else {"fact_type:root/team-user"}
    )
    assert [h.name for h in anchor.hints if h.kind == "input_type"] == [
        "App\\Http\\Requests\\StoreTeamMemberRequest"
    ]
    rules = {h.name: h for h in anchor.hints if h.kind == "input_rule"}
    assert {name: h.value for name, h in rules.items()} == {
        "email": "required|email",
        "invite_code": "['required', 'string']",
        "nickname": "nullable|string",
        "age": "['integer', 'min:18']",
    }
    assert rules["email"].role == (None if ambiguous else "role:root/team-user/email")
    assert all(rules[name].role is None for name in ("invite_code", "nickname", "age"))
    assert rules["email"].citation.path.endswith("StoreTeamMemberRequest.php")
    assert rules["age"].citation.path.endswith("TeamMemberController.php")
    unresolved_rules = [
        f
        for f in result.findings
        if f.reason == "non_literal_argument"
        and f.citations[0].path.endswith("StoreTeamMemberRequest.php")
    ]
    assert len(unresolved_rules) == 1  # The same FormRequest is used by many routes.
    assert unresolved_rules[0].detail == "validation rules"
    assert len(result.findings) == len(set(result.findings))
    # Validation adds neither storage facts nor validation/exchange rules.
    assert {f.name for f in result.model.fact_types} == {"team_user", "teams"}
    assert {r.rule_kind for r in result.model.validation_rules} == {"uniqueness"}
    assert not result.model.exchange_rules


def test_route_in_loop_is_reported_not_guessed(project: Path) -> None:
    result = extract(project)
    dynamic = [f for f in result.findings if f.reason == "dynamic_registration"]
    assert len(dynamic) == 11
    assert all(f.kind == "unresolved" and f.subject is None for f in dynamic)
    assert {
        f.citations[0].start_line
        for f in dynamic
        if f.citations[0].path == "routes/api.php"
    } == {31, 33, 34, 35, 36}
    assert {
        f.citations[0].start_line
        for f in dynamic
        if f.citations[0].path == "routes/extra/groups.php"
    } == {12, 13, 14, 15, 16, 17}
    assert not {a.path for a in result.anchors} & {
        "/loop",
        "/for",
        "/while",
        "/dynamic-handler",
        "/unknown-prefix",
        "/unknown-controller",
        "/each",
        "/map",
        "/array-map",
        "/array-walk",
    }
    assert {f.reason for f in result.findings} == {
        "dynamic_registration",
        "handler_not_found",
        "non_literal_argument",
    }


def test_command_signature_is_an_anchor(project: Path) -> None:
    commands = [a for a in extract(project).anchors if a.kind == "command"]
    assert {a.path for a in commands} == {"teams:sync", "teams:clean"}
    for anchor in commands:
        assert anchor.method is None
        assert not any(h.kind == "operation" for h in anchor.hints)
        digest = hashlib.sha256(anchor.path.encode()).hexdigest()[:8]
        assert anchor.id == f"anchor:root/command/{key_segment(anchor.path)}-{digest}"
        assert anchor.handler.citation is not None
    sync = next(a for a in commands if a.path == "teams:sync")
    assert sync.handler.symbol == "App\\Console\\Commands\\SyncTeams@handle"
    assert (sync.handler.citation.start_line, sync.handler.citation.end_line) == (6, 6)
    assert (
        next(a for a in commands if a.path == "teams:clean").handler.symbol == "closure"
    )


def test_missing_controller_keeps_anchor_and_reports_handler(project: Path) -> None:
    result = extract(project)
    missing = [a for a in result.anchors if a.path.startswith("/missing")]
    assert len(missing) == 2
    for anchor in missing:
        assert anchor.handler is not None and anchor.handler.citation is None
        finding = next(f for f in result.findings if f.subject == anchor.id)
        assert finding.kind == "unresolved" and finding.reason == "handler_not_found"
        assert finding.detail == anchor.handler.symbol
        assert finding.citations == anchor.citations
    assert (
        next(a for a in missing if a.path == "/missing").handler.symbol
        == "MissingController@show"
    )

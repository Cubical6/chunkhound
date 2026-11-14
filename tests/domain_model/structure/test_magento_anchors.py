"""Magento entry points preserve source paths, handlers and input hints."""

import shutil
from pathlib import Path

import pytest

from chunkhound.domain_model.structure.contract import RepositoryRef
from chunkhound.domain_model.structure.extract import build_structure

FIXTURE = Path(__file__).parent / "fixtures" / "magento_anchors"
OWN = "app/code/Acme/Notes"
VENDOR = "vendor/acme/notes"
REPOSITORIES = (RepositoryRef(key="root", path=".", commit="1" * 40, dirty=False),)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    destination = tmp_path / "project"
    shutil.copytree(FIXTURE, destination)
    (destination / "dot-gitignore").rename(destination / ".gitignore")
    return destination


@pytest.mark.parametrize("missing", [None, "class", "method", "inherited"])
def test_webapi_route_is_an_anchor_with_service_handler(
    project: Path, missing: str | None
) -> None:
    interface = project / VENDOR / "src/Api/NoteReaderInterface.php"
    expected_interface = interface
    if missing == "inherited":
        # The first branch cycles; the method is on the second branch's parent.
        for name, body in (
            ("FirstInterface", "extends NoteReaderInterface {}"),
            ("SecondInterface", "extends ThirdInterface {}"),
            (
                "ThirdInterface",
                "{ public function get("
                "\\Acme\\Notes\\Api\\Data\\NoteInterface $note); }",
            ),
        ):
            (interface.parent / f"{name}.php").write_text(
                f"<?php\nnamespace Vendor\\Notes\\Api;\ninterface {name} {body}\n"
            )
        interface.write_text(
            "<?php\nnamespace Vendor\\Notes\\Api;\n"
            "interface NoteReaderInterface extends FirstInterface, SecondInterface {}\n"
        )
        expected_interface = interface.parent / "ThirdInterface.php"
    elif missing == "class":
        interface.unlink()
    elif missing == "method":
        interface.write_text(
            interface.read_text().replace("function get(", "function other(")
        )
    result = build_structure(project, REPOSITORIES)
    assert len(result.anchors) == 5
    anchor = next(a for a in result.anchors if a.path == "/V1/notes/:noteId")
    assert anchor.kind == "http" and anchor.method == "GET"
    assert anchor.source == "magento_webapi"
    assert anchor.handler is not None
    assert anchor.handler.symbol == "Vendor\\Notes\\Api\\NoteReaderInterface@get"
    assert any(h.kind == "operation" and h.value == "read" for h in anchor.hints)
    if missing in {"class", "method"}:
        assert anchor.handler.citation is None
        assert any(
            f.kind == "unresolved"
            and f.reason == "handler_not_found"
            and f.subject == anchor.id
            for f in result.findings
        )
    else:
        citation = anchor.handler.citation
        assert (
            citation
            and citation.path == expected_interface.relative_to(project).as_posix()
        )
        assert (
            "public function get("
            in expected_interface.read_text().splitlines()[citation.start_line - 1]
        )
        assert [(h.kind, h.name) for h in anchor.hints if h.kind == "input_type"] == [
            ("input_type", "Acme\\Notes\\Api\\Data\\NoteInterface")
        ]
    assert not result.model.fact_types
    assert not any(h.kind == "model" for a in result.anchors for h in a.hints)


@pytest.mark.parametrize(
    "configuration",
    [
        "global",
        "rest",
        "missing_class",
        "missing_method",
        "no_preference",
        "trait",
        "parent_trait",
        "inheritdoc",
        "variadic_and_pseudo",
    ],
)
def test_preference_points_handler_at_implementation(
    project: Path, configuration: str
) -> None:
    di = project / OWN / "etc/di.xml"
    implementation = project / OWN / "Model/NoteRepository.php"
    if configuration == "rest":
        rest = di.parent / "webapi_rest/di.xml"
        rest.parent.mkdir()
        di.rename(rest)
        later = project / "packages/z-later"
        (later / "etc").mkdir(parents=True)
        (later / "registration.php").write_text("<?php // registered module\n")
        (later / "etc/module.xml").write_text(
            '<config><module name="Z_Later"/></config>\n'
        )
        (later / "etc/di.xml").write_text(
            '<config><preference for="Acme\\Notes\\Api\\NoteRepositoryInterface" '
            'type="Z\\Later\\WrongRepository"/></config>\n'
        )
    elif configuration == "missing_class":
        implementation.unlink()
    elif configuration == "missing_method":
        implementation.write_text(
            implementation.read_text().replace("function save(", "function other(")
        )
    elif configuration == "no_preference":
        di.unlink()
    elif configuration in {"trait", "parent_trait"}:
        trait = implementation.with_name("SaveTrait.php")
        trait.write_text(
            implementation.read_text().replace(
                "class NoteRepository", "trait SaveTrait"
            )
        )
        if configuration == "trait":
            implementation.write_text(
                "<?php\nnamespace Acme\\Notes\\Model;\n"
                "class NoteRepository { use SaveTrait; }\n"
            )
        else:
            implementation.with_name("BaseRepository.php").write_text(
                "<?php\nnamespace Acme\\Notes\\Model;\n"
                "abstract class BaseRepository { use SaveTrait; }\n"
            )
            implementation.write_text(
                "<?php\nnamespace Acme\\Notes\\Model;\n"
                "class NoteRepository extends BaseRepository {}\n"
            )
    elif configuration == "inheritdoc":
        implementation.write_text(
            "<?php\nnamespace Acme\\Notes\\Model;\nclass NoteRepository {\n"
            "    /** {@inheritdoc} */\n    public function save($renamed) {}\n}\n"
        )
    elif configuration == "variadic_and_pseudo":
        implementation = project / OWN / "Api/Data/NoteRepository.php"
        di.write_text(
            di.read_text().replace("Model\\NoteRepository", "Api\\Data\\NoteRepository")
        )
        pseudo = (
            "string",
            "int",
            "float",
            "bool",
            "array",
            "mixed",
            "null",
            "self",
            "static",
            "callable",
            "iterable",
            "object",
            "void",
            "false",
            "true",
        )
        implementation.write_text(
            "<?php\nnamespace Acme\\Notes\\Api\\Data;\nclass NoteRepository {\n/**\n"
            + "".join(f" * @param {name} $p{i}\n" for i, name in enumerate(pseudo))
            + " * @param NoteInterface ...$notes\n */\npublic function save("
            + ", ".join([*(f"$p{i}" for i in range(len(pseudo))), "...$notes"])
            + ") {}\n}\n"
        )
    result = build_structure(project, REPOSITORIES)
    anchor = next(a for a in result.anchors if a.path == "/V1/notes")
    assert anchor.method == "POST"
    assert (
        anchor.handler
        and anchor.handler.symbol == "Acme\\Notes\\Api\\NoteRepositoryInterface@save"
    )
    assert any(h.kind == "operation" and h.value == "add" for h in anchor.hints)
    citation = anchor.handler.citation
    if configuration.startswith("missing_"):
        assert citation is None
        assert any(
            f.reason == "handler_not_found" and f.subject == anchor.id
            for f in result.findings
        )
    else:
        expected = {
            "no_preference": "Api/NoteRepositoryInterface.php",
            "trait": "Model/SaveTrait.php",
            "parent_trait": "Model/SaveTrait.php",
            "variadic_and_pseudo": "Api/Data/NoteRepository.php",
        }.get(configuration, "Model/NoteRepository.php")
        assert citation and citation.path == f"{OWN}/{expected}"
        lines = (project / citation.path).read_text().splitlines()
        assert "function save(" in lines[citation.start_line - 1]
        assert [h.name for h in anchor.hints if h.kind == "input_type"] == [
            "Acme\\Notes\\Api\\Data\\NoteInterface"
        ]
        assert all(h.fact_type is None and h.role is None for h in anchor.hints)


@pytest.mark.parametrize("inherited", [False, True])
@pytest.mark.parametrize("unmapped", [False, True])
def test_controller_action_is_an_anchor_with_interface_method(
    project: Path, inherited: bool, unmapped: bool
) -> None:
    if inherited:
        api = project / OWN / "Api"
        for name, bases in (
            ("PostInterface", r"\magento\framework\app\action\httppostactioninterface"),
            ("LoopInterface", "CompositeInterface"),
            (
                "CompositeInterface",
                r"LoopInterface, PostInterface, "
                r"\Magento\Framework\App\Action\HttpPatchActionInterface",
            ),
        ):
            (api / f"{name}.php").write_text(
                "<?php\nnamespace Acme\\Notes\\Api;\n"
                f"interface {name} extends {bases} {{}}\n"
            )
        parent = project / OWN / "Controller/Note/BaseAction.php"
        parent.write_text(
            "<?php\nnamespace Acme\\Notes\\Controller\\Note;\n"
            "use Acme\\Notes\\Api\\CompositeInterface as Action;\n"
            "abstract class BaseAction implements action {\n"
            "    public function execute() {}\n}\n"
        )
        (project / OWN / "Controller/Note/Save.php").write_text(
            "<?php\nnamespace Acme\\Notes\\Controller\\Note;\n"
            "use Acme\\Notes\\Controller\\Note\\BaseAction as ParentAction;\n"
            "class Save extends ParentAction {}\n"
        )
        (project / OWN / "Controller/Note/NotAnAction.php").write_text(
            "<?php\nnamespace Acme\\Notes\\Controller\\Note;\n"
            "interface NotAnAction {}\n"
        )
    controller = project / OWN / "Controller/Note/Save.php"
    contents = (
        controller.read_text() + "\nclass Helper { public function execute() {} }\n"
    )
    if unmapped:
        contents = contents.replace(
            "namespace Acme\\Notes\\Controller\\Note;",
            "namespace Custom\\Controller\\Note;",
        )
    controller.write_text(contents)
    if not inherited:
        controller.write_text(
            controller.read_text().replace(
                "implements HttpPostActionInterface",
                "implements httppostactioninterface",
            )
        )
    result = build_structure(project, REPOSITORIES)
    actions = [a for a in result.anchors if a.source == "magento_routes_frontend"]
    assert {(a.method, a.path) for a in actions} == (
        {
            ("POST", "/acme/note/save"),
            ("PATCH", "/acme/note/save"),
            ("ANY", "/acme/note/index"),
        }
        if inherited
        else {("POST", "/acme/note/save"), ("ANY", "/acme/note/index")}
    )
    for anchor in actions:
        assert anchor.handler and anchor.handler.citation
        if anchor.method == "ANY":
            assert not any(h.kind == "operation" for h in anchor.hints)
        else:
            assert anchor.handler.symbol == (
                "Custom\\Controller\\Note\\Save@execute"
                if unmapped
                else "Acme\\Notes\\Controller\\Note\\Save@execute"
            )
            expected = "BaseAction.php" if inherited else "Save.php"
            assert anchor.handler.citation.path == f"{OWN}/Controller/Note/{expected}"
            assert [h.value for h in anchor.hints if h.kind == "operation"] == [
                "change" if anchor.method == "PATCH" else "add"
            ]


@pytest.mark.parametrize("definition", ["explicit", "own", "vendor", "missing"])
@pytest.mark.parametrize("nested", [False, True])
def test_frontend_and_adminhtml_routes_have_their_own_source(
    project: Path, definition: str, nested: bool
) -> None:
    if definition != "explicit":
        donor = (
            project / VENDOR if definition == "vendor" else project / "packages/routes"
        )
        if definition == "own":
            (donor / "etc").mkdir(parents=True)
            (donor / "registration.php").write_text("<?php // registered module\n")
            (donor / "etc/module.xml").write_text(
                '<config><module name="Acme_Routes"/></config>\n'
            )
        for area, front in (("frontend", "acme"), ("adminhtml", "acme_admin")):
            routes = project / OWN / f"etc/{area}/routes.xml"
            routes.write_text(
                '<config><router id="standard"><route id="shared">\n'
                '    <module name="Acme_Notes"/>\n</route></router></config>\n'
            )
            if definition != "missing":
                definition_file = donor / f"etc/{area}/routes.xml"
                definition_file.parent.mkdir(parents=True, exist_ok=True)
                definition_file.write_text(
                    '<config><router id="standard">'
                    f'<route id="shared" frontName="{front}">'
                    '<module name="Vendor_Notes"/></route></router></config>\n'
                )
    if nested:
        for prefix, name in (("Controller", "Save"), ("Controller/Adminhtml", "Edit")):
            original = project / OWN / f"{prefix}/Note/{name}.php"
            destination = original.parent / "Batch" / original.name
            destination.parent.mkdir()
            original.rename(destination)
    result = build_structure(project, REPOSITORIES)
    if definition == "missing":
        assert len(result.anchors) == 2
        unresolved = [f for f in result.findings if f.reason == "vendor_not_followed"]
        assert len(unresolved) == 2
        assert all(
            f.kind == "external_reference"
            and f.subject is None
            and f.detail == "route shared"
            for f in unresolved
        )
        assert {f.citations[0].path for f in unresolved} == {
            f"{OWN}/etc/frontend/routes.xml",
            f"{OWN}/etc/adminhtml/routes.xml",
        }
        for finding in unresolved:
            citation = finding.citations[0]
            lines = (project / citation.path).read_text().splitlines()
            assert '<route id="shared">' in lines[citation.start_line - 1]
            assert "</route>" in lines[citation.end_line - 1]
        return
    directory = "note_batch" if nested else "note"
    assert len(result.anchors) == 5
    assert {
        (a.path, a.source) for a in result.anchors if a.source != "magento_webapi"
    } == {
        (f"/acme/{directory}/save", "magento_routes_frontend"),
        ("/acme/note/index", "magento_routes_frontend"),
        (f"/acme_admin/{directory}/edit", "magento_routes_adminhtml"),
    }
    admin = next(a for a in result.anchors if a.source == "magento_routes_adminhtml")
    assert admin.method == "GET"
    assert admin.handler and admin.handler.citation
    relative = "Note/Batch/Edit.php" if nested else "Note/Edit.php"
    assert admin.handler.citation.path == f"{OWN}/Controller/Adminhtml/{relative}"
    assert admin.citations[0].path == f"{OWN}/etc/adminhtml/routes.xml"


def test_vendor_modules_give_no_anchors(project: Path) -> None:
    # An own route configuration must not turn a vendor module into own actions.
    routes = project / OWN / "etc/frontend/routes.xml"
    routes.write_text(
        routes.read_text().replace(
            '<module name="Acme_Notes"/>',
            '<module name="Acme_Notes"/><module name="Vendor_Notes"/>',
        )
    )
    result = build_structure(project, REPOSITORIES)
    assert len(result.anchors) == 5
    assert all(
        not c.path.startswith("vendor/") for a in result.anchors for c in a.citations
    )
    assert not any("vendor-notes" in a.path for a in result.anchors)
    assert any(
        a.handler
        and a.handler.citation
        and a.handler.citation.path.startswith("vendor/")
        for a in result.anchors
    )

"""Runtime boundaries and configuration evidence are observable C4 contracts."""

from pathlib import Path

from chunkhound.code_mapper.c4.runtime import RuntimeScan, scan_runtime


def test_container_boundaries(fixture_repo: Path) -> None:
    files = sorted(
        p.relative_to(fixture_repo).as_posix()
        for p in fixture_repo.rglob("*")
        if p.is_file() and ".git" not in p.parts
    )
    scan = scan_runtime(
        project_root=fixture_repo,
        scope_path=fixture_repo,
        files=files,
        locked_containers={},
        tombstones={},
    )
    assert (scan.system_id, scan.system_name) == ("systeem:shop", "shop")
    assert {c.id for c in scan.containers} == {
        "container:shop",
        "container:web",
        "container:acme-admin",
    }
    assert {c.manifest for c in scan.containers} == {
        "pyproject.toml",
        "web/package.json",
        "admin/composer.json",
    }
    for file in files:
        expected = (
            "container:web"
            if file.startswith("web/")
            else "container:acme-admin"
            if file.startswith("admin/")
            else "container:shop"
        )
        assert scan.container_of[file] == expected
    for container in scan.containers:
        citation = next(c for c in container.citations if c.file == container.manifest)
        assert citation.source == "configuration"
        assert citation.target == container.id
        assert citation.verified
        assert citation.start_line == citation.end_line == 2
    assert {(s.key, s.file, s.line) for s in scan.storage} >= {
        ("/data", "Dockerfile", 4),
        ("data_dir", "shop/storage.py", 13),
    }
    assert [(d.name, d.manifest, d.line) for d in scan.dependencies] == [
        ("requests", "pyproject.toml", 4)
    ]


def test_dockerfile_does_not_promote_template_package(tmp_path: Path) -> None:
    sources = {
        "package.json": '{"name":"app","bin":"main.js"}',
        "main.js": "console.log('app');\n",
        "templates/package.json": (
            '{"name":"${APP}","bin":"run.js","dependencies":{"template-only":"1"}}'
        ),
        "templates/Dockerfile": "FROM scratch\n",
        "templates/run.js": "console.log('template');\n",
        "image/package.json": "{}",
        "image/Dockerfile": "FROM scratch\n",
    }
    for name, text in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    scan = scan_runtime(
        project_root=tmp_path,
        scope_path=tmp_path,
        files=list(sources),
        locked_containers={},
        tombstones={},
        accepted={"templates/package.json": True},
    )
    assert {c.id for c in scan.containers} == {"container:app", "container:image"}
    assert {c.manifest for c in scan.containers} == {
        "package.json",
        "image/Dockerfile",
    }
    assert all(
        scan.container_of[file] == "container:app"
        for file in sources
        if file.startswith("templates/")
    )
    assert scan.uncertain == []
    assert scan.dependencies == []


def test_scope_without_manifest_or_git(tmp_path: Path) -> None:
    scope = tmp_path / "Plain App"
    scope.mkdir()
    (scope / "main.py").write_text("pass\n", encoding="utf-8")
    scan = scan_runtime(
        project_root=tmp_path,
        scope_path=scope,
        files=["Plain App/main.py"],
        locked_containers={},
        tombstones={},
    )
    assert (scan.system_id, scan.system_name) == ("systeem:plain-app", "Plain App")
    assert len(scan.containers) == 1
    container = scan.containers[0]
    assert container.id == "container:plain-app"
    assert container.root == "Plain App"
    assert container.markers == ("provisional",)
    assert scan.container_of == {"Plain App/main.py": container.id}
    assert container.citations == ()  # No invented configuration evidence.
    removed_manifest = scan_runtime(
        project_root=tmp_path,
        scope_path=scope,
        files=["Plain App/main.py"],
        locked_containers={"Plain App/pyproject.toml": "container:plain-app"},
        tombstones={},
    )
    assert removed_manifest.containers[0].id == "container:plain-app-2"


def test_explicit_startpoints_classification_and_storage_types(tmp_path: Path) -> None:
    sources = {
        "package.json": '{"name":"workspace"}',
        "lib/pyproject.toml": (
            '[project]\nname = "library"\ndependencies = ["httpx>=1"]\n'
        ),
        "bin/Cargo.toml": '[package]\nname = "worker"\n[dependencies]\nserde = "1"\n',
        "bin/src/main.rs": "fn main() {}\n",
        "explicit/Cargo.toml": (
            '[package]\nname="tool"\n[[bin]]\nname="one"\npath="one.rs"\n'
            '[[bin]]\nname="two"\npath="two.rs"\n'
        ),
        "image/Dockerfile": 'FROM scratch\nVOLUME ["/cache", "/logs"]\n',
        "compose.yaml": (
            "services:\n  web:\n    volumes:\n      - ./state:/data\n"
            "volumes:\n  cache:\n"
        ),
        "config.py": (
            'from pathlib import Path as P\ncache: P = P("cache")\n'
            'name: str = "data_dir"\n'
        ),
        "templates/package.json": '{"name":"${APP}","bin":"run.js"}',
    }
    for name, text in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    kwargs = dict(
        project_root=tmp_path,
        scope_path=tmp_path,
        files=list(sources),
        locked_containers={},
        tombstones={},
    )
    scan = scan_runtime(**kwargs)
    assert scan.system_id == "systeem:workspace"
    assert {c.id for c in scan.containers} == {
        "container:worker",
        "container:tool",
        "container:image",
    }
    assert {c.manifest for c in scan.uncertain} == {
        "package.json",
        "lib/pyproject.toml",
    }
    accepted = scan_runtime(**kwargs, accepted={"lib/pyproject.toml": True})
    assert "container:library" in {c.id for c in accepted.containers}
    assert accepted.container_of["lib/pyproject.toml"] == "container:library"
    assert {(s.key, s.file, s.line) for s in scan.storage} == {
        ("/cache", "image/Dockerfile", 2),
        ("/logs", "image/Dockerfile", 2),
        ("/data", "compose.yaml", 4),
        ("cache", "compose.yaml", 6),
        ("cache", "config.py", 2),
    }
    assert {(d.name, d.manifest, d.line) for d in scan.dependencies} == {
        ("httpx", "lib/pyproject.toml", 3),
        ("serde", "bin/Cargo.toml", 4),
    }


def _scan_sources(
    root: Path, sources: dict[str, str], accepted: dict[str, bool] | None = None
) -> RuntimeScan:
    for name, text in sources.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return scan_runtime(
        project_root=root,
        scope_path=root,
        files=list(sources),
        locked_containers={},
        tombstones={},
        accepted=accepted or {},
    )


_PYTHON_APP = '[project]\nname = "chunkhound"\n[project.scripts]\nch = "app:main"\n'
_PYTHON_LIB = '[project]\nname = "chunkhound"\n'
_RUST_LIB = '[package]\nname = "native"\n'
_CDYLIB = (
    '[package]\nname = "native"\n[lib]\ncrate-type = ["cdylib"]\n'
    '[dependencies]\npyo3 = "0.22"\n'
)


def test_system_name_prefers_selected_root_container(tmp_path: Path) -> None:
    scan = _scan_sources(
        tmp_path, {"Cargo.toml": _RUST_LIB, "pyproject.toml": _PYTHON_APP}
    )
    assert (scan.system_id, scan.system_name) == ("systeem:chunkhound", "chunkhound")
    assert [c.name for c in scan.containers] == ["chunkhound"]


def test_system_name_falls_back_to_first_root_manifest(tmp_path: Path) -> None:
    scan = _scan_sources(
        tmp_path,
        {
            "Cargo.toml": _RUST_LIB,
            "pyproject.toml": _PYTHON_LIB,
            "tool/package.json": '{"name":"tool","bin":"run.js"}',
        },
    )
    assert scan.system_name == "native"
    assert [c.name for c in scan.containers] == ["tool"]


def test_system_name_falls_back_to_directory_name(tmp_path: Path) -> None:
    root = tmp_path / "Plain App"
    scan = _scan_sources(root, {"tool/package.json": '{"name":"tool","bin":"run.js"}'})
    assert scan.system_name == "Plain App"


def test_cdylib_beside_another_manifest_is_no_candidate(tmp_path: Path) -> None:
    sources = {"Cargo.toml": _CDYLIB, "pyproject.toml": _PYTHON_LIB}
    for accepted in ({}, {"Cargo.toml": True}):
        scan = _scan_sources(tmp_path, sources, accepted)
        assert scan.system_name == "chunkhound"
        assert "Cargo.toml" not in {c.manifest for c in scan.uncertain}
        assert "Cargo.toml" not in {c.manifest for c in scan.containers}
        assert ("pyo3", "Cargo.toml", 6) in {
            (d.name, d.manifest, d.line) for d in scan.dependencies
        }


def test_mixed_crate_types_still_count_as_cdylib(tmp_path: Path) -> None:
    crate = '[package]\nname = "native"\n[lib]\ncrate-type = ["cdylib", "rlib"]\n'
    scan = _scan_sources(tmp_path, {"Cargo.toml": crate, "pyproject.toml": _PYTHON_LIB})
    assert "Cargo.toml" not in {c.manifest for c in scan.uncertain}


def test_cdylib_with_a_binary_stays_its_own_container(tmp_path: Path) -> None:
    crate = (
        '[package]\nname = "native"\n[lib]\ncrate-type = ["cdylib"]\n'
        '[[bin]]\nname = "native-cli"\npath = "src/cli.rs"\n'
    )
    scan = _scan_sources(tmp_path, {"Cargo.toml": crate, "pyproject.toml": _PYTHON_LIB})
    assert "Cargo.toml" in {c.manifest for c in scan.containers}


def test_cdylib_alone_in_its_directory_stays_a_candidate(tmp_path: Path) -> None:
    sources = {"Cargo.toml": _CDYLIB, "web/package.json": '{"name":"web"}'}
    scan = _scan_sources(tmp_path, sources)
    assert "Cargo.toml" in {c.manifest for c in scan.uncertain}
    assert scan.system_name == "native"
    accepted = _scan_sources(tmp_path, sources, {"Cargo.toml": True})
    assert "Cargo.toml" in {c.manifest for c in accepted.containers}

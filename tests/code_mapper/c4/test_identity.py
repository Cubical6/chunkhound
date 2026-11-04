"""Stable public IDs, including the container portion of the R3/R4 contract."""

from pathlib import Path

import pytest

from chunkhound.code_mapper.c4.identity import (
    assign_component_ids,
    detect_renames,
    element_id,
)
from chunkhound.code_mapper.c4.model import ElementKind
from chunkhound.code_mapper.c4.runtime import assign_container_ids
from chunkhound.utils.git_safe import run_git


def test_component_identity_majority() -> None:
    names = {"frontend/package.json": "app", "backend/package.json": "app"}
    assert assign_container_ids(names, {}, {}) == {
        "frontend/package.json": "container:frontend-app",
        "backend/package.json": "container:backend-app",
    }
    locked = {"frontend/package.json": "container:app"}
    assert assign_container_ids(names, locked, {}) == {
        "frontend/package.json": "container:app",
        "backend/package.json": "container:backend-app",
    }
    # A removed manifest's ID stays reserved; moving does not inherit it.
    assert assign_container_ids({"backend/package.json": "app"}, locked, {}) == {
        "backend/package.json": "container:backend-app"
    }
    tombstones = {"old/package.json": "container:backend-app"}
    assert assign_container_ids(
        {"backend/package.json": "app"}, locked, tombstones
    ) == {"backend/package.json": "container:backend-app-2"}
    # Path normalization collisions use deterministic path order, not input order.
    collisions = {"a_b/package.json": "app", "a-b/package.json": "app"}
    assert assign_container_ids(collisions, {}, {}) == {
        "a-b/package.json": "container:a-b-app",
        "a_b/package.json": "container:a-b-app-2",
    }
    assert locked == {"frontend/package.json": "container:app"}
    assert tombstones == {"old/package.json": "container:backend-app"}

    files = frozenset(f"shop/file_{i}.py" for i in range(10))
    previous = {"component:orders": files}
    for count, expected in (
        (8, "component:orders"),
        (5, "component:renamed"),
        (6, "component:orders"),
    ):
        kept = frozenset(f"shop/file_{i}.py" for i in range(count))
        remainder = files - kept
        current = {"b": ("Renamed", kept), "c": ("Other", remainder)}
        if count == 8:
            current = {"b": ("Renamed", kept | {"shop/new_1.py", "shop/new_2.py"})}
        result = assign_component_ids(
            previous=previous,
            current=current,
            renames={},
            taken_found=frozenset(),
            documented_without_files=frozenset(),
            tombstones={},
        )
        assert result.ids["b"] == expected
        pairs = {(e.from_id, e.to_id, e.kind) for e in result.history}
        if count == 8:
            assert pairs == {("component:orders", "component:orders", "continuation")}
            assert result.tombstones == {}
        else:
            assert result.ids["c"] == "component:other"
            assert ("component:orders", expected, "split") in pairs
            assert ("component:orders", "component:other", "split") in pairs
            assert ("", "component:other", "new") in pairs
            assert result.tombstones == (
                {"component:orders": "component:orders"} if count == 5 else {}
            )
            assert (("component:orders", "", "removed") in pairs) == (count == 5)
    assert previous == {"component:orders": files}


@pytest.mark.parametrize(
    ("kind", "term", "expected"),
    [
        ("system", "Shop", "system:shop"),
        ("container", "Order API", "container:order-api"),
        ("storage", "DATA_DIR", "storage:data-dir"),
        ("external", "acme/pay", "external:acme-pay"),
        (
            "person",
            "Ontwikkelaar met AI-assistent",
            "person:ontwikkelaar-met-ai-assistent",
        ),
        ("component", " Café / Orders ", "component:caf-orders"),
    ],
)
def test_element_id(kind: ElementKind, term: str, expected: str) -> None:
    assert element_id(kind, term) == expected


def test_component_renames_and_noncomparable_files() -> None:
    result = assign_component_ids(
        previous={"component:orders": frozenset({"shop/orders.py", "deleted.py"})},
        current={"b": ("Order Book", frozenset({"shop/order_book.py", "added.py"}))},
        renames={"shop/orders.py": "shop/order_book.py"},
        taken_found=frozenset(),
        documented_without_files=frozenset(),
        tombstones={},
    )
    assert result.ids == {"b": "component:orders"}
    assert [(e.from_id, e.to_id, e.kind) for e in result.history] == [
        ("component:orders", "component:orders", "continuation")
    ]
    assert result.tombstones == {}


def test_component_ids_reserve_found_removed_and_tombstones() -> None:
    tombstones = {
        "component:orders": "old-sha",
        "old/package.json": "component:orders-2",
    }
    current = {
        "z": ("Orders", frozenset({"new_z.py"})),
        "a": ("Orders", frozenset({"new_a.py"})),
        "documented": ("Payments", frozenset({"pay.py"})),
    }
    result = assign_component_ids(
        previous={"component:orders-3": frozenset({"deleted.py"})},
        current=current,
        renames={},
        taken_found=frozenset({"component:orders-4"}),
        documented_without_files=frozenset({"component:payments", "component:orders"}),
        tombstones=tombstones,
    )
    assert result.ids == {
        "a": "component:orders-5",
        "documented": "component:payments",
        "z": "component:orders-6",
    }
    assert result.tombstones == {
        **tombstones,
        "component:orders-3": "component:orders-3",
    }
    assert {(e.from_id, e.to_id, e.kind) for e in result.history} == {
        ("component:orders-3", "", "removed"),
        ("", "component:orders-5", "new"),
        ("", "component:orders-6", "new"),
        ("", "component:payments", "new"),
    }
    assert tombstones == {
        "component:orders": "old-sha",
        "old/package.json": "component:orders-2",
    }

    resurrected = assign_component_ids(
        previous={},
        current={"orders": ("Orders", frozenset({"orders.py"}))},
        renames={},
        taken_found=frozenset(),
        documented_without_files=frozenset(),
        tombstones={"component:orders": "component:orders"},
    )
    assert resurrected.ids == {"orders": "component:orders-2"}


def test_component_merge_needs_mutual_majority() -> None:
    a = frozenset(f"a/{i}.py" for i in range(6))
    b = frozenset(f"b/{i}.py" for i in range(4))
    result = assign_component_ids(
        previous={"component:a": a, "component:b": b},
        current={"joined": ("Joined", a | b)},
        renames={},
        taken_found=frozenset(),
        documented_without_files=frozenset(),
        tombstones={},
    )
    assert result.ids == {"joined": "component:a"}
    assert result.tombstones == {"component:b": "component:b"}
    assert {(e.from_id, e.to_id, e.kind) for e in result.history} == {
        ("component:a", "component:a", "merge"),
        ("component:b", "component:a", "merge"),
        ("component:b", "", "removed"),
    }


def test_component_history_threshold_and_merge_precedence() -> None:
    a = frozenset(f"a/{i}.py" for i in range(20))
    b = frozenset(f"b/{i}.py" for i in range(20))
    x = frozenset({"a/0.py", "b/0.py"})
    y = (a | b) - x
    result = assign_component_ids(
        previous={"component:a": a, "component:b": b},
        current={"x": ("X", x), "y": ("Y", y)},
        renames={},
        taken_found=frozenset(),
        documented_without_files=frozenset(),
        tombstones={},
    )
    # Each 1/20 overlap still qualifies through the 1/2 successor side.
    assert {
        (e.from_id, e.to_id, e.kind) for e in result.history if e.kind == "merge"
    } == {
        (old, new, "merge")
        for old in ("component:a", "component:b")
        for new in ("component:x", "component:y")
    }
    # Neither predecessor reaches a strict majority of either successor.
    assert result.ids == {"x": "component:x", "y": "component:y"}
    assert result.tombstones == {
        "component:a": "component:a",
        "component:b": "component:b",
    }


def test_component_history_ten_percent_boundary() -> None:
    previous = {
        f"component:p{i}": frozenset(f"{i}/{j}.py" for j in range(100))
        for i in range(2)
    }
    current = {
        "x": (
            "X",
            frozenset(
                [f"0/{j}.py" for j in range(10)] + [f"1/{j}.py" for j in range(10, 100)]
            ),
        ),
        "y": (
            "Y",
            frozenset(
                [f"1/{j}.py" for j in range(10)] + [f"0/{j}.py" for j in range(10, 100)]
            ),
        ),
    }
    for count in (10, 9):
        if count == 9:
            current["x"] = ("X", current["x"][1] - {"0/9.py"} | {"1/9.py"})
            current["y"] = ("Y", current["y"][1] - {"1/9.py"} | {"0/9.py"})
        result = assign_component_ids(
            previous=previous,
            current=current,
            renames={},
            taken_found=frozenset(),
            documented_without_files=frozenset(),
            tombstones={},
        )
        pairs = {(e.from_id, e.to_id, e.kind) for e in result.history}
        assert result.ids == {"x": "component:p1", "y": "component:p0"}
        assert pairs == (
            {(old, new, "merge") for old in previous for new in previous}
            if count == 10
            else {(old, old, "continuation") for old in previous}
        )


def test_rename_detection_without_git(tmp_path: Path) -> None:
    assert detect_renames(tmp_path, "unknown-sha") is None


def test_rename_detection_from_committed_git_history(tmp_path: Path) -> None:
    def git(*args: str) -> str:
        result = run_git(args, cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    git("init", "--initial-branch=main")
    old = "orders\told.py"
    new = "order\nbook.py"
    (tmp_path / old).write_text("def orders():\n    return 42\n", encoding="utf-8")
    git("add", ".")
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "base",
    )
    base = git("rev-parse", "HEAD")
    (tmp_path / old).rename(tmp_path / new)
    (tmp_path / "added.py").write_text("added = True\n", encoding="utf-8")
    git("add", ".")
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "rename",
    )
    assert detect_renames(tmp_path, base) == {old: new}
    assert detect_renames(tmp_path, "HEAD") == {}
    assert detect_renames(tmp_path, "unknown-sha") is None

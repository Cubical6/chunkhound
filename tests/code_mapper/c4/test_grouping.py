"""Deterministic file ownership survives replay, fallback and new directories."""

from collections import Counter
from pathlib import Path

from chunkhound.code_mapper.c4.codeboarding.names import (
    ROOT_SCOPE_ID,
    ComponentRule,
    ScopeSpec,
    TreeSpec,
)
from chunkhound.code_mapper.c4.grouping import GroupingResult, build_groups
from chunkhound.code_mapper.c4.model import Reference


def write_sources(root: Path, sources: dict[str, str]) -> None:
    for file, content in sources.items():
        path = root / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def stored_trees(result: GroupingResult) -> dict[str, dict]:
    return {container: tree.to_dict() for container, tree in result.tree_specs.items()}


def owners(result: GroupingResult) -> dict[str, str]:
    return {file: group.id for group in result.groups for file in group.files}


def test_groups_are_deterministic_and_replay(tmp_path: Path) -> None:
    sources = {
        "app/pyproject.toml": '[project]\nname = "shop"\n',
        "app/orders/create.py": "class CreateOrder: pass\n",
        "app/orders/submit.py": "class SubmitOrder: pass\n",
        "app/payments/charge.py": "class ChargePayment: pass\n",
        "app/payments/refund.py": "class RefundPayment: pass\n",
        "web/src/index.ts": "export function start() { return 1; }\n",
    }
    write_sources(tmp_path, sources)
    bindings = {
        file: "container:web" if file.startswith("web/") else "container:shop"
        for file in sources
    }
    roots = {"container:shop": "app", "container:web": "web"}
    references = [
        Reference.model_validate(
            {
                "relation": None,
                "from": "app/orders/create.py",
                "line": 1,
                "to": "app/payments/charge.py",
                "kind": "call",
                "status": "counts",
            }
        ),
    ]
    first = build_groups(
        project_root=tmp_path,
        files=list(sources),
        container_of=bindings,
        container_roots=roots,
        references=references,
        stored={},
        stored_membership={},
    )
    second = build_groups(
        project_root=tmp_path,
        files=list(reversed(sources)),
        container_of=bindings,
        container_roots=roots,
        references=list(reversed(references)),
        stored={},
        stored_membership={},
    )
    assert first.groups == second.groups
    assert stored_trees(first) == stored_trees(second)
    assert first.group_membership == second.group_membership
    assert Counter(file for group in first.groups for file in group.files) == Counter(
        sources.keys()
    )
    assert first.new_group_ids == frozenset(group.id for group in first.groups)
    assert all(group.id.startswith(group.container + "/") for group in first.groups)
    assert (
        len({owners(first)[file] for file in sources if file.startswith("app/")}) >= 2
    )

    addition = "app/orders/update.py"
    write_sources(tmp_path, {addition: "class UpdateOrder: pass\n"})
    bindings[addition] = "container:shop"
    known = build_groups(
        project_root=tmp_path,
        files=list(bindings),
        container_of=bindings,
        container_roots=roots,
        references=references,
        stored=stored_trees(first),
        stored_membership=first.group_membership,
    )
    assert owners(known)[addition] == owners(first)["app/orders/create.py"]
    assert known.new_group_ids == frozenset()
    assert {file: owners(known)[file] for file in sources} == owners(first)

    addition = "app/analytics/report.py"
    write_sources(tmp_path, {addition: "class RevenueReport: pass\n"})
    bindings[addition] = "container:shop"
    changed = build_groups(
        project_root=tmp_path,
        files=list(bindings),
        container_of=bindings,
        container_roots=roots,
        references=references,
        stored=stored_trees(known),
        stored_membership=known.group_membership,
    )
    assert changed.new_group_ids == frozenset({owners(changed)[addition]})
    assert owners(changed)[addition] not in set(owners(known).values())
    assert {
        file: owners(changed)[file] for file in known.group_membership["container:shop"]
    } == {
        file: owners(known)[file] for file in known.group_membership["container:shop"]
    }
    assert Counter(file for group in changed.groups for file in group.files) == Counter(
        bindings.keys()
    )
    replayed = build_groups(
        project_root=tmp_path,
        files=list(bindings),
        container_of=bindings,
        container_roots=roots,
        references=references,
        stored=stored_trees(changed),
        stored_membership=changed.group_membership,
    )
    assert replayed.groups == changed.groups
    assert stored_trees(replayed) == stored_trees(changed)
    assert replayed.group_membership == changed.group_membership
    assert replayed.new_group_ids == frozenset()


def test_known_term_and_fallback_members_stay_while_new_directory_is_grouped(
    tmp_path: Path,
) -> None:
    container = "container:app"
    scope = ScopeSpec(
        ROOT_SCOPE_ID,
        rules=[
            ComponentRule("1", "Orders", prefixes=(("orders",),), terms=("order",)),
            ComponentRule("2", "Loose files", fallback_prefixes=((),)),
        ],
        rung="frontier",
        last_id=7,
    )
    tree = TreeSpec(scopes={ROOT_SCOPE_ID: scope})
    baseline = {
        "app/orders/main.py": "1",
        "app/misc/order.py": "1",  # A known term-owned file outside the named prefix.
        "app/misc/legacy.py": "2",  # Its symbol now votes for Orders; membership wins.
        "app/settings.py": "2",
    }
    sources = {file: "class OrderHandler: pass\n" for file in baseline} | {
        # New directory, caught by terms and root fallback respectively.
        "app/reports/one.py": "class OrderReport: pass\n",
        "app/reports/two.py": "VALUE = 1\n",
        "app/misc/new.py": "VALUE = 2\n",  # Known fallback directory, not new.
        "app/misc/nested/one.py": "VALUE = 3\n",  # New below fallback residue.
    }
    write_sources(tmp_path, sources)
    result = build_groups(
        project_root=tmp_path,
        files=list(sources),
        container_of=dict.fromkeys(sources, container),
        container_roots={container: "app"},
        references=[],
        stored={container: tree.to_dict()},
        stored_membership={container: baseline},
    )
    current = result.group_membership[container]
    assert {file: current[file] for file in baseline} == baseline
    assert current["app/misc/new.py"] == "2"
    reports_id = current["app/reports/one.py"]
    nested_id = current["app/misc/nested/one.py"]
    assert reports_id == current["app/reports/two.py"]
    assert reports_id != nested_id
    assert result.new_group_ids == frozenset(
        {f"{container}/{reports_id}", f"{container}/{nested_id}"}
    )
    assert all(int(local_id) > 7 for local_id in (reports_id, nested_id))
    new_rules = [
        r
        for r in result.tree_specs[container].scope(ROOT_SCOPE_ID).rules
        if r.component_id in {reports_id, nested_id}
    ]
    assert all(
        rule.prefixes and not rule.terms and not rule.fallback_prefixes
        for rule in new_rules
    )
    replayed = build_groups(
        project_root=tmp_path,
        files=list(reversed(sources)),
        container_of=dict.fromkeys(sources, container),
        container_roots={container: "app"},
        references=[],
        stored=stored_trees(result),
        stored_membership=result.group_membership,
    )
    assert replayed.groups == result.groups
    assert replayed.new_group_ids == frozenset()
    assert stored_trees(replayed) == stored_trees(result)
    assert tree.to_dict()["scopes"][ROOT_SCOPE_ID]["last_id"] == 7
    assert baseline["app/misc/legacy.py"] == "2"


def test_explicit_root_survives_changed_file_parent_ancestry(tmp_path: Path) -> None:
    container = "container:provisional"
    original = {
        "scope/src/feature/one.py": "class One: pass\n",
        "scope/src/feature/two.py": "class Two: pass\n",
    }
    write_sources(tmp_path, original)
    first = build_groups(
        project_root=tmp_path,
        files=list(original),
        container_of=dict.fromkeys(original, container),
        container_roots={container: "scope"},
        references=[],
        stored={},
        stored_membership={},
    )
    updated = original | {"scope/tool.py": "VALUE = 1\n"}
    write_sources(tmp_path, {"scope/tool.py": updated["scope/tool.py"]})
    second = build_groups(
        project_root=tmp_path,
        files=list(updated),
        container_of=dict.fromkeys(updated, container),
        container_roots={container: "scope"},
        references=[],
        stored=stored_trees(first),
        stored_membership=first.group_membership,
    )
    assert {file: owners(second)[file] for file in original} == owners(first)
    scope = first.tree_specs[container].scope(ROOT_SCOPE_ID)
    assert any(
        prefix[:2] == ("src", "feature")
        for rule in scope.rules
        for prefix in rule.prefixes
    )
    assert set(owners(second)) == set(updated)


def test_unplaced_and_unparseable_files_are_not_dropped(tmp_path: Path) -> None:
    container = "container:app"
    tree = TreeSpec(
        scopes={
            ROOT_SCOPE_ID: ScopeSpec(
                ROOT_SCOPE_ID,
                rules=[ComponentRule("1", "Known", prefixes=(("known",),))],
                rung="frontier",
            )
        }
    )
    sources = {"known/main.py": "class Main: pass\n", "loose.py": "VALUE = 1\n"}
    write_sources(tmp_path, sources)
    files = [
        *sources,
        "vanished.py",
    ]  # parse_file fails; the input unit still needs ownership.
    result = build_groups(
        project_root=tmp_path,
        files=files,
        container_of=dict.fromkeys(files, container),
        container_roots={container: "."},
        references=[],
        stored={container: tree.to_dict()},
        stored_membership={container: {"known/main.py": "1"}},
    )
    assert Counter(file for group in result.groups for file in group.files) == Counter(
        files
    )
    assert owners(result)["known/main.py"] == f"{container}/1"
    assert owners(result)["loose.py"] in result.new_group_ids
    replayed = build_groups(
        project_root=tmp_path,
        files=files,
        container_of=dict.fromkeys(files, container),
        container_roots={container: "."},
        references=[],
        stored=stored_trees(result),
        stored_membership=result.group_membership,
    )
    assert replayed.groups == result.groups
    assert replayed.new_group_ids == frozenset()

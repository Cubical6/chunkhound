"""Each directory of a container is one group, derived from paths alone."""

from collections import Counter

from chunkhound.code_mapper.c4.grouping import Group, build_groups

SHOP = "container:shop"
WEB = "container:web"
BINDINGS = {
    "app/pyproject.toml": SHOP,
    "app/orders/create.py": SHOP,
    "app/orders/submit.py": SHOP,
    "app/payments/charge.py": SHOP,
    "web/src/index.ts": WEB,
}
ROOTS = {SHOP: "app", WEB: "web"}
NAMES = {SHOP: "shop", WEB: "web"}


def groups_for(bindings: dict[str, str]) -> list[Group]:
    return build_groups(
        files=list(bindings),
        container_of=bindings,
        container_roots=ROOTS,
        container_names=NAMES,
    )


def owners(groups: list[Group]) -> dict[str, str]:
    return {file: group.id for group in groups for file in group.files}


def test_each_directory_is_one_group() -> None:
    files = ["orders/nested/deep.py", "orders/api.py", "main.py", "pyproject.toml"]
    groups = build_groups(
        files=files,
        container_of=dict.fromkeys(files, SHOP),
        container_roots={SHOP: "."},
        container_names={SHOP: "shop"},
    )
    assert groups == [
        Group(f"{SHOP}/.", SHOP, "shop", ".", ("main.py", "pyproject.toml")),
        Group(f"{SHOP}/orders", SHOP, "orders", "orders", ("orders/api.py",)),
        Group(
            f"{SHOP}/orders/nested",
            SHOP,
            "orders/nested",
            "orders/nested",
            ("orders/nested/deep.py",),
        ),
    ]


def test_groups_are_deterministic_and_replay() -> None:
    first = groups_for(BINDINGS)
    assert first == groups_for(dict(reversed(BINDINGS.items())))
    assert first == groups_for(BINDINGS)
    assert Counter(file for group in first for file in group.files) == Counter(
        BINDINGS.keys()
    )
    assert owners(first) == {
        "app/pyproject.toml": f"{SHOP}/.",
        "app/orders/create.py": f"{SHOP}/orders",
        "app/orders/submit.py": f"{SHOP}/orders",
        "app/payments/charge.py": f"{SHOP}/payments",
        "web/src/index.ts": f"{WEB}/src",
    }

    known = groups_for({**BINDINGS, "app/orders/update.py": SHOP})
    assert {group.id for group in known} == {group.id for group in first}
    assert owners(known)["app/orders/update.py"] == f"{SHOP}/orders"

    changed = groups_for({**BINDINGS, "app/orders/report/revenue.py": SHOP})
    assert {group.id for group in changed} - {group.id for group in first} == {
        f"{SHOP}/orders/report"
    }
    assert set(first) <= set(changed)


def test_explicit_root_survives_changed_file_parent_ancestry() -> None:
    provisional = "container:provisional"
    original = dict.fromkeys(
        ["scope/src/feature/one.py", "scope/src/feature/two.py"], provisional
    )

    def groups(bindings: dict[str, str]) -> list[Group]:
        return build_groups(
            files=list(bindings),
            container_of=bindings,
            container_roots={provisional: "scope"},
            container_names={provisional: "scope"},
        )

    first = groups(original)
    assert first == [
        Group(
            f"{provisional}/src/feature",
            provisional,
            "src/feature",
            "src/feature",
            ("scope/src/feature/one.py", "scope/src/feature/two.py"),
        )
    ]
    # A file closer to the root changes the files' common parent, not their group.
    second = groups({**original, "scope/tool.py": provisional})
    assert second == [
        Group(f"{provisional}/.", provisional, "scope", ".", ("scope/tool.py",)),
        *first,
    ]

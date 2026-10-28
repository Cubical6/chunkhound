"""Stable public IDs, including the container portion of the R3/R4 contract."""

from chunkhound.code_mapper.c4.runtime import assign_container_ids


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

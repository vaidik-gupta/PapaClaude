"""Unit tests for the on-disk ManifestRegistry.

Runs against a temp dir seeded with the two shipped defaults, so CRUD, the
protected-default guard, and the 404/409 error statuses are exercised without
touching the repo's real .manifests/.
"""

import pytest

from app.personas.registry import ManifestRegistry, RegistryError
from app.personas.schema import Manifest, Role


def _seed_defaults(dir_):
    (dir_ / "default-parent.yaml").write_text(
        "name: default-parent\nrole: parent\nallowed_tools: [add]\n"
    )
    (dir_ / "default-child.yaml").write_text("name: default-child\nrole: child\n")


@pytest.fixture
def registry(tmp_path):
    _seed_defaults(tmp_path)
    return ManifestRegistry(tmp_path)


def test_list_and_role_filter(registry):
    assert {m.name for m in registry.list()} == {"default-parent", "default-child"}
    assert [m.name for m in registry.list(Role.PARENT)] == ["default-parent"]
    assert [m.name for m in registry.list(Role.CHILD)] == ["default-child"]


def test_get_and_missing(registry):
    assert registry.get("default-parent").role is Role.PARENT
    with pytest.raises(RegistryError) as ei:
        registry.get("nope")
    assert ei.value.status == 404


def test_create_read_back(registry):
    m = Manifest(name="researcher", role=Role.CHILD, description="digs")
    registry.create(m)
    assert registry.get("researcher").description == "digs"


def test_create_existing_conflicts(registry):
    with pytest.raises(RegistryError) as ei:
        registry.create(Manifest(name="default-parent", role=Role.PARENT))
    assert ei.value.status == 409


def test_update_pins_name_to_stem(registry):
    updated = registry.update(
        "default-parent", Manifest(name="ignored", role=Role.PARENT, description="new")
    )
    assert updated.name == "default-parent"
    assert registry.get("default-parent").description == "new"


def test_update_missing(registry):
    with pytest.raises(RegistryError) as ei:
        registry.update("ghost", Manifest(name="ghost", role=Role.PARENT))
    assert ei.value.status == 404


def test_delete_custom_manifest(registry):
    registry.create(Manifest(name="temp", role=Role.CHILD))
    registry.delete("temp")
    with pytest.raises(RegistryError):
        registry.get("temp")


def test_delete_protected_default_conflicts(registry):
    with pytest.raises(RegistryError) as ei:
        registry.delete("default-parent")
    assert ei.value.status == 409


def test_delete_missing(registry):
    with pytest.raises(RegistryError) as ei:
        registry.delete("ghost")
    assert ei.value.status == 404

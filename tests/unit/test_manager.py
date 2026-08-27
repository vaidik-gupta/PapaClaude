"""Unit tests for ResourceManager using the in-memory infra provider."""

import pytest

from app.content.infra import InMemoryInfraProvider
from app.content.manager import ContentTreeStore, ResourceManager
from app.content.tree import Engine, NodeKind


def make_manager():
    providers = {e: InMemoryInfraProvider(e) for e in Engine}
    return ResourceManager(providers, ContentTreeStore()), providers


def test_add_resource_then_data():
    m, providers = make_manager()
    m.add("alice", ["dynamodb", "default"])
    m.add("alice", ["dynamodb", "default", "orders"], metadata={"ttl": 5})
    node = m.add("alice", ["dynamodb", "default", "orders", "o1"], data={"total": 1})

    t = m.tree_of("alice")
    assert node.kind is NodeKind.ITEM
    assert t.has(["dynamodb", "default", "orders", "o1"])
    assert t.get(["dynamodb", "default", "orders"]).metadata == {"ttl": 5}
    # data leaf keeps only its name, never the payload
    assert node.metadata == {}
    # payload actually handed to infra
    assert providers[Engine.DYNAMODB].data[("alice", "dynamodb", "default", "orders", "o1")] == {"total": 1}


def test_data_requires_payload():
    m, _ = make_manager()
    m.add("alice", ["dynamodb", "default"])
    m.add("alice", ["dynamodb", "default", "orders"])
    with pytest.raises(ValueError):
        m.add("alice", ["dynamodb", "default", "orders", "o1"])  # no data


def test_payload_not_allowed_above_data_level():
    m, _ = make_manager()
    with pytest.raises(ValueError):
        m.add("alice", ["dynamodb", "default"], data={"x": 1})


def test_infra_runs_before_tree_and_failure_leaves_tree_clean():
    class BoomProvider(InMemoryInfraProvider):
        def create_resource(self, owner, path, kind, metadata):
            raise RuntimeError("infra down")

    providers = {e: InMemoryInfraProvider(e) for e in Engine}
    providers[Engine.S3] = BoomProvider(Engine.S3)
    m = ResourceManager(providers, ContentTreeStore())

    with pytest.raises(RuntimeError):
        m.add("alice", ["s3", "default"])
    # tree was NOT touched because infra failed first
    assert not m.tree_of("alice").has(["s3", "default"])


def test_delete_data_then_container():
    m, providers = make_manager()
    m.add("alice", ["s3", "default"])
    m.add("alice", ["s3", "default", "assets"])
    m.add("alice", ["s3", "default", "assets", "k1"], data={"a": 1})

    m.delete("alice", ["s3", "default", "assets", "k1"])
    assert not m.tree_of("alice").has(["s3", "default", "assets", "k1"])
    assert ("alice", "s3", "default", "assets", "k1") not in providers[Engine.S3].data

    m.delete("alice", ["s3", "default", "assets"])
    assert not m.tree_of("alice").has(["s3", "default", "assets"])
    assert ("alice", "s3", "default", "assets") not in providers[Engine.S3].resources


def test_delete_missing_or_not_owned_raises():
    m, _ = make_manager()
    with pytest.raises(ValueError):
        m.delete("alice", ["s3", "default"])  # missing

    m.add("alice", ["s3", "default"])
    with pytest.raises(ValueError):
        m.delete("bob", ["s3", "default"])  # not in bob's tree

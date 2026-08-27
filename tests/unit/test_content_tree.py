import pytest

from app.content.tree import ContentTree, Engine, NodeKind, Permission


def make_tree() -> ContentTree:
    return ContentTree("alice")


def test_roots_exist_for_all_engines():
    t = make_tree()
    for e in Engine:
        root = t.get([e.value])
        assert root is not None
        assert root.kind is NodeKind.ENGINE
        assert root.permission is Permission.SYSTEM
        assert root.owner is None


def test_add_and_get_with_metadata():
    t = make_tree()
    node = t.add(["dynamodb", "default", "orders"], kind=NodeKind.TABLE,
                 owner="alice", metadata={"ttl": 5})
    assert node.owner == "alice"
    assert node.kind is NodeKind.TABLE
    assert node.metadata == {"ttl": 5}
    assert t.has(["dynamodb", "default", "orders"])


def test_add_auto_creates_intermediate_group():
    t = make_tree()
    t.add(["dynamodb", "default", "orders"], kind=NodeKind.TABLE, owner="alice")
    grp = t.get(["dynamodb", "default"])
    assert grp is not None
    assert grp.kind is NodeKind.GROUP


def test_add_requires_engine_plus_name():
    t = make_tree()
    with pytest.raises(ValueError):
        t.add(["dynamodb"], kind=NodeKind.GROUP, owner="alice")


def test_remove_returns_node_and_clears_subtree():
    t = make_tree()
    t.add(["mongodb", "default", "app"], kind=NodeKind.DATABASE, owner="alice")
    t.add(["mongodb", "default", "app", "sessions"], kind=NodeKind.COLLECTION, owner="alice")
    removed = t.remove(["mongodb", "default", "app"])
    assert removed is not None
    assert not t.has(["mongodb", "default", "app"])
    assert not t.has(["mongodb", "default", "app", "sessions"])


def test_remove_missing_returns_none():
    t = make_tree()
    assert t.remove(["s3", "nope", "x"]) is None


def test_get_unknown_engine_raises():
    t = make_tree()
    with pytest.raises(ValueError):
        t.get(["notadb", "x"])


def test_walk_includes_roots_and_nodes():
    t = make_tree()
    t.add(["s3", "default", "assets"], kind=NodeKind.BUCKET, owner="alice")
    paths = [p for p, _ in t.walk()]
    assert ["s3"] in paths
    assert ["s3", "default", "assets"] in paths


def test_to_dict_reports_layers_and_metadata():
    t = make_tree()
    t.add(["dynamodb", "default", "orders"], kind=NodeKind.TABLE, owner="alice",
          metadata={"k": "v"})
    root = t.get(["dynamodb"]).to_dict(0)
    assert root["layer"] == 0
    grp = root["children"][0]
    assert grp["layer"] == 1
    table = grp["children"][0]
    assert table["layer"] == 2
    assert table["metadata"] == {"k": "v"}

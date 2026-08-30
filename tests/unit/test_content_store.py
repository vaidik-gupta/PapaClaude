"""Unit tests for ContentTree persistence: cache, write-back, and round-trip."""

from app.content.store import (
    ContentTreeStore,
    ImmediateWriteBack,
    InMemoryTreePersistence,
    TreePersistence,
    WriteBackStrategy,
)
from app.content.tree import ContentTree, Engine, NodeKind, Permission


def _seed(tree: ContentTree) -> None:
    tree.add(["dynamodb", "default"], kind=NodeKind.GROUP, owner="alice")
    tree.add(["dynamodb", "default", "orders"], kind=NodeKind.TABLE, owner="alice",
             metadata={"ttl": 5})


def test_tree_from_dict_roundtrip():
    tree = ContentTree("alice")
    _seed(tree)
    restored = ContentTree.from_dict(tree.to_dict())

    node = restored.get(["dynamodb", "default", "orders"])
    assert node is not None
    assert node.kind is NodeKind.TABLE
    assert node.owner == "alice"
    assert node.permission is Permission.OWNER
    assert node.metadata == {"ttl": 5}
    # engine roots preserved
    assert set(restored.roots) == set(Engine)


def test_get_or_create_loads_from_persistence_on_miss():
    persistence = InMemoryTreePersistence()
    seeded = ContentTree("alice")
    _seed(seeded)
    persistence.save("alice", seeded)

    store = ContentTreeStore(persistence=persistence)
    # cache miss -> loaded from persistence, not a fresh empty tree
    tree = store.get_or_create("alice")
    assert tree.has(["dynamodb", "default", "orders"])


def test_get_or_create_new_user_is_empty():
    store = ContentTreeStore(persistence=InMemoryTreePersistence())
    tree = store.get_or_create("newbie")
    assert not tree.has(["dynamodb", "default"])
    assert set(tree.roots) == set(Engine)


class SpyPersistence(TreePersistence):
    def __init__(self) -> None:
        self.saves: list[str] = []
        self._data: dict[str, dict] = {}

    def load(self, username):
        data = self._data.get(username)
        return ContentTree.from_dict(data) if data else None

    def save(self, username, tree):
        self.saves.append(username)
        self._data[username] = tree.to_dict()


def test_immediate_write_back_persists_on_each_mutation():
    spy = SpyPersistence()
    store = ContentTreeStore(persistence=spy, write_back=ImmediateWriteBack())

    tree = store.get_or_create("alice")
    tree.add(["s3", "default"], kind=NodeKind.GROUP, owner="alice")
    store.on_mutated("alice")
    tree.add(["s3", "default", "assets"], kind=NodeKind.BUCKET, owner="alice")
    store.on_mutated("alice")

    assert spy.saves == ["alice", "alice"]  # write-through: one save per mutation
    # and the persisted snapshot reflects the latest state
    assert spy.load("alice").has(["s3", "default", "assets"])


def test_reload_refreshes_stale_cache_from_persistence():
    persistence = InMemoryTreePersistence()
    store = ContentTreeStore(persistence=persistence)
    store.get_or_create("alice")  # caches a fresh empty tree

    # another writer updates the durable store out-of-band
    other = ContentTree("alice")
    other.add(["s3", "default"], kind=NodeKind.GROUP, owner="alice")
    persistence.save("alice", other)

    # cached copy is still stale...
    assert not store.get_or_create("alice").has(["s3", "default"])
    # ...until reload pulls the durable state into the cache
    reloaded = store.reload("alice")
    assert reloaded.has(["s3", "default"])
    assert store.get_or_create("alice").has(["s3", "default"])


def test_reload_unknown_user_yields_empty_tree():
    store = ContentTreeStore(persistence=InMemoryTreePersistence())
    tree = store.reload("ghost")
    assert set(tree.roots) == set(Engine)
    assert not tree.has(["s3", "default"])


def test_custom_write_back_strategy_is_honored():
    class NeverWriteBack(WriteBackStrategy):
        def on_mutated(self, username, tree, persistence):
            pass  # e.g. a lazy strategy that defers

    spy = SpyPersistence()
    store = ContentTreeStore(persistence=spy, write_back=NeverWriteBack())
    store.get_or_create("alice").add(["s3", "d"], kind=NodeKind.GROUP, owner="alice")
    store.on_mutated("alice")
    assert spy.saves == []  # strategy chose not to persist

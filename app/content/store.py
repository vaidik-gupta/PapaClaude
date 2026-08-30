"""Persistence for per-user ContentTrees, with an in-memory cache in front.

Three collaborators, each swappable:

  * TreePersistence   — the durable backend (load/save a whole tree). Mongo for
                        real deployments; in-memory for tests/local.
  * WriteBackStrategy — WHEN a cached mutation reaches the backend. Immediate
                        (write-through) for now; a lazy strategy can be added
                        without touching the store or the manager.
  * ContentTreeStore  — holds live ContentTree objects (the cache), loads from
                        the backend on a miss, and routes mutations through the
                        write-back strategy.

The ResourceManager mutates the cached tree in place (after infra succeeds) and
then calls `on_mutated`, which is the single hook the write-back strategy acts
on. Everything here is synchronous to match the rest of the content module
(boto3/pymongo); the agent tools already offload these calls to a thread.

Note: the cache is per-process. Multiple app instances each keep their own
cache, so a write in one is not seen by another until reload — acceptable for
now; a read-through/invalidation policy is a separate concern from write-back.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import cached_property

from app.content.tree import ContentTree
from app.logging_config import get_logger

logger = get_logger(__name__)


class TreePersistence(ABC):
    @abstractmethod
    def load(self, username: str) -> ContentTree | None:
        """Return the stored tree for a user, or None if none is stored yet."""

    @abstractmethod
    def save(self, username: str, tree: ContentTree) -> None:
        """Persist the whole tree for a user (upsert)."""


class InMemoryTreePersistence(TreePersistence):
    """Non-durable backend (default). Stores serialized snapshots in a dict."""

    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    def load(self, username: str) -> ContentTree | None:
        data = self._store.get(username)
        return ContentTree.from_dict(data) if data else None

    def save(self, username: str, tree: ContentTree) -> None:
        self._store[username] = tree.to_dict()


class MongoTreePersistence(TreePersistence):
    """Durable backend: one document per user in the `content_trees` collection."""

    COLLECTION = "content_trees"

    @cached_property
    def _collection(self):
        from pymongo import MongoClient

        from app.config import settings

        return MongoClient(settings.mongodb_uri)[settings.mongodb_db][self.COLLECTION]

    def load(self, username: str) -> ContentTree | None:
        doc = self._collection.find_one({"_id": username})
        return ContentTree.from_dict(doc["tree"]) if doc else None

    def save(self, username: str, tree: ContentTree) -> None:
        self._collection.replace_one(
            {"_id": username}, {"_id": username, "tree": tree.to_dict()}, upsert=True
        )


class WriteBackStrategy(ABC):
    @abstractmethod
    def on_mutated(
        self, username: str, tree: ContentTree, persistence: TreePersistence
    ) -> None:
        """Called after a cached tree is mutated; decide when to persist."""


class ImmediateWriteBack(WriteBackStrategy):
    """Write-through: persist on every mutation. Simplest, strongest durability."""

    def on_mutated(self, username, tree, persistence) -> None:
        persistence.save(username, tree)


class ContentTreeStore:
    """Cache of live ContentTrees backed by a persistence + write-back strategy."""

    def __init__(
        self,
        persistence: TreePersistence | None = None,
        write_back: WriteBackStrategy | None = None,
    ) -> None:
        self._cache: dict[str, ContentTree] = {}
        self._persistence = persistence or InMemoryTreePersistence()
        self._write_back = write_back or ImmediateWriteBack()

    def get_or_create(self, username: str) -> ContentTree:
        tree = self._cache.get(username)
        if tree is None:
            tree = self._persistence.load(username) or ContentTree(username)
            self._cache[username] = tree
        return tree

    def on_mutated(self, username: str) -> None:
        """Route a just-applied mutation of the cached tree to write-back."""
        tree = self._cache.get(username)
        if tree is None:  # mutated before it was cached — shouldn't happen
            raise RuntimeError(f"on_mutated for uncached tree {username!r}")
        self._write_back.on_mutated(username, tree, self._persistence)

    def reload(self, username: str) -> ContentTree:
        """Discard the cached tree and re-read it from the durable backend.

        Refreshes this process's view after an out-of-band or another-instance
        write (the cache is per-process, so it can otherwise go stale)."""
        tree = self._persistence.load(username) or ContentTree(username)
        self._cache[username] = tree
        logger.info("Reloaded content tree for %s", username)
        return tree

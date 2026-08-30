"""ResourceManager — the single path for resource/data lifecycle + tree sync.

Every mutation hits infra FIRST and only records it in the ContentTree if that
succeeded, so the DB is the source of truth and a failed DB op can't leave a
phantom node:

  * add    -> validate path, provision infra (container) or write the datum,
              THEN add the node (resources store request metadata; data leaves
              store only their name)
  * delete -> validate, delete from infra, THEN remove the node

ContentTrees are held in a per-user cache backed by a durable store; mutations
are written back through a configurable strategy (see app.content.store).
"""

from __future__ import annotations

from app.content.infra import InfraProvider, default_providers
from app.content.schema import schema_for
from app.content.store import ContentTreeStore, MongoTreePersistence
from app.content.tree import (
    ContentTree,
    Engine,
    Permission,
    ResourceNode,
)
from app.logging_config import get_logger

logger = get_logger(__name__)


class ResourceManager:
    def __init__(
        self,
        providers: dict[Engine, InfraProvider] | None = None,
        store: ContentTreeStore | None = None,
    ) -> None:
        self._providers = providers or default_providers()
        self._store = store or ContentTreeStore()

    def tree_of(self, username: str) -> ContentTree:
        return self._store.get_or_create(username)

    def reload(self, username: str) -> ContentTree:
        """Refresh the user's cached tree from durable storage."""
        return self._store.reload(username)

    def add(
        self,
        username: str,
        path: list[str],
        *,
        metadata: dict | None = None,
        data: dict | None = None,
    ) -> ResourceNode:
        engine = Engine(path[0])
        schema = schema_for(engine)
        tree = self._store.get_or_create(username)
        kind = schema.validate_add(tree, path)  # validates path, derives kind

        provider = self._providers[engine]
        if schema.is_data(kind):
            if data is None:
                raise ValueError("a data payload is required at the data level")
            provider.put_data(username, path, data)  # DB first
            # Data leaves record only their name (metadata), never the payload.
            node = tree.add(path, kind=kind, owner=username, permission=Permission.OWNER)
        else:
            if data is not None:
                raise ValueError("a data payload is only allowed at the data level")
            provider.create_resource(username, path, kind, metadata or {})  # DB first
            node = tree.add(
                path, kind=kind, owner=username, permission=Permission.OWNER,
                metadata=metadata or {},
            )
        self._store.on_mutated(username)  # persist the tree change (write-back)
        logger.info("Added %s %s for %s", kind.value, path, username)
        return node

    def get_data(self, username: str, path: list[str]) -> dict | None:
        """Read a datum's payload from the DB. Validates ownership + that the
        path is a data leaf (payloads never live in the tree)."""
        engine = Engine(path[0])
        schema = schema_for(engine)
        node = self._store.get_or_create(username).get(path)
        if node is None or node.owner != username:
            raise ValueError("data not found or not owned by user")
        if not schema.is_data(node.kind):
            raise ValueError(f"{path} is not a data leaf")
        return self._providers[engine].get_data(username, path)

    def list_data(self, username: str, path: list[str]) -> list[str]:
        """List the data names within an owned container, read from the DB."""
        engine = Engine(path[0])
        schema = schema_for(engine)
        node = self._store.get_or_create(username).get(path)
        if node is None or node.owner != username:
            raise ValueError("container not found or not owned by user")
        if schema.is_data(node.kind):
            raise ValueError(f"{path} is a data leaf, not a container")
        return self._providers[engine].list_data(username, path)

    def delete(self, username: str, path: list[str]) -> None:
        engine = Engine(path[0])
        schema = schema_for(engine)
        tree = self._store.get_or_create(username)
        node = tree.get(path)
        if node is None or node.owner != username:
            raise ValueError("resource not found or not owned by user")
        schema.validate_delete(tree, path)

        provider = self._providers[engine]
        if schema.is_data(node.kind):
            provider.delete_data(username, path)  # DB first
        else:
            provider.delete_resource(username, path, node.kind)  # DB first
        tree.remove(path)
        self._store.on_mutated(username)  # persist the tree change (write-back)
        logger.info("Deleted %s for %s", path, username)


# Production singleton: durable Mongo-backed tree persistence (write-through).
resource_manager = ResourceManager(
    store=ContentTreeStore(persistence=MongoTreePersistence())
)

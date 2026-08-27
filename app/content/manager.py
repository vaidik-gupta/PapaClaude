"""ResourceManager — the single path for resource/data lifecycle + tree sync.

Every mutation hits infra FIRST and only records it in the ContentTree if that
succeeded, so the DB is the source of truth and a failed DB op can't leave a
phantom node:

  * add    -> validate path, provision infra (container) or write the datum,
              THEN add the node (resources store request metadata; data leaves
              store only their name)
  * delete -> validate, delete from infra, THEN remove the node

ContentTrees live in an in-memory store for now (placeholder, like the auth
service); a real store lands with the auth-management service later.
"""

from __future__ import annotations

from app.content.infra import InfraProvider, default_providers
from app.content.schema import schema_for
from app.content.tree import (
    ContentTree,
    Engine,
    Permission,
    ResourceNode,
)
from app.logging_config import get_logger

logger = get_logger(__name__)


class ContentTreeStore:
    """In-memory username -> ContentTree store."""

    def __init__(self) -> None:
        self._trees: dict[str, ContentTree] = {}

    def get_or_create(self, username: str) -> ContentTree:
        tree = self._trees.get(username)
        if tree is None:
            tree = ContentTree(username)
            self._trees[username] = tree
        return tree


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
        logger.info("Added %s %s for %s", kind.value, path, username)
        return node

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
        logger.info("Deleted %s for %s", path, username)


resource_manager = ResourceManager()

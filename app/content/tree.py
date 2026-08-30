"""ContentTree — per-user metadata of the resources the user can reach.

One tree per user. Layer 0 is the three engine roots [dynamodb, s3, mongodb],
present in every user's tree. Below that, each engine nests naturally:

    dynamodb -> instance -> table      -> item
    s3       -> instance -> bucket     -> object
    mongodb  -> instance -> database   -> collection -> document

A path is a list of names starting with the engine, e.g.
["dynamodb", "default", "orders"]. The last level of each engine is data (the
lowest granularity); everything above it is a resource/container.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator


class Engine(str, Enum):
    DYNAMODB = "dynamodb"
    S3 = "s3"
    MONGODB = "mongodb"


class NodeKind(str, Enum):
    ENGINE = "engine"          # layer 0 root
    GROUP = "group"            # layer 1 instance / logical namespace
    TABLE = "table"            # dynamodb container
    BUCKET = "bucket"          # s3 container
    DATABASE = "database"      # mongodb container
    COLLECTION = "collection"  # mongodb container
    ITEM = "item"              # dynamodb data (leaf)
    OBJECT = "object"          # s3 data (leaf)
    DOCUMENT = "document"      # mongodb data (leaf)


class Permission(str, Enum):
    SYSTEM = "system"  # engine roots and structural nodes
    OWNER = "owner"    # creator — read/write


@dataclass
class ResourceNode:
    name: str
    engine: Engine
    kind: NodeKind
    owner: str | None = None
    permission: Permission = Permission.SYSTEM
    metadata: dict = field(default_factory=dict)  # request metadata (name/description/...)
    children: dict[str, ResourceNode] = field(default_factory=dict)

    def to_dict(self, layer: int = 0) -> dict:
        return {
            "name": self.name,
            "engine": self.engine.value,
            "kind": self.kind.value,
            "owner": self.owner,
            "permission": self.permission.value,
            "metadata": self.metadata,
            "layer": layer,
            "children": [c.to_dict(layer + 1) for c in self.children.values()],
        }

    @classmethod
    def from_dict(cls, data: dict) -> ResourceNode:
        node = cls(
            name=data["name"],
            engine=Engine(data["engine"]),
            kind=NodeKind(data["kind"]),
            owner=data.get("owner"),
            permission=Permission(data["permission"]),
            metadata=data.get("metadata", {}),
        )
        for child in data.get("children", []):
            node.children[child["name"]] = ResourceNode.from_dict(child)
        return node


class ContentTree:
    """A single user's view of the resources they can reach."""

    def __init__(self, username: str) -> None:
        self.username = username
        self.roots: dict[Engine, ResourceNode] = {
            e: ResourceNode(name=e.value, engine=e, kind=NodeKind.ENGINE, permission=Permission.SYSTEM)
            for e in Engine
        }

    def _parent_of(self, path: list[str], *, create: bool) -> ResourceNode | None:
        """Return the node that should hold path[-1], creating intermediates if asked."""
        if len(path) < 2:
            raise ValueError("path must be [engine, ...at least one segment]")
        node = self.roots[Engine(path[0])]
        for seg in path[1:-1]:
            child = node.children.get(seg)
            if child is None:
                if not create:
                    return None
                child = ResourceNode(name=seg, engine=node.engine, kind=NodeKind.GROUP)
                node.children[seg] = child
            node = child
        return node

    def add(self, path: list[str], *, kind: NodeKind, owner: str,
            permission: Permission = Permission.OWNER,
            metadata: dict | None = None) -> ResourceNode:
        parent = self._parent_of(path, create=True)
        assert parent is not None  # create=True never returns None
        leaf = ResourceNode(name=path[-1], engine=Engine(path[0]), kind=kind,
                            owner=owner, permission=permission, metadata=metadata or {})
        parent.children[path[-1]] = leaf
        return leaf

    def remove(self, path: list[str]) -> ResourceNode | None:
        parent = self._parent_of(path, create=False)
        if parent is None:
            return None
        return parent.children.pop(path[-1], None)

    def get(self, path: list[str]) -> ResourceNode | None:
        if not path:
            return None
        node = self.roots.get(Engine(path[0]))
        for seg in path[1:]:
            if node is None:
                return None
            node = node.children.get(seg)
        return node

    def has(self, path: list[str]) -> bool:
        return self.get(path) is not None

    def walk(self) -> Iterator[tuple[list[str], ResourceNode]]:
        """Preorder traversal yielding (path, node) for every node."""
        def _walk(prefix: list[str], node: ResourceNode):
            path = [*prefix, node.name]
            yield path, node
            for child in node.children.values():
                yield from _walk(path, child)

        for root in self.roots.values():
            yield from _walk([], root)

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "roots": [r.to_dict(0) for r in self.roots.values()],
        }

    @classmethod
    def from_dict(cls, data: dict) -> ContentTree:
        tree = cls(data["username"])
        tree.roots = {
            Engine(r["engine"]): ResourceNode.from_dict(r) for r in data["roots"]
        }
        return tree

"""Per-engine path schemas.

Each engine nests differently, so each has a schema that validates whether a
path is legal for addition/deletion in a ContentTree. Because the nesting is
deterministic, the schema also derives the NodeKind for a given depth. The last
level of each engine is the *data* level (the lowest granularity); everything
above it is a resource/container.

    layer:      1           2          3           4
    dynamodb    instance    table      item
    s3          instance    bucket     object
    mongodb     instance    database   collection  document
"""

from __future__ import annotations

from abc import ABC

from app.content.tree import ContentTree, Engine, NodeKind


class DBSchema(ABC):
    engine: Engine
    levels: list[NodeKind]  # levels[i] -> kind at layer i+1; last level is data

    @property
    def data_kind(self) -> NodeKind:
        return self.levels[-1]

    def is_data(self, kind: NodeKind) -> bool:
        return kind is self.data_kind

    def kind_for_layer(self, layer: int) -> NodeKind:
        idx = layer - 1
        if 0 <= idx < len(self.levels):
            return self.levels[idx]
        raise ValueError(
            f"{self.engine.value}: no resource level exists at layer {layer}"
        )

    def validate_add(self, tree: ContentTree, path: list[str]) -> NodeKind:
        """Validate that `path` can be added; return the kind it should have."""
        if len(path) < 2:
            raise ValueError("path must be [engine, ...at least one name]")
        if Engine(path[0]) is not self.engine:
            raise ValueError(
                f"path engine '{path[0]}' does not match schema '{self.engine.value}'"
            )
        if not path[-1]:
            raise ValueError("resource name must be non-empty")

        kind = self.kind_for_layer(len(path) - 1)  # raises if too deep

        parent_path = path[:-1]
        if len(parent_path) >= 2 and not tree.has(parent_path):
            raise ValueError(f"parent directory {parent_path} does not exist")
        if tree.has(path):
            raise ValueError(f"resource {path} already exists")
        return kind

    def validate_delete(self, tree: ContentTree, path: list[str]) -> None:
        if len(path) < 2:
            raise ValueError("cannot delete an engine root")
        if Engine(path[0]) is not self.engine:
            raise ValueError(
                f"path engine '{path[0]}' does not match schema '{self.engine.value}'"
            )
        if not tree.has(path):
            raise ValueError(f"resource {path} not found")


class DynamoDBSchema(DBSchema):
    engine = Engine.DYNAMODB
    levels = [NodeKind.GROUP, NodeKind.TABLE, NodeKind.ITEM]


class S3Schema(DBSchema):
    engine = Engine.S3
    levels = [NodeKind.GROUP, NodeKind.BUCKET, NodeKind.OBJECT]


class MongoDBSchema(DBSchema):
    engine = Engine.MONGODB
    levels = [NodeKind.GROUP, NodeKind.DATABASE, NodeKind.COLLECTION, NodeKind.DOCUMENT]


_SCHEMAS: dict[Engine, DBSchema] = {
    s.engine: s for s in (DynamoDBSchema(), S3Schema(), MongoDBSchema())
}


def schema_for(engine: Engine) -> DBSchema:
    return _SCHEMAS[engine]

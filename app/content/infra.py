"""Abstraction over the physical DB infrastructure.

The ResourceManager talks to infra only through this interface, and always
before it touches the ContentTree — so a resource/datum exists in the DB before
it is recorded in the tree, and a failed DB op leaves the tree untouched.

Physical names are namespaced by owner so users sharing an instance never
collide (e.g. table `admin__default__orders`, bucket `admin-default-assets`,
Mongo db `admin__default__app`).

Layer-1 instances (and Mongo databases, which are lazy) have no physical
resource of their own — only containers (table/bucket/collection) and data
(item/object/document) do.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from functools import cached_property

from app.content.tree import Engine, NodeKind
from app.logging_config import get_logger

logger = get_logger(__name__)


class InfraProvider(ABC):
    engine: Engine

    @abstractmethod
    def create_resource(self, owner: str, path: list[str], kind: NodeKind, metadata: dict) -> None:
        ...

    @abstractmethod
    def delete_resource(self, owner: str, path: list[str], kind: NodeKind) -> None:
        ...

    @abstractmethod
    def put_data(self, owner: str, path: list[str], data: dict) -> None:
        ...

    @abstractmethod
    def delete_data(self, owner: str, path: list[str]) -> None:
        ...

    @abstractmethod
    def get_data(self, owner: str, path: list[str]) -> dict | None:
        """Read a single datum's payload; None if it isn't in the DB."""
        ...

    @abstractmethod
    def list_data(self, owner: str, path: list[str]) -> list[str]:
        """List the data names within a container path (source of truth: the DB)."""
        ...


class DynamoDBInfraProvider(InfraProvider):
    engine = Engine.DYNAMODB

    @cached_property
    def _resource(self):
        import boto3

        from app.db._aws import boto3_kwargs

        return boto3.resource("dynamodb", **boto3_kwargs())

    def _table_name(self, owner: str, path: list[str]) -> str:
        # path[1:3] == [instance, table]
        return "__".join([owner, *path[1:3]])

    def create_resource(self, owner, path, kind, metadata) -> None:
        if kind is not NodeKind.TABLE:
            return  # layer-1 instance is logical
        name = self._table_name(owner, path)
        client = self._resource.meta.client
        logger.info("dynamodb: create_table %s", name)
        client.create_table(
            TableName=name,
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        client.get_waiter("table_exists").wait(TableName=name)

    def delete_resource(self, owner, path, kind) -> None:
        if kind is not NodeKind.TABLE:
            return
        name = self._table_name(owner, path)
        client = self._resource.meta.client
        logger.info("dynamodb: delete_table %s", name)
        client.delete_table(TableName=name)
        client.get_waiter("table_not_exists").wait(TableName=name)

    def put_data(self, owner, path, data) -> None:
        table = self._resource.Table(self._table_name(owner, path[:3]))
        table.put_item(Item={"pk": path[-1], **data})

    def delete_data(self, owner, path) -> None:
        table = self._resource.Table(self._table_name(owner, path[:3]))
        table.delete_item(Key={"pk": path[-1]})

    def get_data(self, owner, path) -> dict | None:
        table = self._resource.Table(self._table_name(owner, path[:3]))
        item = table.get_item(Key={"pk": path[-1]}).get("Item")
        if item is None:
            return None
        item.pop("pk", None)  # pk is the datum's name, already known from the path
        return item

    def list_data(self, owner, path) -> list[str]:
        table = self._resource.Table(self._table_name(owner, path))
        return [i["pk"] for i in table.scan(ProjectionExpression="pk").get("Items", [])]


class S3InfraProvider(InfraProvider):
    engine = Engine.S3

    @cached_property
    def _client(self):
        import boto3

        from app.db._aws import boto3_kwargs

        return boto3.client("s3", **boto3_kwargs())

    def _bucket_name(self, owner: str, path: list[str]) -> str:
        # path[1:3] == [instance, bucket]; buckets must be DNS-safe/lowercase
        return "-".join([owner, *path[1:3]]).lower()

    def create_resource(self, owner, path, kind, metadata) -> None:
        if kind is not NodeKind.BUCKET:
            return
        bucket = self._bucket_name(owner, path)
        logger.info("s3: create_bucket %s", bucket)
        self._client.create_bucket(Bucket=bucket)

    def delete_resource(self, owner, path, kind) -> None:
        if kind is not NodeKind.BUCKET:
            return
        bucket = self._bucket_name(owner, path)
        logger.info("s3: delete_bucket %s", bucket)
        objs = self._client.list_objects_v2(Bucket=bucket).get("Contents", [])
        if objs:
            self._client.delete_objects(
                Bucket=bucket, Delete={"Objects": [{"Key": o["Key"]} for o in objs]}
            )
        self._client.delete_bucket(Bucket=bucket)

    def put_data(self, owner, path, data) -> None:
        bucket = self._bucket_name(owner, path[:3])
        self._client.put_object(Bucket=bucket, Key=path[-1], Body=json.dumps(data).encode())

    def delete_data(self, owner, path) -> None:
        bucket = self._bucket_name(owner, path[:3])
        self._client.delete_object(Bucket=bucket, Key=path[-1])

    def get_data(self, owner, path) -> dict | None:
        bucket = self._bucket_name(owner, path[:3])
        try:
            obj = self._client.get_object(Bucket=bucket, Key=path[-1])
        except self._client.exceptions.NoSuchKey:
            return None
        return json.loads(obj["Body"].read())

    def list_data(self, owner, path) -> list[str]:
        bucket = self._bucket_name(owner, path)
        objs = self._client.list_objects_v2(Bucket=bucket).get("Contents", [])
        return [o["Key"] for o in objs]


class MongoDBInfraProvider(InfraProvider):
    engine = Engine.MONGODB

    @cached_property
    def _client(self):
        from pymongo import MongoClient

        from app.config import settings

        return MongoClient(settings.mongodb_uri)

    def _db_name(self, owner: str, path: list[str]) -> str:
        # path[1:3] == [instance, database]
        return "__".join([owner, *path[1:3]])

    def create_resource(self, owner, path, kind, metadata) -> None:
        if kind is not NodeKind.COLLECTION:
            return  # instance + database are lazy
        db = self._client[self._db_name(owner, path[:3])]
        logger.info("mongodb: create_collection %s.%s", db.name, path[3])
        db.create_collection(path[3])

    def delete_resource(self, owner, path, kind) -> None:
        if kind is NodeKind.COLLECTION:
            db = self._client[self._db_name(owner, path[:3])]
            logger.info("mongodb: drop_collection %s.%s", db.name, path[3])
            db.drop_collection(path[3])
        elif kind is NodeKind.DATABASE:
            self._client.drop_database(self._db_name(owner, path))

    def put_data(self, owner, path, data) -> None:
        coll = self._client[self._db_name(owner, path[:3])][path[3]]
        coll.replace_one({"_id": path[-1]}, {"_id": path[-1], **data}, upsert=True)

    def delete_data(self, owner, path) -> None:
        coll = self._client[self._db_name(owner, path[:3])][path[3]]
        coll.delete_one({"_id": path[-1]})

    def get_data(self, owner, path) -> dict | None:
        coll = self._client[self._db_name(owner, path[:3])][path[3]]
        doc = coll.find_one({"_id": path[-1]})
        if doc is None:
            return None
        doc.pop("_id", None)  # _id is the datum's name, already known from the path
        return doc

    def list_data(self, owner, path) -> list[str]:
        coll = self._client[self._db_name(owner, path[:3])][path[3]]
        return [d["_id"] for d in coll.find({}, {"_id": 1})]


class InMemoryInfraProvider(InfraProvider):
    """Placeholder provider that records ops instead of touching a real DB."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.resources: set[tuple[str, ...]] = set()
        self.data: dict[tuple[str, ...], dict] = {}

    def create_resource(self, owner, path, kind, metadata) -> None:
        self.resources.add((owner, *path))

    def delete_resource(self, owner, path, kind) -> None:
        self.resources.discard((owner, *path))

    def put_data(self, owner, path, data) -> None:
        self.data[(owner, *path)] = data

    def delete_data(self, owner, path) -> None:
        self.data.pop((owner, *path), None)

    def get_data(self, owner, path) -> dict | None:
        return self.data.get((owner, *path))

    def list_data(self, owner, path) -> list[str]:
        container = (owner, *path)
        return [key[-1] for key in self.data if key[:-1] == container]


def default_providers() -> dict[Engine, InfraProvider]:
    return {
        Engine.DYNAMODB: DynamoDBInfraProvider(),
        Engine.S3: S3InfraProvider(),
        Engine.MONGODB: MongoDBInfraProvider(),
    }

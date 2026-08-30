"""End-to-end resource/data CRUD against the real containers (LocalStack + Mongo).

Each test uses a unique instance name and cleans up the physical resources it
created, so runs don't collide or leave state behind.
"""

import json

import boto3
import pytest
from pymongo import MongoClient

from app.config import settings
from app.db._aws import boto3_kwargs

pytestmark = pytest.mark.e2e


def test_dynamodb_full_flow(client, admin_headers, dbs_available, unique):
    inst = unique
    table = f"admin__{inst}__orders"
    ddb = boto3.resource("dynamodb", **boto3_kwargs())
    try:
        assert client.post("/resources/db", json={"engine": "dynamodb", "name": inst},
                           headers=admin_headers).status_code == 200
        assert client.post("/resources",
                           json={"parent_path": ["dynamodb", inst], "name": "orders",
                                 "metadata": {"ttl": 5}},
                           headers=admin_headers).status_code == 200
        assert client.post("/resources",
                           json={"parent_path": ["dynamodb", inst, "orders"], "name": "o1",
                                 "data": {"total": 42}},
                           headers=admin_headers).status_code == 200

        # the item really landed in DynamoDB
        item = ddb.Table(table).get_item(Key={"pk": "o1"}).get("Item")
        assert item["total"] == 42

        # tree carries resource metadata; read via API
        node = client.get(f"/resources/dynamodb/{inst}/orders", headers=admin_headers).json()["node"]
        assert node["metadata"] == {"ttl": 5}

        # delete data -> gone from DB and tree
        assert client.delete(f"/resources/dynamodb/{inst}/orders/o1",
                             headers=admin_headers).status_code == 200
        assert ddb.Table(table).get_item(Key={"pk": "o1"}).get("Item") is None
        assert client.get(f"/resources/dynamodb/{inst}/orders/o1",
                          headers=admin_headers).status_code == 404

        # delete table -> dropped in DB
        assert client.delete(f"/resources/dynamodb/{inst}/orders",
                             headers=admin_headers).status_code == 200
        assert table not in {t.name for t in ddb.tables.all()}
    finally:
        try:
            boto3.client("dynamodb", **boto3_kwargs()).delete_table(TableName=table)
        except Exception:
            pass


def test_s3_full_flow(client, admin_headers, dbs_available, unique):
    inst = unique
    bucket = f"admin-{inst}-assets"
    s3 = boto3.client("s3", **boto3_kwargs())
    try:
        assert client.post("/resources/db", json={"engine": "s3", "name": inst},
                           headers=admin_headers).status_code == 200
        assert client.post("/resources",
                           json={"parent_path": ["s3", inst], "name": "assets"},
                           headers=admin_headers).status_code == 200
        assert client.post("/resources",
                           json={"parent_path": ["s3", inst, "assets"], "name": "k1",
                                 "data": {"hello": "world"}},
                           headers=admin_headers).status_code == 200

        body = s3.get_object(Bucket=bucket, Key="k1")["Body"].read().decode()
        assert json.loads(body) == {"hello": "world"}

        assert client.delete(f"/resources/s3/{inst}/assets/k1",
                             headers=admin_headers).status_code == 200
        with pytest.raises(s3.exceptions.NoSuchKey):
            s3.get_object(Bucket=bucket, Key="k1")

        assert client.delete(f"/resources/s3/{inst}/assets",
                             headers=admin_headers).status_code == 200
    finally:
        try:
            objs = s3.list_objects_v2(Bucket=bucket).get("Contents", [])
            if objs:
                s3.delete_objects(Bucket=bucket,
                                  Delete={"Objects": [{"Key": o["Key"]} for o in objs]})
            s3.delete_bucket(Bucket=bucket)
        except Exception:
            pass


def test_mongodb_full_flow(client, admin_headers, dbs_available, unique):
    inst = unique
    dbname = f"admin__{inst}__app"
    mc = MongoClient(settings.mongodb_uri)
    try:
        assert client.post("/resources/db", json={"engine": "mongodb", "name": inst},
                           headers=admin_headers).status_code == 200
        assert client.post("/resources",
                           json={"parent_path": ["mongodb", inst], "name": "app"},
                           headers=admin_headers).status_code == 200
        assert client.post("/resources",
                           json={"parent_path": ["mongodb", inst, "app"], "name": "sessions"},
                           headers=admin_headers).status_code == 200
        assert client.post("/resources",
                           json={"parent_path": ["mongodb", inst, "app", "sessions"],
                                 "name": "d1", "data": {"user": "bob"}},
                           headers=admin_headers).status_code == 200

        doc = mc[dbname]["sessions"].find_one({"_id": "d1"})
        assert doc["user"] == "bob"

        assert client.delete(f"/resources/mongodb/{inst}/app/sessions/d1",
                             headers=admin_headers).status_code == 200
        assert mc[dbname]["sessions"].find_one({"_id": "d1"}) is None

        assert client.delete(f"/resources/mongodb/{inst}/app/sessions",
                             headers=admin_headers).status_code == 200
    finally:
        try:
            mc.drop_database(dbname)
        except Exception:
            pass


def test_validation_errors(client, admin_headers, dbs_available, unique):
    inst = unique
    table = f"admin__{inst}__t"
    client.post("/resources/db", json={"engine": "dynamodb", "name": inst}, headers=admin_headers)
    client.post("/resources", json={"parent_path": ["dynamodb", inst], "name": "t"},
                headers=admin_headers)
    try:
        # missing parent directory
        assert client.post("/resources", json={"parent_path": ["dynamodb", "ghost"], "name": "t"},
                           headers=admin_headers).status_code == 400
        # duplicate resource
        assert client.post("/resources", json={"parent_path": ["dynamodb", inst], "name": "t"},
                           headers=admin_headers).status_code == 400
        # data payload required at the data level
        assert client.post("/resources", json={"parent_path": ["dynamodb", inst, "t"], "name": "x"},
                           headers=admin_headers).status_code == 400
    finally:
        client.delete(f"/resources/dynamodb/{inst}/t", headers=admin_headers)
        try:
            boto3.client("dynamodb", **boto3_kwargs()).delete_table(TableName=table)
        except Exception:
            pass


def test_resources_require_auth(client):
    assert client.post("/resources/db", json={"engine": "s3", "name": "x"}).status_code == 401
    assert client.get("/resources/dynamodb").status_code == 401
    assert client.post("/resources/reload").status_code == 401


def test_reload_tree_reflects_persisted_state(client, admin_headers, dbs_available, unique):
    inst = unique  # a dynamodb instance is logical (no physical table to clean up)
    try:
        assert client.post("/resources/db", json={"engine": "dynamodb", "name": inst},
                           headers=admin_headers).status_code == 200
        tree = client.post("/resources/reload", headers=admin_headers).json()
        dynamo = next(r for r in tree["roots"] if r["name"] == "dynamodb")
        assert inst in {c["name"] for c in dynamo["children"]}
    finally:
        client.delete(f"/resources/dynamodb/{inst}", headers=admin_headers)

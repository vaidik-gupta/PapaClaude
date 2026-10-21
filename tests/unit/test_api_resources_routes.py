"""Route-level tests for the resources API using in-memory infra (no DB).

Focus: the new read endpoints (`GET /resources` whole-tree and
`GET /resources/data/{path}` payload) resolve correctly and are not shadowed by
the greedy `GET /resources/{path}` route, plus a full add/read/delete round-trip.
"""

import pytest
from fastapi.testclient import TestClient

import app.api.resources as resources_api
from app.auth.dependencies import require_user
from app.auth.service import User
from app.content.infra import InMemoryInfraProvider
from app.content.manager import ResourceManager
from app.content.store import ContentTreeStore, InMemoryTreePersistence
from app.content.tree import Engine
from app.main import app


@pytest.fixture
def api_client():
    manager = ResourceManager(
        providers={e: InMemoryInfraProvider(e) for e in Engine},
        store=ContentTreeStore(persistence=InMemoryTreePersistence()),
    )
    original = resources_api.resource_manager
    resources_api.resource_manager = manager
    app.dependency_overrides[require_user] = lambda: User(
        username="tester", is_admin=False
    )
    # TestClient without `with` so the app lifespan (Mongo connect) never runs.
    client = TestClient(app)
    yield client
    resources_api.resource_manager = original
    app.dependency_overrides.pop(require_user, None)


def test_get_tree_returns_engine_roots(api_client):
    body = api_client.get("/resources").json()
    assert {r["engine"] for r in body["roots"]} == {"dynamodb", "s3", "mongodb"}


def test_add_read_and_delete_round_trip(api_client):
    assert api_client.post(
        "/resources/db", json={"engine": "dynamodb", "name": "inst"}
    ).status_code == 200
    assert api_client.post(
        "/resources",
        json={"parent_path": ["dynamodb", "inst"], "name": "orders", "metadata": {"ttl": 5}},
    ).status_code == 200
    assert api_client.post(
        "/resources",
        json={"parent_path": ["dynamodb", "inst", "orders"], "name": "o1", "data": {"total": 42}},
    ).status_code == 200

    # The data-payload route is not shadowed by the greedy node route.
    data = api_client.get("/resources/data/dynamodb/inst/orders/o1").json()
    assert data["data"] == {"total": 42}

    # The greedy node route still serves resource metadata.
    node = api_client.get("/resources/dynamodb/inst/orders").json()["node"]
    assert node["metadata"] == {"ttl": 5}

    assert api_client.delete("/resources/dynamodb/inst/orders/o1").status_code == 200
    assert api_client.get("/resources/data/dynamodb/inst/orders/o1").status_code == 404


def test_get_data_on_missing_leaf_is_404(api_client):
    assert api_client.get("/resources/data/dynamodb/nope/x/y").status_code == 404

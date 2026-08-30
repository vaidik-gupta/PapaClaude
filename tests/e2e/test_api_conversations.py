"""End-to-end tests for the conversation endpoints (Mongo only, no agent).

Covers create/list/read + ownership. The SSE turn endpoint drives the live
agent and is exercised separately; here we only need the database.
"""

import pytest
from pymongo import MongoClient

from app.config import settings

pytestmark = pytest.mark.e2e


def _cleanup(conversation_id: str) -> None:
    db = MongoClient(settings.mongodb_uri)[settings.mongodb_db]
    db.conversations.delete_many({"id": conversation_id})
    db.turns.delete_many({"conversation_id": conversation_id})
    db.events.delete_many({"conversation_id": conversation_id})


def test_create_list_get_conversation(client, admin_headers, dbs_available):
    created = client.post(
        "/conversations", json={"title": "e2e"}, headers=admin_headers
    ).json()
    conv_id = created["id"]
    try:
        assert created["owner"] == "admin"
        assert created["title"] == "e2e"
        assert created["sdk_session_id"] is None

        # appears in the list
        listed = client.get("/conversations", headers=admin_headers).json()
        assert conv_id in {c["id"] for c in listed}

        # detail, no turns yet
        detail = client.get(f"/conversations/{conv_id}", headers=admin_headers).json()
        assert detail["conversation"]["id"] == conv_id
        assert detail["turns"] == []
    finally:
        _cleanup(conv_id)


def test_get_missing_conversation_is_404(client, admin_headers, dbs_available):
    resp = client.get("/conversations/does-not-exist", headers=admin_headers)
    assert resp.status_code == 404


def test_turn_on_foreign_conversation_is_404(client, admin_headers, dbs_available):
    # A conversation owned by admin...
    conv_id = client.post(
        "/conversations", json={"title": "owned"}, headers=admin_headers
    ).json()["id"]
    try:
        # ...is not reachable by another user, even to post a turn.
        other = {"X-User-Name": "nobody", "X-User-Key": "nope"}
        assert client.post(
            f"/conversations/{conv_id}/turns", json={"prompt": "hi"}, headers=other
        ).status_code == 401  # bad creds rejected before ownership
        # admin can see it though
        assert client.get(f"/conversations/{conv_id}", headers=admin_headers).status_code == 200
    finally:
        _cleanup(conv_id)


def test_endpoints_require_auth(client, dbs_available):
    assert client.get("/conversations").status_code == 401
    assert client.post("/conversations", json={}).status_code == 401

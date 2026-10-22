"""End-to-end tests for the conversation endpoints (Mongo only, no agent).

Covers create/list/read + ownership. The SSE turn endpoint drives the live
agent and is exercised separately; here we only need the database.
"""

import os

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
        "/conversations", json={"title": "e2e", "directory": "."}, headers=admin_headers
    ).json()
    conv_id = created["id"]
    try:
        assert created["owner"] == "admin"
        assert created["title"] == "e2e"
        assert created["sdk_session_id"] is None
        # directory is stored resolved to an absolute path
        assert created["directory"] == os.path.abspath(".")

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
        "/conversations", json={"title": "owned", "directory": "."}, headers=admin_headers
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


def test_create_requires_valid_directory(client, admin_headers, dbs_available):
    # Missing directory -> 422 (schema validation).
    assert (
        client.post("/conversations", json={"title": "x"}, headers=admin_headers).status_code
        == 422
    )
    # Non-existent directory -> 400 (must-exist validation).
    resp = client.post(
        "/conversations",
        json={"title": "x", "directory": "/no/such/dir/here"},
        headers=admin_headers,
    )
    assert resp.status_code == 400


def test_child_inherits_and_overrides_directory(client, admin_headers, dbs_available, tmp_path):
    papa = client.post(
        "/conversations", json={"title": "papa", "directory": "."}, headers=admin_headers
    ).json()
    papa_id = papa["id"]
    override = str(tmp_path)
    try:
        # No directory -> inherits the Papa's resolved directory.
        inherited = client.post(
            f"/conversations/{papa_id}/children",
            json={"manifest_name": "default-child"},
            headers=admin_headers,
        ).json()
        assert inherited["directory"] == os.path.abspath(".")
        _cleanup(inherited["id"])

        # Explicit directory -> overrides.
        overridden = client.post(
            f"/conversations/{papa_id}/children",
            json={"manifest_name": "default-child", "directory": override},
            headers=admin_headers,
        ).json()
        assert overridden["directory"] == os.path.abspath(override)
        _cleanup(overridden["id"])
    finally:
        _cleanup(papa_id)


def test_browse_dirs_endpoint(client, admin_headers, dbs_available, tmp_path):
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    listing = client.get(
        "/fs/dirs", params={"path": str(tmp_path)}, headers=admin_headers
    ).json()
    assert listing["path"] == os.path.abspath(str(tmp_path))
    assert "alpha" in listing["entries"] and "beta" in listing["entries"]
    # A bad path is a 400.
    assert (
        client.get(
            "/fs/dirs", params={"path": "/no/such/dir/here"}, headers=admin_headers
        ).status_code
        == 400
    )


def test_widget_respond_resolves_pending(client, admin_headers, dbs_available):
    import asyncio

    from app.agent.widgets import pending_widgets

    conv_id = client.post(
        "/conversations", json={"title": "widget", "directory": "."}, headers=admin_headers
    ).json()["id"]
    try:
        # Simulate a tool having presented a widget: register a pending future.
        loop = asyncio.new_event_loop()
        instance_id = "inst-xyz"
        future = loop.run_until_complete(_register(pending_widgets, instance_id, conv_id))

        resp = client.post(
            f"/conversations/{conv_id}/widgets/{instance_id}/respond",
            json={"value": {"granted": True}},
            headers=admin_headers,
        )
        assert resp.status_code == 204
        assert future.done() and future.result() == {"granted": True}
        loop.close()
    finally:
        _cleanup(conv_id)


def test_widget_respond_unknown_is_404(client, admin_headers, dbs_available):
    conv_id = client.post(
        "/conversations", json={"title": "widget", "directory": "."}, headers=admin_headers
    ).json()["id"]
    try:
        resp = client.post(
            f"/conversations/{conv_id}/widgets/nope/respond",
            json={"value": {}},
            headers=admin_headers,
        )
        assert resp.status_code == 404
    finally:
        _cleanup(conv_id)


async def _register(registry, instance_id, conv_id):
    return registry.register(instance_id, conv_id)

"""API integration tests for health, agent auth, and user management.

These drive the full app through HTTP but don't require the DB containers
(the agent call is mocked; Mongo connect is lazy).
"""

import uuid


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_agent_requires_auth(client):
    assert client.post("/agent", json={"prompt": "hi"}).status_code == 401
    bad = {"X-User-Name": "admin", "X-User-Key": "nope"}
    assert client.post("/agent", json={"prompt": "hi"}, headers=bad).status_code == 401


def test_agent_success_is_mocked(client, admin_headers, monkeypatch):
    async def fake_run_agent(prompt, system_prompt=None):
        return f"echo:{prompt}"

    monkeypatch.setattr("app.api.routes.run_agent", fake_run_agent)
    r = client.post("/agent", json={"prompt": "hi"}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["response"] == "echo:hi"


def test_user_management_admin_only(client, admin_headers):
    name = "u_" + uuid.uuid4().hex[:8]

    # admin can register a user
    assert client.post("/users", json={"username": name, "key": "pw"},
                       headers=admin_headers).status_code == 200
    # duplicate rejected
    assert client.post("/users", json={"username": name, "key": "pw"},
                       headers=admin_headers).status_code == 409
    # the new (non-admin) user cannot register others
    non_admin = {"X-User-Name": name, "X-User-Key": "pw"}
    assert client.post("/users", json={"username": "x", "key": "y"},
                       headers=non_admin).status_code == 403
    # unauthenticated rejected
    assert client.post("/users", json={"username": "z", "key": "y"}).status_code == 401

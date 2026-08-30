"""Unit tests for the per-user content tool server.

Drives the tool handlers directly against a ResourceManager backed by in-memory
infra — no live agent. Verifies the tools act as the bound owner, surface
validation errors as is_error results, and never accept a user parameter.
"""

import json

from app.agent.tools import _content_tools, allowed_tool_names
from app.content.infra import InMemoryInfraProvider
from app.content.manager import ContentTreeStore, ResourceManager
from app.content.tree import Engine


def make_manager() -> ResourceManager:
    providers = {e: InMemoryInfraProvider(e) for e in Engine}
    return ResourceManager(providers, ContentTreeStore())


def handlers(owner: str, mgr: ResourceManager) -> dict:
    """Map tool name -> handler for the tools built for `owner`."""
    return {t.name: t.handler for t in _content_tools(owner, mgr)}


def _text(result: dict):
    return result["content"][0]["text"]


def test_allowed_tool_names_are_namespaced():
    assert allowed_tool_names() == [
        "mcp__content__inspect_tree",
        "mcp__content__list_data",
        "mcp__content__get_data",
        "mcp__content__add",
        "mcp__content__delete",
    ]


async def test_add_get_list_delete_flow_as_owner():
    mgr = make_manager()
    h = handlers("alice", mgr)

    assert not (await h["add"]({"parent_path": ["mongodb"], "name": "default"})).get("is_error")
    await h["add"]({"parent_path": ["mongodb", "default"], "name": "app"})
    await h["add"]({"parent_path": ["mongodb", "default", "app"], "name": "users"})
    added = await h["add"](
        {"parent_path": ["mongodb", "default", "app", "users"], "name": "u1",
         "data": {"name": "Al"}}
    )
    assert json.loads(_text(added))["kind"] == "document"

    got = await h["get_data"]({"path": ["mongodb", "default", "app", "users", "u1"]})
    assert json.loads(_text(got)) == {"name": "Al"}

    listed = await h["list_data"]({"path": ["mongodb", "default", "app", "users"]})
    assert json.loads(_text(listed)) == ["u1"]

    deleted = await h["delete"]({"path": ["mongodb", "default", "app", "users", "u1"]})
    assert not deleted.get("is_error")
    gone = await h["get_data"]({"path": ["mongodb", "default", "app", "users", "u1"]})
    assert gone.get("is_error")  # not owned / not found after delete


async def test_validation_error_becomes_is_error_not_exception():
    mgr = make_manager()
    h = handlers("alice", mgr)
    # get_data on a path that doesn't exist -> clean is_error, no raise
    res = await h["get_data"]({"path": ["dynamodb", "nope", "orders", "x"]})
    assert res["is_error"] is True


async def test_owner_is_bound_and_isolated():
    mgr = make_manager()
    # alice creates data
    ha = handlers("alice", mgr)
    await ha["add"]({"parent_path": ["s3"], "name": "default"})
    await ha["add"]({"parent_path": ["s3", "default"], "name": "assets"})
    await ha["add"]({"parent_path": ["s3", "default", "assets"], "name": "k1",
                     "data": {"v": 1}})

    # bob's tools cannot read alice's datum (same path, different bound owner)
    hb = handlers("bob", mgr)
    res = await hb["get_data"]({"path": ["s3", "default", "assets", "k1"]})
    assert res["is_error"] is True

"""Unit tests for the per-user content tools.

Drives the tool handlers directly against a ResourceManager backed by in-memory
infra — no live agent. Verifies the tools act as the bound owner, surface
validation errors as "failure" ToolResults, and never accept a user parameter.
"""

import json

from copilot import ToolInvocation, ToolResult

from app.agent.tools import TOOL_NAMES, _content_tools
from app.content.infra import InMemoryInfraProvider
from app.content.manager import ContentTreeStore, ResourceManager
from app.content.tree import Engine


def make_manager() -> ResourceManager:
    providers = {e: InMemoryInfraProvider(e) for e in Engine}
    return ResourceManager(providers, ContentTreeStore())


def handlers(owner: str, mgr: ResourceManager) -> dict:
    """Map tool name -> handler for the tools built for `owner`."""
    return {t.name: t.handler for t in _content_tools(owner, mgr)}


async def call(handler, arguments: dict) -> ToolResult:
    """Invoke a tool handler the way the SDK would: with a ToolInvocation."""
    return await handler(ToolInvocation(arguments=arguments))


def _text(result: ToolResult) -> str:
    return result.text_result_for_llm


def _is_error(result: ToolResult) -> bool:
    return result.error is not None or result.result_type == "failure"


def test_tools_expose_expected_names():
    mgr = make_manager()
    tools = _content_tools("alice", mgr)
    assert [t.name for t in tools] == TOOL_NAMES


def test_tools_are_pre_approved():
    mgr = make_manager()
    assert all(t.skip_permission for t in _content_tools("alice", mgr))


async def test_add_get_list_delete_flow_as_owner():
    mgr = make_manager()
    h = handlers("alice", mgr)

    assert not _is_error(await call(h["add"], {"parent_path": ["mongodb"], "name": "default"}))
    await call(h["add"], {"parent_path": ["mongodb", "default"], "name": "app"})
    await call(h["add"], {"parent_path": ["mongodb", "default", "app"], "name": "users"})
    added = await call(
        h["add"],
        {"parent_path": ["mongodb", "default", "app", "users"], "name": "u1",
         "data": {"name": "Al"}},
    )
    assert json.loads(_text(added))["kind"] == "document"

    got = await call(h["get_data"], {"path": ["mongodb", "default", "app", "users", "u1"]})
    assert json.loads(_text(got)) == {"name": "Al"}

    listed = await call(h["list_data"], {"path": ["mongodb", "default", "app", "users"]})
    assert json.loads(_text(listed)) == ["u1"]

    deleted = await call(h["delete"], {"path": ["mongodb", "default", "app", "users", "u1"]})
    assert not _is_error(deleted)
    gone = await call(h["get_data"], {"path": ["mongodb", "default", "app", "users", "u1"]})
    assert _is_error(gone)  # not owned / not found after delete


async def test_validation_error_becomes_failure_not_exception():
    mgr = make_manager()
    h = handlers("alice", mgr)
    # get_data on a path that doesn't exist -> clean failure, no raise
    res = await call(h["get_data"], {"path": ["dynamodb", "nope", "orders", "x"]})
    assert _is_error(res)


async def test_owner_is_bound_and_isolated():
    mgr = make_manager()
    # alice creates data
    ha = handlers("alice", mgr)
    await call(ha["add"], {"parent_path": ["s3"], "name": "default"})
    await call(ha["add"], {"parent_path": ["s3", "default"], "name": "assets"})
    await call(ha["add"], {"parent_path": ["s3", "default", "assets"], "name": "k1",
                           "data": {"v": 1}})

    # bob's tools cannot read alice's datum (same path, different bound owner)
    hb = handlers("bob", mgr)
    res = await call(hb["get_data"], {"path": ["s3", "default", "assets", "k1"]})
    assert _is_error(res)

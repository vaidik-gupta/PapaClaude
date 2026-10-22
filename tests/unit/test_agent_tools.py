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


# --- Permission gating for mutating tools -------------------------------------


class _FakeBridge:
    """A stand-in WidgetBridge: records presented widgets, returns a canned reply."""

    def __init__(self, reply: dict | None = None, raise_cancelled: bool = False):
        self.reply = reply or {}
        self.raise_cancelled = raise_cancelled
        self.presented: list[tuple[str, dict]] = []

    async def present_widget(self, widget_id: str, args: dict) -> dict:
        from app.agent.widgets import WidgetCancelled

        self.presented.append((widget_id, args))
        if self.raise_cancelled:
            raise WidgetCancelled(widget_id)
        return self.reply


async def _seed_datum(mgr: ResourceManager) -> None:
    h = handlers("alice", mgr)
    await call(h["add"], {"parent_path": ["mongodb"], "name": "default"})
    await call(h["add"], {"parent_path": ["mongodb", "default"], "name": "app"})
    await call(h["add"], {"parent_path": ["mongodb", "default", "app"], "name": "users"})
    await call(
        h["add"],
        {"parent_path": ["mongodb", "default", "app", "users"], "name": "u1",
         "data": {"n": 1}},
    )


def _delete_handler(mgr, permissions, bridge):
    from app.agent.tools import gate_tools

    tools = gate_tools(_content_tools("alice", mgr), permissions, bridge)
    return next(t.handler for t in tools if t.name == "delete")


async def test_delete_denied_by_permission():
    mgr = make_manager()
    await _seed_datum(mgr)
    handler = _delete_handler(mgr, {"delete": "deny"}, None)
    res = await call(handler, {"path": ["mongodb", "default", "app", "users", "u1"]})
    assert _is_error(res)
    # datum still present
    still = await call(handlers("alice", mgr)["get_data"],
                       {"path": ["mongodb", "default", "app", "users", "u1"]})
    assert not _is_error(still)


async def test_delete_ask_granted_proceeds():
    mgr = make_manager()
    await _seed_datum(mgr)
    bridge = _FakeBridge(reply={"granted": True})
    handler = _delete_handler(mgr, {"delete": "ask"}, bridge)
    res = await call(handler, {"path": ["mongodb", "default", "app", "users", "u1"]})
    assert not _is_error(res)
    assert bridge.presented and bridge.presented[0][0] == "permission"
    gone = await call(handlers("alice", mgr)["get_data"],
                      {"path": ["mongodb", "default", "app", "users", "u1"]})
    assert _is_error(gone)


async def test_delete_ask_denied_blocks():
    mgr = make_manager()
    await _seed_datum(mgr)
    bridge = _FakeBridge(reply={"granted": False})
    handler = _delete_handler(mgr, {"delete": "ask"}, bridge)
    res = await call(handler, {"path": ["mongodb", "default", "app", "users", "u1"]})
    assert _is_error(res)
    still = await call(handlers("alice", mgr)["get_data"],
                       {"path": ["mongodb", "default", "app", "users", "u1"]})
    assert not _is_error(still)


async def test_delete_ask_cancelled_blocks():
    mgr = make_manager()
    await _seed_datum(mgr)
    bridge = _FakeBridge(raise_cancelled=True)
    handler = _delete_handler(mgr, {"delete": "ask"}, bridge)
    res = await call(handler, {"path": ["mongodb", "default", "app", "users", "u1"]})
    assert _is_error(res)


async def test_delete_auto_skips_widget():
    mgr = make_manager()
    await _seed_datum(mgr)
    bridge = _FakeBridge(reply={"granted": True})
    handler = _delete_handler(mgr, {"delete": "auto"}, bridge)
    res = await call(handler, {"path": ["mongodb", "default", "app", "users", "u1"]})
    assert not _is_error(res)
    assert bridge.presented == []  # auto never asks


async def test_gate_tools_is_generic_across_tools():
    # The wrapper gates by tool name, so any tool (not just delete) is covered:
    # denying `add` blocks it and asking on `get_data` presents a widget.
    from app.agent.tools import gate_tools

    mgr = make_manager()
    await _seed_datum(mgr)

    deny_add = gate_tools(_content_tools("alice", mgr), {"add": "deny"}, None)
    add_handler = next(t.handler for t in deny_add if t.name == "add")
    res = await call(add_handler, {"parent_path": ["mongodb", "default", "app", "users"],
                                   "name": "u2", "data": {"n": 2}})
    assert _is_error(res)

    bridge = _FakeBridge(reply={"granted": True})
    ask_get = gate_tools(_content_tools("alice", mgr), {"get_data": "ask"}, bridge)
    get_handler = next(t.handler for t in ask_get if t.name == "get_data")
    ok = await call(get_handler, {"path": ["mongodb", "default", "app", "users", "u1"]})
    assert not _is_error(ok)
    assert bridge.presented and bridge.presented[0][0] == "permission"

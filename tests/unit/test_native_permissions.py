"""Unit tests for the native permission handler (built-in tool gating).

Maps the per-agent `{auto|ask|deny}` config onto the Copilot SDK's native
permission decisions, routing `ask` to the widget bridge. Uses a real
`PermissionRequestRead` and a fake bridge to assert each outcome without a live
session.
"""

import asyncio

import pytest
from copilot.generated.rpc import (
    PermissionDecisionApproveOnce,
    PermissionDecisionReject,
)
from copilot.generated.session_events import (
    PermissionRequestRead,
    PermissionRequestWrite,
)

from app.agent.native_permissions import build_permission_handler
from app.agent.widgets import PendingWidgets, WidgetBridge
from app.conversations.schema import EventType


def _read(path: str = "/tmp/f.txt") -> PermissionRequestRead:
    return PermissionRequestRead(intention="read it", path=path)


def _write(
    file_name: str = "/tmp/f.txt", diff: str = "--- a\n+++ b\n+hello\n"
) -> PermissionRequestWrite:
    return PermissionRequestWrite(
        can_offer_session_approval=True,
        diff=diff,
        file_name=file_name,
        intention="write it",
    )


def _bridge(registry: PendingWidgets):
    emitted: list[tuple[EventType, dict]] = []
    bridge = WidgetBridge(
        emit=lambda t, p: emitted.append((t, p)),
        conversation_id="conv-1",
        registry=registry,
    )
    return bridge, emitted


async def test_auto_approves_without_widget():
    reg = PendingWidgets()
    bridge, emitted = _bridge(reg)
    handler = build_permission_handler({"read": "auto"}, bridge)

    result = await handler(_read(), {"session_id": "s"})

    assert isinstance(result, PermissionDecisionApproveOnce)
    assert emitted == []  # no widget presented


async def test_deny_rejects_without_widget():
    reg = PendingWidgets()
    bridge, emitted = _bridge(reg)
    handler = build_permission_handler({"read": "deny"}, bridge)

    result = await handler(_read(), {"session_id": "s"})

    assert isinstance(result, PermissionDecisionReject)
    assert emitted == []


async def test_ask_grant_presents_widget_then_approves():
    reg = PendingWidgets()
    bridge, emitted = _bridge(reg)
    handler = build_permission_handler({"read": "ask"}, bridge)

    task = asyncio.create_task(handler(_read("/etc/hosts"), {"session_id": "s"}))
    await asyncio.sleep(0)  # let present_widget register + emit

    assert emitted[0][0] == EventType.WIDGET
    payload = emitted[0][1]
    assert payload["widget_id"] == "permission"
    assert payload["args"]["tool"] == "read"
    assert payload["args"]["args"] == {"path": "/etc/hosts"}

    assert reg.resolve(payload["instance_id"], "conv-1", {"granted": True}) is True
    result = await task

    assert isinstance(result, PermissionDecisionApproveOnce)


async def test_ask_deny_presents_widget_then_rejects():
    reg = PendingWidgets()
    bridge, emitted = _bridge(reg)
    handler = build_permission_handler({"read": "ask"}, bridge)

    task = asyncio.create_task(handler(_read(), {"session_id": "s"}))
    await asyncio.sleep(0)
    reg.resolve(emitted[0][1]["instance_id"], "conv-1", {"granted": False})

    result = await task
    assert isinstance(result, PermissionDecisionReject)


async def test_ask_cancelled_rejects():
    reg = PendingWidgets()
    bridge, emitted = _bridge(reg)
    handler = build_permission_handler({"read": "ask"}, bridge)

    task = asyncio.create_task(handler(_read(), {"session_id": "s"}))
    await asyncio.sleep(0)
    bridge.cancel_all()

    result = await task
    assert isinstance(result, PermissionDecisionReject)


async def test_ask_without_bridge_approves():
    # No stream to surface a widget on -> ask proceeds.
    handler = build_permission_handler({"read": "ask"}, None)
    result = await handler(_read(), {"session_id": "s"})
    assert isinstance(result, PermissionDecisionApproveOnce)


async def test_read_defaults_to_ask_when_unconfigured():
    reg = PendingWidgets()
    bridge, emitted = _bridge(reg)
    handler = build_permission_handler(None, bridge)  # no config -> DEFAULT_PERMISSIONS

    task = asyncio.create_task(handler(_read(), {"session_id": "s"}))
    await asyncio.sleep(0)

    assert emitted and emitted[0][0] == EventType.WIDGET  # read default is ask
    reg.resolve(emitted[0][1]["instance_id"], "conv-1", {"granted": False})
    await task


async def test_write_ask_presents_diff_widget_then_approves():
    reg = PendingWidgets()
    bridge, emitted = _bridge(reg)
    handler = build_permission_handler({"write": "ask"}, bridge)

    task = asyncio.create_task(
        handler(_write("/tmp/x.py", "--- a\n+++ b\n+x = 1\n"), {"session_id": "s"})
    )
    await asyncio.sleep(0)  # let present_widget register + emit

    assert emitted[0][0] == EventType.WIDGET
    payload = emitted[0][1]
    assert payload["widget_id"] == "diff"  # write uses the diff widget, not permission
    assert payload["args"]["tool"] == "write"
    assert payload["args"]["file_name"] == "/tmp/x.py"
    assert payload["args"]["diff"] == "--- a\n+++ b\n+x = 1\n"

    assert reg.resolve(payload["instance_id"], "conv-1", {"granted": True}) is True
    result = await task
    assert isinstance(result, PermissionDecisionApproveOnce)


async def test_write_deny_rejects_without_widget():
    reg = PendingWidgets()
    bridge, emitted = _bridge(reg)
    handler = build_permission_handler({"write": "deny"}, bridge)

    result = await handler(_write(), {"session_id": "s"})

    assert isinstance(result, PermissionDecisionReject)
    assert emitted == []


async def test_write_defaults_to_ask_when_unconfigured():
    reg = PendingWidgets()
    bridge, emitted = _bridge(reg)
    handler = build_permission_handler(None, bridge)  # no config -> DEFAULT_PERMISSIONS

    task = asyncio.create_task(handler(_write(), {"session_id": "s"}))
    await asyncio.sleep(0)

    assert emitted and emitted[0][0] == EventType.WIDGET
    assert emitted[0][1]["widget_id"] == "diff"
    reg.resolve(emitted[0][1]["instance_id"], "conv-1", {"granted": False})
    await task

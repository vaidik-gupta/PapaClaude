"""Unit tests for the widget primitive (WidgetBridge + PendingWidgets).

Exercises present_widget's two outcomes — resolved (answered) and cancelled —
with a fake emit sink, asserting the emitted event sequence and the
process-global registry's resolve/cancel behavior.
"""

import asyncio

import pytest

from app.agent.widgets import (
    PendingWidgets,
    WidgetBridge,
    WidgetCancelled,
)
from app.conversations.schema import EventType


def _bridge(registry: PendingWidgets):
    emitted: list[tuple[EventType, dict]] = []
    bridge = WidgetBridge(
        emit=lambda t, p: emitted.append((t, p)),
        conversation_id="conv-1",
        registry=registry,
    )
    return bridge, emitted


async def test_present_widget_resolves_with_value():
    reg = PendingWidgets()
    bridge, emitted = _bridge(reg)

    task = asyncio.create_task(bridge.present_widget("permission", {"tool": "delete"}))
    await asyncio.sleep(0)  # let present_widget register + emit

    # One widget event emitted carrying an instance id.
    assert emitted[0][0] == EventType.WIDGET
    instance_id = emitted[0][1]["instance_id"]
    assert emitted[0][1]["widget_id"] == "permission"

    assert reg.resolve(instance_id, "conv-1", {"granted": True}) is True
    result = await task

    assert result == {"granted": True}
    assert emitted[1][0] == EventType.WIDGET_RESPONSE
    assert emitted[1][1]["status"] == "answered"
    # Registry no longer tracks it.
    assert reg.resolve(instance_id, "conv-1", {}) is False


async def test_present_widget_cancel_all_raises():
    reg = PendingWidgets()
    bridge, emitted = _bridge(reg)

    task = asyncio.create_task(bridge.present_widget("permission", {}))
    await asyncio.sleep(0)

    bridge.cancel_all()
    with pytest.raises(WidgetCancelled):
        await task

    assert emitted[-1][0] == EventType.WIDGET_RESPONSE
    assert emitted[-1][1]["status"] == "cancelled"


async def test_resolve_rejects_foreign_conversation():
    reg = PendingWidgets()
    bridge, emitted = _bridge(reg)

    task = asyncio.create_task(bridge.present_widget("permission", {}))
    await asyncio.sleep(0)
    instance_id = emitted[0][1]["instance_id"]

    # Wrong conversation id must not resolve the widget.
    assert reg.resolve(instance_id, "other-conv", {"granted": True}) is False
    assert reg.resolve("unknown-id", "conv-1", {}) is False

    bridge.cancel_all()
    with pytest.raises(WidgetCancelled):
        await task

"""Unit tests for the built-in `ask_user` elicitation bridge.

`build_user_input_handler` maps the SDK's `userInput.request` (from the native
`ask_user` tool) onto our widget overlay: a `choice` widget when the request
offers choices, a `question` widget otherwise. A fake bridge drives each
outcome without a live session.
"""

import asyncio

from app.agent.user_input import build_user_input_handler
from app.agent.widgets import PendingWidgets, WidgetBridge
from app.conversations.schema import EventType


def _bridge(registry: PendingWidgets):
    emitted: list[tuple[EventType, dict]] = []
    bridge = WidgetBridge(
        emit=lambda t, p: emitted.append((t, p)),
        conversation_id="conv-1",
        registry=registry,
    )
    return bridge, emitted


async def test_no_choices_presents_question_widget():
    reg = PendingWidgets()
    bridge, emitted = _bridge(reg)
    handler = build_user_input_handler(bridge)

    task = asyncio.create_task(
        handler({"question": "Your name?", "allowFreeform": True}, {"session_id": "s"})
    )
    await asyncio.sleep(0)  # let present_widget register + emit

    payload = emitted[0][1]
    assert payload["widget_id"] == "question"
    assert payload["args"] == {"question": "Your name?"}

    reg.resolve(payload["instance_id"], "conv-1", {"value": "Ada"})
    result = await task
    assert result == {"answer": "Ada", "wasFreeform": True}


async def test_choices_present_choice_widget_and_mark_not_freeform():
    reg = PendingWidgets()
    bridge, emitted = _bridge(reg)
    handler = build_user_input_handler(bridge)

    task = asyncio.create_task(
        handler(
            {"question": "Pick", "choices": ["a", "b"], "allowFreeform": False},
            {"session_id": "s"},
        )
    )
    await asyncio.sleep(0)

    payload = emitted[0][1]
    assert payload["widget_id"] == "choice"
    assert payload["args"] == {"question": "Pick", "options": ["a", "b"]}

    reg.resolve(payload["instance_id"], "conv-1", {"value": "b"})
    result = await task
    assert result == {"answer": "b", "wasFreeform": False}


async def test_freeform_answer_to_choice_request_is_marked_freeform():
    reg = PendingWidgets()
    bridge, emitted = _bridge(reg)
    handler = build_user_input_handler(bridge)

    task = asyncio.create_task(
        handler({"question": "Pick", "choices": ["a", "b"]}, {"session_id": "s"})
    )
    await asyncio.sleep(0)
    reg.resolve(emitted[0][1]["instance_id"], "conv-1", {"value": "something else"})

    result = await task
    assert result == {"answer": "something else", "wasFreeform": True}


async def test_cancelled_returns_empty_answer():
    reg = PendingWidgets()
    bridge, emitted = _bridge(reg)
    handler = build_user_input_handler(bridge)

    task = asyncio.create_task(
        handler({"question": "Your name?"}, {"session_id": "s"})
    )
    await asyncio.sleep(0)
    bridge.cancel_all()

    result = await task
    assert result == {"answer": "", "wasFreeform": True}


async def test_no_bridge_returns_empty_answer():
    handler = build_user_input_handler(None)
    result = await handler({"question": "Your name?"}, {"session_id": "s"})
    assert result == {"answer": "", "wasFreeform": True}

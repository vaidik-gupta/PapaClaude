"""Unit tests for the SDK-message -> domain-event translation seam.

Pure function; no live agent query, so these run without the Claude CLI or auth.
"""

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from app.agent.client import _translate
from app.conversations.schema import EventType


def _types(message):
    return [e.type for e in _translate(message)]


def test_assistant_blocks_map_to_events():
    msg = AssistantMessage(
        content=[
            ThinkingBlock(thinking="hmm", signature="sig"),
            TextBlock(text="hello"),
            ToolUseBlock(id="t1", name="calc", input={"x": 2}),
        ],
        model="claude",
    )
    events = list(_translate(msg))
    assert [e.type for e in events] == [
        EventType.THINKING,
        EventType.ASSISTANT_TEXT,
        EventType.TOOL_USE,
    ]
    assert events[1].payload == {"text": "hello"}
    assert events[2].payload == {"id": "t1", "name": "calc", "input": {"x": 2}}


def test_user_message_yields_only_tool_results():
    msg = UserMessage(
        content=[
            TextBlock(text="echoed prompt — should be ignored"),
            ToolResultBlock(tool_use_id="t1", content="4", is_error=False),
        ]
    )
    events = list(_translate(msg))
    assert len(events) == 1
    assert events[0].type is EventType.TOOL_RESULT
    assert events[0].payload["tool_use_id"] == "t1"
    assert events[0].payload["content"] == "4"


def test_system_message():
    assert _types(SystemMessage(subtype="init", data={"k": "v"})) == [EventType.SYSTEM]


def test_result_message_carries_session_and_summary():
    msg = ResultMessage(
        subtype="success",
        duration_ms=10,
        duration_api_ms=8,
        is_error=False,
        num_turns=1,
        session_id="sess-abc",
        stop_reason="end_turn",
        total_cost_usd=0.01,
        result="the answer",
    )
    (event,) = list(_translate(msg))
    assert event.type is EventType.RESULT
    assert event.payload["session_id"] == "sess-abc"
    assert event.payload["text"] == "the answer"
    assert event.payload["stop_reason"] == "end_turn"
    assert event.payload["total_cost_usd"] == 0.01

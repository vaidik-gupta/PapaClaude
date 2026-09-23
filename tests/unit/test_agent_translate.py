"""Unit tests for the Copilot-event -> domain-event translation seam.

Pure functions over constructed Copilot event data; no live session, so these
run without the Copilot runtime or auth.
"""

from copilot.session_events import (
    AssistantMessageData,
    AssistantReasoningData,
    AssistantUsageData,
    SessionErrorData,
    SessionIdleData,
    ToolExecutionCompleteData,
    ToolExecutionCompleteError,
    ToolExecutionCompleteResult,
    ToolExecutionStartData,
)

from app.agent.client import _translate, _TurnState
from app.conversations.schema import EventType


def _one(data):
    events = list(_translate(data))
    assert len(events) == 1
    return events[0]


def test_assistant_message_maps_to_text():
    ev = _one(AssistantMessageData(content="hello", message_id="m1"))
    assert ev.type is EventType.ASSISTANT_TEXT
    assert ev.payload == {"text": "hello"}


def test_reasoning_maps_to_thinking():
    ev = _one(AssistantReasoningData(content="hmm", reasoning_id="r1"))
    assert ev.type is EventType.THINKING
    assert ev.payload == {"thinking": "hmm"}


def test_tool_start_maps_to_tool_use():
    ev = _one(ToolExecutionStartData(tool_call_id="t1", tool_name="calc", arguments={"x": 2}))
    assert ev.type is EventType.TOOL_USE
    assert ev.payload == {"id": "t1", "name": "calc", "input": {"x": 2}}


def test_tool_complete_success_maps_to_tool_result():
    ev = _one(
        ToolExecutionCompleteData(
            success=True, tool_call_id="t1", result=ToolExecutionCompleteResult(content="4")
        )
    )
    assert ev.type is EventType.TOOL_RESULT
    assert ev.payload == {"tool_use_id": "t1", "content": "4", "is_error": False}


def test_tool_complete_failure_uses_error_message():
    ev = _one(
        ToolExecutionCompleteData(
            success=False, tool_call_id="t1", error=ToolExecutionCompleteError(message="boom")
        )
    )
    assert ev.type is EventType.TOOL_RESULT
    assert ev.payload == {"tool_use_id": "t1", "content": "boom", "is_error": True}


def test_session_error_maps_to_error():
    ev = _one(SessionErrorData(error_type="model", message="rate limited"))
    assert ev.type is EventType.ERROR
    assert ev.payload == {"message": "rate limited"}


def test_idle_is_not_translated_directly():
    # The terminal RESULT is assembled by _TurnState, not _translate.
    assert list(_translate(SessionIdleData())) == []


def test_turn_state_assembles_result_payload():
    state = _TurnState()
    state.observe(AssistantMessageData(content="the answer", message_id="m1"))
    state.observe(AssistantUsageData(model="claude", cost=0.006, finish_reason="stop"))
    state.observe(AssistantUsageData(model="claude", cost=0.004, finish_reason="stop"))
    state.observe(SessionIdleData(aborted=False))

    payload = state.result_payload("sess-abc")
    assert payload["session_id"] == "sess-abc"
    assert payload["text"] == "the answer"
    assert payload["stop_reason"] == "stop"
    assert payload["total_cost_req"] == 0.01  # summed across usage events
    assert payload["is_error"] is False


def test_turn_state_flags_error_and_abort():
    aborted = _TurnState()
    aborted.observe(SessionIdleData(aborted=True))
    assert aborted.result_payload("s")["is_error"] is True

    errored = _TurnState()
    errored.observe(SessionErrorData(error_type="model", message="x"))
    assert errored.result_payload("s")["is_error"] is True

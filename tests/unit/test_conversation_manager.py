"""Unit tests for ConversationManager orchestration.

Uses an in-memory fake store and a fake agent runner, so there is no DB or live
agent — the focus is persist-and-stream ordering, turn finalization, and session
resume across turns.
"""

import pytest

from app.agent.client import AgentEvent
from app.conversations.manager import ConversationManager
from app.conversations.schema import (
    Conversation,
    Event,
    EventType,
    Turn,
    TurnStatus,
)
from app.conversations.store import ConversationStore


class FakeStore(ConversationStore):
    def __init__(self) -> None:
        self.conversations: dict[str, Conversation] = {}
        self.turns: dict[str, Turn] = {}
        self.events: list[Event] = []

    async def create_conversation(self, conversation: Conversation) -> Conversation:
        self.conversations[conversation.id] = conversation
        return conversation

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        return self.conversations.get(conversation_id)

    async def list_conversations(self, owner: str) -> list[Conversation]:
        return [c for c in self.conversations.values() if c.owner == owner]

    async def update_conversation(self, conversation_id: str, **fields) -> None:
        # Re-validate the merged doc so JSON-safe update fields coerce back to
        # models/enums, mirroring the real store's Model(**doc) round-trip.
        merged = {**self.conversations[conversation_id].model_dump(mode="json"), **fields}
        self.conversations[conversation_id] = Conversation(**merged)

    async def next_turn_index(self, conversation_id: str) -> int:
        return sum(1 for t in self.turns.values() if t.conversation_id == conversation_id)

    async def append_turn(self, turn: Turn) -> Turn:
        self.turns[turn.id] = turn
        return turn

    async def update_turn(self, turn_id: str, **fields) -> None:
        merged = {**self.turns[turn_id].model_dump(mode="json"), **fields}
        self.turns[turn_id] = Turn(**merged)

    async def get_turns(self, conversation_id: str) -> list[Turn]:
        ts = [t for t in self.turns.values() if t.conversation_id == conversation_id]
        return sorted(ts, key=lambda t: t.index)

    async def append_event(self, event: Event) -> Event:
        self.events.append(event)
        return event

    async def get_events(self, turn_id: str) -> list[Event]:
        return [e for e in self.events if e.turn_id == turn_id]


def _fake_runner(events: list[AgentEvent]):
    """Build an agent_runner that records the resume id it was called with."""
    calls: list[str | None] = []

    async def runner(prompt, *, resume_session_id=None, system_prompt=None):
        calls.append(resume_session_id)
        for ev in events:
            yield ev

    return runner, calls


async def test_run_turn_persists_streams_and_finalizes():
    store = FakeStore()
    events = [
        AgentEvent(EventType.SYSTEM, {"subtype": "init"}),
        AgentEvent(EventType.ASSISTANT_TEXT, {"text": "PONG"}),
        AgentEvent(EventType.RESULT, {"session_id": "sess-1", "text": "PONG",
                                      "stop_reason": "end_turn"}),
    ]
    runner, calls = _fake_runner(events)
    mgr = ConversationManager(store=store, agent_runner=runner)

    conv = await mgr.create_conversation(owner="u")
    streamed = [e async for e in mgr.run_turn(conv.id, "ping", owner="u")]

    # Every agent event was re-yielded, in order, with 0-based indices.
    assert [e.type for e in streamed] == [
        EventType.SYSTEM, EventType.ASSISTANT_TEXT, EventType.RESULT
    ]
    assert [e.index for e in streamed] == [0, 1, 2]
    # ...and every one was persisted.
    assert len(store.events) == 3

    # First turn resumes nothing.
    assert calls == [None]

    # Turn finalized with the result summary.
    turn = (await store.get_turns(conv.id))[0]
    assert turn.status is TurnStatus.COMPLETE
    assert turn.result.text == "PONG"
    assert turn.completed_at is not None

    # Session pointer saved onto the conversation.
    assert (await store.get_conversation(conv.id)).sdk_session_id == "sess-1"


async def test_second_turn_resumes_saved_session():
    store = FakeStore()
    result_ev = AgentEvent(EventType.RESULT, {"session_id": "sess-1", "text": "ok"})
    runner, calls = _fake_runner([result_ev])
    mgr = ConversationManager(store=store, agent_runner=runner)

    conv = await mgr.create_conversation(owner="u")
    _ = [e async for e in mgr.run_turn(conv.id, "first", owner="u")]
    _ = [e async for e in mgr.run_turn(conv.id, "second", owner="u")]

    # Turn 1 resumed None; turn 2 resumed the id saved from turn 1.
    assert calls == [None, "sess-1"]
    assert await store.next_turn_index(conv.id) == 2


async def test_error_mid_turn_records_error_event_and_status():
    store = FakeStore()

    async def failing_runner(prompt, *, resume_session_id=None, system_prompt=None):
        yield AgentEvent(EventType.ASSISTANT_TEXT, {"text": "partial"})
        raise RuntimeError("boom")

    mgr = ConversationManager(store=store, agent_runner=failing_runner)
    conv = await mgr.create_conversation(owner="u")

    streamed = [e async for e in mgr.run_turn(conv.id, "ping", owner="u")]
    assert [e.type for e in streamed] == [EventType.ASSISTANT_TEXT, EventType.ERROR]
    assert streamed[-1].payload["message"] == "boom"

    turn = (await store.get_turns(conv.id))[0]
    assert turn.status is TurnStatus.ERROR


async def test_run_turn_rejects_wrong_owner():
    store = FakeStore()
    runner, _ = _fake_runner([])
    mgr = ConversationManager(store=store, agent_runner=runner)
    conv = await mgr.create_conversation(owner="owner")

    with pytest.raises(ValueError, match="not found"):
        _ = [e async for e in mgr.run_turn(conv.id, "hi", owner="intruder")]

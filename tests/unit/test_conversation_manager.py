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
from app.personas.schema import Manifest, Role


class FakeRegistry:
    """Minimal registry exposing the default parent/child manifests the manager
    resolves on create."""

    def __init__(self) -> None:
        self._manifests = {
            "default-parent": Manifest(name="default-parent", role=Role.PARENT),
            "default-child": Manifest(name="default-child", role=Role.CHILD),
        }

    def get(self, name: str) -> Manifest:
        return self._manifests[name]


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

    async def list_conversations(
        self, owner: str, role: str | None = None
    ) -> list[Conversation]:
        convs = [c for c in self.conversations.values() if c.owner == owner]
        if role is not None:
            convs = [c for c in convs if c.role.value == role]
        return convs

    async def get_children(self, parent_id: str) -> list[Conversation]:
        return [c for c in self.conversations.values() if c.parent_id == parent_id]

    async def update_conversation(self, conversation_id: str, **fields) -> None:
        # Re-validate the merged doc so JSON-safe update fields coerce back to
        # models/enums, mirroring the real store's Model(**doc) round-trip.
        merged = {**self.conversations[conversation_id].model_dump(mode="json"), **fields}
        self.conversations[conversation_id] = Conversation(**merged)

    async def delete_conversation(self, conversation_id: str) -> None:
        self.conversations.pop(conversation_id, None)
        self.turns = {
            tid: t for tid, t in self.turns.items() if t.conversation_id != conversation_id
        }
        self.events = [e for e in self.events if e.conversation_id != conversation_id]

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

    async def runner(prompt, *, owner=None, resume_session_id=None, system_prompt=None, **kw):
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
    mgr = ConversationManager(store=store, agent_runner=runner, registry=FakeRegistry())

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
    mgr = ConversationManager(store=store, agent_runner=runner, registry=FakeRegistry())

    conv = await mgr.create_conversation(owner="u")
    _ = [e async for e in mgr.run_turn(conv.id, "first", owner="u")]
    _ = [e async for e in mgr.run_turn(conv.id, "second", owner="u")]

    # Turn 1 resumed None; turn 2 resumed the id saved from turn 1.
    assert calls == [None, "sess-1"]
    assert await store.next_turn_index(conv.id) == 2


async def test_error_mid_turn_records_error_event_and_status():
    store = FakeStore()

    async def failing_runner(prompt, *, owner=None, resume_session_id=None, system_prompt=None,
                             **kw):
        yield AgentEvent(EventType.ASSISTANT_TEXT, {"text": "partial"})
        raise RuntimeError("boom")

    mgr = ConversationManager(store=store, agent_runner=failing_runner, registry=FakeRegistry())
    conv = await mgr.create_conversation(owner="u")

    streamed = [e async for e in mgr.run_turn(conv.id, "ping", owner="u")]
    assert [e.type for e in streamed] == [EventType.ASSISTANT_TEXT, EventType.ERROR]
    assert streamed[-1].payload["message"] == "boom"

    turn = (await store.get_turns(conv.id))[0]
    assert turn.status is TurnStatus.ERROR


async def test_result_flagged_is_error_marks_turn_error():
    store = FakeStore()
    result_ev = AgentEvent(EventType.RESULT, {"is_error": True, "text": "", "stop_reason": "budget"})
    runner, _ = _fake_runner([result_ev])
    mgr = ConversationManager(store=store, agent_runner=runner, registry=FakeRegistry())

    conv = await mgr.create_conversation(owner="u")
    _ = [e async for e in mgr.run_turn(conv.id, "hi", owner="u")]

    turn = (await store.get_turns(conv.id))[0]
    assert turn.status is TurnStatus.ERROR


async def test_run_turn_rejects_wrong_owner():
    store = FakeStore()
    runner, _ = _fake_runner([])
    mgr = ConversationManager(store=store, agent_runner=runner, registry=FakeRegistry())
    conv = await mgr.create_conversation(owner="owner")

    with pytest.raises(ValueError, match="not found"):
        _ = [e async for e in mgr.run_turn(conv.id, "hi", owner="intruder")]


async def test_delete_conversation_removes_turns_and_events():
    store = FakeStore()
    runner, _ = _fake_runner(
        [AgentEvent(EventType.RESULT, {"text": "ok", "session_id": "s1"})]
    )
    mgr = ConversationManager(store=store, agent_runner=runner, registry=FakeRegistry())
    conv = await mgr.create_conversation(owner="owner")
    _ = [e async for e in mgr.run_turn(conv.id, "hi", owner="owner")]

    await mgr.delete_conversation(conv.id, owner="owner")

    assert conv.id not in store.conversations
    assert all(t.conversation_id != conv.id for t in store.turns.values())
    assert all(e.conversation_id != conv.id for e in store.events)


async def test_delete_papa_cascades_to_children():
    store = FakeStore()
    runner, _ = _fake_runner([])
    mgr = ConversationManager(store=store, agent_runner=runner, registry=FakeRegistry())
    papa = await mgr.create_conversation(owner="owner")
    child = await mgr.create_child(
        parent_id=papa.id, owner="owner", manifest_name="default-child"
    )

    await mgr.delete_conversation(papa.id, owner="owner")

    assert papa.id not in store.conversations
    assert child.id not in store.conversations


async def test_delete_conversation_rejects_wrong_owner():
    store = FakeStore()
    runner, _ = _fake_runner([])
    mgr = ConversationManager(store=store, agent_runner=runner, registry=FakeRegistry())
    conv = await mgr.create_conversation(owner="owner")

    with pytest.raises(ValueError, match="not found"):
        await mgr.delete_conversation(conv.id, owner="intruder")
    assert conv.id in store.conversations

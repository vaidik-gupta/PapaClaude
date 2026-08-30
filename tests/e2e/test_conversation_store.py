"""Round-trip the conversation domain model through MongoConversationStore.

Marked e2e — needs the local MongoDB container (see conftest.dbs_available).
"""

import pytest

from app.conversations.schema import (
    Conversation,
    Event,
    EventType,
    Turn,
    TurnResult,
    TurnStatus,
)
from app.conversations.store import MongoConversationStore
from app.db.mongodb.mongodb import mongodb

pytestmark = pytest.mark.e2e


@pytest.fixture
async def store(dbs_available):
    await mongodb.connect()
    s = MongoConversationStore()
    await s.ensure_ready()
    created: list[tuple[str, dict]] = []
    yield s, created
    # Clean up only what this test created.
    for coll, query in created:
        await mongodb.db[coll].delete_many(query)
    await mongodb.close()


async def test_conversation_turn_event_roundtrip(store):
    s, created = store

    conv = await s.create_conversation(Conversation(owner="tester", title="hello"))
    created.append((s.CONVERSATIONS, {"id": conv.id}))
    created.append((s.TURNS, {"conversation_id": conv.id}))

    fetched = await s.get_conversation(conv.id)
    assert fetched is not None
    assert fetched.owner == "tester"
    assert fetched.sdk_session_id is None

    # First turn takes index 0.
    assert await s.next_turn_index(conv.id) == 0
    turn = await s.append_turn(
        Turn(conversation_id=conv.id, index=0, prompt="what is 2+2?")
    )
    created.append((s.EVENTS, {"turn_id": turn.id}))
    assert await s.next_turn_index(conv.id) == 1

    # Events land in order.
    for i, etype in enumerate([EventType.ASSISTANT_TEXT, EventType.RESULT]):
        await s.append_event(
            Event(
                conversation_id=conv.id,
                turn_id=turn.id,
                index=i,
                type=etype,
                payload={"n": i},
            )
        )
    events = await s.get_events(turn.id)
    assert [e.type for e in events] == [EventType.ASSISTANT_TEXT, EventType.RESULT]
    assert [e.index for e in events] == [0, 1]

    # Finalize the turn and save the session pointer on the conversation.
    await s.update_turn(
        turn.id,
        status=TurnStatus.COMPLETE.value,
        result=TurnResult(text="4", stop_reason="end_turn").model_dump(mode="json"),
    )
    await s.update_conversation(conv.id, sdk_session_id="sess-123")

    turns = await s.get_turns(conv.id)
    assert len(turns) == 1
    assert turns[0].status is TurnStatus.COMPLETE
    assert turns[0].result.text == "4"
    assert (await s.get_conversation(conv.id)).sdk_session_id == "sess-123"

    convs = await s.list_conversations("tester")
    assert conv.id in {c.id for c in convs}

"""ConversationManager — orchestrates a turn: agent + persistence + streaming.

It resumes the conversation's SDK session, runs the turn, and for every event
the agent emits it persists the event THEN re-yields it (persist-and-stream in
one pass). When the turn's result arrives it finalizes the Turn and saves the
SDK session pointer back onto the Conversation so the next turn can resume it.

The agent runner and the store are both injected (defaulting to the real ones)
so the orchestration can be unit-tested without a live agent or a database.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from app.agent.client import AgentEvent, run_turn
from app.conversations.schema import (
    Conversation,
    Event,
    EventType,
    Turn,
    TurnResult,
    TurnStatus,
)
from app.conversations.store import ConversationStore, MongoConversationStore
from app.logging_config import get_logger

logger = get_logger(__name__)


class ConversationManager:
    def __init__(
        self,
        store: ConversationStore | None = None,
        agent_runner=run_turn,
    ) -> None:
        self._store = store or MongoConversationStore()
        self._run_turn = agent_runner

    async def ensure_ready(self) -> None:
        await self._store.ensure_ready()

    async def create_conversation(self, owner: str, title: str | None = None) -> Conversation:
        return await self._store.create_conversation(Conversation(owner=owner, title=title))

    async def list_conversations(self, owner: str) -> list[Conversation]:
        return await self._store.list_conversations(owner)

    async def get_conversation(self, conversation_id: str, owner: str) -> Conversation:
        conv = await self._store.get_conversation(conversation_id)
        if conv is None or conv.owner != owner:
            raise ValueError("conversation not found")
        return conv

    async def get_turns(self, conversation_id: str) -> list[Turn]:
        return await self._store.get_turns(conversation_id)

    async def get_events(self, turn_id: str) -> list[Event]:
        return await self._store.get_events(turn_id)

    async def run_turn(
        self, conversation_id: str, prompt: str, owner: str
    ) -> AsyncIterator[Event]:
        """Run one turn, persisting each event as it streams and re-yielding it."""
        conv = await self.get_conversation(conversation_id, owner)

        index = await self._store.next_turn_index(conversation_id)
        turn = await self._store.append_turn(
            Turn(conversation_id=conversation_id, index=index, prompt=prompt)
        )
        logger.info("Turn %d started on conversation %s", index, conversation_id)

        event_index = 0
        result: AgentEvent | None = None
        try:
            async for agent_event in self._run_turn(
                prompt, owner=owner, resume_session_id=conv.sdk_session_id
            ):
                event = await self._persist_event(
                    conversation_id, turn.id, event_index, agent_event
                )
                event_index += 1
                if agent_event.type is EventType.RESULT:
                    result = agent_event
                yield event
        except Exception as exc:
            # Record the failure as an event; don't crash the SSE stream.
            logger.exception("Turn %s failed", turn.id)
            err = await self._persist_event(
                conversation_id,
                turn.id,
                event_index,
                AgentEvent(EventType.ERROR, {"message": str(exc)}),
            )
            await self._store.update_turn(
                turn.id, status=TurnStatus.ERROR.value, completed_at=_now_iso()
            )
            yield err
            return

        await self._finalize(conv, turn.id, result)

    async def _persist_event(
        self, conversation_id: str, turn_id: str, index: int, agent_event: AgentEvent
    ) -> Event:
        event = Event(
            conversation_id=conversation_id,
            turn_id=turn_id,
            index=index,
            type=agent_event.type,
            payload=agent_event.payload,
        )
        await self._store.append_event(event)
        return event

    async def _finalize(
        self, conv: Conversation, turn_id: str, result: AgentEvent | None
    ) -> None:
        payload = result.payload if result else {}
        turn_result = TurnResult(
            text=payload.get("text", ""),
            stop_reason=payload.get("stop_reason"),
            num_turns=payload.get("num_turns"),
            total_cost_req=payload.get("total_cost_req"),
        )
        # A result flagged is_error (budget/max-turns/API error) is a failed turn.
        status = TurnStatus.ERROR if payload.get("is_error") else TurnStatus.COMPLETE
        await self._store.update_turn(
            turn_id,
            status=status.value,
            result=turn_result.model_dump(mode="json"),
            completed_at=_now_iso(),
        )

        # Save/refresh the SDK session pointer so the next turn resumes it.
        session_id = payload.get("session_id")
        fields = {"updated_at": _now_iso()}
        if session_id and session_id != conv.sdk_session_id:
            fields["sdk_session_id"] = session_id
        await self._store.update_conversation(conv.id, **fields)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


conversation_manager = ConversationManager()

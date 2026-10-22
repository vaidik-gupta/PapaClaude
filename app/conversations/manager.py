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
from app.personas.registry import ManifestRegistry, manifest_registry
from app.personas.schema import Role

logger = get_logger(__name__)


class ConversationManager:
    def __init__(
        self,
        store: ConversationStore | None = None,
        agent_runner=run_turn,
        registry: ManifestRegistry | None = None,
    ) -> None:
        self._store = store or MongoConversationStore()
        self._run_turn = agent_runner
        self._registry = registry or manifest_registry

    async def ensure_ready(self) -> None:
        await self._store.ensure_ready()

    async def create_conversation(
        self,
        owner: str,
        title: str | None = None,
        manifest_name: str = "default-parent",
        directory: str | None = None,
    ) -> Conversation:
        """Create a Papa (role=parent) conversation, snapshotting its manifest.

        `directory` is the agent's working directory (already validated by the
        caller). Raises ValueError if the manifest does not resolve to a
        role=parent persona (the project endpoint is parent-only).
        """
        manifest = self._registry.get(manifest_name)
        if manifest.role is not Role.PARENT:
            raise ValueError(f"manifest {manifest_name!r} is not a parent manifest")
        conv = Conversation(
            owner=owner,
            title=title,
            role=Role.PARENT,
            directory=directory,
            manifest_name=manifest_name,
            persona=manifest.model_copy(deep=True),
        )
        return await self._store.create_conversation(conv)

    async def create_child(
        self,
        parent_id: str,
        owner: str,
        manifest_name: str,
        title: str | None = None,
        task: str | None = None,
        directory: str | None = None,
    ) -> Conversation:
        """Create a role=child conversation under `parent_id`, snapshotting its
        manifest. `task` is the spawn context (null when added via the UI).

        `directory` is the child's working directory; when None the child
        inherits the Papa's directory. Raises ValueError if the parent is
        missing/foreign or the manifest is not a child manifest.
        """
        parent = await self.get_conversation(parent_id, owner)  # ownership + existence
        manifest = self._registry.get(manifest_name)
        if manifest.role is not Role.CHILD:
            raise ValueError(f"manifest {manifest_name!r} is not a child manifest")
        conv = Conversation(
            owner=owner,
            title=title,
            role=Role.CHILD,
            parent_id=parent_id,
            directory=directory if directory is not None else parent.directory,
            manifest_name=manifest_name,
            task=task,
            persona=manifest.model_copy(deep=True),
        )
        return await self._store.create_conversation(conv)

    async def get_children(self, parent_id: str, owner: str) -> list[Conversation]:
        await self.get_conversation(parent_id, owner)  # ownership + existence
        return await self._store.get_children(parent_id)

    async def delete_conversation(self, conversation_id: str, owner: str) -> None:
        """Delete a conversation (ownership-checked) with its turns and events.

        Deleting a Papa cascades to all of its children; deleting a child only
        removes that child."""
        conv = await self.get_conversation(conversation_id, owner)
        if conv.role is Role.PARENT:
            for child in await self._store.get_children(conversation_id):
                await self._store.delete_conversation(child.id)
        await self._store.delete_conversation(conversation_id)

    async def update_persona(
        self, conversation_id: str, owner: str, patch: dict
    ) -> Conversation:
        """Patch the conversation's bound persona snapshot. `name` and `role` are
        immutable on a snapshot and ignored. Takes effect from the next turn."""
        conv = await self.get_conversation(conversation_id, owner)
        fields = {k: v for k, v in patch.items() if k not in ("name", "role") and v is not None}
        persona = conv.persona.model_copy(update=fields)
        await self._store.update_conversation(
            conversation_id, persona=persona.model_dump(mode="json")
        )
        return await self.get_conversation(conversation_id, owner)

    async def list_conversations(
        self, owner: str, role: str | None = None
    ) -> list[Conversation]:
        return await self._store.list_conversations(owner, role)

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
                prompt,
                owner=owner,
                resume_session_id=conv.sdk_session_id,
                system_prompt=conv.persona.system_prompt or None,
                allowed_tools=conv.persona.allowed_tools,
                role=conv.role.value,
                conversation_id=conv.id,
                working_directory=conv.directory,
                permissions=conv.persona.permissions,
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
            input_tokens=payload.get("input_tokens"),
            output_tokens=payload.get("output_tokens"),
            context_used=payload.get("context_used"),
            context_window=payload.get("context_window"),
            model=payload.get("model"),
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

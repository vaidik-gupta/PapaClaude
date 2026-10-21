"""Domain model for multi-turn conversations.

Three nested entities form the app's own record of a conversation, kept
independently of the SDK session that holds the model's working memory:

    Conversation  one thread with the agent; holds a pointer (sdk_session_id)
                  to the SDK session we resume each turn.
      └─ Turn     one prompt submission -> stream until the ResultMessage.
           └─ Event   one item streamed during a turn (assistant text, a tool
                      call, the final result, ...), captured off the live stream.

The SDK owns the session *context*; we own this log. See ConversationStore for
how it is persisted (Mongo now, other backends later).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from app.personas.schema import PersonaSnapshot, Role


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return uuid4().hex


class ConversationStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class TurnStatus(str, Enum):
    STREAMING = "streaming"  # accepted, agent running / events arriving
    COMPLETE = "complete"    # ResultMessage received, result recorded
    ERROR = "error"          # agent failed mid-turn


class EventType(str, Enum):
    """Our stable event vocabulary, mapped from SDK message/block types so the
    API is insulated from SDK churn."""

    ASSISTANT_TEXT = "assistant_text"
    THINKING = "thinking"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    SYSTEM = "system"
    RESULT = "result"
    ERROR = "error"


def _default_persona() -> PersonaSnapshot:
    """A placeholder snapshot for direct construction; the manager overwrites it
    with the real manifest snapshot on create."""
    return PersonaSnapshot(name="default-parent", role=Role.PARENT)


class Conversation(BaseModel):
    id: str = Field(default_factory=_uuid)
    owner: str
    title: str | None = None
    # Pointer to the SDK session; None until the first turn's ResultMessage.
    sdk_session_id: str | None = None
    status: ConversationStatus = ConversationStatus.ACTIVE
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    # Persona / project fields.
    role: Role = Role.PARENT
    parent_id: str | None = None  # set on children -> their Papa
    manifest_name: str = "default-parent"  # source manifest
    task: str | None = None  # context string from spawn_child; null via UI button
    persona: PersonaSnapshot = Field(default_factory=_default_persona)


class TurnResult(BaseModel):
    """The closing summary of a turn, assembled from the SDK's end-of-turn events."""

    text: str = ""
    stop_reason: str | None = None
    num_turns: int | None = None
    total_cost_req: float | None = None  # Copilot premium-request count, not dollars


class Turn(BaseModel):
    id: str = Field(default_factory=_uuid)
    conversation_id: str
    index: int  # 0-based position within the conversation
    prompt: str
    status: TurnStatus = TurnStatus.STREAMING
    result: TurnResult | None = None
    created_at: datetime = Field(default_factory=_now)
    completed_at: datetime | None = None


class Event(BaseModel):
    id: str = Field(default_factory=_uuid)
    conversation_id: str
    turn_id: str
    index: int  # 0-based position within the turn
    type: EventType
    payload: dict = Field(default_factory=dict)
    ts: datetime = Field(default_factory=_now)

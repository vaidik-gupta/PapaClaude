"""Conversation endpoints — create/list/read conversations and stream a turn.

A turn is delivered as Server-Sent Events: each domain Event is emitted as an
SSE frame (`event: <type>` + JSON `data`) the moment it is produced, while the
ConversationManager persists it in the same pass. Ownership is checked before
the stream opens so a missing/foreign conversation 404s cleanly.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth.dependencies import require_user
from app.auth.service import User
from app.conversations.manager import conversation_manager
from app.conversations.schema import Conversation, Event, Turn
from app.logging_config import get_logger

router = APIRouter(prefix="/conversations", tags=["conversations"])
logger = get_logger(__name__)


class CreateConversationBody(BaseModel):
    title: str | None = None


class TurnBody(BaseModel):
    prompt: str


class TurnDetail(BaseModel):
    turn: Turn
    events: list[Event]


class ConversationDetail(BaseModel):
    conversation: Conversation
    turns: list[TurnDetail]


@router.post("", response_model=Conversation)
async def create_conversation(
    body: CreateConversationBody, user: Annotated[User, Depends(require_user)]
) -> Conversation:
    return await conversation_manager.create_conversation(user.username, body.title)


@router.get("", response_model=list[Conversation])
async def list_conversations(
    user: Annotated[User, Depends(require_user)]
) -> list[Conversation]:
    return await conversation_manager.list_conversations(user.username)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str, user: Annotated[User, Depends(require_user)]
) -> ConversationDetail:
    try:
        conv = await conversation_manager.get_conversation(conversation_id, user.username)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    turns = await conversation_manager.get_turns(conversation_id)
    details = [
        TurnDetail(turn=t, events=await conversation_manager.get_events(t.id)) for t in turns
    ]
    return ConversationDetail(conversation=conv, turns=details)


def _sse(event: Event) -> str:
    return f"event: {event.type.value}\ndata: {event.model_dump_json()}\n\n"


@router.post("/{conversation_id}/turns")
async def create_turn(
    conversation_id: str,
    body: TurnBody,
    user: Annotated[User, Depends(require_user)],
) -> StreamingResponse:
    """Run a turn and stream its events as SSE (persisted as they stream)."""
    # Validate ownership before opening the stream so we can still return a 404.
    try:
        await conversation_manager.get_conversation(conversation_id, user.username)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def stream():
        async for event in conversation_manager.run_turn(
            conversation_id, body.prompt, user.username
        ):
            yield _sse(event)

    return StreamingResponse(stream(), media_type="text/event-stream")

"""Persistence for the conversation domain model.

ConversationStore is the backend-agnostic contract; MongoConversationStore is
the one concrete implementation for now. A DynamoConversationStore (or any
other) can be added later without touching the manager that depends on the ABC.

Turns and events live in their own collections (not embedded in the
conversation) so long event logs never hit Mongo's 16MB document cap and can be
paginated.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.conversations.schema import Conversation, Event, Turn
from app.db.mongodb.mongodb import MongoDB, mongodb
from app.logging_config import get_logger

logger = get_logger(__name__)


class ConversationStore(ABC):
    async def ensure_ready(self) -> None:
        """Backend lifecycle hook (indexes, table creation, ...). No-op by default."""

    @abstractmethod
    async def create_conversation(self, conversation: Conversation) -> Conversation: ...

    @abstractmethod
    async def get_conversation(self, conversation_id: str) -> Conversation | None: ...

    @abstractmethod
    async def list_conversations(
        self, owner: str, role: str | None = None
    ) -> list[Conversation]:
        """Conversations for an owner, optionally filtered by role."""

    @abstractmethod
    async def get_children(self, parent_id: str) -> list[Conversation]:
        """Child conversations of a parent, ordered by creation time."""

    @abstractmethod
    async def update_conversation(self, conversation_id: str, **fields) -> None:
        """Patch top-level conversation fields (e.g. sdk_session_id, status)."""

    @abstractmethod
    async def next_turn_index(self, conversation_id: str) -> int:
        """0-based index the next turn should take within the conversation."""

    @abstractmethod
    async def append_turn(self, turn: Turn) -> Turn: ...

    @abstractmethod
    async def update_turn(self, turn_id: str, **fields) -> None:
        """Patch turn fields (e.g. status, result, completed_at)."""

    @abstractmethod
    async def get_turns(self, conversation_id: str) -> list[Turn]:
        """Turns for a conversation, ordered by index."""

    @abstractmethod
    async def append_event(self, event: Event) -> Event: ...

    @abstractmethod
    async def get_events(self, turn_id: str) -> list[Event]:
        """Events for a turn, ordered by index."""


class MongoConversationStore(ConversationStore):
    CONVERSATIONS = "conversations"
    TURNS = "turns"
    EVENTS = "events"

    def __init__(self, db: MongoDB | None = None) -> None:
        self._mongo = db or mongodb

    @property
    def _db(self):
        if self._mongo.db is None:
            raise RuntimeError("MongoDB is not connected")
        return self._mongo.db

    async def ensure_ready(self) -> None:
        """Create the lookup indexes the queries below rely on. Idempotent."""
        await self._db[self.CONVERSATIONS].create_index("id", unique=True)
        await self._db[self.CONVERSATIONS].create_index("owner")
        await self._db[self.CONVERSATIONS].create_index("parent_id")
        await self._db[self.TURNS].create_index("id", unique=True)
        await self._db[self.TURNS].create_index([("conversation_id", 1), ("index", 1)])
        await self._db[self.EVENTS].create_index("id", unique=True)
        await self._db[self.EVENTS].create_index([("turn_id", 1), ("index", 1)])

    # Store domain models as JSON-safe dicts (ISO datetimes, enum values) so the
    # same shape ports cleanly to other backends. Mongo's own _id is ignored.
    @staticmethod
    def _dump(model) -> dict:
        return model.model_dump(mode="json")

    @staticmethod
    def _strip(doc: dict | None) -> dict | None:
        if doc is not None:
            doc.pop("_id", None)
        return doc

    async def create_conversation(self, conversation: Conversation) -> Conversation:
        await self._db[self.CONVERSATIONS].insert_one(self._dump(conversation))
        logger.info("Created conversation %s for %s", conversation.id, conversation.owner)
        return conversation

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        doc = self._strip(await self._db[self.CONVERSATIONS].find_one({"id": conversation_id}))
        return Conversation(**doc) if doc else None

    async def list_conversations(
        self, owner: str, role: str | None = None
    ) -> list[Conversation]:
        query: dict = {"owner": owner}
        if role is not None:
            query["role"] = role
        cursor = self._db[self.CONVERSATIONS].find(query).sort("created_at", 1)
        return [Conversation(**self._strip(d)) async for d in cursor]

    async def get_children(self, parent_id: str) -> list[Conversation]:
        cursor = self._db[self.CONVERSATIONS].find({"parent_id": parent_id}).sort("created_at", 1)
        return [Conversation(**self._strip(d)) async for d in cursor]

    async def update_conversation(self, conversation_id: str, **fields) -> None:
        await self._db[self.CONVERSATIONS].update_one(
            {"id": conversation_id}, {"$set": fields}
        )

    async def next_turn_index(self, conversation_id: str) -> int:
        return await self._db[self.TURNS].count_documents(
            {"conversation_id": conversation_id}
        )

    async def append_turn(self, turn: Turn) -> Turn:
        await self._db[self.TURNS].insert_one(self._dump(turn))
        return turn

    async def update_turn(self, turn_id: str, **fields) -> None:
        await self._db[self.TURNS].update_one({"id": turn_id}, {"$set": fields})

    async def get_turns(self, conversation_id: str) -> list[Turn]:
        cursor = self._db[self.TURNS].find({"conversation_id": conversation_id}).sort("index", 1)
        return [Turn(**self._strip(d)) async for d in cursor]

    async def append_event(self, event: Event) -> Event:
        await self._db[self.EVENTS].insert_one(self._dump(event))
        return event

    async def get_events(self, turn_id: str) -> list[Event]:
        cursor = self._db[self.EVENTS].find({"turn_id": turn_id}).sort("index", 1)
        return [Event(**self._strip(d)) async for d in cursor]

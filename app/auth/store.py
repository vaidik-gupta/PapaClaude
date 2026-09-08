"""Durable persistence for registered users' key hashes.

Mirrors app.content.store: a small ABC with an in-memory impl (default,
non-durable, for tests) and a Mongo impl (one document per user). Only a key
hash is ever stored here — never a plaintext key (see hashing.py). The seeded
admin account is config-driven and not stored (see service.py).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import cached_property


class UserStore(ABC):
    @abstractmethod
    def get_hash(self, username: str) -> str | None:
        """Return the stored key hash for a user, or None if unknown."""

    @abstractmethod
    def add(self, username: str, key_hash: str) -> None:
        """Persist a new user's key hash. Raise ValueError if it already exists."""


class InMemoryUserStore(UserStore):
    """Non-durable backend (default). Holds hashes in a dict."""

    def __init__(self) -> None:
        self._users: dict[str, str] = {}

    def get_hash(self, username: str) -> str | None:
        return self._users.get(username)

    def add(self, username: str, key_hash: str) -> None:
        if username in self._users:
            raise ValueError(f"User '{username}' already exists")
        self._users[username] = key_hash


class MongoUserStore(UserStore):
    """Durable backend: one document per user in the `users` collection.

    ``_id`` is the username, so Mongo enforces uniqueness atomically."""

    COLLECTION = "users"

    @cached_property
    def _collection(self):
        from pymongo import MongoClient

        from app.config import settings

        return MongoClient(settings.mongodb_uri)[settings.mongodb_db][self.COLLECTION]

    def get_hash(self, username: str) -> str | None:
        doc = self._collection.find_one({"_id": username})
        return doc["key_hash"] if doc else None

    def add(self, username: str, key_hash: str) -> None:
        from pymongo.errors import DuplicateKeyError

        try:
            self._collection.insert_one({"_id": username, "key_hash": key_hash})
        except DuplicateKeyError as exc:
            raise ValueError(f"User '{username}' already exists") from exc

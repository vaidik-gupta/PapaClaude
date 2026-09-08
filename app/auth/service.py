"""Auth service protecting the API.

Placeholder for a real auth-management service, now backed by a durable
UserStore so registered users survive a restart. The admin account stays
config-driven (USER_NAME / USER_KEY) and is authenticated directly against
settings — it is never stored. Additional users the admin registers at runtime
are persisted as scrypt hashes (see hashing.py); their keys are never stored in
plaintext. Swap MongoUserStore for another backend without touching routes.
"""

import secrets
from dataclasses import dataclass

from app.auth.hashing import hash_key, verify_key
from app.auth.store import MongoUserStore, UserStore
from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class User:
    username: str
    is_admin: bool


class AuthService:
    def __init__(self, admin_name: str, admin_key: str, store: UserStore) -> None:
        self._admin_name = admin_name
        self._admin_key = admin_key
        self._store = store

    def authenticate(self, username: str, key: str) -> User | None:
        if not key:
            return None
        if username == self._admin_name:
            # Admin is config-driven; compare the settings key in constant time.
            if secrets.compare_digest(key, self._admin_key):
                return User(username=username, is_admin=True)
            return None
        stored = self._store.get_hash(username)
        if stored and verify_key(key, stored):
            return User(username=username, is_admin=False)
        return None

    def add_user(self, username: str, key: str) -> User:
        if username == self._admin_name:
            raise ValueError(f"User '{username}' already exists")
        self._store.add(username, hash_key(key))  # raises ValueError if it exists
        logger.info("Registered new user: %s", username)
        return User(username=username, is_admin=False)


auth_service = AuthService(settings.user_name, settings.user_key, MongoUserStore())

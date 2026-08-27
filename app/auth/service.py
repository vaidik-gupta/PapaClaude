"""Auth service protecting the API.

In-memory placeholder for a real auth-management service. It seeds a single
admin account from settings (USER_NAME / USER_KEY) and lets the admin register
additional users at runtime. Swap InMemoryAuthService for an external-backed
implementation later without changing the route dependencies that use it.
"""

import secrets
from dataclasses import dataclass

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class User:
    username: str
    is_admin: bool


class InMemoryAuthService:
    def __init__(self, admin_name: str, admin_key: str) -> None:
        self._admin_name = admin_name
        self._users: dict[str, str] = {admin_name: admin_key}  # username -> key

    def authenticate(self, username: str, key: str) -> User | None:
        expected = self._users.get(username)
        if not expected or not key or not secrets.compare_digest(key, expected):
            return None
        return User(username=username, is_admin=username == self._admin_name)

    def add_user(self, username: str, key: str) -> User:
        if username in self._users:
            raise ValueError(f"User '{username}' already exists")
        self._users[username] = key
        logger.info("Registered new user: %s", username)
        return User(username=username, is_admin=False)


auth_service = InMemoryAuthService(settings.user_name, settings.user_key)

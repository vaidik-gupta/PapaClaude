"""FastAPI auth dependencies.

Clients authenticate by sending two headers:
    X-User-Name: <username>
    X-User-Key:  <key>
"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.auth.service import User, auth_service


def require_user(
    x_user_name: Annotated[str | None, Header()] = None,
    x_user_key: Annotated[str | None, Header()] = None,
) -> User:
    if not x_user_name or not x_user_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-User-Name / X-User-Key headers",
        )
    user = auth_service.authenticate(x_user_name, x_user_key)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    return user


def require_admin(user: Annotated[User, Depends(require_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user

"""HTTP routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.agent.client import run_agent
from app.auth.dependencies import require_admin, require_user
from app.auth.service import User, auth_service
from app.logging_config import get_logger

router = APIRouter()
logger = get_logger(__name__)


class AgentRequest(BaseModel):
    prompt: str
    system_prompt: str | None = None


class AgentResponse(BaseModel):
    response: str


class AddUserRequest(BaseModel):
    username: str
    key: str


class UserResponse(BaseModel):
    username: str
    is_admin: bool


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.post("/agent", response_model=AgentResponse)
async def agent_endpoint(
    req: AgentRequest,
    user: Annotated[User, Depends(require_user)],
) -> AgentResponse:
    logger.debug("Agent request received from %s", user.username)
    try:
        text = await run_agent(req.prompt, req.system_prompt)
    except Exception as exc:  # noqa: BLE001 — surface any agent failure as a 500
        logger.exception("Agent query failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return AgentResponse(response=text)


@router.post("/users", response_model=UserResponse)
async def add_user(
    req: AddUserRequest,
    admin: Annotated[User, Depends(require_admin)],
) -> UserResponse:
    try:
        created = auth_service.add_user(req.username, req.key)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return UserResponse(username=created.username, is_admin=created.is_admin)

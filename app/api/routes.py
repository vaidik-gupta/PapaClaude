"""HTTP routes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agent.client import run_agent
from app.logging_config import get_logger

router = APIRouter()
logger = get_logger(__name__)


class AgentRequest(BaseModel):
    prompt: str
    system_prompt: str | None = None


class AgentResponse(BaseModel):
    response: str


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.post("/agent", response_model=AgentResponse)
async def agent_endpoint(req: AgentRequest) -> AgentResponse:
    logger.debug("Agent request received")
    try:
        text = await run_agent(req.prompt, req.system_prompt)
    except Exception as exc:  # noqa: BLE001 — surface any agent failure as a 500
        logger.exception("Agent query failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return AgentResponse(response=text)

"""Thin wrapper around the Claude Agent SDK.

Requires the Claude Code CLI on the host:
    npm install -g @anthropic-ai/claude-code
and an ANTHROPIC_API_KEY.
"""

import os

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    TextBlock,
    query,
)

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)

# The SDK reads ANTHROPIC_API_KEY from the environment; bridge it from settings.
if settings.anthropic_api_key:
    os.environ.setdefault("ANTHROPIC_API_KEY", settings.anthropic_api_key)

DEFAULT_SYSTEM_PROMPT = "You are MyMaid, a helpful assistant."


async def run_agent(prompt: str, system_prompt: str | None = None) -> str:
    """Run a single-turn agent query and return the concatenated text response."""
    options = ClaudeAgentOptions(system_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT)
    logger.debug("Running agent query")

    chunks: list[str] = []
    async for message in query(prompt=prompt, options=options):
        logger.deep_debug("Agent message: %r", message)  # type: ignore[attr-defined]
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    chunks.append(block.text)

    return "".join(chunks)

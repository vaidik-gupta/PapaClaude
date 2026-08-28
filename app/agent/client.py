"""Thin wrapper around the Claude Agent SDK.

Requires the Claude Code CLI on the host:
    npm install -g @anthropic-ai/claude-code

Two auth modes are supported:
  * API key   — set ANTHROPIC_API_KEY (Console pay-as-you-go).
  * OAuth     — leave ANTHROPIC_API_KEY unset and run `claude setup-token`
                once; the SDK then uses your Claude subscription. A set
                ANTHROPIC_API_KEY silently wins over OAuth, so for OAuth mode
                the key must be absent (empty in the env file).
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

# Bridge a real API key from settings into the env the SDK reads. A blank or
# placeholder value is ignored so it can't clobber OAuth (`claude setup-token`).
_key = settings.anthropic_api_key.strip()
if _key and "your-key-here" not in _key:
    os.environ.setdefault("ANTHROPIC_API_KEY", _key)
    logger.info("Claude Agent SDK auth: API key")
else:
    logger.info("Claude Agent SDK auth: OAuth (subscription) via Claude Code CLI")

DEFAULT_SYSTEM_PROMPT = "You are PapaClaude, a helpful assistant."


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

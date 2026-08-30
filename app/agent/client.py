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
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

from app.agent.tools import SERVER_NAME, allowed_tool_names, build_content_server
from app.config import settings
from app.conversations.schema import EventType
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


@dataclass
class AgentEvent:
    """One translated item from the SDK stream. The manager wraps this into a
    persisted domain Event (adding turn/conversation ids and an index)."""

    type: EventType
    payload: dict


def _translate(message: object) -> Iterator[AgentEvent]:
    """Map a single SDK message into zero or more domain-vocabulary events.

    Pure and side-effect free so it can be unit-tested with constructed SDK
    messages, no live query required. This is the one place the SDK's shape is
    translated into our stable EventType vocabulary.
    """
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock):
                yield AgentEvent(EventType.ASSISTANT_TEXT, {"text": block.text})
            elif isinstance(block, ThinkingBlock):
                yield AgentEvent(EventType.THINKING, {"thinking": block.thinking})
            elif isinstance(block, ToolUseBlock):
                yield AgentEvent(
                    EventType.TOOL_USE,
                    {"id": block.id, "name": block.name, "input": block.input},
                )
    elif isinstance(message, UserMessage):
        # Tool results are delivered back as user messages; the echoed prompt
        # text is already stored on the Turn, so only tool results are logged.
        content = message.content if isinstance(message.content, list) else []
        for block in content:
            if isinstance(block, ToolResultBlock):
                yield AgentEvent(
                    EventType.TOOL_RESULT,
                    {
                        "tool_use_id": block.tool_use_id,
                        "content": block.content,
                        "is_error": block.is_error,
                    },
                )
    elif isinstance(message, SystemMessage):
        yield AgentEvent(EventType.SYSTEM, {"subtype": message.subtype, "data": message.data})
    elif isinstance(message, ResultMessage):
        # Carries everything the manager needs to finalize the turn and, on the
        # first turn, save the session pointer onto the conversation.
        yield AgentEvent(
            EventType.RESULT,
            {
                "session_id": message.session_id,
                "stop_reason": message.stop_reason,
                "num_turns": message.num_turns,
                "total_cost_usd": message.total_cost_usd,
                "is_error": message.is_error,
                "text": message.result or "",
            },
        )


async def run_turn(
    prompt: str,
    *,
    owner: str,
    resume_session_id: str | None = None,
    system_prompt: str | None = None,
) -> AsyncIterator[AgentEvent]:
    """Run one turn, resuming the given SDK session, and stream translated events.

    The agent is sandboxed to a per-user content tool server: no built-in tools
    (`tools=[]`), only our user-bound MCP tools, pre-approved and run without
    prompting (`dontAsk`), and no ambient MCP config (`strict_mcp_config`).

    Exceptions from the SDK propagate to the caller (the manager records the
    turn as errored); this stays a pure translator of the happy path.
    """
    options = ClaudeAgentOptions(
        system_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT,
        resume=resume_session_id,
        tools=[],  # no built-in tools (no Bash/Read/... on the host)
        mcp_servers={SERVER_NAME: build_content_server(owner)},
        allowed_tools=allowed_tool_names(),
        permission_mode="dontAsk",
        strict_mcp_config=True,
    )
    logger.debug("Running turn for %s (resume=%s)", owner, resume_session_id)

    async for message in query(prompt=prompt, options=options):
        logger.deep_debug("Agent message: %r", message)  # type: ignore[attr-defined]
        for event in _translate(message):
            yield event

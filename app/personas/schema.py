"""Persona manifest model — the shape stored as YAML on disk and snapshotted
onto a conversation.

A Manifest is a persona template in the library (`.manifests/*.yaml`). On
conversation creation the manifest is copied verbatim onto the conversation as
its bound PersonaSnapshot, so editing the file later never mutates existing
conversations. Snapshot and manifest share the same shape, so `PersonaSnapshot`
is just an alias of `Manifest`.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Role(str, Enum):
    PARENT = "parent"
    CHILD = "child"


class Manifest(BaseModel):
    name: str  # unique; == filename stem
    role: Role = Role.PARENT
    description: str = ""
    system_prompt: str = ""
    model: str | None = None  # None => settings.copilot_model
    allowed_tools: list[str] = Field(default_factory=list)
    max_turns: int | None = None
    permission_mode: str = "auto"  # informational for now
    # Per-tool permission config: { tool_name: "auto" | "ask" | "deny" }.
    permissions: dict[str, str] = Field(default_factory=dict)


# The snapshot bound onto a conversation is structurally identical to the
# manifest it was copied from.
PersonaSnapshot = Manifest

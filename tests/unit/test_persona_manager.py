"""Unit tests for the persona/project additions to ConversationManager and the
spawn_child tool.

Reuses the in-memory FakeStore/FakeRegistry from test_conversation_manager, so
snapshot-on-create, create_child, update_persona, and the spawn_child tool are
covered without a DB, live agent, or on-disk manifests.
"""

import json

import pytest
from copilot import ToolInvocation

from app.agent.tools import build_spawn_child_tool
from app.conversations.manager import ConversationManager
from app.personas.schema import Role
from tests.unit.test_conversation_manager import FakeRegistry, FakeStore, _fake_runner


def _mgr() -> ConversationManager:
    runner, _ = _fake_runner([])
    return ConversationManager(store=FakeStore(), agent_runner=runner, registry=FakeRegistry())


async def test_create_conversation_snapshots_manifest():
    mgr = _mgr()
    conv = await mgr.create_conversation(owner="u", manifest_name="default-parent")
    assert conv.role is Role.PARENT
    assert conv.manifest_name == "default-parent"
    assert conv.persona.name == "default-parent"
    assert conv.persona.role is Role.PARENT


async def test_create_conversation_rejects_child_manifest():
    mgr = _mgr()
    with pytest.raises(ValueError, match="not a parent manifest"):
        await mgr.create_conversation(owner="u", manifest_name="default-child")


async def test_create_child_without_task():
    mgr = _mgr()
    papa = await mgr.create_conversation(owner="u")
    child = await mgr.create_child(papa.id, owner="u", manifest_name="default-child")
    assert child.role is Role.CHILD
    assert child.parent_id == papa.id
    assert child.task is None
    assert child.persona.name == "default-child"


async def test_create_child_with_task():
    mgr = _mgr()
    papa = await mgr.create_conversation(owner="u")
    child = await mgr.create_child(
        papa.id, owner="u", manifest_name="default-child", task="do the thing"
    )
    assert child.task == "do the thing"
    kids = await mgr.get_children(papa.id, owner="u")
    assert [c.id for c in kids] == [child.id]


async def test_create_child_inherits_directory_when_none():
    mgr = _mgr()
    papa = await mgr.create_conversation(owner="u", directory="/papa/dir")
    child = await mgr.create_child(papa.id, owner="u", manifest_name="default-child")
    assert child.directory == "/papa/dir"


async def test_create_child_overrides_directory():
    mgr = _mgr()
    papa = await mgr.create_conversation(owner="u", directory="/papa/dir")
    child = await mgr.create_child(
        papa.id, owner="u", manifest_name="default-child", directory="/child/dir"
    )
    assert child.directory == "/child/dir"


async def test_run_turn_passes_working_directory():
    captured: dict = {}

    async def runner(prompt, *, owner=None, resume_session_id=None, working_directory=None, **kw):
        captured["working_directory"] = working_directory
        return
        yield  # make this an async generator

    mgr = ConversationManager(store=FakeStore(), agent_runner=runner, registry=FakeRegistry())
    conv = await mgr.create_conversation(owner="u", directory="/work/here")
    _ = [e async for e in mgr.run_turn(conv.id, "ping", owner="u")]
    assert captured["working_directory"] == "/work/here"


async def test_run_turn_passes_permissions():
    captured: dict = {}

    async def runner(prompt, *, owner=None, permissions=None, **kw):
        captured["permissions"] = permissions
        return
        yield  # make this an async generator

    mgr = ConversationManager(store=FakeStore(), agent_runner=runner, registry=FakeRegistry())
    conv = await mgr.create_conversation(owner="u", directory="/work/here")
    # The snapshot carries whatever the manifest declared (default: empty dict).
    _ = [e async for e in mgr.run_turn(conv.id, "ping", owner="u")]
    assert captured["permissions"] == conv.persona.permissions


async def test_create_child_rejects_parent_manifest():
    mgr = _mgr()
    papa = await mgr.create_conversation(owner="u")
    with pytest.raises(ValueError, match="not a child manifest"):
        await mgr.create_child(papa.id, owner="u", manifest_name="default-parent")


async def test_create_child_foreign_parent():
    mgr = _mgr()
    papa = await mgr.create_conversation(owner="owner")
    with pytest.raises(ValueError, match="not found"):
        await mgr.create_child(papa.id, owner="intruder", manifest_name="default-child")


async def test_update_persona_patches_snapshot_ignoring_name_and_role():
    mgr = _mgr()
    conv = await mgr.create_conversation(owner="u")
    updated = await mgr.update_persona(
        conv.id,
        owner="u",
        patch={
            "system_prompt": "new prompt",
            "allowed_tools": ["add"],
            "name": "hacked",
            "role": "child",
        },
    )
    assert updated.persona.system_prompt == "new prompt"
    assert updated.persona.allowed_tools == ["add"]
    # name/role immutable on a snapshot.
    assert updated.persona.name == "default-parent"
    assert updated.persona.role is Role.PARENT
    assert updated.role is Role.PARENT


async def test_spawn_child_tool_creates_child_and_returns_ids(monkeypatch):
    mgr = _mgr()
    papa = await mgr.create_conversation(owner="u")

    # The tool imports the module-level conversation_manager lazily; point it at
    # our in-memory manager.
    import app.conversations.manager as mgr_mod

    monkeypatch.setattr(mgr_mod, "conversation_manager", mgr)

    tool = build_spawn_child_tool(owner="u", parent_id=papa.id)
    result = await tool.handler(
        ToolInvocation(
            arguments={
                "manifest_name": "default-child",
                "context": "summarize the tree",
                "title": "Summarizer",
            }
        )
    )
    payload = json.loads(result.text_result_for_llm)
    assert payload["manifest_name"] == "default-child"
    assert payload["title"] == "Summarizer"

    kids = await mgr.get_children(papa.id, owner="u")
    assert len(kids) == 1
    assert kids[0].id == payload["child_id"]
    assert kids[0].task == "summarize the tree"


async def test_spawn_child_tool_directory_inherit_override_and_invalid(monkeypatch, tmp_path):
    mgr = _mgr()
    papa = await mgr.create_conversation(owner="u", directory=str(tmp_path))

    import app.conversations.manager as mgr_mod

    monkeypatch.setattr(mgr_mod, "conversation_manager", mgr)
    tool = build_spawn_child_tool(owner="u", parent_id=papa.id)

    # Omitted directory -> inherits the Papa's.
    inherited = await tool.handler(
        ToolInvocation(arguments={"manifest_name": "default-child", "context": "c"})
    )
    assert json.loads(inherited.text_result_for_llm)["directory"] == str(tmp_path)

    # Explicit existing directory -> resolved absolute.
    sub = tmp_path / "sub"
    sub.mkdir()
    overridden = await tool.handler(
        ToolInvocation(
            arguments={"manifest_name": "default-child", "context": "c", "directory": str(sub)}
        )
    )
    assert json.loads(overridden.text_result_for_llm)["directory"] == str(sub.resolve())

    # Non-existent directory -> failure ToolResult, no child created.
    bad = await tool.handler(
        ToolInvocation(
            arguments={
                "manifest_name": "default-child",
                "context": "c",
                "directory": "/no/such/dir/here",
            }
        )
    )
    assert bad.result_type == "failure"


async def test_list_conversations_defaults_to_role_filter():
    mgr = _mgr()
    papa = await mgr.create_conversation(owner="u")
    await mgr.create_child(papa.id, owner="u", manifest_name="default-child")
    parents = await mgr.list_conversations("u", role="parent")
    assert [c.id for c in parents] == [papa.id]
    children = await mgr.list_conversations("u", role="child")
    assert [c.role for c in children] == [Role.CHILD]

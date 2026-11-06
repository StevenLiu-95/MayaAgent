"""Unit tests for context compression + loop guards (no Maya required)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_compress_old_tools_keeps_recent_and_user():
    from maya_agent.core.context_compress import compress_messages_for_llm
    from maya_agent.llm.base import ChatMessage, ImageAttachment

    long_ok = "X" * 3000
    msgs = [
        ChatMessage(role="system", content="SYS"),
        ChatMessage(role="user", content="u1"),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "get_scene_info", "arguments": "{}"},
                }
            ],
        ),
        ChatMessage(
            role="tool",
            content=long_ok,
            name="get_scene_info",
            tool_call_id="c1",
        ),
        ChatMessage(role="assistant", content="done1"),
        ChatMessage(
            role="user",
            content="u2",
            images=[ImageAttachment(mime="image/png", data_b64="abc", name="a")],
        ),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "c2",
                    "type": "function",
                    "function": {"name": "list_selection", "arguments": "{}"},
                }
            ],
        ),
        ChatMessage(
            role="tool",
            content="Y" * 3000,
            name="list_selection",
            tool_call_id="c2",
        ),
        ChatMessage(
            role="user",
            content="u3",
            images=[ImageAttachment(mime="image/png", data_b64="def", name="b")],
        ),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "c3",
                    "type": "function",
                    "function": {"name": "get_mesh_stats", "arguments": "{}"},
                }
            ],
        ),
        ChatMessage(
            role="tool",
            content="Z" * 3000,
            name="get_mesh_stats",
            tool_call_id="c3",
        ),
    ]
    # Groups: u1 | asst+tool1 | done1 | u2 | asst+tool2 | u3 | asst+tool3
    # protect_recent_groups=2 → last 2 groups intact (asst+tool3 and ... wait)
    # Actually groups are: [u1], [asst+c1,tool], [done1], [u2], [asst+c2,tool], [u3], [asst+c3,tool]
    # n=7, protect=2 → compress groups 0..4, keep 5,6
    out = compress_messages_for_llm(
        msgs,
        enabled=True,
        protect_recent_groups=2,
        soft_limit=1200,
        head_chars=600,
        tail_chars=200,
        strip_old_images=True,
        keep_recent_image_users=1,
    )
    tools = [m for m in out if m.role == "tool"]
    assert len(tools) == 3
    assert "truncated for context" in (tools[0].content or "")
    assert len(tools[0].content) < 3000
    # last tool group protected
    assert tools[-1].content == "Z" * 3000
    # user/assistant text unchanged
    users = [m for m in out if m.role == "user"]
    assert users[0].content == "u1"
    # only most recent imaged user keeps images
    imaged = [m for m in users if m.images]
    assert len(imaged) == 1
    assert imaged[0].content == "u3"
    assert out[0].content == "SYS"


def test_memory_as_list_compresses_export_raw():
    from maya_agent.core.memory import ConversationMemory
    from maya_agent.llm.base import ChatMessage

    mem = ConversationMemory(limit=100)
    mem.add(ChatMessage(role="system", content="S"))
    long_body = "A" * 4000
    # Build 3 tool groups so oldest compresses with protect=2
    for i in range(3):
        mem.add(
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": f"id{i}",
                        "type": "function",
                        "function": {"name": "get_scene_info", "arguments": "{}"},
                    }
                ],
            )
        )
        mem.add(
            ChatMessage(
                role="tool",
                content=long_body,
                name="get_scene_info",
                tool_call_id=f"id{i}",
            )
        )
    llm_view = mem.as_list(for_llm=True)
    raw_view = mem.as_list(for_llm=False)
    ser = mem.to_serializable()
    tool_llm = [m for m in llm_view if m.role == "tool"]
    tool_raw = [m for m in raw_view if m.role == "tool"]
    assert any("truncated" in (m.content or "") for m in tool_llm)
    assert all(len(m.content or "") == 4000 for m in tool_raw)
    assert any(
        len(x.get("content") or "") == 4000
        for x in ser
        if x.get("role") == "tool"
    )


def test_loop_guard_dedup_and_fuse():
    from maya_agent.core.loop_guards import TurnLoopGuard, tool_signature
    from maya_agent.tools.registry import RegisteredTool, ToolResult, _REGISTRY

    def _h(**kw):
        return ToolResult(ok=True)

    # Ensure readonly classification via registry
    _REGISTRY["get_scene_info"] = RegisteredTool(
        name="get_scene_info",
        description="x",
        parameters={},
        handler=_h,
        category="scene",
        destructive=False,
    )

    g = TurnLoopGuard(enabled=True, consecutive_limit=3, dedup_readonly=True)
    args = "{}"
    sig = tool_signature("get_scene_info", args)
    assert "::" in sig

    d1 = g.evaluate("get_scene_info", args)
    assert not d1.skip_execute
    g.remember_success("get_scene_info", args, '{"ok":true,"message":"scene"}')

    d2 = g.evaluate("get_scene_info", args)
    assert d2.skip_execute and d2.deduplicated
    assert d2.result and d2.result.ok

    d3 = g.evaluate("get_scene_info", args)
    assert d3.skip_execute and d3.fused
    assert d3.result and not d3.result.ok
    assert "上限" in (d3.result.error or "")

    # Remaining calls also short-circuited
    d4 = g.evaluate("get_scene_info", args)
    assert d4.skip_execute and d4.break_remaining


def test_loop_guard_write_no_dedup_but_fuses():
    from maya_agent.core.loop_guards import TurnLoopGuard
    from maya_agent.tools.registry import RegisteredTool, ToolResult, _REGISTRY

    def _h(**kw):
        return ToolResult(ok=True)

    _REGISTRY["create_primitive"] = RegisteredTool(
        name="create_primitive",
        description="x",
        parameters={},
        handler=_h,
        category="modeling",
        destructive=False,
    )
    g = TurnLoopGuard(enabled=True, consecutive_limit=3, dedup_readonly=True)
    args = '{"shape":"cube"}'
    assert not g.evaluate("create_primitive", args).skip_execute
    g.remember_success("create_primitive", args, '{"ok":true}')
    # write tools are not deduped
    d2 = g.evaluate("create_primitive", args)
    assert not d2.skip_execute
    d3 = g.evaluate("create_primitive", args)
    assert d3.fused and d3.skip_execute


def test_disabled_flags():
    from maya_agent.core.context_compress import compress_messages_for_llm
    from maya_agent.core.loop_guards import TurnLoopGuard
    from maya_agent.llm.base import ChatMessage

    long_ok = "Q" * 5000
    msgs = [
        ChatMessage(role="system", content="S"),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "c",
                    "type": "function",
                    "function": {"name": "get_scene_info", "arguments": "{}"},
                }
            ],
        ),
        ChatMessage(role="tool", content=long_ok, name="get_scene_info", tool_call_id="c"),
    ]
    out = compress_messages_for_llm(msgs, enabled=False)
    assert out[2].content == long_ok

    g = TurnLoopGuard(enabled=False, consecutive_limit=2)
    g.remember_success("get_scene_info", "{}", "x")
    assert not g.evaluate("get_scene_info", "{}").skip_execute
    assert not g.evaluate("get_scene_info", "{}").skip_execute


def main():
    test_compress_old_tools_keeps_recent_and_user()
    test_memory_as_list_compresses_export_raw()
    test_loop_guard_dedup_and_fuse()
    test_loop_guard_write_no_dedup_but_fuses()
    test_disabled_flags()
    print("test_context_guards: OK")


if __name__ == "__main__":
    main()

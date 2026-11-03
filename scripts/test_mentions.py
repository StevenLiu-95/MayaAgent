"""Offline unit tests for composer @-mention parse / expand."""

from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maya_agent.i18n import set_language
from maya_agent.ui.mention import (
    KIND_OBJECT,
    KIND_SESSION,
    KIND_TOOL,
    expand_mentions,
    format_token,
    parse_mentions,
    search_mentions,
)

# Expand/ref strings follow the active UI language.
set_language("zh-CN")


def _ok(name: str) -> None:
    print(f"  OK  {name}")


def test_parse_basic() -> None:
    text = "请用 @工具:create_primitive 在 @对象:pCube1 上操作，参考 @会话:绑骨"
    toks = parse_mentions(text)
    assert len(toks) == 3, toks
    assert toks[0].kind == KIND_TOOL and toks[0].value == "create_primitive"
    assert toks[1].kind == KIND_OBJECT and toks[1].value == "pCube1"
    assert toks[2].kind == KIND_SESSION and toks[2].value == "绑骨"
    _ok("parse_basic")


def test_parse_aliases_and_long_name() -> None:
    text = "@tool:export_fbx and @object:|group1|pCube1 @session:abc123"
    toks = parse_mentions(text)
    assert [t.kind for t in toks] == [KIND_TOOL, KIND_OBJECT, KIND_SESSION]
    assert toks[1].value == "|group1|pCube1"
    _ok("parse_aliases_long_name")


def test_parse_ignores_email_like() -> None:
    # '@' mid-token should not count; plain email-ish without kind is ignored.
    text = "mail@example.com  hello"
    assert parse_mentions(text) == []
    _ok("parse_ignores_email_like")


def test_format_token() -> None:
    # Canonical kinds are English; Chinese aliases normalize the same way.
    assert format_token("工具", "create_primitive") == "@tool:create_primitive"
    assert format_token("tool", "x") == "@tool:x"
    assert format_token("对象", "pCube1") == "@object:pCube1"
    _ok("format_token")


def test_expand_tool() -> None:
    from maya_agent.tools.registry import ensure_tools_loaded, get_tool

    ensure_tools_loaded()
    assert get_tool("create_primitive") is not None
    block = expand_mentions("用 @工具:create_primitive 建一个箱子")
    assert block.startswith("[引用]")
    assert "create_primitive" in block
    assert "未找到" not in block
    _ok("expand_tool")


def test_expand_missing_tool() -> None:
    block = expand_mentions("@工具:definitely_not_a_real_tool_zz")
    assert "未找到" in block
    _ok("expand_missing_tool")


def test_expand_object_without_maya() -> None:
    block = expand_mentions("看看 @对象:pCube1")
    assert block.startswith("[引用]")
    assert "pCube1" in block
    # Outside Maya the node lookup returns 未找到 — must not raise.
    assert "未找到" in block
    _ok("expand_object_without_maya")


def test_expand_session() -> None:
    session = SimpleNamespace(
        id="deadbeef0001",
        title="角色绑骨",
        memory=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "请帮我绑一个 biped"},
        ],
    )
    mgr = SimpleNamespace(
        list_sessions=lambda: [session],
        active=lambda: session,
    )
    block = expand_mentions("参考 @会话:角色绑骨", session_manager=mgr)
    assert "角色绑骨" in block
    assert "deadbeef0001" in block
    assert "请帮我绑一个 biped" in block
    _ok("expand_session")


def test_expand_session_by_id_and_dup_title() -> None:
    a = SimpleNamespace(
        id="aaa",
        title="同名",
        memory=[{"role": "user", "content": "first"}],
    )
    b = SimpleNamespace(
        id="bbb",
        title="同名",
        memory=[{"role": "user", "content": "second"}],
    )
    mgr = SimpleNamespace(list_sessions=lambda: [a, b], active=lambda: a)
    block = expand_mentions("@会话:同名#bbb", session_manager=mgr)
    assert "second" in block
    assert "bbb" in block
    _ok("expand_session_dup_title")


def test_search_mentions_cross_category() -> None:
    # Bare "@" → categories only.
    bare = search_mentions("")
    assert bare and all(it.is_category for it in bare)
    assert {it.key for it in bare} >= {"tools", "scene", "selection", "sessions"}

    # "@adv" must hit adv_* tools, not only category labels (which don't match "adv").
    hits = search_mentions("adv")
    tool_names = [it.label for it in hits if it.category_id == "tools" and not it.is_category]
    assert tool_names, hits
    assert any(n.startswith("adv_") for n in tool_names), tool_names
    _ok("search_mentions_cross_category")


def test_expand_dedupe() -> None:
    block = expand_mentions(
        "@工具:create_primitive 再 @工具:create_primitive",
    )
    # One reference line for the tool (header [引用] excluded).
    tool_lines = [
        ln
        for ln in block.splitlines()
        if "create_primitive" in ln and ln.lstrip().startswith("-")
    ]
    assert len(tool_lines) == 1, block_lines
    _ok("expand_dedupe")


def main() -> None:
    print("Maya Agent mention tests")
    test_parse_basic()
    test_parse_aliases_and_long_name()
    test_parse_ignores_email_like()
    test_format_token()
    test_expand_tool()
    test_expand_missing_tool()
    test_expand_object_without_maya()
    test_expand_session()
    test_expand_session_by_id_and_dup_title()
    test_search_mentions_cross_category()
    test_expand_dedupe()
    print("ALL PASSED")


if __name__ == "__main__":
    main()

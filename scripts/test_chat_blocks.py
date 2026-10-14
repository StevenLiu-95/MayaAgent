"""Unit tests for chat block parts SSOT (no Qt required)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _derive_tools_from_parts(parts):
    return [
        {
            "name": p.get("name") or "tool",
            "status": p.get("status") or "done",
            **({"result": p["result"]} if p.get("result") is not None else {}),
            **({"images": p["images"]} if p.get("images") else {}),
        }
        for p in parts
        if p.get("kind") == "tool"
    ]


def test_parts_derive_summaries():
    parts = [
        {"kind": "thinking", "text": "plan"},
        {"kind": "tool", "name": "create_cube", "status": "done", "result": "{}"},
        {"kind": "text", "text": "Done."},
    ]
    text = "".join(p.get("text") or "" for p in parts if p.get("kind") == "text")
    think = "".join(p.get("text") or "" for p in parts if p.get("kind") == "thinking")
    tools = _derive_tools_from_parts(parts)
    assert text == "Done."
    assert think == "plan"
    assert len(tools) == 1
    assert tools[0]["name"] == "create_cube"
    assert tools[0]["status"] == "done"


def test_legacy_restore_order():
    """Legacy blocks without parts keep thinking → tools → text order."""
    block = {
        "type": "assistant",
        "thinking": "t",
        "tools": [{"name": "a", "status": "done", "result": "ok"}],
        "text": "hello",
    }
    assert not block.get("parts")
    timeline = []
    if block.get("thinking"):
        timeline.append(("thinking", block["thinking"]))
    for tool in block.get("tools") or []:
        timeline.append(("tool", tool.get("name")))
    if block.get("text"):
        timeline.append(("text", block["text"]))
    assert timeline == [("thinking", "t"), ("tool", "a"), ("text", "hello")]


def test_parts_preferred_over_legacy():
    block = {
        "type": "assistant",
        "thinking": "stale",
        "tools": [{"name": "old", "status": "done"}],
        "text": "stale",
        "parts": [
            {"kind": "text", "text": "fresh"},
            {"kind": "tool", "name": "new", "status": "done", "result": "1"},
        ],
    }
    parts = block.get("parts")
    assert parts
    kinds = [p["kind"] for p in parts]
    assert kinds == ["text", "tool"]


if __name__ == "__main__":
    test_parts_derive_summaries()
    test_legacy_restore_order()
    test_parts_preferred_over_legacy()
    print("test_chat_blocks: OK")

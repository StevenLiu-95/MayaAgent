"""Smoke test ChatPanel with PySide (skip if unavailable)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    try:
        import PySide6  # noqa: F401
    except ImportError:
        try:
            import PySide2  # noqa: F401
        except ImportError:
            print("SKIP: no PySide")
            return 0

    from maya_agent.ui.qt_bind import QT_BINDING
    from maya_agent.ui.chat import create_chat_panel

    print("binding", QT_BINDING)

    from maya_agent.ui.qt_bind import QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    p = create_chat_panel()
    p.begin_assistant()
    p.append_assistant_text("hello **world**")
    p.tool_start("create_cube")
    p.tool_end("create_cube", '{"ok": true}')
    p.finish_assistant()
    blocks = p.blocks
    assert blocks[-1]["type"] == "assistant"
    assert blocks[-1].get("parts")
    assert any(x.get("kind") == "tool" for x in blocks[-1]["parts"])
    assert "tools" in blocks[-1]

    p.restore_blocks(
        [
            {"type": "user", "text": "hi"},
            {
                "type": "assistant",
                "thinking": "t",
                "tools": [{"name": "x", "status": "done", "result": "{}"}],
                "text": "done",
            },
        ]
    )
    assert len(p.blocks) == 2
    print("ChatPanel smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

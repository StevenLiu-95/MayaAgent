#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sync resources/prompts/system_zh.md → .cursor/rules/maya-agent-system.mdc

Cursor does not inject MCP ``instructions`` into the agent context, so the
IDE-side default rules live in an alwaysApply Cursor rule. This script keeps
that rule body identical to the Maya panel prompt source file.
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "resources" / "prompts" / "system_zh.md"
DST = ROOT / ".cursor" / "rules" / "maya-agent-system.mdc"

HEADER = """\
---
description: MayaAgent system prompt (same as Maya panel) — follow when using MayaAgent MCP
alwaysApply: true
---

# MayaAgent 系统提示词（与面板共用）

> 正文同步自 `resources/prompts/system_zh.md`。修改该文件后运行：
> `python scripts/sync_cursor_maya_rules.py`
> （启动 MCP / 复制 MCP 配置时也会自动同步。）
>
> 需要含 Maya 运行时环境（版本、工具数、ADV 等）的完整版时，调用 MCP 工具
> `mayaagent_rules`，或查看 `mayaagent_status` 返回的 `rules` 字段。

"""


def sync(*, check: bool = False) -> int:
    if not SRC.is_file():
        print(f"ERROR: missing {SRC}")
        return 1
    body = SRC.read_text(encoding="utf-8").strip() + "\n"
    text = HEADER + body
    if check:
        if not DST.is_file():
            print(f"OUT_OF_SYNC: missing {DST}")
            return 2
        current = DST.read_text(encoding="utf-8")
        if current != text:
            print(f"OUT_OF_SYNC: {DST} differs from {SRC}")
            return 2
        print(f"OK  in sync: {DST}")
        return 0
    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_text(text, encoding="utf-8", newline="\n")
    print(f"OK  wrote {DST} ({len(body)} chars from {SRC.name})")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 2 if rule file is missing or out of sync (no write)",
    )
    args = parser.parse_args()
    raise SystemExit(sync(check=bool(args.check)))


if __name__ == "__main__":
    main()

"""Qt style helpers."""

from __future__ import annotations

from pathlib import Path

from maya_agent.utils.config import get_config


def load_stylesheet() -> str:
    path = Path(__file__).resolve().parent / "styles" / "dark.qss"
    if path.exists():
        text = path.read_text(encoding="utf-8")
    else:
        text = ""
    cfg = get_config()
    family = cfg.get("ui.font_family", "Microsoft YaHei UI")
    size = cfg.get("ui.font_size", 13)
    text = text.replace('"Microsoft YaHei UI"', f'"{family}"')
    text = text.replace("font-size: 13px;", f"font-size: {size}px;")
    return text

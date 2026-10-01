"""Qt style helpers."""

from __future__ import annotations

import re
from pathlib import Path

from maya_agent.utils.config import get_config

_BASE_FONT_PX = 13
_DEFAULT_SCALE_PCT = 100
_MIN_SCALE = 0.5
_MAX_SCALE = 2.0


def ui_scale_factor(cfg=None) -> float:
    """Return UI scale multiplier (1.0 = 100%). Migrates legacy ui.font_size."""
    if cfg is None:
        cfg = get_config()
    raw = cfg.get("ui.ui_scale")
    if raw is None:
        old = cfg.get("ui.font_size")
        if old is not None:
            try:
                raw = round(float(old) / _BASE_FONT_PX * 100)
            except (TypeError, ValueError):
                raw = _DEFAULT_SCALE_PCT
        else:
            raw = _DEFAULT_SCALE_PCT
    try:
        return max(_MIN_SCALE, min(_MAX_SCALE, float(raw) / 100.0))
    except (TypeError, ValueError):
        return 1.0


def load_stylesheet() -> str:
    path = Path(__file__).resolve().parent / "styles" / "dark.qss"
    if path.exists():
        text = path.read_text(encoding="utf-8")
    else:
        text = ""
    cfg = get_config()
    family = cfg.get("ui.font_family", "Microsoft YaHei UI")
    factor = ui_scale_factor(cfg)
    text = text.replace('"Microsoft YaHei UI"', f'"{family}"')

    def _scale_px(match: re.Match) -> str:
        n = int(match.group(1))
        # Keep 1px hairlines crisp; scale everything else (fonts, padding, heights…)
        if n <= 1:
            return match.group(0)
        return f"{max(1, int(round(n * factor)))}px"

    return re.sub(r"(\d+)px", _scale_px, text)

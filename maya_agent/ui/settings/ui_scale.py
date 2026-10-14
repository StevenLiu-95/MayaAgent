"""UI scale helpers."""

def _resolve_ui_scale_pct(cfg) -> int:
    """Prefer ui.ui_scale; migrate legacy ui.font_size (13px ≈ 100%)."""
    raw = cfg.get("ui.ui_scale")
    if raw is not None:
        try:
            return max(75, min(175, int(raw)))
        except (TypeError, ValueError):
            return 100
    old = cfg.get("ui.font_size")
    if old is not None:
        try:
            return max(75, min(175, int(round(float(old) / 13 * 100))))
        except (TypeError, ValueError):
            pass
    return 100


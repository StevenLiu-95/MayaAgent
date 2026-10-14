"""Default config snapshots for restore-defaults buttons."""

from __future__ import annotations

class ConfigDefaults:
    """Factory UI values from bundled default_config (not the merged user config)."""

    @staticmethod
    def load() -> dict:
        try:
            data = get_config()._load_default_config()
        except Exception:
            data = {}
        app = data.get("app") if isinstance(data, dict) else {}
        ui = data.get("ui") if isinstance(data, dict) else {}
        if not isinstance(app, dict):
            app = {}
        if not isinstance(ui, dict):
            ui = {}
        scale = 100
        try:
            scale = max(75, min(175, int(ui.get("ui_scale", 100))))
        except (TypeError, ValueError):
            scale = 100
        bridge = data.get("bridge") if isinstance(data, dict) else {}
        if not isinstance(bridge, dict):
            bridge = {}
        maya = data.get("maya") if isinstance(data, dict) else {}
        if not isinstance(maya, dict):
            maya = {}
        try:
            bridge_port = int(bridge.get("port", 8765) or 8765)
        except (TypeError, ValueError):
            bridge_port = 8765
        return {
            "language": str(app.get("language") or "zh-CN"),
            "font_family": str(ui.get("font_family") or "Microsoft YaHei UI"),
            "ui_scale": scale,
            "temp_dir": str(ui.get("temp_dir") or ""),
            "advanced_skeleton_path": str(
                maya.get("advanced_skeleton_path") or ""
            ),
            "bridge_enabled": bool(bridge.get("enabled", True)),
            "bridge_auto_start": bool(bridge.get("auto_start", False)),
            "bridge_port": bridge_port,
            "bridge_port_auto": bool(bridge.get("port_auto", True)),
            "bridge_confirm_mode": str(
                bridge.get("confirm_mode") or "maya_dialog"
            ),
            "bridge_share_agent": bool(bridge.get("share_panel_agent", True)),
        }

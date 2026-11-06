"""Shared system prompt builder — panel Agent and MCP use the same text."""

from __future__ import annotations

from typing import Optional

from maya_agent.core.agent_mode import mode_system_addon, normalize_mode
from maya_agent.core.rules_manager import get_rules_for_prompt
from maya_agent.tools.registry import ensure_tools_loaded, tool_specs
from maya_agent.utils.config import get_config
from maya_agent.utils.maya_compat import in_maya, maya_version


def build_system_prompt(mode: Optional[str] = None) -> str:
    """
    Full system prompt used by MayaAgent (resources prompt + runtime env).

    Panel chat and MCP instructions / ``GET /v1/system-prompt`` must call this
    so edits to ``resources/prompts/system_zh.md`` apply to both sides.
    """
    cfg = get_config()
    filter_mode = normalize_mode(mode)
    prompt = cfg.system_prompt()
    ensure_tools_loaded()
    adv_line = "- AdvancedSkeleton: 不可用（adv_* 已隐藏；可用 auto_rig_character）\n"
    try:
        from maya_agent.tools.adv_rig import adv_tools_available, _find_adv_root

        if adv_tools_available():
            adv_line = (
                f"- AdvancedSkeleton: 可用（{_find_adv_root()}）；"
                "优先 adv_auto_rig / adv_next_step\n"
            )
    except Exception:
        pass
    env = (
        f"\n\n## 运行环境\n- Maya: {maya_version() if in_maya() else '未在 Maya 内'}\n"
        f"{adv_line}"
        f"- 工具数量: {len(tool_specs(mode=filter_mode))}\n"
        f"- Agent 模式: {filter_mode}\n"
    )
    full = prompt + env + mode_system_addon(filter_mode)
    try:
        rules = get_rules_for_prompt()
    except Exception:
        rules = ""
    if rules:
        full = full + "\n\n" + rules
    return full

"""Agent operating modes and tool allow/deny filtering."""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence

# Public mode strings used by UI / config / MCP.
MODE_AGENT = "agent"
MODE_ASK = "ask"
MODE_PLAN = "plan"  # planning phase (UI label); internal filter uses PLAN_PLANNING
MODE_PLAN_PLANNING = "plan_planning"
MODE_PLAN_EXECUTING = "plan_executing"

ALL_MODES = frozenset(
    {
        MODE_AGENT,
        MODE_ASK,
        MODE_PLAN,
        MODE_PLAN_PLANNING,
        MODE_PLAN_EXECUTING,
    }
)

# UI-facing modes (combo box).
UI_MODES = (MODE_AGENT, MODE_ASK, MODE_PLAN)

# Name prefixes treated as read-only for Ask / Plan planning.
_ASK_NAME_PREFIXES = (
    "get_",
    "list_",
    "check_",
    "preflight_",
    "describe_",
    "lookup_",
    "search_",
    "capture_",
    "read_",
    "web_search",
    "fetch_",
    "generate_chart",
    "verify_",
    "path_info",
)

# Exact names allowed in Ask even if prefixes miss them.
_ASK_EXACT = frozenset(
    {
        "path_info",
        "get_workspace_info",
        "adv_rig_status",
        "meshy_balance",
        "meshy_get_task",
        "tripo_balance",
        "tripo_get_task",
        "tripo_list_tasks",
        "hunyuan_test_connection",
        "hunyuan_get_job",
        "hunyuan_list_profile_templates",
        "hunyuan_list_motions",
        "list_skeleton_templates",
    }
)

# Cloud / write-heavy categories: only exact allowlist query tools may pass.
_CLOUD_CATEGORIES = frozenset({"meshy", "tripo", "hunyuan"})

# Categories that never appear in Ask / Plan planning (even if not destructive).
_ASK_DENY_CATEGORIES = frozenset({"scripting"})

# Name prefixes always denied in Ask / Plan planning.
_ASK_DENY_PREFIXES = (
    "execute_",
    "write_",
    "delete_",
    "create_",
    "export_",
    "import_",
    "save_",
    "open_",
    "bind_",
    "unbind_",
    "set_",
    "assign_",
    "bake_",
    "copy_animation",
    "playblast",
    "auto_rig",
    "adv_auto",
    "adv_build",
    "adv_bind",
    "adv_create",
    "adv_set",
    "adv_import",
    "adv_next",
    "meshy_text",
    "meshy_image",
    "meshy_multi",
    "meshy_retexture",
    "meshy_remesh",
    "meshy_rig",
    "meshy_animate",
    "meshy_download",
    "meshy_import",
    "tripo_text",
    "tripo_image",
    "tripo_multiview",
    "tripo_texture",
    "tripo_convert",
    "tripo_download",
    "tripo_import",
    "tripo_rig",
    "tripo_animate",
    "hunyuan_text",
    "hunyuan_image",
    "hunyuan_multi",
    "hunyuan_texture",
    "hunyuan_submit",
    "hunyuan_download",
    "hunyuan_import",
    "hunyuan_reduce",
    "hunyuan_rig",
    "hunyuan_animate",
)

_PLAN_ONLY_CREATE = "create_plan"
_PLAN_ONLY_UPDATE = "update_plan_step"


def normalize_mode(mode: Optional[str], *, default: str = MODE_AGENT) -> str:
    """
    Normalize user/config mode to an internal filter mode.

    ``plan`` (UI) maps to ``plan_planning``. Unknown values fall back to default.
    """
    raw = (mode or "").strip().lower()
    if not raw:
        return default if default in ALL_MODES else MODE_AGENT
    if raw == MODE_PLAN:
        return MODE_PLAN_PLANNING
    if raw in ALL_MODES:
        return raw
    return default if default in ALL_MODES else MODE_AGENT


def ui_mode_from_internal(mode: Optional[str]) -> str:
    """Map internal mode back to UI combo value (agent/ask/plan)."""
    m = normalize_mode(mode)
    if m in (MODE_PLAN_PLANNING, MODE_PLAN_EXECUTING):
        return MODE_PLAN
    if m == MODE_ASK:
        return MODE_ASK
    return MODE_AGENT


def _name_allowed_ask(name: str) -> bool:
    if name in (_PLAN_ONLY_CREATE, _PLAN_ONLY_UPDATE):
        return False
    if name in _ASK_EXACT:
        return True
    for deny in _ASK_DENY_PREFIXES:
        if name.startswith(deny) or name == deny:
            return False
    for prefix in _ASK_NAME_PREFIXES:
        if name.startswith(prefix) or name == prefix:
            return True
    return False


def is_readonly_tool(reg: Any) -> bool:
    """Heuristic: whether a RegisteredTool is safe for Ask mode."""
    name = getattr(reg, "name", "") or ""
    if getattr(reg, "destructive", False):
        return False
    category = getattr(reg, "category", "") or ""
    if category in _ASK_DENY_CATEGORIES:
        return False
    if category in _CLOUD_CATEGORIES:
        return name in _ASK_EXACT
    return _name_allowed_ask(name)


def is_tool_allowed(reg: Any, mode: Optional[str]) -> bool:
    """Return True if ``reg`` may be exposed / executed under ``mode``."""
    m = normalize_mode(mode)
    name = getattr(reg, "name", "") or ""

    if m == MODE_AGENT:
        # Plan tools only appear in plan modes.
        if name in (_PLAN_ONLY_CREATE, _PLAN_ONLY_UPDATE):
            return False
        return True

    if m == MODE_ASK:
        if name in (_PLAN_ONLY_CREATE, _PLAN_ONLY_UPDATE):
            return False
        return is_readonly_tool(reg)

    if m == MODE_PLAN_PLANNING:
        if name == _PLAN_ONLY_CREATE:
            return True
        if name == _PLAN_ONLY_UPDATE:
            return False
        return is_readonly_tool(reg)

    if m == MODE_PLAN_EXECUTING:
        if name == _PLAN_ONLY_CREATE:
            return False
        # Full tool set plus update_plan_step; create_plan hidden.
        return True

    return False


def filter_tools_for_mode(tools: Iterable[Any], mode: Optional[str]) -> List[Any]:
    """Filter RegisteredTool (or any object with name/destructive/category)."""
    return [t for t in tools if is_tool_allowed(t, mode)]


def mode_denied_message(tool_name: str, mode: Optional[str]) -> str:
    m = normalize_mode(mode)
    label = {
        MODE_ASK: "Ask（只读）",
        MODE_PLAN_PLANNING: "Plan（规划）",
        MODE_PLAN_EXECUTING: "Plan（执行）",
        MODE_AGENT: "Agent",
    }.get(m, m)
    return (
        f"当前模式为 {label}，不允许调用工具 `{tool_name}`。"
        f"请切换到 Agent 模式，或在 Plan 模式下先批准执行计划。"
    )


def mode_system_addon(mode: Optional[str]) -> str:
    """Extra system-prompt section for the active mode."""
    m = normalize_mode(mode)
    if m == MODE_ASK:
        return (
            "\n\n## 当前模式：Ask（只读）\n"
            "- 只能查询场景、检查资产、检索文档/网络与分析，**禁止**修改场景或执行写操作。\n"
            "- 不要调用创建/删除/绑定/导出/脚本执行等工具；若用户要求修改，说明需切换到 Agent 或 Plan 模式。\n"
        )
    if m == MODE_PLAN_PLANNING:
        return (
            "\n\n## 当前模式：Plan（规划）\n"
            "- 先用只读工具调研当前场景与需求，必要时联网/查文档。\n"
            "- 调研充分后**必须**调用 `create_plan` 提交结构化执行计划（标题、概述、有序步骤）。\n"
            "- 提交计划后停止，等待用户在界面批准；**不要**在本阶段修改场景。\n"
            "- 不要调用 `update_plan_step`（仅批准后的执行阶段可用）。\n"
        )
    if m == MODE_PLAN_EXECUTING:
        return (
            "\n\n## 当前模式：Plan（执行）\n"
            "- 用户已批准计划。按步骤顺序使用工具完成任务。\n"
            "- 每完成或开始关键步骤时调用 `update_plan_step` 更新状态"
            "（pending / in_progress / done / skipped）。\n"
            "- 不要再调用 `create_plan`；若需大幅改计划，提示用户回到 Plan 规划。\n"
        )
    return (
        "\n\n## 当前模式：Agent\n"
        "- 可使用全部可用工具完成用户任务；危险操作仍可能弹出确认。\n"
    )

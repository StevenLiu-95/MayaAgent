"""Agent Skills tools — list / read SKILL.md and package resources."""

from __future__ import annotations

from maya_agent.core import skills_manager
from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.utils.config import get_config


def _skills_disabled() -> bool:
    return not bool(get_config().get("agent.skills_enabled", True))


@tool(
    name="list_skills",
    description=(
        "List installed Agent Skills (name, description, path, flags). "
        "Use when checking which skills are available or before read_skill. "
        "Skills whose metadata.requires is unmet (e.g. Meshy key missing) are "
        "hidden unless include_unavailable=true."
    ),
    parameters=obj_schema(
        {
            "include_manual": {
                "type": "boolean",
                "description": (
                    "Include skills marked disable-model-invocation "
                    "(manual / explicit use only). Default true."
                ),
            },
            "include_unavailable": {
                "type": "boolean",
                "description": (
                    "Include skills whose metadata.requires is not met "
                    "(missing API / ADV). Default false."
                ),
            },
        }
    ),
    category="skills",
    main_thread=False,
)
def list_skills(
    include_manual: bool = True, include_unavailable: bool = False
) -> ToolResult:
    if _skills_disabled():
        return ToolResult(ok=False, error="Agent Skills are disabled in settings (扩展)")
    skills_manager.reload_skills()
    items = []
    for s in skills_manager.discover_skills(force_reload=True):
        if s.disable_model_invocation and not include_manual:
            continue
        if not include_unavailable and not skills_manager.skill_requirement_met(s):
            continue
        items.append(s.to_dict())
    return ToolResult(
        ok=True,
        message=f"发现 {len(items)} 个 Skill",
        data={
            "skills_dir": skills_manager.skills_root_display(),
            "bundled_skills_dir": str(skills_manager.bundled_skills_root()).replace(
                "\\", "/"
            ),
            "count": len(items),
            "skills": items,
        },
    )


@tool(
    name="read_skill",
    description=(
        "Load the full instructions from an installed skill's SKILL.md. "
        "Call when a task matches a skill description from the available_skills catalog."
    ),
    parameters=obj_schema(
        {
            "name": {
                "type": "string",
                "description": "Skill name (directory name / catalog name)",
            },
        },
        required=["name"],
    ),
    category="skills",
    main_thread=False,
)
def read_skill(name: str) -> ToolResult:
    if _skills_disabled():
        return ToolResult(ok=False, error="Agent Skills are disabled in settings (扩展)")
    try:
        payload = skills_manager.load_skill(name)
    except FileNotFoundError as e:
        return ToolResult(ok=False, error=str(e))
    except Exception as e:
        return ToolResult(ok=False, error=f"failed to load skill: {e}")

    activation = None
    try:
        from maya_agent.core.tool_exposure import get_exposure_router

        router = get_exposure_router()
        if router is not None:
            activation = router.activate_from_skill(payload)
            payload = dict(payload)
            payload["tool_activation"] = activation
    except Exception:
        activation = None

    msg = f"已加载 Skill: {payload.get('name')}"
    if isinstance(activation, dict) and activation.get("activated_via"):
        msg = f"{msg}（已按 {activation.get('activated_via')} 激活相关工具）"
    return ToolResult(ok=True, message=msg, data=payload)


@tool(
    name="read_skill_resource",
    description=(
        "Read a text file inside a skill package (relative path from the skill root), "
        "e.g. references/guide.md or scripts/helper.py."
    ),
    parameters=obj_schema(
        {
            "name": {
                "type": "string",
                "description": "Skill name",
            },
            "path": {
                "type": "string",
                "description": "Relative path within the skill directory",
            },
        },
        required=["name", "path"],
    ),
    category="skills",
    main_thread=False,
)
def read_skill_resource(name: str, path: str) -> ToolResult:
    if _skills_disabled():
        return ToolResult(ok=False, error="Agent Skills are disabled in settings (扩展)")
    try:
        payload = skills_manager.read_skill_resource(name, path)
    except FileNotFoundError as e:
        return ToolResult(ok=False, error=str(e))
    except ValueError as e:
        return ToolResult(ok=False, error=str(e))
    except Exception as e:
        return ToolResult(ok=False, error=f"failed to read resource: {e}")
    return ToolResult(
        ok=True,
        message=f"已读取 {payload.get('path')}",
        data=payload,
    )

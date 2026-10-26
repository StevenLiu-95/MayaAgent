"""Tool registry and decorator for Maya Agent tools."""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from maya_agent.llm.base import ToolSpec

@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    message: str = ""
    error: str = ""
    images: Optional[List[Any]] = None  # ImageAttachment list for vision models

    def to_str(self) -> str:
        payload = {
            "ok": self.ok,
            "message": self.message,
            "data": self.data,
            "error": self.error,
        }
        imgs = [img for img in (self.images or []) if getattr(img, "data_b64", "")]
        if imgs:
            payload["images_attached"] = len(imgs)
            names = [getattr(img, "name", "") or "viewport" for img in imgs]
            note = f"已附带 {len(imgs)} 张图像供视觉分析: {', '.join(names)}"
            if payload["message"]:
                payload["message"] = f"{payload['message']}（{note}）"
            else:
                payload["message"] = note
        return json.dumps(payload, ensure_ascii=False, default=str)


@dataclass
class RegisteredTool:
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[..., ToolResult]
    category: str = "general"
    destructive: bool = False
    requires_vision: bool = False
    # When False, ToolExecutor runs the handler on the worker thread
    # (HTTP / long polls). Maya cmds tools must keep the default True.
    main_thread: bool = True


_REGISTRY: Dict[str, RegisteredTool] = {}
_MIN_HEALTHY_TOOLS = 50
# Canaries that always register (no API key / ADV gate). Missing any of these
# after load means the registry was wiped mid-reload (e.g. reloading this module).
_CORE_CANARY_TOOLS = (
    "get_scene_info",
    "create_primitive",
    "execute_python",
    "export_fbx",
)
# Not a tool provider — reloading it re-binds ``_REGISTRY = {}`` and drops
# every tool registered by modules that sort before "registry".
_SKIP_TOOL_MODULES = frozenset({"registry"})


def tool(
    name: str,
    description: str,
    parameters: Dict[str, Any],
    category: str = "general",
    destructive: bool = False,
    requires_vision: bool = False,
    main_thread: bool = True,
):
    """Register a callable as an agent tool."""

    def decorator(fn: Callable[..., ToolResult]):
        _REGISTRY[name] = RegisteredTool(
            name=name,
            description=description,
            parameters=parameters,
            handler=fn,
            category=category,
            destructive=destructive,
            requires_vision=requires_vision,
            main_thread=main_thread,
        )
        return fn

    return decorator


def get_tool(name: str) -> Optional[RegisteredTool]:
    return _REGISTRY.get(name)


def all_tools() -> List[RegisteredTool]:
    return list(_REGISTRY.values())


def tool_specs(*, vision: bool = True) -> List[ToolSpec]:
    """Return OpenAI-style tool schemas. Vision-only / unavailable Meshy/Tripo/Hunyuan/ADV tools omitted."""
    meshy_ok = True
    try:
        from maya_agent.tools.meshy_client import meshy_tools_available

        meshy_ok = meshy_tools_available()
    except Exception:
        meshy_ok = False

    tripo_ok = True
    try:
        from maya_agent.tools.tripo_client import tripo_tools_available

        tripo_ok = tripo_tools_available()
    except Exception:
        tripo_ok = False

    hunyuan_ok = True
    try:
        from maya_agent.tools.hunyuan_client import hunyuan_tools_available

        hunyuan_ok = hunyuan_tools_available()
    except Exception:
        hunyuan_ok = False

    adv_ok = True
    try:
        from maya_agent.tools.adv_rig import adv_tools_available

        adv_ok = adv_tools_available()
    except Exception:
        adv_ok = False

    specs = []
    for t in _REGISTRY.values():
        if t.requires_vision and not vision:
            continue
        if t.category == "meshy" and not meshy_ok:
            continue
        if t.category == "tripo" and not tripo_ok:
            continue
        if t.category == "hunyuan" and not hunyuan_ok:
            continue
        if t.category == "adv" and not adv_ok:
            continue
        specs.append(
            ToolSpec(name=t.name, description=t.description, parameters=t.parameters)
        )
    return specs


def tools_by_category() -> Dict[str, List[RegisteredTool]]:
    cats: Dict[str, List[RegisteredTool]] = {}
    for t in _REGISTRY.values():
        cats.setdefault(t.category, []).append(t)
    return cats


def run_tool(name: str, arguments: Dict[str, Any]) -> ToolResult:
    reg = get_tool(name)
    if not reg:
        return ToolResult(ok=False, error=f"未知工具: {name}")
    try:
        result = reg.handler(**(arguments or {}))
        if not isinstance(result, ToolResult):
            return ToolResult(ok=True, data=result)
        return result
    except TypeError as e:
        return ToolResult(ok=False, error=f"工具 {name} 参数无效: {e}")
    except Exception as e:
        return ToolResult(
            ok=False,
            error=f"{type(e).__name__}: {e}",
            data={"traceback": traceback.format_exc()},
        )


def _reload_tool_helpers() -> None:
    import importlib
    import sys

    for full in (
        "maya_agent.tools._maya",
        "maya_agent.tools._mesh",
        "maya_agent.tools._uv",
    ):
        if full in sys.modules:
            try:
                importlib.reload(sys.modules[full])
            except Exception:
                pass


def _iter_public_tool_modules():
    import pkgutil

    import maya_agent.tools as tools_pkg

    for mod in pkgutil.iter_modules(tools_pkg.__path__):
        if mod.name.startswith("_"):
            continue
        if mod.name in _SKIP_TOOL_MODULES:
            continue
        yield f"maya_agent.tools.{mod.name}"


def _registry_incomplete() -> bool:
    """True when tool count is low or core canary tools are missing."""
    if len(_REGISTRY) < _MIN_HEALTHY_TOOLS:
        return True
    return any(name not in _REGISTRY for name in _CORE_CANARY_TOOLS)


def _hard_reset_tool_modules() -> None:
    """
    Drop tool submodules from ``sys.modules`` and re-import into *this*
    registry module.

    Keeps ``maya_agent.tools.registry`` loaded so ``_REGISTRY`` identity stays
    stable for callers that already imported symbols from this module.
    """
    import importlib
    import sys

    _REGISTRY.clear()
    for name in list(sys.modules):
        if name == "maya_agent.tools.registry":
            continue
        if name == "maya_agent.tools" or name.startswith("maya_agent.tools."):
            sys.modules.pop(name, None)
    import maya_agent.tools  # noqa: F401

    _reload_tool_helpers()
    for full in _iter_public_tool_modules():
        importlib.import_module(full)


def ensure_tools_loaded() -> None:
    """Import all tool modules so decorators register."""
    import importlib
    import sys

    force_reload = len(_REGISTRY) == 0
    if force_reload:
        _reload_tool_helpers()

    for full in _iter_public_tool_modules():
        # Never reload this module: that would rebind ``_REGISTRY = {}`` and
        # wipe tools already registered by modules sorted before "registry"
        # (meshy, modeling, hunyuan, …).
        if force_reload and full in sys.modules:
            try:
                importlib.reload(sys.modules[full])
            except Exception:
                importlib.import_module(full)
        else:
            importlib.import_module(full)

    if _registry_incomplete():
        try:
            _hard_reset_tool_modules()
        except Exception:
            pass


def heal_tools_if_needed() -> Dict[str, Any]:
    """
    Ensure a healthy tool count. Used by bridge health/start.
    Returns {tool_count, healed, warning}.
    """
    import sys

    ensure_tools_loaded()
    count = len(_REGISTRY)
    healed = False
    warning = ""
    if _registry_incomplete():
        healed = True
        try:
            _hard_reset_tool_modules()
        except Exception as e:
            warning = f"hard_reset_failed:{e}"
        count = len(_REGISTRY)
        if _registry_incomplete():
            missing = [n for n in _CORE_CANARY_TOOLS if n not in _REGISTRY]
            warning = warning or (
                f"tool_count={count} incomplete (missing={missing or 'count'}); "
                "拖入 recover_tools_dragdrop.mel 或 maya_agent.reload()"
            )
        # Rebind http_server's imported function refs to this module's callables
        try:
            hs = sys.modules.get("maya_agent.bridge.http_server")
            if hs is not None:
                hs.ensure_tools_loaded = ensure_tools_loaded
                hs.tool_specs = tool_specs
                hs.heal_tools_if_needed = heal_tools_if_needed
        except Exception:
            pass
    return {"tool_count": count, "healed": healed, "warning": warning}


def obj_schema(properties: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    schema: Dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema

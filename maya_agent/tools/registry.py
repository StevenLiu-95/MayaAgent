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


_REGISTRY: Dict[str, RegisteredTool] = {}


def tool(
    name: str,
    description: str,
    parameters: Dict[str, Any],
    category: str = "general",
    destructive: bool = False,
    requires_vision: bool = False,
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
        )
        return fn

    return decorator


def get_tool(name: str) -> Optional[RegisteredTool]:
    return _REGISTRY.get(name)


def all_tools() -> List[RegisteredTool]:
    return list(_REGISTRY.values())


def tool_specs(*, vision: bool = True) -> List[ToolSpec]:
    """Return OpenAI-style tool schemas. Vision-only tools omitted when vision=False."""
    specs = []
    for t in _REGISTRY.values():
        if t.requires_vision and not vision:
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


def ensure_tools_loaded() -> None:
    """Import all tool modules so decorators register."""
    import importlib
    import pkgutil

    import maya_agent.tools as tools_pkg

    for mod in pkgutil.iter_modules(tools_pkg.__path__):
        if mod.name.startswith("_"):
            continue
        importlib.import_module(f"maya_agent.tools.{mod.name}")


def obj_schema(properties: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    schema: Dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema

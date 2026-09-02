"""Tool registry and decorator for Maya Agent tools."""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from maya_agent.llm.base import ToolSpec

@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    message: str = ""
    error: str = ""

    def to_str(self) -> str:
        payload = {
            "ok": self.ok,
            "message": self.message,
            "data": self.data,
            "error": self.error,
        }
        return json.dumps(payload, ensure_ascii=False, default=str)

@dataclass
class RegisteredTool:
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[..., ToolResult]
    category: str = "general"
    destructive: bool = False

_REGISTRY: Dict[str, RegisteredTool] = {}

def tool(
    name: str,
    description: str,
    parameters: Dict[str, Any],
    category: str = "general",
    destructive: bool = False,
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
        )
        return fn

    return decorator

def get_tool(name: str) -> Optional[RegisteredTool]:
    return _REGISTRY.get(name)

def all_tools() -> List[RegisteredTool]:
    return list(_REGISTRY.values())

def tool_specs() -> List[ToolSpec]:
    return [
        ToolSpec(name=t.name, description=t.description, parameters=t.parameters)
        for t in _REGISTRY.values()
    ]

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

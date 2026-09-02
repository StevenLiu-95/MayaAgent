"""Lighting tools."""

from __future__ import annotations

from typing import List, Optional

from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.tools._maya import cmds as _cmds

@tool(
    name="create_light",
    description="创建灯光：directional / spot / point / area / ambient。",
    parameters=obj_schema(
        {
            "light_type": {
                "type": "string",
                "enum": ["directional", "spot", "point", "area", "ambient"],
                "default": "directional",
            },
            "name": {"type": "string", "default": ""},
            "intensity": {"type": "number", "default": 1.0},
            "color": {
                "type": "array",
                "items": {"type": "number"},
                "default": [1, 1, 1],
            },
            "position": {
                "type": "array",
                "items": {"type": "number"},
                "default": [0, 10, 0],
            },
        }
    ),
    category="lighting",
)
def create_light(
    light_type: str = "directional",
    name: str = "",
    intensity: float = 1.0,
    color: Optional[List[float]] = None,
    position: Optional[List[float]] = None,
) -> ToolResult:
    c = _cmds()
    color = color or [1, 1, 1]
    position = position or [0, 10, 0]
    creators = {
        "directional": c.directionalLight,
        "spot": c.spotLight,
        "point": c.pointLight,
        "area": c.areaLight,
        "ambient": c.ambientLight,
    }
    if light_type not in creators:
        return ToolResult(ok=False, error="未知灯光类型")
    kwargs = {"intensity": intensity, "rgb": color}
    if name:
        kwargs["name"] = name
    light = creators[light_type](**kwargs)
    # areaLight/directional return shape; get transform
    transform = c.listRelatives(light, parent=True) if c.nodeType(light) != "transform" else [light]
    transform = transform[0] if transform else light
    c.xform(transform, worldSpace=True, translation=position)
    return ToolResult(ok=True, data={"light": light, "transform": transform}, message=f"灯光已创建: {transform}")

@tool(
    name="create_three_point_lighting",
    description="快速创建三点布光（主光/辅光/背光），适合预览角色。",
    parameters=obj_schema(
        {
            "target": {"type": "string", "default": "", "description": "目标物体，空则原点"},
            "key_intensity": {"type": "number", "default": 1.2},
            "fill_intensity": {"type": "number", "default": 0.5},
            "rim_intensity": {"type": "number", "default": 0.8},
        }
    ),
    category="lighting",
)
def create_three_point_lighting(
    target: str = "",
    key_intensity: float = 1.2,
    fill_intensity: float = 0.5,
    rim_intensity: float = 0.8,
) -> ToolResult:
    c = _cmds()
    center = [0, 1, 0]
    if target and c.objExists(target):
        center = c.xform(target, query=True, worldSpace=True, rotatePivot=True)

    def _make(name, pos, intensity, rgb):
        shape = c.directionalLight(name=name, intensity=intensity, rgb=rgb)
        tr = c.listRelatives(shape, parent=True)[0]
        c.xform(tr, worldSpace=True, translation=pos)
        c.viewLookAt(tr, pos=(center[0], center[1], center[2])) if hasattr(c, "viewLookAt") else None
        # aim constraint style look-at via aimConstraint to locator
        loc = c.spaceLocator(name=f"{name}_aim")[0]
        c.xform(loc, worldSpace=True, translation=center)
        c.aimConstraint(loc, tr, aimVector=(0, 0, -1), upVector=(0, 1, 0))
        return tr

    key = _make("lgt_key", [center[0] + 4, center[1] + 5, center[2] + 4], key_intensity, [1, 0.98, 0.95])
    fill = _make("lgt_fill", [center[0] - 4, center[1] + 2, center[2] + 3], fill_intensity, [0.8, 0.85, 1])
    rim = _make("lgt_rim", [center[0], center[1] + 4, center[2] - 5], rim_intensity, [1, 1, 1])
    grp = c.group([key, fill, rim], name="grp_threePointLights")
    return ToolResult(ok=True, data={"group": grp, "lights": [key, fill, rim]}, message="三点光已创建")

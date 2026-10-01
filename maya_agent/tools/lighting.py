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


@tool(
    name="create_environment_light",
    description=(
        "创建建筑/外观预览用环境光：默认 ambient + 顶部柔和平行光；"
        "若已加载 Arnold，可加 aiSkyDomeLight（可选 HDR 路径）。"
    ),
    parameters=obj_schema(
        {
            "intensity": {"type": "number", "default": 0.6, "description": "环境光强度"},
            "sun_intensity": {"type": "number", "default": 0.9, "description": "顶部日光强度"},
            "color": {
                "type": "array",
                "items": {"type": "number"},
                "default": [0.85, 0.9, 1.0],
                "description": "环境色 RGB",
            },
            "use_skydome": {
                "type": "boolean",
                "default": True,
                "description": "尽量创建 Arnold 天空穹顶（无 mtoa 则跳过）",
            },
            "hdri_path": {
                "type": "string",
                "default": "",
                "description": "可选 HDR/EXR 路径接到 skydome",
            },
            "name_prefix": {"type": "string", "default": "lgt_env"},
        }
    ),
    category="lighting",
)
def create_environment_light(
    intensity: float = 0.6,
    sun_intensity: float = 0.9,
    color: Optional[List[float]] = None,
    use_skydome: bool = True,
    hdri_path: str = "",
    name_prefix: str = "lgt_env",
) -> ToolResult:
    c = _cmds()
    color = color or [0.85, 0.9, 1.0]
    prefix = (name_prefix or "lgt_env").strip() or "lgt_env"
    created = []

    amb_shape = c.ambientLight(name=f"{prefix}_ambient", intensity=float(intensity), rgb=color)
    amb = c.listRelatives(amb_shape, parent=True)[0]
    created.append(amb)

    sun_shape = c.directionalLight(
        name=f"{prefix}_sun", intensity=float(sun_intensity), rgb=[1.0, 0.98, 0.94]
    )
    sun = c.listRelatives(sun_shape, parent=True)[0]
    c.xform(sun, worldSpace=True, translation=[5, 20, 5])
    c.xform(sun, worldSpace=True, rotation=[-60, 35, 0])
    created.append(sun)

    skydome = ""
    hdri_path = (hdri_path or "").replace("\\", "/")
    if use_skydome:
        try:
            c.loadPlugin("mtoa", quiet=True)
        except Exception:
            pass
        try:
            if "aiSkyDomeLight" in (c.listNodeTypes("light") or []) or hasattr(c, "shadingNode"):
                # aiSkyDomeLight is created via shadingNode asLight
                try:
                    sky_shape = c.shadingNode("aiSkyDomeLight", asLight=True, name=f"{prefix}_skydome")
                except Exception:
                    sky_shape = None
                if sky_shape:
                    parents = c.listRelatives(sky_shape, parent=True) or []
                    skydome = parents[0] if parents else sky_shape
                    created.append(skydome)
                    try:
                        c.setAttr(f"{sky_shape}.intensity", float(intensity))
                    except Exception:
                        pass
                    if hdri_path:
                        try:
                            file_node = c.shadingNode(
                                "file", asTexture=True, isColorManaged=True, name=f"{prefix}_hdri"
                            )
                            c.setAttr(f"{file_node}.fileTextureName", hdri_path, type="string")
                            c.connectAttr(f"{file_node}.outColor", f"{sky_shape}.color", force=True)
                        except Exception:
                            pass
        except Exception:
            skydome = ""

    grp = c.group(created, name=f"grp_{prefix}")
    data = {
        "group": grp,
        "ambient": amb,
        "sun": sun,
        "skydome": skydome or None,
        "hdri_path": hdri_path or None,
    }
    msg = f"环境光已创建: {grp}"
    if skydome:
        msg += f"（含 skydome={skydome}）"
    else:
        msg += "（未创建 skydome，使用 ambient+日光）"
    return ToolResult(ok=True, data=data, message=msg)

"""Material and shading tools."""

from __future__ import annotations

from typing import List, Optional

from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.tools._maya import cmds as _cmds

@tool(
    name="create_material",
    description="创建材质：lambert/blinn/phong/standardSurface/aiStandardSurface。",
    parameters=obj_schema(
        {
            "name": {"type": "string", "default": "mat_new"},
            "shader_type": {
                "type": "string",
                "enum": [
                    "lambert",
                    "blinn",
                    "phong",
                    "standardSurface",
                    "aiStandardSurface",
                ],
                "default": "standardSurface",
            },
            "color": {
                "type": "array",
                "items": {"type": "number"},
                "description": "RGB 0-1",
                "default": [0.5, 0.5, 0.5],
            },
            "metalness": {"type": "number", "default": 0.0},
            "roughness": {"type": "number", "default": 0.5},
        }
    ),
    category="materials",
)
def create_material(
    name: str = "mat_new",
    shader_type: str = "standardSurface",
    color: Optional[List[float]] = None,
    metalness: float = 0.0,
    roughness: float = 0.5,
) -> ToolResult:
    c = _cmds()
    color = color or [0.5, 0.5, 0.5]
    # Fallback if Arnold/standardSurface missing
    available = set(c.listNodeTypes("shader") or [])
    if shader_type not in available:
        if "standardSurface" in available:
            shader_type = "standardSurface"
        else:
            shader_type = "lambert"
    shader = c.shadingNode(shader_type, asShader=True, name=name)
    sg = c.sets(renderable=True, noSurfaceShader=True, empty=True, name=f"{shader}SG")
    c.connectAttr(f"{shader}.outColor", f"{sg}.surfaceShader", force=True)

    if c.attributeQuery("color", node=shader, exists=True):
        c.setAttr(f"{shader}.color", *color, type="double3")
    elif c.attributeQuery("baseColor", node=shader, exists=True):
        c.setAttr(f"{shader}.baseColor", *color, type="double3")

    if c.attributeQuery("metalness", node=shader, exists=True):
        c.setAttr(f"{shader}.metalness", metalness)
    if c.attributeQuery("specularRoughness", node=shader, exists=True):
        c.setAttr(f"{shader}.specularRoughness", roughness)
    elif c.attributeQuery("roughness", node=shader, exists=True):
        c.setAttr(f"{shader}.roughness", roughness)

    return ToolResult(
        ok=True,
        data={"shader": shader, "shading_group": sg, "type": shader_type},
        message=f"材质已创建: {shader}",
    )

@tool(
    name="assign_material",
    description="将材质指定给对象。",
    parameters=obj_schema(
        {
            "shader": {"type": "string"},
            "objects": {"type": "array", "items": {"type": "string"}, "default": []},
        },
        required=["shader"],
    ),
    category="materials",
)
def assign_material(shader: str, objects: Optional[List[str]] = None) -> ToolResult:
    c = _cmds()
    targets = objects or (c.ls(selection=True) or [])
    if not targets:
        return ToolResult(ok=False, error="无对象")
    if not c.objExists(shader):
        return ToolResult(ok=False, error=f"材质不存在: {shader}")
    sgs = c.listConnections(shader, type="shadingEngine") or []
    if not sgs:
        return ToolResult(ok=False, error="找不到 shadingEngine")
    c.sets(targets, edit=True, forceElement=sgs[0])
    return ToolResult(ok=True, data={"sg": sgs[0], "objects": targets}, message="材质已指定")

@tool(
    name="assign_texture",
    description="为材质颜色/基础色连接文件纹理。",
    parameters=obj_schema(
        {
            "shader": {"type": "string"},
            "file_path": {"type": "string"},
            "attribute": {
                "type": "string",
                "default": "auto",
                "description": "auto/color/baseColor/normalCamera 等",
            },
        },
        required=["shader", "file_path"],
    ),
    category="materials",
)
def assign_texture(shader: str, file_path: str, attribute: str = "auto") -> ToolResult:
    c = _cmds()
    if not c.objExists(shader):
        return ToolResult(ok=False, error="材质不存在")
    file_node = c.shadingNode("file", asTexture=True, isColorManaged=True, name=f"{shader}_tex")
    place = c.shadingNode("place2dTexture", asUtility=True)
    for attr in (
        "coverage",
        "translateFrame",
        "rotateFrame",
        "mirrorU",
        "mirrorV",
        "stagger",
        "wrapU",
        "wrapV",
        "repeatUV",
        "offset",
        "rotateUV",
        "noiseUV",
        "vertexUvOne",
        "vertexUvTwo",
        "vertexUvThree",
        "vertexCameraOne",
    ):
        if c.attributeQuery(attr, node=place, exists=True) and c.attributeQuery(
            attr, node=file_node, exists=True
        ):
            try:
                c.connectAttr(f"{place}.{attr}", f"{file_node}.{attr}", force=True)
            except Exception:
                pass
    c.connectAttr(f"{place}.outUV", f"{file_node}.uvCoord", force=True)
    c.connectAttr(f"{place}.outUvFilterSize", f"{file_node}.uvFilterSize", force=True)
    c.setAttr(f"{file_node}.fileTextureName", file_path, type="string")

    if attribute == "auto":
        if c.attributeQuery("baseColor", node=shader, exists=True):
            attribute = "baseColor"
        else:
            attribute = "color"
    c.connectAttr(f"{file_node}.outColor", f"{shader}.{attribute}", force=True)
    return ToolResult(
        ok=True,
        data={"file_node": file_node, "attribute": attribute},
        message="纹理已连接",
    )

@tool(
    name="list_materials",
    description="列出场景中的材质与 shading group。",
    parameters=obj_schema({}),
    category="materials",
)
def list_materials() -> ToolResult:
    c = _cmds()
    mats = c.ls(materials=True) or []
    data = []
    for m in mats:
        sgs = c.listConnections(m, type="shadingEngine") or []
        data.append({"shader": m, "type": c.nodeType(m), "sg": sgs})
    return ToolResult(ok=True, data=data, message=f"共 {len(data)} 个材质")

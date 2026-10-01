"""Material and shading tools."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.tools._maya import cmds as _cmds


# Logical property → candidate Maya attributes (first existing wins)
_ATTR_CANDIDATES: Dict[str, List[str]] = {
    "color": ["baseColor", "color", "outColor"],
    "metalness": ["metalness", "metallic"],
    "roughness": ["specularRoughness", "diffuseRoughness", "roughness", "eccentricity"],
    "specular": ["specularColor", "specular"],
    "emission": ["emissionColor", "incandescence", "glowIntensity"],
    "opacity": ["opacity", "transparency"],
    "ior": ["specularIOR", "refractiveIndex"],
    "normal": ["normalCamera"],
    "coat": ["coat", "coatRoughness"],
}

# Documented mapping used by create_material itself
_CREATE_MATERIAL_MAP: Dict[str, Dict[str, str]] = {
    "standardSurface": {
        "color": "baseColor",
        "metalness": "metalness",
        "roughness": "specularRoughness",
    },
    "aiStandardSurface": {
        "color": "baseColor",
        "metalness": "metalness",
        "roughness": "specularRoughness",
    },
    "lambert": {
        "color": "color",
        "metalness": "(n/a)",
        "roughness": "(n/a — use diffuse roughness N/A)",
    },
    "blinn": {
        "color": "color",
        "metalness": "(n/a)",
        "roughness": "eccentricity",
    },
    "phong": {
        "color": "color",
        "metalness": "(n/a)",
        "roughness": "(use cosinePower inverted loosely)",
    },
}


def _name_candidates(query: str, pool: List[str], limit: int = 8) -> List[str]:
    q = (query or "").lower()
    if not q:
        return []
    scored: List[Tuple[int, str]] = []
    for name in pool:
        low = name.lower()
        short = low.split("|")[-1]
        score = 0
        if short == q or low == q:
            score = 100
        elif short.startswith(q) or q.startswith(short):
            score = 80
        elif q in short or short in q:
            score = 60
        else:
            for suf in ("sg", "mat", "mtl", "shader"):
                s2 = short[: -len(suf)] if short.endswith(suf) else short
                q2 = q[: -len(suf)] if q.endswith(suf) else q
                if s2 and q2 and (s2 == q2 or s2 in q2 or q2 in s2):
                    score = max(score, 50)
        if score:
            scored.append((score, name))
    scored.sort(key=lambda x: (-x[0], x[1]))
    out: List[str] = []
    seen = set()
    for _, n in scored:
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
        if len(out) >= limit:
            break
    return out


def _resolve_shading_group(name: str) -> Tuple[Optional[str], Optional[str], Dict[str, Any]]:
    """Accept shader or shadingEngine name. Returns (sg, shader, meta)."""
    c = _cmds()
    meta: Dict[str, Any] = {"query": name}
    if not name:
        return None, None, {**meta, "error": "材质名为空"}

    if c.objExists(name):
        ntype = c.nodeType(name)
        meta["node_type"] = ntype
        if ntype == "shadingEngine":
            shaders = c.listConnections(f"{name}.surfaceShader") or []
            return name, (shaders[0] if shaders else ""), meta
        sgs = c.listConnections(name, type="shadingEngine") or []
        if sgs:
            return sgs[0], name, meta
        return None, None, {
            **meta,
            "error": f"节点 {name}（类型 {ntype}）未连接到 shadingEngine",
        }

    alts = []
    if not name.lower().endswith("sg"):
        alts.extend([f"{name}SG", f"{name}Sg"])
    if name.lower().endswith("sg"):
        alts.extend([name[:-2], name[:-2] + "Shader"])
    for alt in alts:
        if c.objExists(alt):
            return _resolve_shading_group(alt)

    mats = c.ls(materials=True) or []
    sgs = c.ls(type="shadingEngine") or []
    return None, None, {
        **meta,
        "error": f"材质/SG 不存在: {name}",
        "candidates": _name_candidates(name, mats + sgs),
        "hint": "可传 shader 名或 shadingEngine 名（create_material 返回的 shading_group）",
    }


def _resolve_attr(shader: str, logical: str) -> Optional[str]:
    c = _cmds()
    for cand in _ATTR_CANDIDATES.get(logical, [logical]):
        try:
            if c.attributeQuery(cand, node=shader, exists=True):
                return cand
        except Exception:
            continue
    return None


def _set_color3(shader: str, attr: str, rgb: List[float]) -> bool:
    c = _cmds()
    try:
        c.setAttr(f"{shader}.{attr}", float(rgb[0]), float(rgb[1]), float(rgb[2]), type="double3")
        return True
    except Exception:
        return False


def _probe_shader_attrs(shader: str) -> Dict[str, Any]:
    c = _cmds()
    resolved: Dict[str, Optional[str]] = {}
    for logical in _ATTR_CANDIDATES:
        resolved[logical] = _resolve_attr(shader, logical)
    keyables: List[str] = []
    try:
        keyables = c.listAttr(shader, keyable=True) or []
    except Exception:
        pass
    return {
        "shader": shader,
        "type": c.nodeType(shader) if c.objExists(shader) else "",
        "logical_to_attr": resolved,
        "keyable_sample": keyables[:40],
    }


@tool(
    name="create_material",
    description=(
        "创建材质并返回实际节点名：data.shader + data.shading_group。"
        "SG 默认命名为 {name}SG（可用 sg_name 覆盖）。"
        "roughness→standardSurface.specularRoughness；metalness→metalness；"
        "color→baseColor 或 color。随后用返回的 shader/shading_group 调用 assign_material。"
    ),
    parameters=obj_schema(
        {
            "name": {"type": "string", "default": "mat_new"},
            "sg_name": {
                "type": "string",
                "default": "",
                "description": "可选 shadingEngine 名；空则用 {name}SG",
            },
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
    sg_name: str = "",
    shader_type: str = "standardSurface",
    color: Optional[List[float]] = None,
    metalness: float = 0.0,
    roughness: float = 0.5,
) -> ToolResult:
    c = _cmds()
    color = color or [0.5, 0.5, 0.5]
    requested_name = (name or "mat_new").strip() or "mat_new"
    requested_type = shader_type

    available = set(c.listNodeTypes("shader") or [])
    if shader_type not in available:
        if "standardSurface" in available:
            shader_type = "standardSurface"
        else:
            shader_type = "lambert"

    shader = c.shadingNode(shader_type, asShader=True, name=requested_name)
    # Prefer requested sg name; fall back to actual shader short name + SG
    desired_sg = (sg_name or "").strip() or f"{requested_name}SG"
    if c.objExists(desired_sg):
        desired_sg = f"{shader}SG"
    sg = c.sets(renderable=True, noSurfaceShader=True, empty=True, name=desired_sg)
    c.connectAttr(f"{shader}.outColor", f"{sg}.surfaceShader", force=True)

    applied: Dict[str, str] = {}
    color_attr = _resolve_attr(shader, "color")
    if color_attr and color_attr != "outColor":
        if _set_color3(shader, color_attr, color):
            applied["color"] = color_attr

    metal_attr = _resolve_attr(shader, "metalness")
    if metal_attr:
        try:
            c.setAttr(f"{shader}.{metal_attr}", float(metalness))
            applied["metalness"] = metal_attr
        except Exception:
            pass

    rough_attr = _resolve_attr(shader, "roughness")
    if rough_attr:
        try:
            c.setAttr(f"{shader}.{rough_attr}", float(roughness))
            applied["roughness"] = rough_attr
        except Exception:
            pass

    data = {
        "shader": shader,
        "shading_group": sg,
        "sg": sg,  # alias for convenience
        "type": shader_type,
        "requested_name": requested_name,
        "requested_type": requested_type,
        "type_fallback": requested_type != shader_type,
        "attrs_applied": applied,
        "attr_map_reference": _CREATE_MATERIAL_MAP.get(shader_type, {}),
    }
    msg = (
        f"材质已创建: shader={shader}, shading_group={sg}, type={shader_type}"
        f"（assign_material 可传 shader 或 shading_group）"
    )
    return ToolResult(ok=True, data=data, message=msg)


@tool(
    name="assign_material",
    description=(
        "将材质指定给对象。参数 shader 可传材质节点名或 shadingEngine 名"
        "（优先用 create_material 返回的 shader / shading_group）；"
        "找不到时返回 candidates 候选列表。"
    ),
    parameters=obj_schema(
        {
            "shader": {
                "type": "string",
                "description": "材质节点名或 shadingEngine 名（如 mat_Glass / mat_GlassSG）",
            },
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
    sg, resolved_shader, meta = _resolve_shading_group(shader)
    if not sg:
        err = meta.get("error") or f"材质不存在: {shader}"
        return ToolResult(ok=False, error=err, data=meta)
    c.sets(targets, edit=True, forceElement=sg)
    return ToolResult(
        ok=True,
        data={
            "sg": sg,
            "shading_group": sg,
            "shader": resolved_shader,
            "objects": targets,
            "resolved_from": shader,
        },
        message=f"材质已指定: shader={resolved_shader}, shading_group={sg}, objects={len(targets)}",
    )


@tool(
    name="describe_material_attrs",
    description=(
        "查询材质逻辑属性→实际 Maya 属性名映射（color/metalness/roughness 等）。"
        "可指定已有 shader，或只查 shader_type 的参考表（不依赖场景节点）。"
    ),
    parameters=obj_schema(
        {
            "shader": {
                "type": "string",
                "default": "",
                "description": "已有材质节点名；空则只返回类型参考表",
            },
            "shader_type": {
                "type": "string",
                "default": "standardSurface",
                "description": "无 shader 时查询该类型的参考映射",
            },
        }
    ),
    category="materials",
)
def describe_material_attrs(shader: str = "", shader_type: str = "standardSurface") -> ToolResult:
    c = _cmds()
    if shader:
        if not c.objExists(shader):
            mats = c.ls(materials=True) or []
            return ToolResult(
                ok=False,
                error=f"材质不存在: {shader}",
                data={"candidates": _name_candidates(shader, mats)},
            )
        probe = _probe_shader_attrs(shader)
        sgs = c.listConnections(shader, type="shadingEngine") or []
        probe["shading_groups"] = sgs
        probe["create_material_reference"] = _CREATE_MATERIAL_MAP.get(
            probe.get("type") or "", {}
        )
        return ToolResult(
            ok=True,
            data=probe,
            message=(
                f"{shader}({probe.get('type')}): "
                + ", ".join(
                    f"{k}→{v}" for k, v in (probe.get("logical_to_attr") or {}).items() if v
                )
            ),
        )

    st = shader_type or "standardSurface"
    return ToolResult(
        ok=True,
        data={
            "shader_type": st,
            "create_material_reference": _CREATE_MATERIAL_MAP.get(st, {}),
            "logical_candidates": _ATTR_CANDIDATES,
            "note": (
                "create_material 的 roughness 优先写 specularRoughness；"
                "metalness 写 metalness；color 写 baseColor/color"
            ),
        },
        message=f"参考映射: {st} → {_CREATE_MATERIAL_MAP.get(st, {})}",
    )


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
        mats = c.ls(materials=True) or []
        return ToolResult(
            ok=False,
            error="材质不存在",
            data={"candidates": _name_candidates(shader, mats)},
        )
    file_path = file_path.replace("\\", "/")
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
        attribute = _resolve_attr(shader, "color") or "color"
    c.connectAttr(f"{file_node}.outColor", f"{shader}.{attribute}", force=True)
    return ToolResult(
        ok=True,
        data={"file_node": file_node, "attribute": attribute},
        message=f"纹理已连接到 {shader}.{attribute}",
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
        data.append({"shader": m, "type": c.nodeType(m), "sg": sgs, "shading_group": sgs})
    return ToolResult(ok=True, data=data, message=f"共 {len(data)} 个材质")

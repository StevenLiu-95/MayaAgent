"""Export / import tools for game pipelines."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.tools._maya import cmds as _cmds, in_maya
from maya_agent.utils.maya_compat import ensure_plugin


def _norm_path(path: str) -> str:
    return (path or "").replace("\\", "/")


def _file_meta(path: str) -> Dict[str, Any]:
    meta: Dict[str, Any] = {"path": _norm_path(path)}
    try:
        if path and os.path.isfile(path):
            meta["size_bytes"] = os.path.getsize(path)
            meta["exists"] = True
        else:
            meta["exists"] = False
    except Exception:
        meta["exists"] = False
    return meta

@tool(
    name="export_fbx",
    description="导出 FBX（Unity/Unreal 常用）。可仅导出选择。",
    parameters=obj_schema(
        {
            "file_path": {"type": "string"},
            "selection_only": {"type": "boolean", "default": True},
            "export_animation": {"type": "boolean", "default": False},
            "export_skins": {"type": "boolean", "default": True},
            "embed_textures": {"type": "boolean", "default": False},
            "generate_lod": {"type": "boolean", "default": False},
            "up_axis": {"type": "string", "enum": ["y", "z"], "default": "y"},
        },
        required=["file_path"],
    ),
    category="export",
)
def export_fbx(
    file_path: str,
    selection_only: bool = True,
    export_animation: bool = False,
    export_skins: bool = True,
    embed_textures: bool = False,
    generate_lod: bool = False,
    up_axis: str = "y",
) -> ToolResult:
    c = _cmds()
    if not ensure_plugin("fbxmaya"):
        return ToolResult(ok=False, error="无法加载 fbxmaya 插件")
    from maya_agent.utils.maya_compat import mel

    m = mel()
    m.eval(f'FBXExportUpAxis "{up_axis}";')
    m.eval(f"FBXExportSkins -v {'true' if export_skins else 'false'};")
    m.eval(f"FBXExportAnimationOnly -v {'true' if export_animation and not export_skins else 'false'};")
    m.eval(f"FBXExportBakeComplexAnimation -v {'true' if export_animation else 'false'};")
    m.eval(f"FBXExportEmbeddedTextures -v {'true' if embed_textures else 'false'};")
    m.eval("FBXExportSmoothingGroups -v true;")
    m.eval("FBXExportSmoothMesh -v false;")
    m.eval("FBXExportTangents -v true;")
    path = _norm_path(file_path)
    if not path.lower().endswith(".fbx"):
        path += ".fbx"
    if selection_only:
        sel = c.ls(selection=True) or []
        if not sel:
            return ToolResult(ok=False, error="未选择对象")
        m.eval(f'FBXExport -f "{path}" -s;')
    else:
        m.eval(f'FBXExport -f "{path}";')
    _ = generate_lod  # reserved for future LOD chain export
    return ToolResult(ok=True, data=_file_meta(path), message=f"FBX 已导出: {path}")

@tool(
    name="import_fbx",
    description="导入 FBX 文件。",
    parameters=obj_schema(
        {
            "file_path": {"type": "string"},
            "namespace": {"type": "string", "default": ""},
        },
        required=["file_path"],
    ),
    category="export",
)
def import_fbx(file_path: str, namespace: str = "") -> ToolResult:
    c = _cmds()
    if not ensure_plugin("fbxmaya"):
        return ToolResult(ok=False, error="无法加载 fbxmaya 插件")
    path = _norm_path(file_path)
    kwargs = {"i": True, "type": "FBX", "ignoreVersion": True, "mergeNamespacesOnClash": False, "options": "fbx", "rpr": "fbx"}
    if namespace:
        kwargs["namespace"] = namespace
    nodes = c.file(path, **kwargs)
    return ToolResult(ok=True, data=nodes, message=f"已导入 FBX: {path}")

@tool(
    name="export_obj",
    description="导出 OBJ。",
    parameters=obj_schema(
        {
            "file_path": {"type": "string"},
            "selection_only": {"type": "boolean", "default": True},
        },
        required=["file_path"],
    ),
    category="export",
)
def export_obj(file_path: str, selection_only: bool = True) -> ToolResult:
    c = _cmds()
    ensure_plugin("objExport")
    path = _norm_path(file_path)
    if not path.lower().endswith(".obj"):
        path += ".obj"
    if selection_only:
        c.file(path, force=True, options="groups=1;ptgroups=1;materials=1;smoothing=1;normals=1", typ="OBJexport", exportSelected=True)
    else:
        c.file(path, force=True, options="groups=1;ptgroups=1;materials=1;smoothing=1;normals=1", typ="OBJexport", exportAll=True)
    return ToolResult(ok=True, data=_file_meta(path), message=f"OBJ 已导出: {path}")

@tool(
    name="export_usd",
    description="导出 USD/USDA/USDC（需 mayaUsd 插件）。",
    parameters=obj_schema(
        {
            "file_path": {"type": "string"},
            "selection_only": {"type": "boolean", "default": True},
        },
        required=["file_path"],
    ),
    category="export",
)
def export_usd(file_path: str, selection_only: bool = True) -> ToolResult:
    c = _cmds()
    if not ensure_plugin("mayaUsdPlugin") and not ensure_plugin("pxrUsd"):
        return ToolResult(ok=False, error="未找到 Maya USD 插件")
    path = _norm_path(file_path)
    try:
        if selection_only:
            c.mayaUSDExport(file=path, selection=True)
        else:
            c.mayaUSDExport(file=path)
    except Exception:
        # older API
        c.file(path, force=True, type="USD Export", exportSelected=selection_only, exportAll=not selection_only)
    return ToolResult(ok=True, data=_file_meta(path), message=f"USD 已导出: {path}")

@tool(
    name="export_abc",
    description="导出 Alembic 缓存。",
    parameters=obj_schema(
        {
            "file_path": {"type": "string"},
            "roots": {"type": "array", "items": {"type": "string"}, "default": []},
            "start": {"type": "number"},
            "end": {"type": "number"},
        },
        required=["file_path"],
    ),
    category="export",
)
def export_abc(
    file_path: str,
    roots: Optional[List[str]] = None,
    start: Optional[float] = None,
    end: Optional[float] = None,
) -> ToolResult:
    c = _cmds()
    if not ensure_plugin("AbcExport"):
        return ToolResult(ok=False, error="无法加载 AbcExport")
    roots = roots or (c.ls(selection=True, long=True) or [])
    if not roots:
        return ToolResult(ok=False, error="需要导出根对象")
    if start is None:
        start = c.playbackOptions(query=True, minTime=True)
    if end is None:
        end = c.playbackOptions(query=True, maxTime=True)
    path = _norm_path(file_path)
    if not path.lower().endswith(".abc"):
        path += ".abc"
    root_args = " ".join([f"-root {r}" for r in roots])
    job = f'-frameRange {start} {end} -uvWrite -worldSpace {root_args} -file "{path}"'
    c.AbcExport(j=job)
    return ToolResult(ok=True, data=_file_meta(path), message=f"Alembic 已导出: {path}")


@tool(
    name="save_scene",
    description="保存当前 Maya 场景。返回路径、格式、文件大小、是否首次命名保存。",
    parameters=obj_schema(
        {
            "file_path": {
                "type": "string",
                "default": "",
                "description": "空则保存到当前文件",
            },
            "as_ascii": {"type": "boolean", "default": False},
        }
    ),
    category="export",
)
def save_scene(file_path: str = "", as_ascii: bool = False) -> ToolResult:
    c = _cmds()
    typ = "mayaAscii" if as_ascii else "mayaBinary"
    prev_name = _norm_path(c.file(query=True, sceneName=True) or "")
    first_save = False
    if file_path:
        path = _norm_path(file_path)
        first_save = not bool(prev_name) or prev_name != path
        c.file(rename=path)
        out = c.file(save=True, type=typ)
    else:
        if not prev_name:
            return ToolResult(ok=False, error="场景尚未命名，请提供 file_path")
        out = c.file(save=True, type=typ)
    out_path = _norm_path(out if isinstance(out, str) else (c.file(query=True, sceneName=True) or ""))
    meta = _file_meta(out_path)
    meta.update(
        {
            "type": typ,
            "as_ascii": bool(as_ascii),
            "first_named_save": first_save,
            "previous_path": prev_name or None,
        }
    )
    size_note = ""
    if meta.get("size_bytes") is not None:
        kb = meta["size_bytes"] / 1024.0
        size_note = f"，{kb:.1f} KB" if kb < 1024 else f"，{kb/1024.0:.2f} MB"
    fmt = "ASCII (.ma)" if as_ascii else "Binary (.mb)"
    return ToolResult(
        ok=True,
        data=meta,
        message=f"场景已保存: {out_path}（{fmt}{size_note}）",
    )


@tool(
    name="open_scene",
    description="打开 Maya 场景文件。",
    parameters=obj_schema(
        {"file_path": {"type": "string"}, "force": {"type": "boolean", "default": False}},
        required=["file_path"],
    ),
    category="export",
    destructive=True,
)
def open_scene(file_path: str, force: bool = False) -> ToolResult:
    c = _cmds()
    path = _norm_path(file_path)
    c.file(path, open=True, force=force)
    return ToolResult(ok=True, data={"path": path}, message=f"已打开: {path}")
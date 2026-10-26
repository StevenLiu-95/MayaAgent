"""UV mapping tools — cut/sew, unwrap, layout, density, quality, game pipeline."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from maya_agent.llm.image_codec import attachment_from_raw_file
from maya_agent.tools._maya import cmds as _cmds
from maya_agent.tools._mesh import short_name
from maya_agent.tools._uv import (
    CUT_MODES,
    capture_uv_snapshot,
    check_quality,
    cleanup_for_uv,
    collect_cut_edges,
    current_texel_density,
    face_count,
    layout_mesh,
    map_cut_edges,
    map_sew_edges,
    mesh_topology_report,
    optimize_mesh,
    project_uv,
    resolve_cut_mode_auto,
    resolve_mesh,
    set_texel_density_on_mesh,
    shell_summaries,
    unfold_mesh,
    uv_coord_count,
    uv_shell_count,
)
from maya_agent.tools.registry import ToolResult, obj_schema, tool

_CUT_MODE_ENUM = list(CUT_MODES)
_EDGE_SELECT_MODES = ["hard", "angle", "material", "border", "selection", "indices"]


def _mesh_or_fail(name: str = "") -> ToolResult:
    tf, shape, err = resolve_mesh(name)
    if err or not tf:
        return ToolResult(ok=False, error=err or "无网格")
    return ToolResult(ok=True, data={"transform": tf, "shape": shape})


@tool(
    name="cut_uv_edges",
    description=(
        "沿指定边切开 UV（polyMapCut）。精确拆分必用。"
        "mode=hard|angle|material|border|selection|indices；"
        "硬表面常用 hard/angle，材质分岛用 material，手动缝用 selection/indices。"
        "快速一键请用 prepare_game_uv。"
    ),
    parameters=obj_schema(
        {
            "name": {"type": "string", "default": "", "description": "网格；空则当前选择"},
            "mode": {
                "type": "string",
                "enum": _EDGE_SELECT_MODES,
                "default": "hard",
            },
            "angle_degrees": {
                "type": "number",
                "default": 45,
                "description": "mode=angle 时邻面法线夹角阈值（度）",
            },
            "indices": {
                "type": "array",
                "items": {"type": ["integer", "string"]},
                "default": [],
                "description": "边索引；mode=indices 时必填",
            },
        }
    ),
    category="uv",
)
def cut_uv_edges(
    name: str = "",
    mode: str = "hard",
    angle_degrees: float = 45.0,
    indices: Optional[List[Any]] = None,
) -> ToolResult:
    picked = _mesh_or_fail(name)
    if not picked.ok:
        return picked
    tf = picked.data["transform"]
    edge_ids, err = collect_cut_edges(
        tf, mode=mode, angle_degrees=angle_degrees, indices=indices
    )
    if err:
        return ToolResult(ok=False, error=err)
    if not edge_ids:
        return ToolResult(
            ok=True,
            data={"mesh": short_name(tf), "cut": 0, "mode": mode},
            message=f"未找到可切边（mode={mode}）",
        )
    try:
        info = map_cut_edges(tf, edge_ids)
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
    info["mesh"] = short_name(tf)
    info["mode"] = mode
    return ToolResult(
        ok=True,
        data=info,
        message=(
            f"已切开 {info['cut']} 条边（{mode}）；"
            f"shells {info['shells_before']}→{info['shells_after']}"
        ),
    )


@tool(
    name="sew_uv_edges",
    description=(
        "缝合 UV 边（polyMapSew / polyMapSewMove）。"
        "mode 同 cut_uv_edges；move=true 时合并 UV 位置。"
        "用于合并过度切开的壳或修复接缝。"
    ),
    parameters=obj_schema(
        {
            "name": {"type": "string", "default": ""},
            "mode": {
                "type": "string",
                "enum": _EDGE_SELECT_MODES,
                "default": "selection",
            },
            "angle_degrees": {"type": "number", "default": 45},
            "indices": {
                "type": "array",
                "items": {"type": ["integer", "string"]},
                "default": [],
            },
            "move": {
                "type": "boolean",
                "default": True,
                "description": "True=Sew+Move 合并位置；False=仅拓扑缝合",
            },
        }
    ),
    category="uv",
)
def sew_uv_edges(
    name: str = "",
    mode: str = "selection",
    angle_degrees: float = 45.0,
    indices: Optional[List[Any]] = None,
    move: bool = True,
) -> ToolResult:
    picked = _mesh_or_fail(name)
    if not picked.ok:
        return picked
    tf = picked.data["transform"]
    edge_ids, err = collect_cut_edges(
        tf, mode=mode, angle_degrees=angle_degrees, indices=indices
    )
    if err:
        return ToolResult(ok=False, error=err)
    if not edge_ids:
        return ToolResult(
            ok=True,
            data={"mesh": short_name(tf), "sewn": 0, "mode": mode},
            message=f"未找到可缝边（mode={mode}）",
        )
    try:
        info = map_sew_edges(tf, edge_ids, move=move)
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
    info["mesh"] = short_name(tf)
    info["mode"] = mode
    return ToolResult(
        ok=True,
        data=info,
        message=(
            f"已缝合 {info['sewn']} 条边（move={info.get('move')}）；"
            f"shells {info['shells_before']}→{info['shells_after']}"
        ),
    )


@tool(
    name="get_uv_info",
    description=(
        "查询 UV 壳数量、UV 点数、每壳 bbox/面积采样与是否出 0–1。"
        "决策切缝或 Layout 前先调用；不修改场景。"
    ),
    parameters=obj_schema({"name": {"type": "string", "default": ""}}),
    category="uv",
)
def get_uv_info(name: str = "") -> ToolResult:
    picked = _mesh_or_fail(name)
    if not picked.ok:
        return picked
    tf = picked.data["transform"]
    summary = shell_summaries(tf)
    summary["mesh"] = short_name(tf)
    out01 = sum(1 for s in summary.get("shells") or [] if s.get("out_of_01"))
    return ToolResult(
        ok=True,
        data=summary,
        message=(
            f"{short_name(tf)}: shells={summary.get('shell_count')}, "
            f"uvs={summary.get('uv_coords')}, out_of_01_shells={out01}"
            + ("（shell 列表已截断）" if summary.get("truncated") else "")
        ),
    )


@tool(
    name="auto_unwrap_uv",
    description=(
        "投影展开 UV（automatic/planar/cylindrical/spherical）。"
        "可先按 cut_mode 切缝再展开；optimize/do_layout 控制后续优化与排布。"
        "游戏资产一键流程优先 prepare_game_uv；需精确切缝时先 cut_uv_edges。"
    ),
    parameters=obj_schema(
        {
            "name": {"type": "string", "default": ""},
            "method": {
                "type": "string",
                "enum": ["automatic", "planar", "cylindrical", "spherical"],
                "default": "automatic",
            },
            "cut_mode": {
                "type": "string",
                "enum": _CUT_MODE_ENUM,
                "default": "none",
                "description": "展开前切缝；none=不切",
            },
            "angle_degrees": {"type": "number", "default": 45},
            "projection_axis": {
                "type": "string",
                "default": "y",
                "description": "planar 投影轴：x/y/z",
            },
            "optimize": {"type": "boolean", "default": True},
            "do_layout": {
                "type": "boolean",
                "default": True,
                "description": "展开后是否 Layout 到 0–1",
            },
            "layout_resolution": {"type": "integer", "default": 256},
            "layout_spacing": {"type": "number", "default": 0.006},
        }
    ),
    category="uv",
)
def auto_unwrap_uv(
    name: str = "",
    method: str = "automatic",
    cut_mode: str = "none",
    angle_degrees: float = 45.0,
    projection_axis: str = "y",
    optimize: bool = True,
    do_layout: bool = True,
    layout_resolution: int = 256,
    layout_spacing: float = 0.006,
) -> ToolResult:
    picked = _mesh_or_fail(name)
    if not picked.ok:
        return picked
    tf = picked.data["transform"]
    steps: Dict[str, Any] = {"mesh": short_name(tf)}
    try:
        if cut_mode and cut_mode.lower() not in ("none", "skip", ""):
            edge_ids, err = collect_cut_edges(
                tf, mode=cut_mode, angle_degrees=angle_degrees
            )
            if err:
                return ToolResult(ok=False, error=err)
            if edge_ids:
                steps["cut"] = map_cut_edges(tf, edge_ids)
            else:
                steps["cut"] = {"cut": 0}

        used = project_uv(tf, method=method, projection_axis=projection_axis)
        steps["project"] = used

        if optimize:
            try:
                steps["unfold"] = unfold_mesh(tf, iterations=2000)
            except Exception as e:
                steps["unfold_error"] = str(e)
            try:
                steps["optimize"] = optimize_mesh(tf)
            except Exception as e:
                steps["optimize_error"] = str(e)

        if do_layout:
            steps["layout"] = layout_mesh(
                tf,
                resolution=layout_resolution,
                spacing=layout_spacing,
            )
    except Exception as e:
        return ToolResult(ok=False, error=str(e), data=steps)

    steps["shells"] = uv_shell_count(tf)
    steps["uv_coords"] = uv_coord_count(tf)
    return ToolResult(
        ok=True,
        data=steps,
        message=f"UV 已用 {steps.get('project', method)} 展开；shells={steps['shells']}",
    )


@tool(
    name="unfold_uv",
    description=(
        "对已切开的 UV 做 unfold（优先 u3dUnfold，回退 unfold）。"
        "切缝后若岛扭曲，用此工具松弛；不要替代切缝。"
    ),
    parameters=obj_schema(
        {
            "name": {"type": "string", "default": ""},
            "iterations": {"type": "integer", "default": 5000},
            "pin_borders": {"type": "boolean", "default": False},
            "stop_threshold": {"type": "number", "default": 0.001},
        }
    ),
    category="uv",
)
def unfold_uv(
    name: str = "",
    iterations: int = 5000,
    pin_borders: bool = False,
    stop_threshold: float = 0.001,
) -> ToolResult:
    picked = _mesh_or_fail(name)
    if not picked.ok:
        return picked
    tf = picked.data["transform"]
    try:
        info = unfold_mesh(
            tf,
            iterations=iterations,
            pin_borders=pin_borders,
            stop_threshold=stop_threshold,
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
    info["mesh"] = short_name(tf)
    return ToolResult(
        ok=True,
        data=info,
        message=f"unfold 完成（{info['backend']}，iterations={iterations}）",
    )


@tool(
    name="optimize_uv",
    description=(
        "优化 UV 减少拉伸（优先 u3dOptimize，回退 unfold）。"
        "Layout 前或质检发现拉伸时使用。"
    ),
    parameters=obj_schema(
        {
            "name": {"type": "string", "default": ""},
            "iterations": {"type": "integer", "default": 100},
        }
    ),
    category="uv",
)
def optimize_uv(name: str = "", iterations: int = 100) -> ToolResult:
    picked = _mesh_or_fail(name)
    if not picked.ok:
        return picked
    tf = picked.data["transform"]
    try:
        info = optimize_mesh(tf, iterations=iterations)
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
    info["mesh"] = short_name(tf)
    return ToolResult(
        ok=True,
        data=info,
        message=f"optimize 完成（{info['backend']}）",
    )


@tool(
    name="layout_uv",
    description=(
        "排布 UV 岛到 0–1（优先 u3dLayout）。"
        "scale_mode=uniform|fill；rotate 允许旋转壳；udim 如 1002 则整体偏移到对应 tile。"
    ),
    parameters=obj_schema(
        {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "网格列表；空则当前选择",
            },
            "resolution": {"type": "integer", "default": 256},
            "spacing": {"type": "number", "default": 0.006},
            "margin": {"type": "number", "default": 0.01},
            "scale_mode": {
                "type": "string",
                "enum": ["uniform", "fill"],
                "default": "uniform",
            },
            "rotate": {"type": "boolean", "default": True},
            "udim": {
                "type": "integer",
                "default": 1001,
                "description": "目标 UDIM tile（1001=0–1）",
            },
        }
    ),
    category="uv",
)
def layout_uv(
    names: Optional[List[str]] = None,
    resolution: int = 256,
    spacing: float = 0.006,
    margin: float = 0.01,
    scale_mode: str = "uniform",
    rotate: bool = True,
    udim: int = 1001,
) -> ToolResult:
    c = _cmds()
    targets: List[str] = []
    seen = set()

    def _add(node: str) -> Optional[str]:
        tf, _, err = resolve_mesh(node)
        if not tf:
            return err
        if tf not in seen:
            seen.add(tf)
            targets.append(tf)
        return None

    if names:
        for n in names:
            err = _add(n)
            if err and n:
                return ToolResult(ok=False, error=err)
    else:
        sel = c.ls(selection=True, flatten=True) or []
        hosts = []
        for item in sel:
            hosts.append(item.split(".")[0])
        hosts.extend(c.ls(selection=True, type="transform", long=True) or [])
        last_err = "无对象"
        for h in hosts:
            err = _add(h)
            if err:
                last_err = err
        if not targets:
            return ToolResult(ok=False, error=last_err)

    results = []
    for t in targets:
        try:
            info = layout_mesh(
                t,
                resolution=resolution,
                spacing=spacing,
                margin=margin,
                scale_mode=scale_mode,
                rotate=rotate,
                udim=udim,
            )
            info["mesh"] = short_name(t)
            results.append(info)
        except Exception as e:
            return ToolResult(ok=False, error=f"{short_name(t)}: {e}", data=results)
    return ToolResult(
        ok=True,
        data=results,
        message=f"UV Layout 完成（{len(results)} 个物体，udim={udim}）",
    )


@tool(
    name="set_texel_density",
    description=(
        "按目标 texel 密度（px/cm）或参考网格缩放全部 UV。"
        "游戏资产统一密度时使用；会整体缩放，不单独重排岛（可再 layout_uv）。"
    ),
    parameters=obj_schema(
        {
            "name": {"type": "string", "default": ""},
            "target_px_per_cm": {
                "type": "number",
                "default": 10.24,
                "description": "目标密度；有 reference_mesh 时忽略",
            },
            "texture_size": {"type": "integer", "default": 1024},
            "reference_mesh": {
                "type": "string",
                "default": "",
                "description": "匹配此网格的当前密度",
            },
        }
    ),
    category="uv",
)
def set_texel_density(
    name: str = "",
    target_px_per_cm: float = 10.24,
    texture_size: int = 1024,
    reference_mesh: str = "",
) -> ToolResult:
    picked = _mesh_or_fail(name)
    if not picked.ok:
        return picked
    tf = picked.data["transform"]
    try:
        info = set_texel_density_on_mesh(
            tf,
            target_px_per_cm=target_px_per_cm,
            texture_size=texture_size,
            reference_mesh=reference_mesh,
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
    return ToolResult(
        ok=True,
        data=info,
        message=(
            f"texel density {info['density_before']:.3f}→{info['density_after']:.3f} "
            f"px/cm（scale={info['scale']:.4f}）"
        ),
    )


@tool(
    name="check_uv_quality",
    description=(
        "检测 UV 质量：疑似重叠、翻转面、零面积、出 0–1、shell 数。"
        "展开/Layout 后应调用；根据 issues 决定是否补切或重排。"
    ),
    parameters=obj_schema(
        {
            "name": {"type": "string", "default": ""},
            "max_faces": {
                "type": "integer",
                "default": 12000,
                "description": "采样面数上限（大网格自动截断）",
            },
        }
    ),
    category="uv",
)
def check_uv_quality(name: str = "", max_faces: int = 12000) -> ToolResult:
    picked = _mesh_or_fail(name)
    if not picked.ok:
        return picked
    tf = picked.data["transform"]
    data = check_quality(tf, max_faces=max_faces)
    # Also attach density snapshot
    try:
        data["texel_density_1024"] = current_texel_density(tf, 1024)
    except Exception:
        pass
    issues = data.get("issues") or []
    msg = (
        f"UV 质检 {'通过' if data.get('ok') else '有问题'}："
        f"shells={data.get('shells')}, "
        + ("；".join(issues) if issues else "无显著问题")
    )
    return ToolResult(ok=True, data=data, message=msg)


@tool(
    name="check_uv_overlaps",
    description=(
        "兼容旧名：转发到 check_uv_quality（真实重叠/翻转检测）。"
        "新对话请直接用 check_uv_quality。"
    ),
    parameters=obj_schema({"name": {"type": "string", "default": ""}}),
    category="uv",
)
def check_uv_overlaps(name: str = "") -> ToolResult:
    return check_uv_quality(name=name)


@tool(
    name="preflight_uv",
    description=(
        "UV 预检：非流形边/点、shell/面数；apply_cleanup=true 时焊点+polyCleanup+删历史。"
        "展开前若怀疑网格脏，先调本工具；一键流程 prepare_game_uv 默认已含清理。"
    ),
    parameters=obj_schema(
        {
            "name": {"type": "string", "default": ""},
            "apply_cleanup": {"type": "boolean", "default": False},
            "merge_threshold": {"type": "number", "default": 0.001},
        }
    ),
    category="uv",
)
def preflight_uv(
    name: str = "",
    apply_cleanup: bool = False,
    merge_threshold: float = 0.001,
) -> ToolResult:
    picked = _mesh_or_fail(name)
    if not picked.ok:
        return picked
    tf = picked.data["transform"]
    report = mesh_topology_report(tf)
    cleanup = None
    if apply_cleanup:
        cleanup = cleanup_for_uv(tf, merge_threshold=merge_threshold)
        report = cleanup.get("after") or mesh_topology_report(tf)
    data: Dict[str, Any] = {"preflight": report}
    if cleanup:
        data["cleanup"] = cleanup
    needs = report.get("needs_cleanup")
    msg = (
        f"UV 预检 {short_name(tf)}：nm_v={report.get('nonmanifold_vertices')} "
        f"nm_e={report.get('nonmanifold_edges')} shells={report.get('shells')} "
        f"faces={report.get('faces')}"
        + ("；已清理" if cleanup else ("；建议清理" if needs else "；拓扑正常"))
    )
    return ToolResult(ok=True, data=data, message=msg)


@tool(
    name="prepare_game_uv",
    description=(
        "游戏 UV 一键：预检清理→切缝→投影→unfold/optimize→Layout（含非流形重试）→质检。"
        "默认 cut_mode=auto（适量硬边则 hard，否则 none，避免大网格切碎）；"
        "也可 hard/angle/material/none。精修缝线用 cut_uv_edges/sew_uv_edges；看图用 capture_uv_layout。"
    ),
    parameters=obj_schema(
        {
            "name": {"type": "string", "default": ""},
            "cut_mode": {
                "type": "string",
                "enum": _CUT_MODE_ENUM,
                "default": "auto",
            },
            "angle_degrees": {"type": "number", "default": 45},
            "method": {
                "type": "string",
                "enum": ["automatic", "planar", "cylindrical", "spherical"],
                "default": "automatic",
            },
            "projection_axis": {"type": "string", "default": "y"},
            "layout_resolution": {"type": "integer", "default": 512},
            "layout_spacing": {"type": "number", "default": 0.006},
            "layout_margin": {"type": "number", "default": 0.01},
            "scale_mode": {
                "type": "string",
                "enum": ["uniform", "fill"],
                "default": "uniform",
            },
            "udim": {"type": "integer", "default": 1001},
            "skip_cleanup": {"type": "boolean", "default": False},
            "skip_quality": {"type": "boolean", "default": False},
        }
    ),
    category="uv",
)
def prepare_game_uv(
    name: str = "",
    cut_mode: str = "auto",
    angle_degrees: float = 45.0,
    method: str = "automatic",
    projection_axis: str = "y",
    layout_resolution: int = 512,
    layout_spacing: float = 0.006,
    layout_margin: float = 0.01,
    scale_mode: str = "uniform",
    udim: int = 1001,
    skip_cleanup: bool = False,
    skip_quality: bool = False,
) -> ToolResult:
    picked = _mesh_or_fail(name)
    if not picked.ok:
        return picked
    tf = picked.data["transform"]
    steps: Dict[str, Any] = {"mesh": short_name(tf)}

    try:
        # 0) Preflight / cleanup
        before = mesh_topology_report(tf)
        steps["preflight"] = {"before": before}
        if not skip_cleanup:
            steps["preflight"]["cleanup"] = cleanup_for_uv(tf)
            steps["preflight"]["after"] = steps["preflight"]["cleanup"].get("after")

        # Resolve cut mode
        mode_in = (cut_mode or "auto").lower()
        mode_resolved = mode_in
        cut_meta: Dict[str, Any] = {}
        if mode_in in ("auto",):
            mode_resolved, cut_meta = resolve_cut_mode_auto(tf)

        # 1) Cut
        if mode_resolved not in ("none", "skip", ""):
            edge_ids, err = collect_cut_edges(
                tf, mode=mode_resolved, angle_degrees=angle_degrees
            )
            if err:
                return ToolResult(ok=False, error=err, data=steps)
            steps["cut"] = map_cut_edges(tf, edge_ids) if edge_ids else {"cut": 0}
            steps["cut"]["mode"] = mode_resolved
            steps["cut"]["mode_requested"] = mode_in
            steps["cut"]["mode_resolved"] = mode_resolved
            if cut_meta:
                steps["cut"]["auto_meta"] = cut_meta
        else:
            steps["cut"] = {
                "cut": 0,
                "mode": "none",
                "mode_requested": mode_in,
                "mode_resolved": "none",
                "auto_meta": cut_meta,
            }

        # 2) Project
        steps["project"] = project_uv(tf, method=method, projection_axis=projection_axis)

        # 3) Unfold + optimize
        try:
            steps["unfold"] = unfold_mesh(tf, iterations=3000)
        except Exception as e:
            steps["unfold_error"] = str(e)
        try:
            steps["optimize"] = optimize_mesh(tf, iterations=80)
        except Exception as e:
            steps["optimize_error"] = str(e)

        # 4) Layout (auto bump resolution for dense meshes)
        res = int(layout_resolution) if layout_resolution else 512
        try:
            if face_count(tf) > 10000:
                res = max(res, 512)
        except Exception:
            pass
        steps["layout"] = layout_mesh(
            tf,
            resolution=res,
            spacing=layout_spacing,
            margin=layout_margin,
            scale_mode=scale_mode,
            rotate=True,
            udim=udim,
        )

        # 5) Quality
        if not skip_quality:
            steps["quality"] = check_quality(tf)
            try:
                steps["texel_density_1024"] = current_texel_density(tf, 1024)
            except Exception:
                pass
    except Exception as e:
        return ToolResult(ok=False, error=str(e), data=steps)

    steps["shells"] = uv_shell_count(tf)
    q = steps.get("quality") or {}
    ok_q = q.get("ok", True)
    issues = q.get("issues") or []
    cut_n = (steps.get("cut") or {}).get("cut", 0)
    mode_r = (steps.get("cut") or {}).get("mode_resolved", cut_mode)
    layout_backend = (steps.get("layout") or {}).get("backend", "")
    msg = (
        f"游戏 UV 完成：cut={mode_r}/{cut_n}，project={steps.get('project')}，"
        f"layout={layout_backend}，shells={steps['shells']}，"
        f"质检={'通过' if ok_q else '有问题'}"
    )
    if issues:
        msg += " — " + "；".join(issues[:4])
    return ToolResult(ok=True, data=steps, message=msg)


@tool(
    name="capture_uv_layout",
    description=(
        "截取/导出 UV 布局线框图（非模型视口）。"
        "用于视觉确认岛排布、重叠、出界；展开或 Layout 后应调用。"
        "优先 Maya uvSnapshot，失败则 matplotlib 回退；返回附带图像供视觉模型分析。"
        "不要用 capture_viewport 代替本工具看 UV。"
    ),
    parameters=obj_schema(
        {
            "name": {
                "type": "string",
                "default": "",
                "description": "网格；空则当前选择",
            },
            "resolution": {
                "type": "integer",
                "default": 1024,
                "description": "输出边长像素（64–4096）",
            },
            "entire_uv_range": {
                "type": "boolean",
                "default": False,
                "description": "True=框住全部 UV；False=默认 0–1（可配合 u/v_min/max）",
            },
            "anti_aliased": {"type": "boolean", "default": True},
            "u_min": {"type": "number", "default": 0},
            "u_max": {"type": "number", "default": 1},
            "v_min": {"type": "number", "default": 0},
            "v_max": {"type": "number", "default": 1},
            "uv_set": {
                "type": "string",
                "default": "",
                "description": "UV set 名；空则当前 set",
            },
        }
    ),
    category="uv",
    requires_vision=True,
)
def capture_uv_layout(
    name: str = "",
    resolution: int = 1024,
    entire_uv_range: bool = False,
    anti_aliased: bool = True,
    u_min: float = 0.0,
    u_max: float = 1.0,
    v_min: float = 0.0,
    v_max: float = 1.0,
    uv_set: str = "",
) -> ToolResult:
    picked = _mesh_or_fail(name)
    if not picked.ok:
        return picked
    tf = picked.data["transform"]
    try:
        info = capture_uv_snapshot(
            tf,
            resolution=resolution,
            entire_uv_range=entire_uv_range,
            anti_aliased=anti_aliased,
            file_format="jpg",
            u_min=u_min,
            u_max=u_max,
            v_min=v_min,
            v_max=v_max,
            uv_set=uv_set,
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e))

    path = info.get("path") or ""
    try:
        attachment = attachment_from_raw_file(path)
        attachment.name = attachment.name or f"uv_{info.get('mesh', 'layout')}"
    except Exception as e:
        return ToolResult(
            ok=False,
            error=f"UV 图已写出但编码失败: {e}",
            data=info,
        )

    return ToolResult(
        ok=True,
        data=info,
        message=(
            f"UV 布局图已生成（{info.get('method')}，{info.get('resolution')}px，"
            f"shells={info.get('shells')}）：{path}"
        ),
        images=[attachment],
    )

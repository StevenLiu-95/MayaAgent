"""Shared UV helpers for Maya Agent UV tools (Maya 2020–2026)."""

from __future__ import annotations

import math
import os
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from maya_agent.tools._maya import cmds as _cmds
from maya_agent.tools._mesh import (
    EDGE,
    border_edges,
    component_count,
    component_strings,
    flatten_components,
    hard_edges,
    indices_of,
    primary_mesh,
    remember_selection,
    resolve_components,
    short_name,
    transform_of,
)
from maya_agent.utils.paths import agent_temp_subdir

CUT_MODES = ("hard", "angle", "material", "border", "selection", "indices", "none")
_MAX_SHELL_SAMPLES = 48
_MAX_FACE_QUALITY = 12000
_ANGLE_EDGE_CAP = 25000


def resolve_mesh(name: str = "") -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (transform, shape, error). Uses selection when name empty."""
    c = _cmds()
    if name and name.strip():
        if not c.objExists(name):
            return None, None, f"对象不存在: {name}"
        tf, shape = primary_mesh(name)
        if not tf or not shape:
            return None, None, f"未找到多边形 mesh: {name}"
        return tf, shape, None

    sel = c.ls(selection=True, flatten=True) or []
    for item in sel:
        host = item.split(".")[0]
        tf, shape = primary_mesh(host)
        if tf and shape:
            return tf, shape, None
    objs = c.ls(selection=True, type="transform", long=True) or []
    for obj in objs:
        tf, shape = primary_mesh(obj)
        if tf and shape:
            return tf, shape, None
    return None, None, "请指定网格名，或先选择多边形物体"


def uv_shell_count(mesh: str) -> int:
    c = _cmds()
    try:
        return int(c.polyEvaluate(mesh, uvShell=True) or 0)
    except Exception:
        return 0


def uv_coord_count(mesh: str) -> int:
    c = _cmds()
    try:
        return int(c.polyEvaluate(mesh, uvcoord=True) or 0)
    except Exception:
        return 0


def face_count(mesh: str) -> int:
    return component_count(mesh, "face")


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return float(a[0]) * float(b[0]) + float(a[1]) * float(b[1]) + float(a[2]) * float(b[2])


def _norm(v: Sequence[float]) -> Tuple[float, float, float]:
    x, y, z = float(v[0]), float(v[1]), float(v[2])
    n = math.sqrt(x * x + y * y + z * z)
    if n < 1e-12:
        return (0.0, 0.0, 0.0)
    return (x / n, y / n, z / n)


def _face_normal(mesh: str, face_id: int) -> Optional[Tuple[float, float, float]]:
    c = _cmds()
    try:
        raw = c.polyInfo(f"{mesh}.f[{face_id}]", faceNormals=True) or []
        if not raw:
            return None
        # "FACE_NORMAL 12: 0.0 1.0 0.0"
        text = str(raw[0])
        parts = text.replace(":", " ").split()
        nums = [float(p) for p in parts if _is_float(p)]
        if len(nums) >= 4:
            # face id + xyz
            return _norm(nums[-3:])
        if len(nums) >= 3:
            return _norm(nums[-3:])
    except Exception:
        pass
    return None


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except Exception:
        return False


def _edge_connected_faces(mesh: str, edge_id: int) -> List[int]:
    c = _cmds()
    try:
        faces = c.polyListComponentConversion(f"{mesh}.e[{edge_id}]", toFace=True) or []
        return indices_of(flatten_components(faces))
    except Exception:
        return []


def edges_by_angle(mesh: str, angle_degrees: float = 45.0) -> List[int]:
    """Edges whose adjacent face normals differ by >= angle_degrees."""
    c = _cmds()
    tf = transform_of(mesh)
    n_edges = component_count(tf, EDGE)
    if n_edges <= 0:
        return []
    threshold = max(0.0, min(180.0, float(angle_degrees)))
    cos_thresh = math.cos(math.radians(threshold))
    found: List[int] = []
    # Cap for very dense meshes — sample via polySelectConstraint if too large
    if n_edges > _ANGLE_EDGE_CAP:
        try:
            c.select(f"{tf}.e[*]", replace=True)
            c.polySelectConstraint(mode=3, type=0x8000, angle=True, anglebound=(threshold, 180))
            sel = c.ls(selection=True, flatten=True) or []
            c.polySelectConstraint(disable=True)
            return indices_of(sel)
        except Exception:
            pass

    face_n_cache: Dict[int, Tuple[float, float, float]] = {}
    for i in range(n_edges):
        fids = _edge_connected_faces(tf, i)
        if len(fids) < 2:
            continue
        normals = []
        for fid in fids[:2]:
            if fid not in face_n_cache:
                n = _face_normal(tf, fid)
                if n:
                    face_n_cache[fid] = n
            if fid in face_n_cache:
                normals.append(face_n_cache[fid])
        if len(normals) < 2:
            continue
        d = max(-1.0, min(1.0, _dot(normals[0], normals[1])))
        # angle between normals >= threshold  <=>  dot <= cos(threshold)
        if d <= cos_thresh:
            found.append(i)
    return found


def edges_by_material(mesh: str) -> List[int]:
    """Edges shared by faces assigned to different shading groups."""
    c = _cmds()
    tf = transform_of(mesh)
    shapes = c.listRelatives(tf, shapes=True, type="mesh", fullPath=True) or []
    if not shapes:
        return []
    shape = shapes[0]
    face_sg: Dict[int, str] = {}
    try:
        sgs = c.listConnections(shape, type="shadingEngine") or []
        sgs = list(dict.fromkeys(sgs))
        for sg in sgs:
            members = c.sets(sg, q=True) or []
            for m in flatten_components(members):
                if ".f[" not in m:
                    continue
                host = m.split(".")[0]
                if short_name(host) != short_name(tf) and host != tf and not m.startswith(tf):
                    # allow short-name match
                    if short_name(transform_of(host)) != short_name(tf):
                        continue
                for idx in indices_of([m]):
                    face_sg[idx] = sg
    except Exception:
        return []

    if len(set(face_sg.values())) <= 1:
        return []

    n_edges = component_count(tf, EDGE)
    found: List[int] = []
    for i in range(n_edges):
        fids = _edge_connected_faces(tf, i)
        if len(fids) < 2:
            continue
        sgs = {face_sg.get(f) for f in fids if f in face_sg}
        sgs.discard(None)
        if len(sgs) >= 2:
            found.append(i)
    return found


def collect_cut_edges(
    mesh: str,
    mode: str = "hard",
    angle_degrees: float = 45.0,
    indices: Optional[Sequence[Any]] = None,
) -> Tuple[List[int], Optional[str]]:
    """
    Collect edge indices for UV cut/sew.
    Returns (edge_ids, error).
    """
    mode = (mode or "hard").lower().strip()
    tf = transform_of(mesh)

    if mode in ("none", "skip", ""):
        return [], None

    if mode in ("hard", "hard_edges"):
        return hard_edges(tf), None

    if mode in ("angle", "by_angle"):
        return edges_by_angle(tf, angle_degrees), None

    if mode in ("material", "shader", "shading"):
        return edges_by_material(tf), None

    if mode in ("border", "boundary"):
        return border_edges(tf), None

    if mode in ("selection", "current", "indices", "index"):
        comps, _, err = resolve_components(
            mesh=tf,
            kind=EDGE,
            mode="indices" if indices else "current",
            indices=indices,
        )
        if err and not comps:
            return [], err
        return indices_of(comps), None

    return [], f"未知切缝模式: {mode}（可用: {', '.join(CUT_MODES)}）"


def edge_component_list(mesh: str, edge_ids: Sequence[int]) -> List[str]:
    if not edge_ids:
        return []
    return flatten_components(component_strings(transform_of(mesh), EDGE, edge_ids))


def map_cut_edges(mesh: str, edge_ids: Sequence[int]) -> Dict[str, Any]:
    c = _cmds()
    tf = transform_of(mesh)
    before = uv_shell_count(tf)
    comps = edge_component_list(tf, edge_ids)
    if not comps:
        return {"cut": 0, "shells_before": before, "shells_after": before}
    c.select(comps, replace=True)
    try:
        c.polyMapCut(comps)
    except Exception as e:
        raise RuntimeError(f"polyMapCut 失败: {e}") from e
    after = uv_shell_count(tf)
    return {
        "cut": len(edge_ids),
        "shells_before": before,
        "shells_after": after,
    }


def map_sew_edges(mesh: str, edge_ids: Sequence[int], move: bool = True) -> Dict[str, Any]:
    c = _cmds()
    tf = transform_of(mesh)
    before = uv_shell_count(tf)
    comps = edge_component_list(tf, edge_ids)
    if not comps:
        return {"sewn": 0, "shells_before": before, "shells_after": before, "move": move}
    c.select(comps, replace=True)
    try:
        if move:
            c.polyMapSewMove(comps)
        else:
            c.polyMapSew(comps)
    except Exception as e:
        # Fallback: sew without move
        try:
            c.polyMapSew(comps)
            move = False
        except Exception as e2:
            raise RuntimeError(f"polyMapSew 失败: {e}; fallback: {e2}") from e2
    after = uv_shell_count(tf)
    return {
        "sewn": len(edge_ids),
        "shells_before": before,
        "shells_after": after,
        "move": move,
    }


def project_uv(
    mesh: str,
    method: str = "automatic",
    projection_axis: str = "y",
) -> str:
    """Apply projection. Returns method used."""
    c = _cmds()
    tf = transform_of(mesh)
    method = (method or "automatic").lower()
    axis = (projection_axis or "y").lower().strip().lstrip("+")
    if axis in ("up", "top"):
        axis = "y"
    if axis in ("front",):
        axis = "z"
    if axis in ("right", "side"):
        axis = "x"
    if axis not in ("x", "y", "z"):
        axis = "y"

    if method == "automatic":
        c.polyAutoProjection(
            tf,
            lm=0,
            pb=0,
            ibd=1,
            cm=0,
            l=2,
            sc=1,
            o=1,
            p=6,
            ps=0.2,
            ws=0,
        )
        return "automatic"
    if method == "planar":
        c.polyProjection(f"{tf}.f[*]", type="Planar", md=axis)
        return f"planar:{axis}"
    if method == "cylindrical":
        c.polyProjection(f"{tf}.f[*]", type="Cylindrical")
        return "cylindrical"
    if method == "spherical":
        c.polyProjection(f"{tf}.f[*]", type="Spherical")
        return "spherical"
    raise ValueError(f"未知展开方法: {method}")


def unfold_mesh(
    mesh: str,
    iterations: int = 5000,
    pin_borders: bool = False,
    stop_threshold: float = 0.001,
) -> Dict[str, Any]:
    c = _cmds()
    tf = transform_of(mesh)
    backend = "unfold"
    try:
        # Unfold3D plugin command when available
        c.u3dUnfold(tf, ite=int(iterations), pin=bool(pin_borders), pini=0, bi=pin_borders)
        backend = "u3dUnfold"
    except Exception:
        try:
            c.unfold(
                tf,
                i=int(iterations),
                ss=float(stop_threshold),
                gb=0,
                gmb=0.5,
                pub=0,
                ps=0,
                oa=0,
                us=False,
            )
            backend = "unfold"
        except Exception as e:
            raise RuntimeError(f"unfold 失败: {e}") from e
    return {"backend": backend, "iterations": int(iterations), "pin_borders": pin_borders}


def optimize_mesh(mesh: str, iterations: int = 100) -> Dict[str, Any]:
    c = _cmds()
    tf = transform_of(mesh)
    backend = "u3dOptimize"
    try:
        c.u3dOptimize(tf, ite=int(iterations), power=1, sag=0)
        backend = "u3dOptimize"
    except Exception:
        try:
            c.unfold(tf, i=min(int(iterations) * 20, 5000), ss=0.001, gb=0, gmb=0.5, pub=0, ps=0, oa=0, us=False)
            backend = "unfold"
        except Exception as e:
            raise RuntimeError(f"optimize 失败: {e}") from e
    return {"backend": backend, "iterations": int(iterations)}


def layout_mesh(
    mesh: str,
    resolution: int = 256,
    spacing: float = 0.006,
    margin: float = 0.01,
    scale_mode: str = "uniform",
    rotate: bool = True,
    udim: int = 1001,
) -> Dict[str, Any]:
    c = _cmds()
    tf = transform_of(mesh)
    scale_mode = (scale_mode or "uniform").lower()
    # u3dLayout: scl 1 = preserve ratio (uniform), 2 = fill
    scl = 2 if scale_mode in ("fill", "stretch", "nonuniform") else 1
    backend = "u3dLayout"
    try:
        kwargs: Dict[str, Any] = {
            "res": int(resolution),
            "scl": scl,
            "spc": float(spacing),
            "mar": float(margin),
        }
        # rotate shells when supported
        try:
            c.u3dLayout(tf, box=rotate, **kwargs)
        except TypeError:
            c.u3dLayout(tf, **kwargs)
    except Exception:
        backend = "polyLayoutUV"
        try:
            c.polyLayoutUV(
                tf,
                scale=1 if scl == 1 else 2,
                layout=2,
                percentageSpace=max(0.0, float(spacing) * 100.0),
                rotateOn=bool(rotate),
            )
        except Exception as e:
            raise RuntimeError(f"layout 失败: {e}") from e

    tile = int(udim) if udim else 1001
    offset = udim_offset(tile)
    if offset != (0.0, 0.0):
        try:
            c.polyEditUV(f"{tf}.map[*]", u=offset[0], v=offset[1], relative=True)
        except Exception:
            try:
                c.polyEditUV(f"{tf}.uv[*]", u=offset[0], v=offset[1], relative=True)
            except Exception:
                pass

    return {
        "backend": backend,
        "resolution": int(resolution),
        "spacing": float(spacing),
        "margin": float(margin),
        "scale_mode": scale_mode,
        "rotate": bool(rotate),
        "udim": tile,
        "offset_uv": list(offset),
    }


def udim_offset(udim: int) -> Tuple[float, float]:
    """UDIM 1001 → (0,0); 1002 → (1,0); 1011 → (0,1)."""
    t = int(udim)
    if t < 1001:
        t = 1001
    idx = t - 1001
    return (float(idx % 10), float(idx // 10))


def _get_mesh_fn(shape: str):
    from maya.api import OpenMaya as om

    sel = om.MSelectionList()
    sel.add(shape)
    dag = sel.getDagPath(0)
    dag.extendToShape()
    return om.MFnMesh(dag), dag


def shell_summaries(mesh: str, max_shells: int = _MAX_SHELL_SAMPLES) -> Dict[str, Any]:
    """Summarize UV shells via OpenMaya (bbox + approximate area)."""
    c = _cmds()
    tf = transform_of(mesh)
    shapes = c.listRelatives(tf, shapes=True, type="mesh", fullPath=True) or []
    if not shapes:
        return {"shells": [], "shell_count": 0, "truncated": False}
    shape = shapes[0]
    shell_count = uv_shell_count(tf)
    out: List[Dict[str, Any]] = []
    truncated = False
    try:
        fn, _ = _get_mesh_fn(shape)
        # UV shell ids per face-vertex via getUvShellsIds
        u_arr, v_arr = fn.getUVs()
        shells_ids, nb_shells = fn.getUvShellsIds()
        shell_count = int(nb_shells)
        # Aggregate per shell
        shells: Dict[int, Dict[str, float]] = {}
        for uvid, sid in enumerate(shells_ids):
            sid = int(sid)
            if uvid >= len(u_arr):
                break
            u, v = float(u_arr[uvid]), float(v_arr[uvid])
            bucket = shells.setdefault(
                sid,
                {
                    "u_min": u,
                    "u_max": u,
                    "v_min": v,
                    "v_max": v,
                    "uv_count": 0,
                },
            )
            bucket["u_min"] = min(bucket["u_min"], u)
            bucket["u_max"] = max(bucket["u_max"], u)
            bucket["v_min"] = min(bucket["v_min"], v)
            bucket["v_max"] = max(bucket["v_max"], v)
            bucket["uv_count"] += 1

        items = sorted(shells.items(), key=lambda kv: kv[0])
        if len(items) > max_shells:
            truncated = True
            items = items[:max_shells]
        for sid, b in items:
            w = b["u_max"] - b["u_min"]
            h = b["v_max"] - b["v_min"]
            out_of_01 = (
                b["u_min"] < -1e-4
                or b["v_min"] < -1e-4
                or b["u_max"] > 1.0 + 1e-4
                or b["v_max"] > 1.0 + 1e-4
            )
            out.append(
                {
                    "shell": sid,
                    "uv_count": int(b["uv_count"]),
                    "bbox": [b["u_min"], b["v_min"], b["u_max"], b["v_max"]],
                    "size": [w, h],
                    "area_approx": max(0.0, w * h),
                    "out_of_01": out_of_01,
                }
            )
    except Exception:
        # Fallback: shell count only
        return {
            "shells": [],
            "shell_count": shell_count,
            "uv_coords": uv_coord_count(tf),
            "truncated": False,
            "note": "OpenMaya shell 详情不可用，仅返回计数",
        }

    return {
        "shells": out,
        "shell_count": shell_count,
        "uv_coords": uv_coord_count(tf),
        "truncated": truncated,
    }


def _tri_area_2d(a: Tuple[float, float], b: Tuple[float, float], c: Tuple[float, float]) -> float:
    return 0.5 * ((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]))


def _aabb_overlap(
    a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]
) -> bool:
    # a,b = (umin, vmin, umax, vmax)
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def check_quality(mesh: str, max_faces: int = _MAX_FACE_QUALITY) -> Dict[str, Any]:
    """
    Detect flipped / zero-area UV faces, out-of-bounds UVs, and approximate overlaps.
    """
    c = _cmds()
    tf = transform_of(mesh)
    shapes = c.listRelatives(tf, shapes=True, type="mesh", fullPath=True) or []
    result: Dict[str, Any] = {
        "mesh": short_name(tf),
        "shells": uv_shell_count(tf),
        "uv_coords": uv_coord_count(tf),
        "faces": face_count(tf),
        "flipped": 0,
        "zero_area": 0,
        "out_of_01_uvs": 0,
        "overlap_pairs_est": 0,
        "overlap_faces_est": 0,
        "truncated": False,
        "ok": True,
        "issues": [],
    }
    if not shapes:
        result["ok"] = False
        result["issues"].append("无 mesh shape")
        return result

    shape = shapes[0]
    try:
        from maya.api import OpenMaya as om

        fn, _ = _get_mesh_fn(shape)
        n_faces = fn.numPolygons
        sample_n = min(n_faces, int(max_faces))
        result["truncated"] = sample_n < n_faces

        face_boxes: List[Tuple[int, Tuple[float, float, float, float]]] = []
        flipped = 0
        zero_area = 0
        out_uv = 0

        u_arr, v_arr = fn.getUVs()
        for fi in range(sample_n):
            pts: List[Tuple[float, float]] = []
            try:
                verts = fn.getPolygonVertices(fi)
                for local_i, _vid in enumerate(verts):
                    try:
                        uvid = fn.getPolygonUVid(fi, local_i)
                        u = float(u_arr[uvid])
                        v = float(v_arr[uvid])
                        pts.append((u, v))
                        if u < -1e-4 or v < -1e-4 or u > 1.0 + 1e-4 or v > 1.0 + 1e-4:
                            out_uv += 1
                    except Exception:
                        continue
            except Exception:
                continue
            if len(pts) < 3:
                continue
            # Fan triangulation area / orientation
            area_sum = 0.0
            for i in range(1, len(pts) - 1):
                area_sum += _tri_area_2d(pts[0], pts[i], pts[i + 1])
            if abs(area_sum) < 1e-12:
                zero_area += 1
            elif area_sum < 0:
                flipped += 1
            us = [p[0] for p in pts]
            vs = [p[1] for p in pts]
            face_boxes.append((fi, (min(us), min(vs), max(us), max(vs))))

        # Approximate overlap: AABB pairs (O(n^2) capped)
        overlap_pairs = 0
        overlap_faces = set()
        max_pairs_check = min(len(face_boxes), 4000)
        boxes = face_boxes[:max_pairs_check]
        for i in range(len(boxes)):
            fi, bi = boxes[i]
            aw = max(1e-12, bi[2] - bi[0])
            ah = max(1e-12, bi[3] - bi[1])
            a_area = aw * ah
            for j in range(i + 1, len(boxes)):
                fj, bj = boxes[j]
                if not _aabb_overlap(bi, bj):
                    continue
                # Require significant interior overlap (ignore shared-edge grazes)
                ou0 = max(bi[0], bj[0])
                ov0 = max(bi[1], bj[1])
                ou1 = min(bi[2], bj[2])
                ov1 = min(bi[3], bj[3])
                ow, oh = ou1 - ou0, ov1 - ov0
                if ow <= 1e-5 or oh <= 1e-5:
                    continue
                o_area = ow * oh
                bw = max(1e-12, bj[2] - bj[0])
                bh = max(1e-12, bj[3] - bj[1])
                b_area = bw * bh
                smaller = min(a_area, b_area)
                if o_area > smaller * 0.15:
                    overlap_pairs += 1
                    overlap_faces.add(fi)
                    overlap_faces.add(fj)
                    if overlap_pairs > 500:
                        break
            if overlap_pairs > 500:
                break

        result["flipped"] = flipped
        result["zero_area"] = zero_area
        result["out_of_01_uvs"] = out_uv
        result["overlap_pairs_est"] = overlap_pairs
        result["overlap_faces_est"] = len(overlap_faces)
        result["sampled_faces"] = sample_n

        issues = []
        if overlap_pairs > 0:
            issues.append(f"疑似 UV 重叠约 {overlap_pairs} 对面 AABB（涉及 ~{len(overlap_faces)} 面）")
        if flipped > 0:
            issues.append(f"翻转 UV 面 {flipped}")
        if zero_area > 0:
            issues.append(f"零面积 UV 面 {zero_area}")
        if out_uv > 0:
            issues.append(f"出 0–1 的 UV 点 {out_uv}")
        if result["truncated"]:
            issues.append(f"已采样 {sample_n}/{n_faces} 面")
        result["issues"] = issues
        result["ok"] = overlap_pairs == 0 and flipped == 0 and zero_area == 0
    except Exception as e:
        # Fallback: polySelectConstraint overlapping if available
        try:
            c.select(f"{tf}.f[*]", replace=True)
            c.polySelectConstraint(mode=3, type=0x0010, overlapping=True)
            ov = c.ls(selection=True, flatten=True) or []
            c.polySelectConstraint(disable=True)
            n_ov = len(ov)
            result["overlap_faces_est"] = n_ov
            result["overlap_pairs_est"] = n_ov
            if n_ov:
                result["issues"].append(f"polySelectConstraint 报告重叠面 {n_ov}")
                result["ok"] = False
            else:
                result["issues"].append(f"OpenMaya 质检失败({e})；约束未检出重叠")
                result["ok"] = True
        except Exception as e2:
            result["ok"] = False
            result["issues"].append(f"质检失败: {e}; fallback: {e2}")
    return result


def world_surface_area(mesh: str) -> float:
    """Approximate world-space surface area via OpenMaya."""
    c = _cmds()
    tf = transform_of(mesh)
    shapes = c.listRelatives(tf, shapes=True, type="mesh", fullPath=True) or []
    if not shapes:
        return 0.0
    try:
        from maya.api import OpenMaya as om

        fn, dag = _get_mesh_fn(shapes[0])
        # Include world transform
        matrix = dag.inclusiveMatrix()
        area = 0.0
        for i in range(fn.numPolygons):
            try:
                pts = []
                for vid in fn.getPolygonVertices(i):
                    p = fn.getPoint(vid, om.MSpace.kObject) * matrix
                    pts.append(p)
                if len(pts) < 3:
                    continue
                # Fan
                for j in range(1, len(pts) - 1):
                    e1 = pts[j] - pts[0]
                    e2 = pts[j + 1] - pts[0]
                    cross = e1 ^ e2
                    area += 0.5 * cross.length()
            except Exception:
                continue
        return float(area)
    except Exception:
        return 0.0


def uv_surface_area(mesh: str) -> float:
    c = _cmds()
    tf = transform_of(mesh)
    shapes = c.listRelatives(tf, shapes=True, type="mesh", fullPath=True) or []
    if not shapes:
        return 0.0
    try:
        fn, _ = _get_mesh_fn(shapes[0])
        u_arr, v_arr = fn.getUVs()
        area = 0.0
        for fi in range(fn.numPolygons):
            pts: List[Tuple[float, float]] = []
            verts = fn.getPolygonVertices(fi)
            for local_i, _ in enumerate(verts):
                try:
                    uvid = fn.getPolygonUVid(fi, local_i)
                    pts.append((float(u_arr[uvid]), float(v_arr[uvid])))
                except Exception:
                    continue
            if len(pts) < 3:
                continue
            for i in range(1, len(pts) - 1):
                area += abs(_tri_area_2d(pts[0], pts[i], pts[i + 1]))
        return float(area)
    except Exception:
        return 0.0


def current_texel_density(mesh: str, texture_size: int = 1024) -> float:
    """
    Approximate texel density in px/cm.
    Assumes Maya linear unit; converts cm if unit is cm (Maya default often cm).
    """
    wa = world_surface_area(mesh)
    ua = uv_surface_area(mesh)
    if wa <= 1e-12 or ua <= 1e-12:
        return 0.0
    # UV area in [0,1]^2 → texture pixels^2 = ua * tex^2
    # density ≈ sqrt(pixel_area / world_area)
    c = _cmds()
    try:
        unit = c.currentUnit(query=True, linear=True)
    except Exception:
        unit = "cm"
    # Convert world area to cm^2
    to_cm = {
        "mm": 0.1,
        "millimeter": 0.1,
        "cm": 1.0,
        "centimeter": 1.0,
        "m": 100.0,
        "meter": 100.0,
        "in": 2.54,
        "inch": 2.54,
        "ft": 30.48,
        "foot": 30.48,
        "yd": 91.44,
        "yard": 91.44,
    }
    scale = float(to_cm.get(str(unit).lower(), 1.0))
    wa_cm2 = wa * (scale * scale)
    if wa_cm2 <= 1e-12:
        return 0.0
    return float(math.sqrt((ua * float(texture_size) * float(texture_size)) / wa_cm2))


def scale_uv_all(mesh: str, scale: float, pivot_u: float = 0.5, pivot_v: float = 0.5) -> None:
    c = _cmds()
    tf = transform_of(mesh)
    s = float(scale)
    if abs(s - 1.0) < 1e-9:
        return
    # Relative scale about pivot: translate to origin, scale, translate back
    try:
        c.polyEditUV(f"{tf}.map[*]", u=-pivot_u, v=-pivot_v, relative=True)
        c.polyEditUV(f"{tf}.map[*]", scaleU=s, scaleV=s, relative=True)
        c.polyEditUV(f"{tf}.map[*]", u=pivot_u, v=pivot_v, relative=True)
    except Exception:
        c.polyEditUV(f"{tf}.uv[*]", u=-pivot_u, v=-pivot_v, relative=True)
        c.polyEditUV(f"{tf}.uv[*]", scaleU=s, scaleV=s, relative=True)
        c.polyEditUV(f"{tf}.uv[*]", u=pivot_u, v=pivot_v, relative=True)


def set_texel_density_on_mesh(
    mesh: str,
    target_px_per_cm: float,
    texture_size: int = 1024,
    reference_mesh: str = "",
) -> Dict[str, Any]:
    """Scale UVs so texel density matches target or reference mesh."""
    tf = transform_of(mesh)
    if reference_mesh:
        rtf, _, err = resolve_mesh(reference_mesh)
        if err or not rtf:
            raise RuntimeError(err or "参考网格无效")
        target = current_texel_density(rtf, texture_size)
        if target <= 1e-9:
            raise RuntimeError("参考网格 texel density 无效（可能无 UV）")
    else:
        target = float(target_px_per_cm)
        if target <= 0:
            raise RuntimeError("target_px_per_cm 必须 > 0")

    current = current_texel_density(tf, texture_size)
    if current <= 1e-9:
        raise RuntimeError("当前 texel density 无效（先展开 UV）")
    scale = target / current
    scale_uv_all(tf, scale)
    after = current_texel_density(tf, texture_size)
    return {
        "mesh": short_name(tf),
        "texture_size": int(texture_size),
        "density_before": current,
        "density_after": after,
        "target": target,
        "scale": scale,
        "reference": short_name(reference_mesh) if reference_mesh else "",
    }


def _uv_snapshot_dir() -> str:
    return str(agent_temp_subdir("uv"))


def _snapshot_out_path(mesh: str, resolution: int, ext: str = "jpg") -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in short_name(mesh))
    safe = (safe or "mesh")[:64]
    stamp = time.strftime("%Y%m%d_%H%M%S")
    name = f"uv_{safe}_{resolution}_{stamp}.{ext.lstrip('.')}"
    return os.path.join(_uv_snapshot_dir(), name).replace("\\", "/")


def _uv_edges_for_draw(mesh: str) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:
    """Collect UV edge segments for matplotlib fallback."""
    c = _cmds()
    tf = transform_of(mesh)
    shapes = c.listRelatives(tf, shapes=True, type="mesh", fullPath=True) or []
    if not shapes:
        return []
    try:
        fn, _ = _get_mesh_fn(shapes[0])
        u_arr, v_arr = fn.getUVs()
        segs: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
        seen = set()
        for fi in range(fn.numPolygons):
            verts = fn.getPolygonVertices(fi)
            n = len(verts)
            if n < 2:
                continue
            uvs: List[Tuple[float, float]] = []
            for local_i in range(n):
                try:
                    uvid = fn.getPolygonUVid(fi, local_i)
                    uvs.append((float(u_arr[uvid]), float(v_arr[uvid])))
                except Exception:
                    uvs.append((0.0, 0.0))
            for i in range(n):
                a, b = uvs[i], uvs[(i + 1) % n]
                key = (round(a[0], 6), round(a[1], 6), round(b[0], 6), round(b[1], 6))
                key_r = (key[2], key[3], key[0], key[1])
                if key in seen or key_r in seen:
                    continue
                seen.add(key)
                segs.append((a, b))
        return segs
    except Exception:
        return []


def _draw_uv_layout_matplotlib(
    mesh: str,
    out_path: str,
    resolution: int = 1024,
    entire_range: bool = False,
    u_min: float = 0.0,
    u_max: float = 1.0,
    v_min: float = 0.0,
    v_max: float = 1.0,
) -> str:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    segs = _uv_edges_for_draw(mesh)
    if not segs:
        raise RuntimeError("无法读取 UV 边（网格可能无 UV）")

    if entire_range:
        us = [p[0] for a, b in segs for p in (a, b)]
        vs = [p[1] for a, b in segs for p in (a, b)]
        pad = 0.02
        u_min = min(us) - pad
        u_max = max(us) + pad
        v_min = min(vs) - pad
        v_max = max(vs) + pad

    dpi = 100
    fig_w = max(1.0, float(resolution) / dpi)
    fig, ax = plt.subplots(figsize=(fig_w, fig_w), dpi=dpi)
    ax.set_facecolor("#1a1a1a")
    fig.patch.set_facecolor("#1a1a1a")
    for a, b in segs:
        ax.plot([a[0], b[0]], [a[1], b[1]], color="#e8e8e8", linewidth=0.4, solid_capstyle="round")
    # 0-1 frame
    ax.plot([0, 1, 1, 0, 0], [0, 0, 1, 1, 0], color="#4fc3f7", linewidth=0.8, alpha=0.8)
    ax.set_xlim(u_min, u_max)
    ax.set_ylim(v_min, v_max)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("U", color="#aaa")
    ax.set_ylabel("V", color="#aaa")
    ax.tick_params(colors="#888", labelsize=7)
    for spine in ax.spines.values():
        spine.set_color("#555")
    ax.set_title(short_name(mesh), color="#ccc", fontsize=9)
    fig.tight_layout(pad=0.3)
    fig.savefig(out_path, dpi=dpi, facecolor=fig.get_facecolor())
    plt.close(fig)
    if not os.path.isfile(out_path) or os.path.getsize(out_path) < 32:
        raise RuntimeError("matplotlib UV 出图失败")
    return out_path


def capture_uv_snapshot(
    mesh: str,
    resolution: int = 1024,
    entire_uv_range: bool = False,
    anti_aliased: bool = True,
    file_format: str = "jpg",
    u_min: float = 0.0,
    u_max: float = 1.0,
    v_min: float = 0.0,
    v_max: float = 1.0,
    uv_set: str = "",
) -> Dict[str, Any]:
    """
    Export UV wireframe image via cmds.uvSnapshot; matplotlib fallback.
    Returns dict with path, method, resolution, mesh.
    """
    c = _cmds()
    tf = transform_of(mesh)
    res = max(64, min(int(resolution), 4096))
    fmt = (file_format or "jpg").lower().lstrip(".")
    if fmt == "jpeg":
        fmt = "jpg"
    # Documented formats; png often works in newer Maya but jpg is safest for vision
    if fmt not in ("jpg", "tif", "tiff", "iff", "sgi", "gif", "rla", "png"):
        fmt = "jpg"
    out_ext = "jpg" if fmt == "jpg" else ("tif" if fmt in ("tif", "tiff") else fmt)
    out_path = _snapshot_out_path(tf, res, out_ext)

    method = "uvSnapshot"
    with remember_selection():
        c.select(tf, replace=True)
        kwargs: Dict[str, Any] = {
            "overwrite": True,
            "name": out_path,
            "xResolution": res,
            "yResolution": res,
            "antiAliased": bool(anti_aliased),
            "fileFormat": "tif" if fmt == "tiff" else fmt,
            "redColor": 255,
            "greenColor": 255,
            "blueColor": 255,
        }
        if uv_set:
            kwargs["uvSetName"] = uv_set
        if entire_uv_range:
            kwargs["entireUVRange"] = True
        else:
            kwargs["uMin"] = float(u_min)
            kwargs["uMax"] = float(u_max)
            kwargs["vMin"] = float(v_min)
            kwargs["vMax"] = float(v_max)
        try:
            c.uvSnapshot(**kwargs)
        except Exception as e1:
            # Retry without color / range extras
            try:
                c.uvSnapshot(
                    overwrite=True,
                    name=out_path,
                    xResolution=res,
                    yResolution=res,
                    antiAliased=bool(anti_aliased),
                    fileFormat="jpg",
                )
            except Exception as e2:
                # matplotlib fallback → always png/jpg path
                out_path = _snapshot_out_path(tf, res, "png")
                try:
                    _draw_uv_layout_matplotlib(
                        tf,
                        out_path,
                        resolution=res,
                        entire_range=entire_uv_range,
                        u_min=u_min,
                        u_max=u_max,
                        v_min=v_min,
                        v_max=v_max,
                    )
                    method = "matplotlib"
                except Exception as e3:
                    raise RuntimeError(
                        f"uvSnapshot 失败: {e1}; retry: {e2}; matplotlib: {e3}"
                    ) from e3

    if not os.path.isfile(out_path) or os.path.getsize(out_path) < 32:
        # Last resort matplotlib
        out_path = _snapshot_out_path(tf, res, "png")
        _draw_uv_layout_matplotlib(
            tf,
            out_path,
            resolution=res,
            entire_range=entire_uv_range,
            u_min=u_min,
            u_max=u_max,
            v_min=v_min,
            v_max=v_max,
        )
        method = "matplotlib"

    return {
        "mesh": short_name(tf),
        "path": out_path.replace("\\", "/"),
        "method": method,
        "resolution": res,
        "entire_uv_range": bool(entire_uv_range),
        "shells": uv_shell_count(tf),
        "uv_coords": uv_coord_count(tf),
    }

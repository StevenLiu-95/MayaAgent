"""Shared mesh / component helpers for modeling tools (Maya 2020–2026)."""

from __future__ import annotations

import math
import re
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from maya_agent.tools._maya import cmds as _cmds
from maya_agent.tools._maya import mel as _mel

FACE, EDGE, VERTEX = "face", "edge", "vertex"
_KIND_TOKEN = {FACE: ".f[", EDGE: ".e[", VERTEX: ".vtx["}
_KIND_TO_FLAG = {FACE: "f", EDGE: "e", VERTEX: "vtx"}

DIR_PRESETS = {
    "x": (1.0, 0.0, 0.0),
    "+x": (1.0, 0.0, 0.0),
    "-x": (-1.0, 0.0, 0.0),
    "right": (1.0, 0.0, 0.0),
    "left": (-1.0, 0.0, 0.0),
    "y": (0.0, 1.0, 0.0),
    "+y": (0.0, 1.0, 0.0),
    "-y": (0.0, -1.0, 0.0),
    "top": (0.0, 1.0, 0.0),
    "up": (0.0, 1.0, 0.0),
    "bottom": (0.0, -1.0, 0.0),
    "down": (0.0, -1.0, 0.0),
    "z": (0.0, 0.0, 1.0),
    "+z": (0.0, 0.0, 1.0),
    "-z": (0.0, 0.0, -1.0),
    "front": (0.0, 0.0, 1.0),
    "back": (0.0, 0.0, -1.0),
}

_MAX_LIST = 80
_FACE_NORMAL_RE = re.compile(
    r"FACE_NORMAL\s+(\d+)\s*:\s*([-\d.eE]+)\s+([-\d.eE]+)\s+([-\d.eE]+)"
)


def as_vec3(value: Optional[Sequence[float]], default: Optional[Tuple[float, float, float]] = None):
    if value is None:
        return default
    if len(value) < 3:
        return default
    return (float(value[0]), float(value[1]), float(value[2]))


def normalize(v: Sequence[float]) -> Tuple[float, float, float]:
    x, y, z = float(v[0]), float(v[1]), float(v[2])
    n = math.sqrt(x * x + y * y + z * z)
    if n < 1e-12:
        return (0.0, 0.0, 0.0)
    return (x / n, y / n, z / n)


def resolve_direction(
    direction: str = "",
    vector: Optional[Sequence[float]] = None,
) -> Optional[Tuple[float, float, float]]:
    if vector is not None and len(vector) >= 3:
        return normalize(vector)
    key = (direction or "").strip().lower()
    if not key:
        return None
    preset = DIR_PRESETS.get(key)
    if not preset:
        return None
    return preset


def transform_of(node: str) -> str:
    c = _cmds()
    if not c.objExists(node):
        return node
    ntype = c.nodeType(node)
    if ntype == "mesh":
        parents = c.listRelatives(node, parent=True, fullPath=True) or []
        return parents[0] if parents else node
    return node


def short_name(node: str) -> str:
    return (node or "").split("|")[-1]


def collect_mesh_shapes(root: str) -> List[str]:
    c = _cmds()
    if not c.objExists(root):
        return []
    ntype = c.nodeType(root)
    if ntype == "mesh":
        return [root]
    shapes = c.listRelatives(root, shapes=True, type="mesh", fullPath=True) or []
    descendants = c.listRelatives(root, allDescendents=True, type="mesh", fullPath=True) or []
    return list(dict.fromkeys(list(shapes) + list(descendants)))


def primary_mesh(node: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (transform, shape) for the first mesh under node."""
    c = _cmds()
    if not node or not c.objExists(node):
        return None, None
    shapes = collect_mesh_shapes(node)
    if not shapes:
        return None, None
    shape = shapes[0]
    tf = transform_of(shape)
    return tf, shape


def targets_or_selection(names: Optional[Sequence[str]] = None) -> List[str]:
    c = _cmds()
    if names:
        found = [n for n in names if n and c.objExists(n)]
        if found:
            return list(found)
    return c.ls(selection=True, long=True) or []


def poly_stats(shape: str) -> Dict[str, Any]:
    c = _cmds()
    stats: Dict[str, Any] = {"shape": shape}
    for key, kw in (
        ("vertices", {"vertex": True}),
        ("edges", {"edge": True}),
        ("faces", {"face": True}),
        ("triangles", {"triangle": True}),
        ("uvs", {"uvcoord": True}),
    ):
        try:
            stats[key] = int(c.polyEvaluate(shape, **kw) or 0)
        except Exception:
            stats[key] = 0
    stats["transform"] = transform_of(shape)
    try:
        tf = stats["transform"]
        bb = c.exactWorldBoundingBox(tf)
        stats["bbox"] = bbox_dict(bb)
    except Exception:
        stats["bbox"] = None
    return stats


def bbox_dict(bb: Sequence[float]) -> Dict[str, Any]:
    return {
        "min": [float(bb[0]), float(bb[1]), float(bb[2])],
        "max": [float(bb[3]), float(bb[4]), float(bb[5])],
        "center": [
            0.5 * (bb[0] + bb[3]),
            0.5 * (bb[1] + bb[4]),
            0.5 * (bb[2] + bb[5]),
        ],
        "size": [
            float(bb[3] - bb[0]),
            float(bb[4] - bb[1]),
            float(bb[5] - bb[2]),
        ],
    }


def component_count(mesh: str, kind: str) -> int:
    c = _cmds()
    key = {"face": "face", "edge": "edge", "vertex": "vertex"}[kind]
    try:
        return int(c.polyEvaluate(mesh, **{key: True}) or 0)
    except Exception:
        return 0


def compact_ranges(indices: Sequence[int]) -> List[str]:
    if not indices:
        return []
    ordered = sorted({int(i) for i in indices if int(i) >= 0})
    out: List[str] = []
    start = prev = ordered[0]
    for i in ordered[1:]:
        if i == prev + 1:
            prev = i
            continue
        out.append(f"{start}:{prev}" if start != prev else str(start))
        start = prev = i
    out.append(f"{start}:{prev}" if start != prev else str(start))
    return out


def component_strings(mesh: str, kind: str, indices: Sequence[int]) -> List[str]:
    flag = _KIND_TO_FLAG[kind]
    tf = transform_of(mesh)
    return [f"{tf}.{flag}[{span}]" for span in compact_ranges(indices)]


def flatten_components(items: Sequence[str]) -> List[str]:
    c = _cmds()
    if not items:
        return []
    try:
        return list(c.ls(list(items), flatten=True) or [])
    except Exception:
        return list(items)


def indices_of(components: Sequence[str]) -> List[int]:
    found: List[int] = []
    rx = re.compile(r"\[(\d+)\]")
    for item in flatten_components(components):
        m = rx.search(item)
        if m:
            found.append(int(m.group(1)))
    return found


def filter_kind(items: Sequence[str], kind: str) -> List[str]:
    token = _KIND_TOKEN[kind]
    return [x for x in flatten_components(items) if token in x]


def current_components(kind: str, mesh: str = "") -> List[str]:
    c = _cmds()
    sel = c.ls(selection=True, flatten=True) or []
    comps = filter_kind(sel, kind)
    if mesh:
        tf = short_name(transform_of(mesh))
        long_tf = transform_of(mesh)
        comps = [
            x
            for x in comps
            if x.startswith(long_tf + ".")
            or x.startswith(tf + ".")
            or f"|{tf}." in x
        ]
    return comps


@contextmanager
def remember_selection():
    c = _cmds()
    prev = c.ls(selection=True, long=True) or []
    try:
        yield prev
    finally:
        try:
            if prev:
                c.select(prev, replace=True)
            else:
                c.select(clear=True)
        except Exception:
            pass


def select_components(components: Sequence[str], replace: bool = True, add: bool = False) -> List[str]:
    c = _cmds()
    flat = flatten_components(components)
    if not flat:
        if replace and not add:
            c.select(clear=True)
        return []
    c.select(flat, replace=replace and not add, add=add)
    return c.ls(selection=True, flatten=True) or flat


def parse_index_spec(
    indices: Optional[Sequence[Any]] = None,
    index_from: Optional[int] = None,
    index_to: Optional[int] = None,
    count: int = 0,
) -> List[int]:
    out: List[int] = []
    if indices:
        for raw in indices:
            if isinstance(raw, (list, tuple)) and len(raw) == 2:
                a, b = int(raw[0]), int(raw[1])
                lo, hi = (a, b) if a <= b else (b, a)
                out.extend(range(lo, hi + 1))
                continue
            text = str(raw).strip()
            if ":" in text:
                a_s, b_s = text.split(":", 1)
                a = int(a_s) if a_s else 0
                b = int(b_s) if b_s else max(count - 1, 0)
                lo, hi = (a, b) if a <= b else (b, a)
                out.extend(range(lo, hi + 1))
            else:
                try:
                    out.append(int(text))
                except ValueError:
                    continue
    if index_from is not None or index_to is not None:
        a = int(index_from) if index_from is not None else 0
        b = int(index_to) if index_to is not None else max(count - 1, 0)
        lo, hi = (a, b) if a <= b else (b, a)
        out.extend(range(lo, hi + 1))
    if count > 0:
        out = [i for i in out if 0 <= i < count]
    return sorted(set(out))


def _xform_dir(matrix: Sequence[float], v: Sequence[float]) -> Tuple[float, float, float]:
    x, y, z = float(v[0]), float(v[1]), float(v[2])
    return (
        x * matrix[0] + y * matrix[4] + z * matrix[8],
        x * matrix[1] + y * matrix[5] + z * matrix[9],
        x * matrix[2] + y * matrix[6] + z * matrix[10],
    )


def _fn_mesh(node: str):
    try:
        from maya.api import OpenMaya as om
    except Exception:
        return None, None
    sl = om.MSelectionList()
    try:
        sl.add(transform_of(node))
    except Exception:
        try:
            sl.add(node)
        except Exception:
            return None, None
    dag = sl.getDagPath(0)
    try:
        dag.extendToShape()
    except Exception:
        pass
    try:
        return om.MFnMesh(dag), om
    except Exception:
        return None, None


def face_normals_world(mesh: str) -> List[Tuple[int, Tuple[float, float, float]]]:
    fn, om = _fn_mesh(mesh)
    if fn is not None and om is not None:
        out = []
        for i in range(fn.numPolygons):
            n = fn.getFaceNormal(i, om.MSpace.kWorld)
            out.append((i, (float(n.x), float(n.y), float(n.z))))
        return out
    c = _cmds()
    tf = transform_of(mesh)
    matrix = c.xform(tf, q=True, ws=True, matrix=True)
    raw = c.polyInfo(tf, faceNormals=True) or []
    out = []
    for line in raw:
        m = _FACE_NORMAL_RE.search(str(line))
        if not m:
            continue
        i = int(m.group(1))
        local = (float(m.group(2)), float(m.group(3)), float(m.group(4)))
        out.append((i, _xform_dir(matrix, local)))
    return out


def face_centers_world(mesh: str) -> List[Tuple[int, Tuple[float, float, float]]]:
    fn, om = _fn_mesh(mesh)
    if fn is not None and om is not None:
        out = []
        for i in range(fn.numPolygons):
            ids = fn.getPolygonVertices(i)
            acc = om.MVector()
            for vid in ids:
                p = fn.getPoint(vid, om.MSpace.kWorld)
                acc += om.MVector(p)
            n = float(len(ids) or 1)
            acc = acc / n
            out.append((i, (float(acc.x), float(acc.y), float(acc.z))))
        return out
    c = _cmds()
    tf = transform_of(mesh)
    nfaces = component_count(tf, FACE)
    out = []
    for i in range(nfaces):
        try:
            pts = c.xform(f"{tf}.f[{i}]", q=True, ws=True, t=True)
            if pts and len(pts) >= 3:
                n = len(pts) // 3
                cx = sum(pts[k * 3] for k in range(n)) / n
                cy = sum(pts[k * 3 + 1] for k in range(n)) / n
                cz = sum(pts[k * 3 + 2] for k in range(n)) / n
                out.append((i, (cx, cy, cz)))
        except Exception:
            continue
    return out


def faces_by_normal(
    mesh: str,
    direction: Sequence[float],
    angle_degrees: float = 35.0,
) -> List[int]:
    target = normalize(direction)
    if target == (0.0, 0.0, 0.0):
        return []
    cos_lim = math.cos(math.radians(max(0.1, min(angle_degrees, 180.0))))
    hit = []
    for i, n in face_normals_world(mesh):
        nn = normalize(n)
        if nn[0] * target[0] + nn[1] * target[1] + nn[2] * target[2] >= cos_lim:
            hit.append(i)
    return hit


def faces_by_bbox(
    mesh: str,
    bbox_min: Sequence[float],
    bbox_max: Sequence[float],
) -> List[int]:
    mn = as_vec3(bbox_min)
    mx = as_vec3(bbox_max)
    if not mn or not mx:
        return []
    lo = (min(mn[0], mx[0]), min(mn[1], mx[1]), min(mn[2], mx[2]))
    hi = (max(mn[0], mx[0]), max(mn[1], mx[1]), max(mn[2], mx[2]))
    hit = []
    for i, p in face_centers_world(mesh):
        if lo[0] <= p[0] <= hi[0] and lo[1] <= p[1] <= hi[1] and lo[2] <= p[2] <= hi[2]:
            hit.append(i)
    return hit


def _polyinfo_indices(mesh: str, **flags) -> List[int]:
    c = _cmds()
    tf = transform_of(mesh)
    with remember_selection():
        try:
            c.select(tf, replace=True)
            raw = c.polyInfo(**flags) or []
        except Exception:
            return []
    return indices_of([str(x) for x in raw])


def border_edges(mesh: str) -> List[int]:
    return _polyinfo_indices(mesh, borderEdges=True)


def hard_edges(mesh: str) -> List[int]:
    # polyInfo(hardEdges) is not universal; fall back to crease / edge smooth
    c = _cmds()
    tf = transform_of(mesh)
    n = component_count(tf, EDGE)
    found: List[int] = []
    # Batch query via polyCrease / polySoftEdge is slow; use polyInfo if present
    try:
        raw = c.polyInfo(tf, hardEdges=True) or []
        ids = indices_of([str(x) for x in raw])
        if ids:
            return ids
    except Exception:
        pass
    if n > 4000:
        return found
    try:
        for i in range(n):
            angle = c.polySoftEdge(f"{tf}.e[{i}]", q=True, angle=True)
            if angle is not None and float(angle if not isinstance(angle, (list, tuple)) else angle[0]) < 1.0:
                found.append(i)
    except Exception:
        pass
    return found


def nonmanifold_components(mesh: str, kind: str) -> List[int]:
    if kind == VERTEX:
        return _polyinfo_indices(mesh, nonManifoldVertices=True)
    if kind == EDGE:
        return _polyinfo_indices(mesh, nonManifoldEdges=True)
    return _polyinfo_indices(mesh, laminaFaces=True)


def convert_components(items: Sequence[str], to_kind: str, border: bool = False) -> List[str]:
    c = _cmds()
    if not items:
        return []
    kwargs = {}
    if to_kind == FACE:
        kwargs["toFace"] = True
    elif to_kind == EDGE:
        kwargs["toEdge"] = True
    else:
        kwargs["toVertex"] = True
    if border:
        kwargs["border"] = True
    try:
        converted = c.polyListComponentConversion(list(items), **kwargs) or []
        return flatten_components(converted)
    except Exception:
        return []


def grow_or_shrink(components: Sequence[str], grow: bool = True) -> List[str]:
    c = _cmds()
    if not components:
        return []
    with remember_selection():
        c.select(list(components), replace=True)
        try:
            _mel().eval("GrowPolygonSelectionRegion;" if grow else "ShrinkPolygonSelectionRegion;")
        except Exception:
            pass
        return c.ls(selection=True, flatten=True) or []


def summarize_components(components: Sequence[str], kind: str) -> Dict[str, Any]:
    flat = flatten_components(components)
    ids = indices_of(flat)
    return {
        "kind": kind,
        "count": len(flat),
        "indices_sample": ids[:_MAX_LIST],
        "components_sample": flat[:_MAX_LIST],
        "compact": compact_ranges(ids)[:40],
        "truncated": len(flat) > _MAX_LIST,
    }


def resolve_components(
    *,
    mesh: str = "",
    kind: str = FACE,
    mode: str = "current",
    indices: Optional[Sequence[Any]] = None,
    index_from: Optional[int] = None,
    index_to: Optional[int] = None,
    direction: str = "",
    normal: Optional[Sequence[float]] = None,
    angle_degrees: float = 35.0,
    bbox_min: Optional[Sequence[float]] = None,
    bbox_max: Optional[Sequence[float]] = None,
    convert_from: str = "",
) -> Tuple[List[str], Optional[str], Optional[str]]:
    """
    Resolve mesh components. Returns (component_list, mesh_transform, error).
    """
    kind = (kind or FACE).lower()
    if kind in ("f", "faces", "facet", "poly"):
        kind = FACE
    elif kind in ("e", "edges"):
        kind = EDGE
    elif kind in ("v", "vtx", "verts", "vertices", "vertex"):
        kind = VERTEX
    if kind not in (FACE, EDGE, VERTEX):
        return [], None, f"未知分量类型: {kind}"

    c = _cmds()
    tf = mesh
    if tf and not c.objExists(tf):
        return [], None, f"对象不存在: {tf}"
    if tf:
        tf, shape = primary_mesh(tf)
        if not tf:
            return [], None, f"未找到多边形 mesh: {mesh}"
    else:
        sel = c.ls(selection=True, flatten=True) or []
        comps = filter_kind(sel, kind)
        if comps:
            # Infer mesh from first component
            host = comps[0].split(".")[0]
            tf, _ = primary_mesh(host)
        else:
            objs = c.ls(selection=True, type="transform", long=True) or []
            if objs:
                tf, _ = primary_mesh(objs[0])
        if not tf:
            return [], None, "请指定 mesh，或先选择网格/分量"

    n = component_count(tf, kind)
    mode = (mode or "current").lower()
    ids: List[int] = []
    comps: List[str] = []

    parsed = parse_index_spec(indices, index_from, index_to, count=n)
    if parsed:
        ids = parsed
        mode = "indices"

    if mode in ("current", "selection"):
        comps = current_components(kind, tf)
        if not comps and parsed:
            comps = flatten_components(component_strings(tf, kind, parsed))
        elif not comps:
            return [], tf, "当前没有该类型的分量选择；请传 indices / by_normal / all"
    elif mode in ("all", "*"):
        ids = list(range(n))
    elif mode in ("indices", "index", "range"):
        if not ids:
            return [], tf, "请提供 indices 或 index_from/index_to"
    elif mode in ("by_normal", "normal", "facing"):
        direc = resolve_direction(direction, normal)
        if not direc:
            return [], tf, "by_normal 需要 direction（top/bottom/front/back/left/right）或 normal=[x,y,z]"
        face_ids = faces_by_normal(tf, direc, angle_degrees)
        if kind == FACE:
            ids = face_ids
        else:
            face_comps = flatten_components(component_strings(tf, FACE, face_ids))
            comps = convert_components(face_comps, kind, border=False)
    elif mode in ("by_bbox", "bbox", "by_world_bbox"):
        if not bbox_min or not bbox_max:
            return [], tf, "by_bbox 需要 bbox_min 与 bbox_max"
        face_ids = faces_by_bbox(tf, bbox_min, bbox_max)
        if kind == FACE:
            ids = face_ids
        else:
            face_comps = flatten_components(component_strings(tf, FACE, face_ids))
            comps = convert_components(face_comps, kind, border=False)
    elif mode in ("border", "boundary", "holes"):
        eids = border_edges(tf)
        if kind == EDGE:
            ids = eids
        else:
            edge_comps = flatten_components(component_strings(tf, EDGE, eids))
            comps = convert_components(edge_comps, kind, border=(kind == FACE))
    elif mode in ("hard", "hard_edges"):
        eids = hard_edges(tf)
        if kind == EDGE:
            ids = eids
        else:
            edge_comps = flatten_components(component_strings(tf, EDGE, eids))
            comps = convert_components(edge_comps, kind)
    elif mode in ("nonmanifold", "non_manifold"):
        ids = nonmanifold_components(tf, kind)
    elif mode in ("grow", "shrink"):
        src = current_components(kind, tf)
        if not src and parsed:
            src = flatten_components(component_strings(tf, kind, parsed))
        if not src:
            return [], tf, "grow/shrink 需要已有分量选择或 indices"
        comps = grow_or_shrink(src, grow=(mode == "grow"))
        comps = filter_kind(comps, kind)
    elif mode == "convert":
        src_kind = (convert_from or "").lower() or FACE
        if src_kind in ("f", "faces"):
            src_kind = FACE
        elif src_kind in ("e", "edges"):
            src_kind = EDGE
        elif src_kind in ("v", "vtx", "verts", "vertices"):
            src_kind = VERTEX
        src = current_components(src_kind, tf)
        if not src:
            return [], tf, "convert 需要当前已选分量，或改用 indices"
        comps = convert_components(src, kind)
    else:
        return [], tf, f"未知 mode: {mode}"

    if not comps and ids:
        comps = flatten_components(component_strings(tf, kind, ids))
    if not comps:
        return [], tf, "没有匹配的分量"
    return comps, tf, None


def apply_world_transform(
    node: str,
    position: Optional[Sequence[float]] = None,
    rotation: Optional[Sequence[float]] = None,
    scale: Optional[Sequence[float]] = None,
) -> None:
    c = _cmds()
    pos = as_vec3(position)
    rot = as_vec3(rotation)
    scl = as_vec3(scale)
    if pos:
        c.xform(node, ws=True, translation=list(pos))
    if rot:
        c.xform(node, ws=True, rotation=list(rot))
    if scl:
        # xform scale with ws=True is unreliable; object-space scale
        c.xform(node, ws=False, scale=list(scl))


def sample_result(items: Iterable[Any], limit: int = _MAX_LIST) -> List[Any]:
    seq = list(items)
    return seq[:limit]

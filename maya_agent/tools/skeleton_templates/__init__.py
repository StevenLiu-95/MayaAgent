"""Skeleton template registry (data modules only; tools live in skeleton_factory.py)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from maya_agent.tools.skeleton_templates import biped as _biped
from maya_agent.tools.skeleton_templates import biped_bendy as _biped_bendy
from maya_agent.tools.skeleton_templates import biped_game as _biped_game
from maya_agent.tools.skeleton_templates import bird as _bird
from maya_agent.tools.skeleton_templates import bug as _bug
from maya_agent.tools.skeleton_templates import cat as _cat
from maya_agent.tools.skeleton_templates import dinosaur as _dinosaur
from maya_agent.tools.skeleton_templates import dragon as _dragon
from maya_agent.tools.skeleton_templates import fish as _fish
from maya_agent.tools.skeleton_templates import gorilla as _gorilla
from maya_agent.tools.skeleton_templates import horse as _horse
from maya_agent.tools.skeleton_templates import previs as _previs
from maya_agent.tools.skeleton_templates import ue4 as _ue4
from maya_agent.tools.skeleton_templates import ue5 as _ue5
from maya_agent.tools.skeleton_templates import vehicle as _vehicle

TemplateMod = Any

_CORE: Dict[str, TemplateMod] = {
    "biped": _biped,
    "biped_game": _biped_game,
    "biped_bendy": _biped_bendy,
    "ue5": _ue5,
    "ue4": _ue4,
    "previs": _previs,
    "cat": _cat,
    "horse": _horse,
    "gorilla": _gorilla,
    "bird": _bird,
    "fish": _fish,
    "bug": _bug,
    "dinosaur": _dinosaur,
    "dragon": _dragon,
    "vehicle": _vehicle,
}


def get_template(template_id: str) -> Optional[TemplateMod]:
    return _CORE.get(template_id)


def list_templates() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for tid, mod in _CORE.items():
        rows.append(
            {
                "id": tid,
                "label": getattr(mod, "LABEL", tid),
                "available": True,
                "joint_count": len(getattr(mod, "JOINTS", [])),
                "needs_mirror": bool(getattr(mod, "NEEDS_MIRROR", False)),
                "tool": f"create_skeleton_{tid}",
            }
        )
    return rows


def template_payload(template_id: str) -> Tuple[List[Dict[str, Any]], bool, str]:
    """Return (joints, needs_mirror, label) or raise KeyError / ValueError."""
    mod = _CORE.get(template_id)
    if not mod:
        raise KeyError(f"未知模板: {template_id}；可用: {', '.join(_CORE.keys())}")
    joints = list(getattr(mod, "JOINTS", []) or [])
    if not joints:
        raise ValueError(f"模板「{template_id}」关节数据为空")
    return joints, bool(mod.NEEDS_MIRROR), str(mod.LABEL)

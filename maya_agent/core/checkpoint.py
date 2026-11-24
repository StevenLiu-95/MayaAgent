"""Checkpoints: scene snapshot + dialogue position + AI-memory position.

A checkpoint is created at the end of one AI answer. It binds:

* scene   -- ``<temp>/checkpoints/<id>.mb`` written with ``file -exportAll``
* dialogue-- a ``{"type": "checkpoint", "id", "name"}`` block in ``ui_blocks``
* memory  -- ``memory_seq``: the stable ``ChatMessage.seq`` of the last message

Pure helpers (truncation, ids) have no Maya dependency and are unit-tested
offline. ``snapshot_scene`` / ``restore_scene`` need ``maya.cmds``.
"""

from __future__ import annotations

import copy
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from maya_agent.utils.logger import get_logger
from maya_agent.utils.maya_compat import in_maya, run_on_main_thread
from maya_agent.utils.paths import agent_temp_subdir

log = get_logger("maya_agent.checkpoint")

BLOCK_TYPE = "checkpoint"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_checkpoint_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Checkpoint:
    id: str
    name: str = ""
    created_at: str = ""
    memory_seq: int = 0
    snapshot_path: str = ""
    scene_meta: Dict[str, Any] = field(default_factory=dict)
    plan: Optional[Dict[str, Any]] = None
    scene_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "memory_seq": int(self.memory_seq),
            "snapshot_path": self.snapshot_path,
            "scene_meta": dict(self.scene_meta or {}),
            "plan": copy.deepcopy(self.plan) if self.plan else None,
            "scene_path": self.scene_path,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Checkpoint":
        plan = data.get("plan")
        meta = data.get("scene_meta")
        try:
            seq = int(data.get("memory_seq") or 0)
        except (TypeError, ValueError):
            seq = 0
        return cls(
            id=str(data.get("id") or new_checkpoint_id()),
            name=str(data.get("name") or ""),
            created_at=str(data.get("created_at") or _now_iso()),
            memory_seq=seq,
            snapshot_path=str(data.get("snapshot_path") or ""),
            scene_meta=dict(meta) if isinstance(meta, dict) else {},
            plan=dict(plan) if isinstance(plan, dict) else None,
            scene_path=str(data.get("scene_path") or ""),
        )

    @property
    def has_snapshot(self) -> bool:
        return bool(self.snapshot_path) and os.path.isfile(self.snapshot_path)


def new_checkpoint(
    *,
    name: str = "",
    memory_seq: int = 0,
    plan: Optional[Dict[str, Any]] = None,
    scene_path: str = "",
) -> Checkpoint:
    return Checkpoint(
        id=new_checkpoint_id(),
        name=name,
        created_at=_now_iso(),
        memory_seq=int(memory_seq or 0),
        plan=copy.deepcopy(plan) if plan else None,
        scene_path=scene_path or "",
    )


# --------------------------------------------------------------------------
# Pure data helpers (no Maya)
# --------------------------------------------------------------------------


def truncate_memory_dicts(
    memory: List[Dict[str, Any]], memory_seq: int
) -> List[Dict[str, Any]]:
    """Keep system messages and every message with ``seq <= memory_seq``."""
    out: List[Dict[str, Any]] = []
    for item in memory or []:
        if not isinstance(item, dict):
            continue
        if item.get("role") == "system":
            out.append(copy.deepcopy(item))
            continue
        try:
            seq = int(item.get("seq") or 0)
        except (TypeError, ValueError):
            seq = 0
        if seq <= int(memory_seq):
            out.append(copy.deepcopy(item))
    return out


def find_checkpoint_block(blocks: List[Dict[str, Any]], cp_id: str) -> int:
    for i, b in enumerate(blocks or []):
        if b.get("type") == BLOCK_TYPE and b.get("id") == cp_id:
            return i
    return -1


def truncate_blocks(
    blocks: List[Dict[str, Any]], cp_id: str
) -> Optional[List[Dict[str, Any]]]:
    """Blocks up to and including the checkpoint block (deep copy)."""
    idx = find_checkpoint_block(blocks, cp_id)
    if idx < 0:
        return None
    return [copy.deepcopy(b) for b in blocks[: idx + 1]]


def make_block(cp: Checkpoint) -> Dict[str, Any]:
    return {"type": BLOCK_TYPE, "id": cp.id, "name": cp.name}


# --------------------------------------------------------------------------
# Snapshot storage
# --------------------------------------------------------------------------


def snapshot_dir() -> Path:
    return agent_temp_subdir("checkpoints")


def snapshot_path_for(cp_id: str) -> Path:
    return snapshot_dir() / f"{cp_id}.mb"


def delete_snapshot(path: str) -> bool:
    """Delete a snapshot file, only if it lives in the checkpoints directory."""
    if not path:
        return False
    try:
        p = Path(path).resolve()
        root = snapshot_dir().resolve()
        if root not in p.parents:
            return False
        if p.is_file():
            p.unlink()
            return True
    except OSError as e:
        log.debug("delete snapshot failed %s: %s", path, e)
    except Exception:
        pass
    return False


# --------------------------------------------------------------------------
# Maya scene snapshot / restore
# --------------------------------------------------------------------------


def _capture_scene_meta(cmds) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    try:
        meta["units"] = {
            "linear": cmds.currentUnit(query=True, linear=True),
            "angle": cmds.currentUnit(query=True, angle=True),
            "time": cmds.currentUnit(query=True, time=True),
        }
    except Exception:
        pass
    try:
        meta["time"] = {
            "min": cmds.playbackOptions(query=True, minTime=True),
            "max": cmds.playbackOptions(query=True, maxTime=True),
            "start": cmds.playbackOptions(query=True, animationStartTime=True),
            "end": cmds.playbackOptions(query=True, animationEndTime=True),
            "current": cmds.currentTime(query=True),
        }
    except Exception:
        pass
    try:
        meta["selection"] = list(cmds.ls(selection=True, long=True) or [])
    except Exception:
        pass
    return meta


def snapshot_scene(cp_id: str) -> Tuple[str, Dict[str, Any], str]:
    """
    Export the whole scene to the checkpoints directory.

    Returns ``(path, scene_meta, error)``. ``path`` is empty on failure or
    when not running inside Maya (the checkpoint is then dialogue-only).
    """
    if not in_maya():
        return "", {}, "not in Maya"
    path = str(snapshot_path_for(cp_id)).replace("\\", "/")

    def _do() -> Tuple[str, Dict[str, Any], str]:
        import maya.cmds as cmds

        meta = _capture_scene_meta(cmds)
        try:
            cmds.file(
                path,
                exportAll=True,
                type="mayaBinary",
                force=True,
                preserveReferences=True,
                constructionHistory=True,
                channels=True,
                constraints=True,
                expressions=True,
                shader=True,
                options="v=0;",
            )
        except Exception as e:
            log.warning("snapshot export failed: %s", e)
            return "", meta, f"{type(e).__name__}: {e}"
        if not os.path.isfile(path):
            return "", meta, "snapshot file was not written"
        try:
            meta["size_bytes"] = os.path.getsize(path)
        except OSError:
            pass
        return path, meta, ""

    try:
        return run_on_main_thread(_do)
    except Exception as e:
        log.warning("snapshot failed: %s", e)
        return "", {}, f"{type(e).__name__}: {e}"


def restore_scene_safe(
    path: str, scene_meta: Optional[Dict[str, Any]] = None
) -> Tuple[bool, str]:
    """
    ``restore_scene`` with a safety net: the current scene is exported first
    and re-imported if the restore fails half-way (the scene is replaced via
    ``file -new``, so a failure would otherwise lose the user's work).
    """
    backup_path, backup_meta, _berr = snapshot_scene("_pre_restore")
    ok, err = restore_scene(path, scene_meta)
    if ok:
        delete_snapshot(backup_path)
        return True, ""
    if backup_path:
        rok, _rerr = restore_scene(backup_path, backup_meta)
        delete_snapshot(backup_path)
        if rok:
            return False, f"{err} (the previous scene was recovered)"
        return False, f"{err} (recovery failed)"
    return False, err


def restore_scene(path: str, scene_meta: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    """
    Replace the current scene with the snapshot at ``path``.

    New scene + import keeps the user's scene name (re-applied afterwards) and
    never fires ``kAfterOpen``. Scene hooks are suppressed for the duration.
    """
    if not in_maya():
        return False, "not in Maya"
    if not path or not os.path.isfile(path):
        return False, "snapshot file missing"
    meta = scene_meta or {}

    def _do() -> Tuple[bool, str]:
        import maya.cmds as cmds
        from maya_agent.plugin.scene_hooks import suppress_scene_hooks

        orig_name = ""
        try:
            orig_name = cmds.file(query=True, sceneName=True) or ""
        except Exception:
            pass
        try:
            with suppress_scene_hooks():
                cmds.file(new=True, force=True)
                units = meta.get("units") or {}
                # Set units first so the import does not rescale the snapshot.
                for key in ("linear", "angle", "time"):
                    val = units.get(key)
                    if not val:
                        continue
                    kwargs = {key: val}
                    if key == "time":
                        kwargs["updateAnimation"] = False
                    try:
                        cmds.currentUnit(**kwargs)
                    except Exception:
                        pass
                cmds.file(
                    path,
                    i=True,
                    type="mayaBinary",
                    ignoreVersion=True,
                    mergeNamespacesOnClash=False,
                    preserveReferences=True,
                    options="v=0;",
                )
                tm = meta.get("time") or {}
                try:
                    if tm:
                        cmds.playbackOptions(
                            minTime=tm.get("min"),
                            maxTime=tm.get("max"),
                            animationStartTime=tm.get("start"),
                            animationEndTime=tm.get("end"),
                        )
                        if tm.get("current") is not None:
                            cmds.currentTime(tm.get("current"), edit=True)
                except Exception:
                    pass
                sel = [n for n in (meta.get("selection") or []) if cmds.objExists(n)]
                try:
                    if sel:
                        cmds.select(sel, replace=True, noExpand=True)
                    else:
                        cmds.select(clear=True)
                except Exception:
                    pass
                if orig_name:
                    try:
                        cmds.file(rename=orig_name)
                    except Exception as e:
                        log.debug("rename scene back failed: %s", e)
        except Exception as e:
            log.warning("restore scene failed: %s", e)
            return False, f"{type(e).__name__}: {e}"
        return True, ""

    try:
        return run_on_main_thread(_do)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

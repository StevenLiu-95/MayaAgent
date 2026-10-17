# -*- coding: utf-8 -*-
"""Unit checks for Tripo client helpers (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maya_agent.tools.skin_weights import (
    WORLD_SCALE_SYNC_THRESHOLD,
    uniform_scale_from_matrix16,
    world_scale_ratio_compatible,
)
from maya_agent.tools.tripo import (
    _normalize_progress,
    _wait_progress,
    animation_attrs_for_mode,
    short_joint_name,
)
from maya_agent.tools.tripo_client import (
    SUCCESS_STATUS,
    TERMINAL_STATUSES,
    TripoError,
    _unwrap_response,
    drop_none,
    filter_system_prompt_tripo,
    httpx_timeout_for_upload,
    pick_image_urls,
    pick_model_url,
    summarize_task,
    tripo_cfg,
    tripo_tools_available,
)


def test_unwrap_ok() -> None:
    data = _unwrap_response({"code": 0, "data": {"task_id": "task_abc"}}, http_status=200)
    assert data == {"task_id": "task_abc"}


def test_unwrap_error() -> None:
    try:
        _unwrap_response(
            {"code": 2010, "message": "Insufficient credits", "suggestion": "top up"},
            http_status=200,
        )
        raise AssertionError("expected TripoError")
    except TripoError as e:
        assert "2010" in str(e) or "Insufficient" in str(e)


def test_terminal_and_summarize() -> None:
    assert SUCCESS_STATUS in TERMINAL_STATUSES
    task = {
        "task_id": "task_1",
        "type": "text_to_model",
        "status": "success",
        "progress": 100,
        "credits_consumed": 10.0,
        "output": {
            "model_url": "https://cdn.example.com/out.glb",
            "rendered_image_url": "https://cdn.example.com/prev.png",
        },
    }
    s = summarize_task(task)
    assert s["task_id"] == "task_1"
    assert s["output"]["model_url"].endswith(".glb")

    fmt, url = pick_model_url(task, prefer=["fbx", "glb"])
    assert fmt == "glb"
    assert url.startswith("https://")

    imgs = pick_image_urls(task)
    assert any(u.endswith(".png") for u in imgs)


def test_pick_fbx_preferred() -> None:
    task = {
        "status": "success",
        "output": {
            "model_url": "https://cdn.example.com/a.glb",
            "pbr_model_url": "https://cdn.example.com/a.fbx",
        },
    }
    fmt, url = pick_model_url(task, prefer=["fbx", "glb"])
    assert fmt == "fbx"
    assert url.endswith(".fbx")


def test_drop_none_and_timeout() -> None:
    assert drop_none({"a": 1, "b": None, "c": ""}) == {"a": 1}
    conf = tripo_cfg()
    t_small = httpx_timeout_for_upload(0)
    assert float(t_small.read) == float(conf["timeout"])
    t_big = httpx_timeout_for_upload(20 * 1024 * 1024)
    assert float(t_big.write) >= float(conf["upload_timeout"])


def test_normalize_and_wait_progress_callback() -> None:
    assert _normalize_progress(None) is None
    assert _normalize_progress(50) == 50
    assert _normalize_progress(0.5) == 50
    assert _normalize_progress(1) == 1
    assert _normalize_progress(100) == 100

    # Must not raise (regression: endpoint= was an invalid kwarg)
    seen = []

    def _capture(**kwargs):
        seen.append(kwargs)

    import maya_agent.tools.tripo as tripo_mod

    original = tripo_mod.report_tool_progress
    tripo_mod.report_tool_progress = _capture  # type: ignore[assignment]
    try:
        cb = _wait_progress("texture", "task_abc")
        cb({"status": "running", "progress": 42})
    finally:
        tripo_mod.report_tool_progress = original  # type: ignore[assignment]
    assert len(seen) == 1
    assert seen[0]["kind"] == "texture"
    assert seen[0]["progress"] == 42
    assert seen[0]["status"] == "running"
    assert "endpoint" not in seen[0]


def test_prompt_filter() -> None:
    # Without key, tools unavailable → strip Tripo section
    text = "# Intro\nhello\n# Tripo\n- line\n### 工具开发\nmore\n"
    # Force unavailable by temporarily checking filter when not available
    # If tools are available (user has key), filter returns unchanged — still ok.
    out = filter_system_prompt_tripo(text)
    if not tripo_tools_available():
        assert "# Tripo" not in out
        assert "### 工具开发" in out or "more" in out
    else:
        assert "# Tripo" in out


def test_world_scale_ratio_gate() -> None:
    # Identity matrix → scale 1
    ident = [
        1, 0, 0, 0,
        0, 1, 0, 0,
        0, 0, 1, 0,
        0, 0, 0, 1,
    ]
    assert abs(uniform_scale_from_matrix16(ident) - 1.0) < 1e-6
    # Uniform scale 100
    s100 = [
        100, 0, 0, 0,
        0, 100, 0, 0,
        0, 0, 100, 0,
        0, 0, 0, 1,
    ]
    assert abs(uniform_scale_from_matrix16(s100) - 100.0) < 1e-6
    assert world_scale_ratio_compatible(1.0, 1.0)
    assert world_scale_ratio_compatible(1.1, 1.0, threshold=WORLD_SCALE_SYNC_THRESHOLD)
    assert not world_scale_ratio_compatible(100.0, 1.0)
    assert not world_scale_ratio_compatible(1.0, 100.0)
    assert not world_scale_ratio_compatible(0.0, 1.0)


def test_animation_attrs_for_mode() -> None:
    assert animation_attrs_for_mode("rotations_only", "Hip") == [
        "rotateX",
        "rotateY",
        "rotateZ",
    ]
    assert "translateX" not in animation_attrs_for_mode("rotations_only", "Root")
    root_attrs = animation_attrs_for_mode("rotations_and_root_translate", "Root")
    assert "rotateX" in root_attrs and "translateX" in root_attrs
    # Limb never gets translate even in root mode
    limb = animation_attrs_for_mode("rotations_and_root_translate", "L_Foot")
    assert limb == ["rotateX", "rotateY", "rotateZ"]
    assert short_joint_name("tripo_anim2:Hip") == "Hip"
    assert short_joint_name("|grp|ns:L_Foot") == "L_Foot"


def main() -> None:
    test_unwrap_ok()
    test_unwrap_error()
    test_terminal_and_summarize()
    test_pick_fbx_preferred()
    test_drop_none_and_timeout()
    test_normalize_and_wait_progress_callback()
    test_prompt_filter()
    test_world_scale_ratio_gate()
    test_animation_attrs_for_mode()
    conf = tripo_cfg()
    print(
        "ok:",
        f"base_url={conf['base_url']}",
        f"default_model={conf['default_model']}",
        f"tools_available={tripo_tools_available()}",
    )


if __name__ == "__main__":
    main()

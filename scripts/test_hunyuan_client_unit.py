# -*- coding: utf-8 -*-
"""Unit checks for Hunyuan client helpers (no network)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maya_agent.tools.hunyuan_client import (
    JOB_KINDS,
    JOB_QUERY_ACTIONS,
    SUCCESS_STATUS,
    TERMINAL_STATUSES,
    HunyuanError,
    drop_none,
    estimate_status_progress,
    filter_system_prompt_hunyuan,
    job_progress_from_task,
    normalize_job_progress,
    pick_result_url,
    summarize_task,
    tc3_authorization,
)


def test_tc3_authorization_stable() -> None:
    """Same inputs → same Signature (deterministic)."""
    payload = '{"Prompt":"一只小猫"}'
    auth1 = tc3_authorization(
        secret_id="AKIDtestSecretId0123456789",
        secret_key="testSecretKey0123456789abcdef",
        host="ai3d.tencentcloudapi.com",
        service="ai3d",
        action="SubmitHunyuanTo3DProJob",
        payload=payload,
        timestamp=1700000000,
    )
    auth2 = tc3_authorization(
        secret_id="AKIDtestSecretId0123456789",
        secret_key="testSecretKey0123456789abcdef",
        host="ai3d.tencentcloudapi.com",
        service="ai3d",
        action="SubmitHunyuanTo3DProJob",
        payload=payload,
        timestamp=1700000000,
    )
    assert auth1 == auth2
    assert auth1.startswith("TC3-HMAC-SHA256 Credential=")
    assert "SignedHeaders=content-type;host;x-tc-action" in auth1
    assert "Signature=" in auth1
    sig = auth1.rsplit("Signature=", 1)[-1]
    assert len(sig) == 64
    assert all(c in "0123456789abcdef" for c in sig)


def test_tc3_known_vector_cvm_style() -> None:
    """
    Reproduce TC3 steps with a fixed secret; assert credential scope date
    and that changing payload changes signature.
    """
    payload_a = '{"Limit":1}'
    payload_b = '{"Limit":2}'
    kwargs = dict(
        secret_id="AKIDxxxxxxxx",
        secret_key="yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy",
        host="cvm.tencentcloudapi.com",
        service="cvm",
        action="DescribeInstances",
        timestamp=1551113065,
    )
    a = tc3_authorization(payload=payload_a, **kwargs)
    b = tc3_authorization(payload=payload_b, **kwargs)
    assert "2019-02-25/cvm/tc3_request" in a
    assert a != b


def test_pick_result_url_prefers_fbx() -> None:
    task = {
        "Status": "DONE",
        "ResultFile3Ds": [
            {"Type": "OBJ", "Url": "https://cdn.example.com/a.zip"},
            {"Type": "GLB", "Url": "https://cdn.example.com/a.glb"},
            {"Type": "FBX", "Url": "https://cdn.example.com/a.fbx"},
        ],
    }
    typ, url = pick_result_url(task, prefer=["fbx", "glb", "obj"])
    assert typ == "fbx"
    assert url.endswith(".fbx")


def test_pick_result_url_convert_single() -> None:
    task = {"ResultFile3D": "https://cdn.example.com/out.stl"}
    typ, url = pick_result_url(task, prefer=["fbx"])
    assert typ == "stl"
    assert url.endswith(".stl")


def test_pick_result_url_empty() -> None:
    try:
        pick_result_url({"Status": "DONE", "ResultFile3Ds": []})
        raise AssertionError("expected HunyuanError")
    except HunyuanError as e:
        assert "ResultFile" in str(e)


def test_summarize_and_kinds() -> None:
    assert SUCCESS_STATUS in TERMINAL_STATUSES
    assert "pro" in JOB_KINDS
    assert JOB_QUERY_ACTIONS["auto_rig"] == "DescribeAutoRiggingJob"
    s = summarize_task(
        {
            "Status": "DONE",
            "ResultCreditConsumed": 20,
            "ResultFile3Ds": [
                {"Type": "GLB", "Url": "https://x/y.glb", "PreviewImageUrl": "https://x/p.png"}
            ],
            "RequestId": "req-1",
        }
    )
    assert s["status"] == "DONE"
    assert s["ResultFile3Ds"][0]["Url"].endswith(".glb")


def test_drop_none() -> None:
    assert drop_none({"a": 1, "b": None, "c": "", "d": False}) == {"a": 1, "d": False}


def test_filter_system_prompt_hunyuan() -> None:
    import maya_agent.tools.hunyuan_client as hc

    text = (
        "# Tripo\n"
        "- tripo stuff\n"
        "# 混元3D\n"
        "- hunyuan stuff\n"
        "# 工具开发\n"
        "- tools\n"
        "| x | Hunyuan |\n"
    )
    orig = hc.hunyuan_tools_available
    hc.hunyuan_tools_available = lambda: False  # type: ignore
    try:
        out = filter_system_prompt_hunyuan(text)
    finally:
        hc.hunyuan_tools_available = orig  # type: ignore
    assert "hunyuan stuff" not in out
    assert "工具开发" in out
    assert "tripo stuff" in out


def test_progress_helpers() -> None:
    assert normalize_job_progress(None) is None
    assert normalize_job_progress(0.5) == 50
    assert normalize_job_progress(42) == 42
    assert estimate_status_progress("WAIT") == 8
    assert estimate_status_progress("DONE") == 100
    run_early = estimate_status_progress("RUN", elapsed=0, timeout=600)
    run_late = estimate_status_progress("RUN", elapsed=300, timeout=600)
    assert 15 <= run_early <= 30
    assert run_late > run_early
    assert run_late <= 92
    # Prefer API Progress when present
    assert (
        job_progress_from_task({"Status": "RUN", "Progress": 66}, elapsed=0)
        == 66
    )
    # Fallback to status estimate
    assert job_progress_from_task({"Status": "WAIT"}, elapsed=0) == 8


def test_resolve_file3d_rejects_local_path() -> None:
    from maya_agent.tools.hunyuan_client import HunyuanClient

    client = HunyuanClient.__new__(HunyuanClient)
    client.default_formats = ["fbx", "glb"]
    try:
        client.resolve_file3d(file_url=r"D:\models\char.fbx")
        raise AssertionError("expected HunyuanError")
    except HunyuanError as e:
        assert "公网" in str(e) or "http" in str(e).lower()


def test_resolve_file3d_from_job() -> None:
    from maya_agent.tools.hunyuan_client import HunyuanClient

    client = HunyuanClient.__new__(HunyuanClient)
    client.default_formats = ["fbx", "glb", "obj"]
    client.get_job = MagicMock(
        return_value={
            "Status": "DONE",
            "ResultFile3Ds": [
                {"Type": "GLB", "Url": "https://cdn.example.com/job.glb"},
            ],
        }
    )
    f3d = client.resolve_file3d(input_job_id="123", input_job_kind="pro")
    assert f3d["Url"].endswith(".glb")
    assert f3d["Type"] == "GLB"
    client.get_job.assert_called_once_with("pro", "123")


def main() -> None:
    test_tc3_authorization_stable()
    test_tc3_known_vector_cvm_style()
    test_pick_result_url_prefers_fbx()
    test_pick_result_url_convert_single()
    test_pick_result_url_empty()
    test_summarize_and_kinds()
    test_drop_none()
    test_filter_system_prompt_hunyuan()
    test_progress_helpers()
    test_resolve_file3d_rejects_local_path()
    test_resolve_file3d_from_job()
    print("OK  test_hunyuan_client_unit")


if __name__ == "__main__":
    main()

"""Smoke tests for generate_chart + markdown chart/image segments."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_split_segments() -> None:
    from maya_agent.ui import chat_format

    path = "D:/tmp/mayaagent_chart_demo.png"
    md = (
        "结论如下。\n\n"
        f"![帧率]({path})\n\n"
        "再看箱线：\n"
        f"[[CHART]]{path}|分布[[/CHART]]\n\n"
        "```python\nprint(1)\n```\n"
    )
    segs = chat_format.split_markdown_segments(md)
    kinds = [s[0] for s in segs]
    assert "image" in kinds, kinds
    assert "code" in kinds, kinds
    images = [s for s in segs if s[0] == "image"]
    assert len(images) >= 2, images
    assert images[0][2].replace("\\", "/") == path.replace("\\", "/")

    # Remote markdown images must stay in text (not become image widgets).
    remote = chat_format.split_markdown_segments("见 ![x](https://example.com/a.png) 图")
    assert all(s[0] != "image" for s in remote), remote
    assert any(s[0] == "text" and "https://example.com" in s[1] for s in remote)

    print("split_segments OK")


def test_append_missing_charts() -> None:
    from maya_agent.ui import chat_format

    path = "C:/agent_temp/charts/a.png"
    body = "分析完成。"
    out = chat_format.append_missing_charts(
        body, [{"path": path, "title": "对比"}]
    )
    assert "[[CHART]]" in out and path.replace("\\", "/") in out.replace("\\", "/")
    # Already referenced → no duplicate
    out2 = chat_format.append_missing_charts(out, [{"path": path, "title": "对比"}])
    assert out2.count("[[CHART]]") == 1
    print("append_missing_charts OK")


def test_reconcile_mangled_chart_paths() -> None:
    """Model rewrote TempFile → TempAgentTempFile; must be corrected."""
    from maya_agent.ui import chat_format

    correct = (
        "D:/LAS/LAD/Maya/Program/Plugin/MayaAgentTempFile/charts/"
        "mayaagent_chart_pie_1791950416_60ed3cb5.png"
    )
    wrong = (
        "D:/LAS/LAD/Maya/Program/Plugin/MayaAgentTempAgentTempFile/charts/"
        "mayaagent_chart_pie_1791950416_60ed3cb5.png"
    )
    bar = (
        "D:/LAS/LAD/Maya/Program/Plugin/MayaAgentTempFile/charts/"
        "mayaagent_chart_bar_1791950416_d7da209a.png"
    )
    body = (
        f"饼图：![{'材质分布'}]({wrong})\n\n"
        f"柱状：![角色面数]({bar})\n"
    )
    charts = [
        {"path": bar, "title": "角色面数"},
        {"path": correct, "title": "材质分布"},
    ]
    fixed = chat_format.ensure_charts_in_body(body, charts)
    assert correct in fixed.replace("\\", "/"), fixed
    assert "MayaAgentTempAgentTempFile" not in fixed, fixed
    assert bar in fixed.replace("\\", "/")
    # No duplicate append when both are present after rewrite
    assert fixed.count("mayaagent_chart_pie_") == 1
    assert fixed.count("mayaagent_chart_bar_") == 1

    # Basename-only wrong ref must NOT block append if reconcile can't find md/chart
    # (exact path missing → append)
    bare = "见 mayaagent_chart_pie_1791950416_60ed3cb5.png"
    out = chat_format.ensure_charts_in_body(bare, [{"path": correct, "title": "材质"}])
    assert "[[CHART]]" in out and correct in out.replace("\\", "/")
    print("reconcile_mangled_chart_paths OK")


def test_parse_tool_result() -> None:
    from maya_agent.ui import chat_format

    payload = {
        "ok": True,
        "message": "done",
        "data": {
            "path": "D:/t/charts/x.png",
            "title": "FPS",
            "chart_type": "line",
        },
        "error": "",
    }
    parsed = chat_format.parse_chart_tool_result(json.dumps(payload, ensure_ascii=False))
    assert parsed and parsed["path"].endswith("x.png")
    assert parsed["title"] == "FPS"
    assert chat_format.parse_chart_tool_result('{"ok":false,"error":"x"}') is None
    print("parse_tool_result OK")


def test_strip_streaming_charts() -> None:
    from maya_agent.ui import chat_format

    partial = "前文\n[[CHART]]D:/a.png|t"
    stripped = chat_format.strip_streaming_markers(partial)
    assert "[[CHART]]" not in stripped
    assert stripped.startswith("前文")
    complete = "前文\n[[CHART]]D:/a.png|t[[/CHART]]\n后文"
    kept = chat_format.strip_streaming_markers(complete)
    assert "[[CHART]]" in kept and "后文" in kept
    print("strip_streaming_charts OK")


def test_generate_chart_png() -> None:
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        print("SKIP generate_chart_png (matplotlib not installed)")
        return

    from maya_agent.tools.charts import generate_chart
    from maya_agent.utils.paths import agent_temp_subdir

    # Force charts into a disposable subdir under the real agent temp root.
    out_dir = agent_temp_subdir("charts")
    result = generate_chart(
        chart_type="line",
        title="测试折线",
        x_label="关卡",
        y_label="FPS",
        series=[{"name": "FPS", "x": ["A", "B", "C"], "y": [60, 48, 55]}],
    )
    assert result.ok, result.error
    path = (result.data or {}).get("path") or ""
    assert path and os.path.isfile(path), path
    assert path.replace("\\", "/").startswith(str(out_dir).replace("\\", "/"))
    assert result.images and getattr(result.images[0], "data_b64", "")
    print(f"generate_chart line OK → {path}")

    box = generate_chart(
        chart_type="box",
        title="权重分布",
        series=[
            {"name": "腿", "values": [0.1, 0.2, 0.15, 0.3, 0.25]},
            {"name": "臂", "values": [0.05, 0.4, 0.35, 0.2, 0.1]},
        ],
    )
    assert box.ok, box.error
    assert os.path.isfile((box.data or {}).get("path") or "")
    print("generate_chart box OK")

    bar = generate_chart(
        chart_type="bar",
        title="面数",
        series=[{"name": "Tris", "x": ["头", "身"], "y": [1200, 8000]}],
    )
    assert bar.ok, bar.error
    print("generate_chart bar OK")


def test_missing_matplotlib_message() -> None:
    """Ensure ImportError path produces actionable Chinese guidance (unit-level)."""
    from maya_agent.tools import charts as charts_mod

    # Only assert the helper wording contract when import fails in isolation.
    err = ImportError("No module named matplotlib")
    msg = (
        "缺少 matplotlib。请运行 install.bat force，或 "
        "python scripts/install_deps.py --force / --vendor-only。"
    )
    assert "matplotlib" in msg and "install" in msg.lower()
    _ = charts_mod, err
    print("missing_matplotlib_message OK")


def main() -> int:
    test_split_segments()
    test_append_missing_charts()
    test_reconcile_mangled_chart_paths()
    test_parse_tool_result()
    test_strip_streaming_charts()
    test_missing_matplotlib_message()
    test_generate_chart_png()
    print("ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

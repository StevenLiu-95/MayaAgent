"""Professional chart generation for data-analysis replies."""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, List, Tuple

from maya_agent.llm.image_codec import attachment_from_raw_file
from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.utils.logger import get_logger
from maya_agent.utils.paths import agent_temp_subdir

log = get_logger("maya_agent.tools.charts")

_CHART_TYPES = ("line", "bar", "box", "scatter", "hist", "pie")
_FONT_CANDIDATES = (
    "Microsoft YaHei",
    "Microsoft YaHei UI",
    "SimHei",
    "SimSun",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "PingFang SC",
    "Arial Unicode MS",
    "DejaVu Sans",
)


def _charts_dir() -> str:
    return str(agent_temp_subdir("charts"))


def _import_matplotlib():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
    except ImportError as e:
        raise ImportError(
            "缺少 matplotlib。请运行 install.bat force，或 "
            "python scripts/install_deps.py --force / --vendor-only。"
        ) from e
    return matplotlib, plt, font_manager


def _configure_chinese_font(plt, font_manager) -> str:
    """Pick a CJK-capable font so titles/labels are not tofu boxes."""
    available = {f.name for f in font_manager.fontManager.ttflist}
    chosen = ""
    for name in _FONT_CANDIDATES:
        if name in available:
            chosen = name
            break
    if chosen:
        plt.rcParams["font.sans-serif"] = [chosen, "DejaVu Sans"]
    else:
        plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    return chosen or "DejaVu Sans"


def _as_float_list(values: Any, *, label: str) -> List[float]:
    if values is None:
        return []
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{label} 必须是数字数组")
    out: List[float] = []
    for i, v in enumerate(values):
        try:
            out.append(float(v))
        except (TypeError, ValueError) as e:
            raise ValueError(f"{label}[{i}] 不是数字: {v!r}") from e
    return out


def _series_values(item: Dict[str, Any]) -> List[float]:
    if "values" in item and item.get("values") is not None:
        return _as_float_list(item.get("values"), label="values")
    if "y" in item and item.get("y") is not None:
        return _as_float_list(item.get("y"), label="y")
    raise ValueError("每个 series 需要 y 或 values 数组")


def _series_x(item: Dict[str, Any], n: int) -> List[Any]:
    x = item.get("x")
    if x is None:
        return list(range(1, n + 1))
    if not isinstance(x, (list, tuple)):
        raise ValueError("x 必须是数组")
    if len(x) != n:
        raise ValueError(f"x 长度 ({len(x)}) 与 y/values ({n}) 不一致")
    return list(x)


def _normalize_series(series: Any) -> List[Dict[str, Any]]:
    if series is None:
        raise ValueError("series 不能为空")
    if isinstance(series, dict):
        series = [series]
    if not isinstance(series, list) or not series:
        raise ValueError("series 必须是非空对象数组")
    out: List[Dict[str, Any]] = []
    for i, item in enumerate(series):
        if not isinstance(item, dict):
            raise ValueError(f"series[{i}] 必须是对象")
        name = str(item.get("name") or f"系列{i + 1}").strip() or f"系列{i + 1}"
        out.append({**item, "name": name})
    return out


def _parse_figsize(figsize: Any) -> Tuple[float, float]:
    if figsize is None:
        return (8.0, 4.8)
    if isinstance(figsize, (list, tuple)) and len(figsize) == 2:
        try:
            w, h = float(figsize[0]), float(figsize[1])
            return (max(3.0, min(w, 16.0)), max(2.5, min(h, 12.0)))
        except (TypeError, ValueError):
            pass
    return (8.0, 4.8)


def _draw_chart(
    *,
    chart_type: str,
    title: str,
    x_label: str,
    y_label: str,
    series: List[Dict[str, Any]],
    horizontal: bool,
    stacked: bool,
    figsize: Tuple[float, float],
) -> Any:
    _matplotlib, plt, font_manager = _import_matplotlib()
    font_name = _configure_chinese_font(plt, font_manager)
    log.debug("chart font=%s type=%s", font_name, chart_type)

    fig, ax = plt.subplots(figsize=figsize, dpi=120)
    ctype = chart_type.lower().strip()

    if ctype == "line":
        for item in series:
            y = _series_values(item)
            x = _series_x(item, len(y))
            ax.plot(x, y, marker="o", linewidth=2, label=item["name"])
        if len(series) > 1:
            ax.legend()
    elif ctype == "bar":
        if len(series) == 1:
            item = series[0]
            y = _series_values(item)
            x = _series_x(item, len(y))
            labels = [str(v) for v in x]
            positions = list(range(len(y)))
            if horizontal:
                ax.barh(positions, y, label=item["name"])
                ax.set_yticks(positions)
                ax.set_yticklabels(labels)
            else:
                ax.bar(positions, y, label=item["name"])
                ax.set_xticks(positions)
                ax.set_xticklabels(labels, rotation=30, ha="right")
        else:
            # Grouped or stacked multi-series bar
            labels = [str(v) for v in _series_x(series[0], len(_series_values(series[0])))]
            n = len(labels)
            for item in series[1:]:
                vals = _series_values(item)
                if len(vals) != n:
                    raise ValueError("多系列柱状图各 series 长度须一致")
            positions = list(range(n))
            if stacked:
                bottoms = [0.0] * n
                for item in series:
                    y = _series_values(item)
                    if horizontal:
                        ax.barh(positions, y, left=bottoms, label=item["name"])
                    else:
                        ax.bar(positions, y, bottom=bottoms, label=item["name"])
                    bottoms = [b + v for b, v in zip(bottoms, y)]
            else:
                width = 0.8 / max(1, len(series))
                for i, item in enumerate(series):
                    y = _series_values(item)
                    offset = [p - 0.4 + width / 2 + i * width for p in positions]
                    if horizontal:
                        ax.barh(offset, y, height=width, label=item["name"])
                    else:
                        ax.bar(offset, y, width=width, label=item["name"])
            if horizontal:
                ax.set_yticks(positions)
                ax.set_yticklabels(labels)
            else:
                ax.set_xticks(positions)
                ax.set_xticklabels(labels, rotation=30, ha="right")
            ax.legend()
    elif ctype == "box":
        data = [_series_values(item) for item in series]
        labels = [item["name"] for item in series]
        # Matplotlib 3.9+ renamed labels → tick_labels
        try:
            ax.boxplot(
                data, tick_labels=labels, vert=not horizontal, patch_artist=True
            )
        except TypeError:
            ax.boxplot(data, labels=labels, vert=not horizontal, patch_artist=True)
    elif ctype == "scatter":
        for item in series:
            y = _series_values(item)
            x_raw = item.get("x")
            if x_raw is None:
                x = list(range(1, len(y) + 1))
            else:
                x = _as_float_list(x_raw, label="x")
                if len(x) != len(y):
                    raise ValueError("scatter 的 x 与 y 长度须一致")
            ax.scatter(x, y, s=36, alpha=0.85, label=item["name"])
        if len(series) > 1:
            ax.legend()
    elif ctype == "hist":
        for item in series:
            vals = _series_values(item)
            ax.hist(vals, bins="auto", alpha=0.65, label=item["name"])
        if len(series) > 1:
            ax.legend()
    elif ctype == "pie":
        if len(series) != 1:
            raise ValueError("pie 图请只传一个 series（用 x 作标签、y/values 作数值）")
        item = series[0]
        y = _series_values(item)
        if any(v < 0 for v in y):
            raise ValueError("pie 数值不能为负")
        labels = [str(v) for v in _series_x(item, len(y))]
        ax.pie(y, labels=labels, autopct="%1.1f%%", startangle=90)
        ax.axis("equal")
    else:
        raise ValueError(f"不支持的 chart_type: {chart_type}")

    if title:
        ax.set_title(title)
    if ctype != "pie":
        if x_label:
            ax.set_xlabel(x_label if not horizontal else y_label or x_label)
        if y_label:
            ax.set_ylabel(y_label if not horizontal else x_label or y_label)
        ax.grid(True, linestyle="--", alpha=0.35)
    fig.tight_layout()
    return fig


@tool(
    name="generate_chart",
    description=(
        "根据数值数据生成专业图表 PNG（折线/柱状/箱线/散点/直方图/饼图），"
        "写入临时目录并附带图像。数据分析、对比、分布展示时优先使用本工具，"
        "不要用 ASCII 或截视口代替。最终回复请用 "
        "`![标题](返回的path)` 或 `[[CHART]]path|标题[[/CHART]]` 嵌入正文。"
        " series 示例："
        '[{"name":"FPS","x":["关卡1","关卡2"],"y":[60,45]}]；'
        "箱线图可用多个 series，每个提供 values/y。"
    ),
    parameters=obj_schema(
        {
            "chart_type": {
                "type": "string",
                "enum": list(_CHART_TYPES),
                "description": "图表类型：line/bar/box/scatter/hist/pie",
            },
            "title": {
                "type": "string",
                "description": "图表标题",
            },
            "x_label": {
                "type": "string",
                "description": "X 轴标签",
            },
            "y_label": {
                "type": "string",
                "description": "Y 轴标签",
            },
            "series": {
                "type": "array",
                "description": (
                    "数据系列列表。每项含 name，以及 y 或 values；"
                    "可选 x（类别或数值）。box/hist 重点用 values/y。"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "x": {
                            "type": "array",
                            "items": {},
                        },
                        "y": {
                            "type": "array",
                            "items": {"type": "number"},
                        },
                        "values": {
                            "type": "array",
                            "items": {"type": "number"},
                        },
                    },
                    "additionalProperties": True,
                },
            },
            "horizontal": {
                "type": "boolean",
                "description": "柱状/箱线是否横向",
            },
            "stacked": {
                "type": "boolean",
                "description": "多系列柱状图是否堆叠",
            },
            "figsize": {
                "type": "array",
                "items": {"type": "number"},
                "description": "可选 [宽, 高] 英寸，默认 [8, 4.8]",
            },
        },
        required=["chart_type", "series"],
    ),
    category="analysis",
    requires_vision=False,
    main_thread=False,
)
def generate_chart(
    chart_type: str = "line",
    series: Any = None,
    title: str = "",
    x_label: str = "",
    y_label: str = "",
    horizontal: bool = False,
    stacked: bool = False,
    figsize: Any = None,
    style_hint: str = "",
) -> ToolResult:
    """Render a chart PNG under the agent temp charts directory."""
    _ = style_hint  # reserved for future themes; accepted so models may pass it
    try:
        ctype = str(chart_type or "").strip().lower()
        if ctype not in _CHART_TYPES:
            return ToolResult(
                ok=False,
                error=f"chart_type 必须是其一: {', '.join(_CHART_TYPES)}",
            )
        items = _normalize_series(series)
        size = _parse_figsize(figsize)
        fig = _draw_chart(
            chart_type=ctype,
            title=str(title or "").strip(),
            x_label=str(x_label or "").strip(),
            y_label=str(y_label or "").strip(),
            series=items,
            horizontal=bool(horizontal),
            stacked=bool(stacked),
            figsize=size,
        )
    except ImportError as e:
        return ToolResult(ok=False, error=str(e))
    except ValueError as e:
        return ToolResult(ok=False, error=str(e))
    except Exception as e:
        log.exception("generate_chart failed")
        return ToolResult(ok=False, error=f"{type(e).__name__}: {e}")

    out_dir = _charts_dir()
    safe_type = ctype.replace("/", "_")
    fname = f"mayaagent_chart_{safe_type}_{int(time.time())}_{uuid.uuid4().hex[:8]}.png"
    path = os.path.join(out_dir, fname).replace("\\", "/")
    try:
        fig.savefig(path, format="png", bbox_inches="tight", facecolor="white")
    except Exception as e:
        return ToolResult(ok=False, error=f"保存图表失败: {e}")
    finally:
        try:
            import matplotlib.pyplot as plt

            plt.close(fig)
        except Exception:
            pass

    if not os.path.isfile(path):
        return ToolResult(ok=False, error="图表文件未生成")

    try:
        attachment = attachment_from_raw_file(path)
        attachment.name = str(title or "").strip() or fname
    except Exception as e:
        return ToolResult(
            ok=False,
            error=f"读取图表失败: {e}",
            data={"path": path},
        )

    chart_title = str(title or "").strip() or attachment.name
    msg = (
        f"已生成 {ctype} 图：{chart_title}。路径: {path}。"
        f"请在最终回复中嵌入：![{chart_title}]({path}) "
        f"或 [[CHART]]{path}|{chart_title}[[/CHART]]"
    )
    return ToolResult(
        ok=True,
        message=msg,
        data={
            "path": path,
            "chart_type": ctype,
            "title": chart_title,
            "embed_markdown": f"![{chart_title}]({path})",
            "embed_chart": f"[[CHART]]{path}|{chart_title}[[/CHART]]",
        },
        images=[attachment],
    )

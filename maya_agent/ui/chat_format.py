"""Chat message formatting: Qt-safe rich text + tool result summaries."""

from __future__ import annotations

import html
import json
import re
from typing import Any, Dict, List, Optional, Tuple


def escape(text: str) -> str:
    return html.escape(text or "", quote=False)


_CHOICES_BLOCK_RE = re.compile(
    r"\[\[CHOICES\]\]\s*(.*?)\s*\[\[/CHOICES\]\]",
    re.IGNORECASE | re.DOTALL,
)
_NUMBERED_ITEM_RE = re.compile(r"^\s*(\d+)[\.、\)]\s+(.+?)\s*$")
_CHOICE_HINT_RE = re.compile(
    r"(确认|请选择|请回复|是否|还是|选项|请告诉我|你想|要不要|"
    r"请问|哪(一种|个|种)|如何|怎么|哪种|哪边|"
    r"需要我|希望|更倾向|先确认|不清楚|不确定|"
    r"路径|命名|格式|方案|参数)",
    re.IGNORECASE,
)


def extract_user_choices(text: str) -> Tuple[str, List[Dict[str, str]]]:
    """
    Extract clickable reply choices from assistant text.

    Supports:
      1) Explicit block (preferred for any clarification / confirmation):
         [[CHOICES]]
         标签
         标签|自动发送的完整回复
         [[/CHOICES]]
      2) Trailing numbered list (1. / 1、 / 1)) when the message asks
         the user a question or seeks feedback.

    Returns (display_text, choices) where each choice is
    {"label": str, "reply": str}.
    """
    raw = text or ""
    if not raw.strip():
        return raw, []

    # --- Explicit block (preferred) ---
    match = _CHOICES_BLOCK_RE.search(raw)
    if match:
        choices: List[Dict[str, str]] = []
        for line in match.group(1).splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "|" in line:
                label, reply = line.split("|", 1)
                label, reply = label.strip(), reply.strip()
            else:
                label, reply = line, line
            if label:
                choices.append({"label": label, "reply": reply or label})
        display = (_CHOICES_BLOCK_RE.sub("", raw)).strip()
        display = re.sub(r"\n{3,}", "\n\n", display)
        return display, choices[:6]

    # --- Heuristic: consecutive numbered options near the end ---
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    # Find runs of numbered items
    best: Optional[Tuple[int, int, List[Dict[str, str]]]] = None
    i = 0
    while i < len(lines):
        m = _NUMBERED_ITEM_RE.match(lines[i])
        if not m:
            i += 1
            continue
        start = i
        items: List[Dict[str, str]] = []
        expect = int(m.group(1))
        while i < len(lines):
            m2 = _NUMBERED_ITEM_RE.match(lines[i])
            if not m2:
                break
            num = int(m2.group(1))
            if items and num != expect:
                break
            label = m2.group(2).strip()
            # Strip leading「」 quotes noise
            items.append({"label": label, "reply": label})
            expect = num + 1
            i += 1
        end = i  # exclusive
        if len(items) >= 2:
            # Prefer runs closer to the end
            if best is None or start >= best[0]:
                best = (start, end, items)
        continue

    if not best:
        return raw, []

    start, end, items = best
    # Require confirmation-ish wording nearby (above or below the list)
    window = "\n".join(lines[max(0, start - 4) : min(len(lines), end + 3)])
    if not _CHOICE_HINT_RE.search(window):
        return raw, []
    # Only treat as choices if the run is in the last ~60% of the message
    if start < len(lines) * 0.35 and end < len(lines) - 2:
        return raw, []

    # Drop trailing "请回复…" lines right after the list
    drop_end = end
    while drop_end < len(lines) and re.match(
        r"^\s*(请回复.*|请选择.*|告诉我.*)?\s*$", lines[drop_end]
    ):
        if lines[drop_end].strip():
            if re.match(r"^\s*请(回复|选择)", lines[drop_end]):
                drop_end += 1
                break
            break
        drop_end += 1

    display_lines = lines[:start] + lines[drop_end:]
    display = "\n".join(display_lines).strip()
    display = re.sub(r"\n{3,}", "\n\n", display)
    # Keep a short hint that buttons are below
    if display and not display.endswith(("：", ":", "。", "？", "?")):
        display = display.rstrip() + "。"
    return display, items[:6]


def markdown_to_html(text: str) -> str:
    """
    Convert a markdown subset to HTML that Qt RichText actually renders well.

    Avoid relying on <ul>/<ol> CSS margins (often ignored by QLabel/QTextDocument).
    Lists are emitted as indented paragraphs with bullet glyphs.
    """
    if not text:
        return ""

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: List[str] = []
    i = 0
    in_table = False
    table_rows: List[List[str]] = []
    prev_blank = True

    def flush_table():
        nonlocal in_table, table_rows
        if not table_rows:
            in_table = False
            return
        cleaned = []
        for row in table_rows:
            if all(re.fullmatch(r":?-+:?", c.strip().replace(" ", "")) for c in row):
                continue
            cleaned.append(row)
        if not cleaned:
            table_rows = []
            in_table = False
            return
        html_rows = []
        for ri, row in enumerate(cleaned):
            tag = "th" if ri == 0 else "td"
            color = "#c4c4cc" if ri == 0 else "#e4e4ea"
            weight = "600" if ri == 0 else "400"
            border = "#3f4048"
            cells = "".join(
                f'<{tag} style="padding:5px 8px;border-bottom:1px solid {border};'
                f'color:{color};font-weight:{weight};text-align:left;">'
                f"{_inline(c.strip())}</{tag}>"
                for c in row
            )
            html_rows.append(f"<tr>{cells}</tr>")
        out.append(
            '<table width="100%" cellspacing="0" cellpadding="0" '
            'style="margin:4px 0 6px 0;">'
            + "".join(html_rows)
            + "</table>"
        )
        table_rows = []
        in_table = False

    def add_para(inner: str, *, top: int = 1, bottom: int = 1, left: int = 0):
        out.append(
            f'<p style="margin:{top}px 0 {bottom}px {left}px;line-height:135%;'
            f'color:#e8e8ea;">{inner}</p>'
        )

    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()

        # fenced code
        if line.strip().startswith("```"):
            flush_table()
            i += 1
            code_lines = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            code = escape("\n".join(code_lines))
            out.append(
                '<p style="margin:4px 0;padding:6px 8px;background-color:#1a1b20;'
                "color:#d0d0d6;font-family:Consolas,'Courier New',monospace;"
                f'font-size:12px;line-height:130%;">{code.replace(chr(10), "<br/>")}</p>'
            )
            prev_blank = False
            continue

        # markdown table
        if "|" in line and line.strip().startswith("|"):
            cells = [c for c in line.strip().strip("|").split("|")]
            if not in_table:
                in_table = True
                table_rows = []
            table_rows.append(cells)
            i += 1
            prev_blank = False
            continue
        else:
            flush_table()

        # blank line → paragraph gap
        if not line.strip():
            if not prev_blank:
                out.append('<p style="margin:0;padding:0;font-size:3px;color:transparent;">&nbsp;</p>')
            prev_blank = True
            i += 1
            continue

        # headers
        m = re.match(r"^(#{1,3})\s+(.*)$", line.strip())
        if m:
            level = len(m.group(1))
            size = {1: 15, 2: 14, 3: 13}[level]
            top = 8 if not prev_blank else 4
            out.append(
                f'<p style="margin:{top}px 0 3px 0;font-size:{size}px;font-weight:700;'
                f'color:#f2f2f5;line-height:130%;">{_inline(m.group(2))}</p>'
            )
            prev_blank = False
            i += 1
            continue

        # unordered / nested list (indent by leading spaces)
        m = re.match(r"^(\s*)([-*•])\s+(.*)$", raw)
        if m:
            indent_spaces = len(m.group(1).replace("\t", "    "))
            level = min(indent_spaces // 2, 3)
            body = m.group(3)
            left = 6 + level * 14
            bullet = "•" if level == 0 else "–"
            top = 3 if prev_blank else 1
            add_para(
                f'<span style="color:#8a8a93;">{bullet}</span>&nbsp;&nbsp;{_inline(body)}',
                top=top,
                bottom=1,
                left=left,
            )
            prev_blank = False
            i += 1
            continue

        # ordered list
        m = re.match(r"^(\s*)(\d+)[.)]\s+(.*)$", raw)
        if m:
            indent_spaces = len(m.group(1).replace("\t", "    "))
            level = min(indent_spaces // 2, 3)
            num = m.group(2)
            body = m.group(3)
            left = 6 + level * 14
            top = 3 if prev_blank else 1
            add_para(
                f'<span style="color:#8a8a93;">{num}.</span>&nbsp;&nbsp;{_inline(body)}',
                top=top,
                bottom=1,
                left=left,
            )
            prev_blank = False
            i += 1
            continue

        # section label like "对象统计：" / "**汇总**"
        stripped = line.strip()
        top = 6 if not prev_blank else 2
        # slightly emphasize labels ending with fullwidth/halfwidth colon
        if re.search(r"[：:]$", stripped) and len(stripped) <= 40:
            add_para(
                f'<span style="color:#c8c8d0;font-weight:600;">{_inline(stripped)}</span>',
                top=top,
                bottom=1,
                left=0,
            )
        else:
            add_para(_inline(stripped), top=top, bottom=2, left=0)
        prev_blank = False
        i += 1

    flush_table()
    return (
        '<div style="color:#e8e8ea;font-size:13px;">'
        + "".join(out)
        + "</div>"
    )


def _inline(text: str) -> str:
    """Inline markdown: code, bold, italic."""
    s = escape(text)
    # strip accidental leading pipe often seen in Maya long names pasted as `|node`
    # keep content, soften code look
    s = re.sub(
        r"`([^`]+)`",
        lambda m: (
            '<span style="background-color:#32333c;color:#dcc9a0;padding:0 4px;'
            f'font-family:Consolas,monospace;font-size:12px;">{_clean_code(m.group(1))}</span>'
        ),
        s,
    )
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", s)
    return s


def _clean_code(raw: str) -> str:
    t = escape(raw.strip())
    # Maya DAG path often starts with | — keep last short name readable
    if t.startswith("|") and "|" in t[1:]:
        t = t.split("|")[-1]
    elif t.startswith("|"):
        t = t[1:]
    return t


def summarize_tool_result_views(
    name: str, result_json: str
) -> Tuple[str, str, str, bool, bool]:
    """
    Returns (title, preview_html, full_html, ok, needs_expand).
    preview_html is a shortened view for the chat card.
    """
    title, full, ok, plain_len = _summarize_tool_result_impl(
        name, result_json, compact=False
    )
    _, preview, _, _preview_len = _summarize_tool_result_impl(
        name, result_json, compact=True
    )
    needs = preview != full or plain_len > 360
    return title, preview, full, ok, needs


def _summarize_tool_result_impl(
    name: str, result_json: str, *, compact: bool
) -> Tuple[str, str, bool, int]:
    """Returns (title, body_html, ok, plain_text_length)."""
    try:
        data = json.loads(result_json) if result_json else {}
    except json.JSONDecodeError:
        raw = result_json or ""
        preview = escape(raw[:300] + ("…" if len(raw) > 300 else ""))
        body = f'<p style="margin:2px 0;color:#b0b0b8;font-size:11px;">{preview}</p>'
        return f"工具 {escape(name)}", body, False, len(raw)

    ok = bool(data.get("ok", True))
    message = data.get("message") or ""
    error = data.get("error") or ""
    payload = data.get("data")

    title = f"{'完成' if ok else '失败'} · {escape(name)}"
    parts: List[str] = []
    if message:
        parts.append(
            f'<p style="margin:0 0 4px 0;color:#d0d0d6;">{escape(message)}</p>'
        )
    if error:
        parts.append(
            f'<p style="margin:0 0 4px 0;color:#e07070;">{escape(str(error))}</p>'
        )

    summary = _format_payload(name, payload, compact=compact)
    if summary:
        parts.append(summary)
    elif payload is not None:
        dump = json.dumps(payload, ensure_ascii=False, indent=2)
        limit = 280 if compact else 4000
        clipped = dump[:limit] + ("…" if len(dump) > limit else "")
        compact_html = escape(clipped)
        parts.append(
            f'<p style="margin:4px 0 0 0;color:#a8a8b0;font-size:11px;'
            f'font-family:Consolas,monospace;">{compact_html.replace(chr(10), "<br/>")}</p>'
        )

    body = "".join(parts) or "<i>无返回数据</i>"
    plain = re.sub(r"<[^>]+>", " ", body)
    plain = html.unescape(re.sub(r"\s+", " ", plain)).strip()
    return title, body, ok, len(plain)


def _format_payload(name: str, payload: Any, *, compact: bool = True) -> str:
    if payload is None:
        return ""

    clip = 160 if compact else 8000

    if name == "get_scene_info" and isinstance(payload, dict):
        counts = payload.get("counts") or {}
        sel = payload.get("selection") or []
        sel_txt = (
            "、".join(_short_name(s) for s in sel[:8]) if sel else "无"
        )
        rows = [
            ("文件", payload.get("file", "")),
            ("Maya", payload.get("maya_version", "")),
            ("单位", f"{payload.get('units', '')} / {payload.get('time_unit', '')}"),
            (
                "统计",
                f"网格 {counts.get('meshes', 0)} · 变换 {counts.get('transforms', 0)} · "
                f"骨骼 {counts.get('joints', 0)} · 灯光 {counts.get('lights', 0)} · "
                f"相机 {counts.get('cameras', 0)}",
            ),
            ("选择", sel_txt),
        ]
        return _kv_table(rows, clip=clip)

    if name == "get_mesh_stats" and isinstance(payload, dict):
        return _kv_table(
            [
                ("对象", _short_name(payload.get("node", ""))),
                ("顶点", payload.get("vertices", "")),
                ("边", payload.get("edges", "")),
                ("面", payload.get("faces", "")),
                ("三角面", payload.get("triangles", "")),
                ("UV", payload.get("uvs", "")),
            ],
            clip=clip,
        )

    if name in ("execute_python", "execute_mel") and isinstance(payload, dict):
        rows = []
        for key in ("result", "stdout", "stderr", "traceback"):
            if key not in payload:
                continue
            val = payload.get(key)
            if val is None or val == "":
                continue
            rows.append((key, val))
        if rows:
            return _kv_table(rows, clip=clip)
        return ""

    if isinstance(payload, list):
        if not payload:
            return '<p style="margin:2px 0;color:#b0b0b8;">空列表</p>'
        limit = 8 if compact else 40
        items = "、".join(escape(_short_name(x)) for x in payload[:limit])
        more = f" 等 {len(payload)} 项" if len(payload) > limit else ""
        return f'<p style="margin:2px 0;color:#d0d0d6;">{items}{more}</p>'

    if isinstance(payload, dict):
        if len(payload) <= 8 and all(
            not isinstance(v, (dict, list)) or (isinstance(v, list) and len(v) < 5)
            for v in payload.values()
        ):
            rows = []
            for k, v in payload.items():
                if isinstance(v, list):
                    v = "、".join(_short_name(i) for i in v[:6])
                rows.append((str(k), v))
            return _kv_table(rows, clip=clip)

    if isinstance(payload, (str, int, float, bool)):
        text = _clip_text(_short_name(payload), clip)
        return f'<p style="margin:2px 0;color:#d0d0d6;">{escape(text)}</p>'

    return ""


def _clip_text(value: Any, limit: int) -> str:
    s = str(value)
    if limit <= 0 or len(s) <= limit:
        return s
    return s[: max(0, limit - 1)].rstrip() + "…"


def _short_name(value: Any) -> str:
    s = str(value)
    if "|" in s:
        s = s.split("|")[-1]
    return s


def _kv_table(rows: List[Tuple[str, Any]], clip: int = 160) -> str:
    trs = []
    for k, v in rows:
        text = _clip_text(v, clip)
        # Preserve newlines in long script output for readability
        cell = escape(text).replace("\n", "<br/>")
        trs.append(
            "<tr>"
            f'<td style="color:#8e8e98;padding:2px 12px 2px 0;white-space:nowrap;'
            f'vertical-align:top;font-size:11px;">{escape(str(k))}</td>'
            f'<td style="color:#e0e0e6;padding:2px 0;font-size:11px;'
            f'vertical-align:top;font-family:Consolas,monospace;">{cell}</td>'
            "</tr>"
        )
    return (
        '<table cellspacing="0" cellpadding="0" style="margin:2px 0;border:none;">'
        + "".join(trs)
        + "</table>"
    )

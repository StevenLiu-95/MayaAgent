"""Composer @-mention picker (Cursor-style) and send-time expansion."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from maya_agent.i18n import t

# Canonical token kinds (English; Chinese aliases still accepted).
KIND_TOOL = "tool"
KIND_OBJECT = "object"
KIND_SESSION = "session"

_KIND_ALIASES = {
    "工具": KIND_TOOL,
    "tool": KIND_TOOL,
    "对象": KIND_OBJECT,
    "object": KIND_OBJECT,
    "obj": KIND_OBJECT,
    "会话": KIND_SESSION,
    "session": KIND_SESSION,
    "chat": KIND_SESSION,
}

# @tool:name  @object:path  @session:title_or_id  (+ Chinese aliases)
_TOKEN_RE = re.compile(
    r"@(?P<kind>工具|对象|会话|tool|object|obj|session|chat):"
    r"(?P<value>[^\s@]+)",
    re.UNICODE,
)

_SCENE_LIST_LIMIT = 300


@dataclass
class MentionToken:
    kind: str
    value: str
    start: int
    end: int
    raw: str

    @property
    def display(self) -> str:
        return f"@{self.kind}:{self.value}"


@dataclass
class MentionItem:
    """One row in the mention popup list."""

    key: str
    label: str
    insert: str
    detail: str = ""
    category_id: str = ""
    is_category: bool = False
    has_children: bool = False


def normalize_kind(kind: str) -> str:
    raw = (kind or "").strip()
    return _KIND_ALIASES.get(raw.lower(), _KIND_ALIASES.get(raw, raw))


def parse_mentions(text: str) -> List[MentionToken]:
    """Extract @-mention tokens from composer / agent text."""
    out: List[MentionToken] = []
    if not text:
        return out
    for m in _TOKEN_RE.finditer(text):
        kind = normalize_kind(m.group("kind"))
        value = (m.group("value") or "").strip()
        if not kind or not value:
            continue
        out.append(
            MentionToken(
                kind=kind,
                value=value,
                start=m.start(),
                end=m.end(),
                raw=m.group(0),
            )
        )
    return out


def format_token(kind: str, value: str) -> str:
    return f"@{normalize_kind(kind)}:{(value or '').strip()}"


def _short_name(path: str) -> str:
    path = (path or "").strip()
    if not path:
        return ""
    return path.rsplit("|", 1)[-1]


def _session_summary(session: Any, max_chars: int = 80) -> str:
    memory = getattr(session, "memory", None) or []
    for msg in memory:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "user":
            continue
        content = msg.get("content") or ""
        if isinstance(content, list):
            parts = []
            for p in content:
                if isinstance(p, dict) and p.get("type") == "text":
                    parts.append(str(p.get("text") or ""))
                elif isinstance(p, str):
                    parts.append(p)
            content = "".join(parts)
        text = str(content).strip().replace("\n", " ")
        if text:
            return text if len(text) <= max_chars else text[: max_chars - 1] + "…"
    return ""


def _lookup_session(session_manager: Any, value: str) -> Any:
    if session_manager is None:
        return None
    sessions = list(session_manager.list_sessions() or [])
    raw = (value or "").strip()
    title = raw
    sid = ""
    if "#" in raw:
        title, sid = raw.rsplit("#", 1)
        title = title.strip()
        sid = sid.strip()
    if sid:
        for s in sessions:
            if getattr(s, "id", "") == sid:
                return s
    for s in sessions:
        if getattr(s, "id", "") == raw:
            return s
    matches = [s for s in sessions if getattr(s, "title", "") == title]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1 and sid:
        for s in matches:
            if getattr(s, "id", "") == sid:
                return s
    return matches[0] if matches else None


def _maya_node_info(name: str) -> Optional[Dict[str, Any]]:
    """Resolve a scene node on the Maya main thread. Returns None outside Maya."""
    try:
        from maya_agent.utils.maya_compat import in_maya, run_on_main_thread
    except Exception:
        return None
    if not in_maya():
        return None

    def _query() -> Optional[Dict[str, Any]]:
        try:
            from maya_agent.tools._maya import cmds

            c = cmds()
            if c is None:
                return None
            targets = c.ls(name, long=True) or []
            if not targets and "|" not in name:
                targets = c.ls(name, long=True) or c.ls(f"*|{name}", long=True) or []
            if not targets:
                # Exact long-name try
                if c.objExists(name):
                    targets = c.ls(name, long=True) or [name]
            if not targets:
                return None
            path = targets[0]
            node_type = ""
            try:
                node_type = c.nodeType(path) or ""
            except Exception:
                node_type = ""
            selected = False
            try:
                sel = set(c.ls(selection=True, long=True) or [])
                selected = path in sel or name in sel
            except Exception:
                selected = False
            return {
                "path": path,
                "short": _short_name(path),
                "type": node_type,
                "selected": selected,
            }
        except Exception:
            return None

    try:
        return run_on_main_thread(_query)
    except Exception:
        return None


def _list_scene_objects(query: str = "", limit: int = _SCENE_LIST_LIMIT) -> List[MentionItem]:
    try:
        from maya_agent.utils.maya_compat import in_maya, run_on_main_thread
    except Exception:
        return []
    if not in_maya():
        return []

    q = (query or "").strip().lower()

    def _query() -> List[Tuple[str, str]]:
        try:
            from maya_agent.tools._maya import cmds

            c = cmds()
            if c is None:
                return []
            paths = c.ls(dag=True, transforms=True, long=True) or []
            rows: List[Tuple[str, str]] = []
            for path in paths:
                short = _short_name(path)
                if q and q not in short.lower() and q not in path.lower():
                    continue
                rows.append((short or path, path))
                if len(rows) >= limit:
                    break
            return rows
        except Exception:
            return []

    try:
        rows = run_on_main_thread(_query) or []
    except Exception:
        rows = []
    items: List[MentionItem] = []
    for short, path in rows:
        # Prefer short name; fall back to long path when ambiguous short names collide.
        insert_name = short
        items.append(
            MentionItem(
                key=path,
                label=short,
                insert=format_token(KIND_OBJECT, insert_name),
                detail=path if path != short else "",
                category_id="scene",
            )
        )
    # Disambiguate duplicate short names with long path insert.
    counts: Dict[str, int] = {}
    for it in items:
        counts[it.label] = counts.get(it.label, 0) + 1
    for it in items:
        if counts.get(it.label, 0) > 1:
            it.insert = format_token(KIND_OBJECT, it.key)
            it.detail = it.key
    return items


def _list_selection_objects() -> List[MentionItem]:
    try:
        from maya_agent.utils.maya_compat import in_maya, run_on_main_thread
    except Exception:
        return []
    if not in_maya():
        return []

    def _query() -> List[str]:
        try:
            from maya_agent.tools._maya import cmds

            c = cmds()
            if c is None:
                return []
            return list(c.ls(selection=True, long=True) or [])
        except Exception:
            return []

    try:
        paths = run_on_main_thread(_query) or []
    except Exception:
        paths = []
    items: List[MentionItem] = []
    shorts = [_short_name(p) for p in paths]
    counts: Dict[str, int] = {}
    for s in shorts:
        counts[s] = counts.get(s, 0) + 1
    for path, short in zip(paths, shorts):
        insert_name = path if counts.get(short, 0) > 1 else short
        items.append(
            MentionItem(
                key=path,
                label=short or path,
                insert=format_token(KIND_OBJECT, insert_name),
                detail=path if path != short else t("mention.selected"),
                category_id="selection",
            )
        )
    return items


def _list_tools(query: str = "") -> List[MentionItem]:
    from maya_agent.tools.registry import all_tools, ensure_tools_loaded

    ensure_tools_loaded()
    q = (query or "").strip().lower()
    items: List[MentionItem] = []
    for tool in sorted(all_tools(), key=lambda x: x.name.lower()):
        hay = f"{tool.name} {tool.category} {tool.description}".lower()
        if q and q not in hay:
            continue
        items.append(
            MentionItem(
                key=tool.name,
                label=tool.name,
                insert=format_token(KIND_TOOL, tool.name),
                detail=f"{tool.category} · {tool.description}",
                category_id="tools",
            )
        )
    return items


def _list_sessions(session_manager: Any, query: str = "") -> List[MentionItem]:
    if session_manager is None:
        return []
    q = (query or "").strip().lower()
    active_id = ""
    try:
        active_id = session_manager.active().id
    except Exception:
        active_id = ""
    # Detect duplicate titles for #id suffix.
    sessions = list(session_manager.list_sessions() or [])
    title_counts: Dict[str, int] = {}
    for s in sessions:
        title_counts[s.title] = title_counts.get(s.title, 0) + 1

    items: List[MentionItem] = []
    for s in sessions:
        title = s.title or s.id
        hay = f"{title} {s.id}".lower()
        if q and q not in hay:
            continue
        if title_counts.get(title, 0) > 1 or re.search(r"[\s@]", title):
            value = f"{title}#{s.id}" if not re.search(r"[\s@]", title) else s.id
            # Prefer id when title has whitespace / @.
            if re.search(r"[\s@]", title):
                value = s.id
            else:
                value = f"{title}#{s.id}"
        else:
            value = title
        detail_parts = []
        if s.id == active_id:
            detail_parts.append(t("mention.current_session"))
        n = len(getattr(s, "memory", None) or [])
        if n:
            detail_parts.append(t("mention.session_msgs", n=n))
        items.append(
            MentionItem(
                key=s.id,
                label=title,
                insert=format_token(KIND_SESSION, value),
                detail=" · ".join(detail_parts),
                category_id="sessions",
            )
        )
    return items


def category_items() -> List[MentionItem]:
    return [
        MentionItem(
            key="tools",
            label=t("mention.cat.tools"),
            insert="",
            detail=t("mention.cat.tools_hint"),
            category_id="tools",
            is_category=True,
            has_children=True,
        ),
        MentionItem(
            key="scene",
            label=t("mention.cat.scene"),
            insert="",
            detail=t("mention.cat.scene_hint"),
            category_id="scene",
            is_category=True,
            has_children=True,
        ),
        MentionItem(
            key="selection",
            label=t("mention.cat.selection"),
            insert="",
            detail=t("mention.cat.selection_hint"),
            category_id="selection",
            is_category=True,
            has_children=True,
        ),
        MentionItem(
            key="sessions",
            label=t("mention.cat.sessions"),
            insert="",
            detail=t("mention.cat.sessions_hint"),
            category_id="sessions",
            is_category=True,
            has_children=True,
        ),
    ]


def list_mention_items(
    category_id: str,
    query: str = "",
    session_manager: Any = None,
) -> List[MentionItem]:
    if category_id == "tools":
        return _list_tools(query)
    if category_id == "scene":
        return _list_scene_objects(query)
    if category_id == "selection":
        items = _list_selection_objects()
        q = (query or "").strip().lower()
        if q:
            items = [
                it
                for it in items
                if q in it.label.lower() or q in (it.detail or "").lower()
            ]
        return items
    if category_id == "sessions":
        return _list_sessions(session_manager, query)
    return []


_SEARCH_LIMIT = 40


def _filter_categories(query: str) -> List[MentionItem]:
    q = (query or "").strip().lower()
    items = category_items()
    if not q:
        return items
    return [
        it
        for it in items
        if q in it.label.lower()
        or q in it.key.lower()
        or q in (it.detail or "").lower()
    ]


def search_mentions(
    query: str,
    *,
    session_manager: Any = None,
    limit: int = _SEARCH_LIMIT,
) -> List[MentionItem]:
    """
    Cross-category search used while typing after ``@`` (before picking a category).

    Empty query → category menu only.
    Non-empty → matching categories (if any) + tools / selection / scene / sessions.
    """
    q = (query or "").strip()
    if not q:
        return category_items()

    out: List[MentionItem] = []
    seen: set = set()

    def _add(items: List[MentionItem]) -> None:
        for it in items:
            key = (it.category_id, it.key, it.insert)
            if key in seen:
                continue
            seen.add(key)
            out.append(it)

    # Keep drill-in categories when the query matches their labels (e.g. "@工").
    _add(_filter_categories(q))

    _add(_list_tools(q))
    _add(
        [
            it
            for it in _list_selection_objects()
            if q.lower() in it.label.lower() or q.lower() in (it.detail or "").lower()
        ]
    )
    _add(_list_scene_objects(q))
    _add(_list_sessions(session_manager, q))

    if limit and len(out) > limit:
        # Prefer concrete inserts over category rows when trimming.
        cats = [it for it in out if it.is_category]
        rest = [it for it in out if not it.is_category][: max(0, limit - len(cats))]
        out = cats + rest
    return out


def expand_mentions(
    text: str,
    *,
    session_manager: Any = None,
) -> str:
    """Build a localized reference block for tokens found in ``text``."""
    tokens = parse_mentions(text)
    if not tokens:
        return ""

    seen = set()
    unique: List[MentionToken] = []
    for tok in tokens:
        key = (tok.kind, tok.value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(tok)

    lines: List[str] = [t("mention.ref.header")]
    for tok in unique:
        if tok.kind == KIND_TOOL:
            from maya_agent.tools.registry import ensure_tools_loaded, get_tool

            ensure_tools_loaded()
            reg = get_tool(tok.value)
            if reg:
                lines.append(
                    t(
                        "mention.ref.tool",
                        name=reg.name,
                        description=reg.description,
                        category=reg.category,
                    )
                )
            else:
                lines.append(t("mention.ref.tool_missing", name=tok.value))
        elif tok.kind == KIND_OBJECT:
            info = _maya_node_info(tok.value)
            if info:
                sel = (
                    t("yes") if info.get("selected") else t("no")
                )
                lines.append(
                    t(
                        "mention.ref.object",
                        name=info.get("short") or tok.value,
                        type=info.get("type") or "?",
                        path=info.get("path") or tok.value,
                        selected=sel,
                    )
                )
            else:
                lines.append(t("mention.ref.object_missing", name=tok.value))
        elif tok.kind == KIND_SESSION:
            session = _lookup_session(session_manager, tok.value)
            if session is not None:
                n = len(getattr(session, "memory", None) or [])
                summary = _session_summary(session) or t("mention.ref.no_user_msg")
                lines.append(
                    t(
                        "mention.ref.session",
                        title=session.title,
                        id=session.id,
                        n=n,
                        summary=summary,
                    )
                )
            else:
                lines.append(t("mention.ref.session_missing", name=tok.value))
        else:
            lines.append(
                t("mention.ref.unknown", kind=tok.kind, value=tok.value)
            )
    return "\n".join(lines) if len(lines) > 1 else ""


# Qt UI classes are built lazily so parse/expand stay importable without PySide.
MentionPopup = None  # type: ignore[misc, assignment]
MentionController = None  # type: ignore[misc, assignment]


def _ensure_ui_classes() -> Tuple[Any, Any]:
    global MentionPopup, MentionController
    if MentionPopup is not None and MentionController is not None:
        return MentionPopup, MentionController

    from maya_agent.ui.qt_bind import QtCore, QtGui, QtWidgets

    class _MentionPopup(QtWidgets.QFrame):
        """Floating list used by MentionController.

        Must NOT use ``Qt.Popup``: that steals keyboard focus from the composer
        and makes typing after ``@`` feel stuck / as if input exited.
        """

        item_activated = QtCore.Signal(object)  # MentionItem
        cancelled = QtCore.Signal()

        def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
            # Tool + no-activate: float above composer without taking focus.
            flags = QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint
            try:
                flags |= QtCore.Qt.WindowStaysOnTopHint
            except Exception:
                pass
            try:
                flags |= QtCore.Qt.WindowDoesNotAcceptFocus
            except Exception:
                pass
            super().__init__(parent, flags)
            self.setObjectName("mentionPopup")
            self.setFocusPolicy(QtCore.Qt.NoFocus)
            try:
                self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
            except Exception:
                pass
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(4, 4, 4, 4)
            lay.setSpacing(2)
            self._header = QtWidgets.QLabel("")
            self._header.setObjectName("mentionHeader")
            self._header.setFocusPolicy(QtCore.Qt.NoFocus)
            self._header.hide()
            lay.addWidget(self._header)
            self.list = QtWidgets.QListWidget()
            self.list.setObjectName("mentionList")
            self.list.setFocusPolicy(QtCore.Qt.NoFocus)
            self.list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            try:
                self.list.setAttribute(QtCore.Qt.WA_MacShowFocusRect, False)
            except Exception:
                pass
            self.list.itemClicked.connect(self._on_click)
            self.list.itemDoubleClicked.connect(self._on_click)
            lay.addWidget(self.list)
            self._empty = QtWidgets.QLabel(t("mention.empty"))
            self._empty.setObjectName("mentionEmpty")
            self._empty.setFocusPolicy(QtCore.Qt.NoFocus)
            self._empty.setWordWrap(True)
            self._empty.hide()
            lay.addWidget(self._empty)
            self.setFixedWidth(320)
            self._items: List[MentionItem] = []

        def set_header(self, text: str) -> None:
            if text:
                self._header.setText(text)
                self._header.show()
            else:
                self._header.hide()

        def set_items(self, items: Sequence[MentionItem]) -> None:
            self._items = list(items)
            self.list.clear()
            if not self._items:
                self.list.hide()
                self._empty.setText(t("mention.empty"))
                self._empty.show()
                self.adjustSize()
                return
            self._empty.hide()
            self.list.show()
            for it in self._items:
                label = it.label
                if it.has_children:
                    label = f"{label}  ›"
                row = QtWidgets.QListWidgetItem(label)
                if it.detail:
                    row.setToolTip(it.detail)
                row.setData(QtCore.Qt.UserRole, it)
                self.list.addItem(row)
            self.list.setCurrentRow(0)
            visible = min(10, len(self._items))
            row_h = self.list.sizeHintForRow(0) if self.list.count() else 24
            if row_h <= 0:
                row_h = 24
            self.list.setFixedHeight(visible * row_h + 4)
            self.adjustSize()

        def current_item(self) -> Optional[MentionItem]:
            row = self.list.currentRow()
            if 0 <= row < len(self._items):
                return self._items[row]
            return None

        def move_selection(self, delta: int) -> None:
            if not self._items:
                return
            row = self.list.currentRow()
            if row < 0:
                row = 0
            row = (row + delta) % len(self._items)
            self.list.setCurrentRow(row)

        def _on_click(self, item: QtWidgets.QListWidgetItem) -> None:
            data = item.data(QtCore.Qt.UserRole)
            if isinstance(data, MentionItem):
                self.item_activated.emit(data)

        def activate_current(self) -> bool:
            it = self.current_item()
            if it is None:
                return False
            self.item_activated.emit(it)
            return True

    class _MentionController(QtCore.QObject):
        """Owns popup state for a composer QPlainTextEdit."""

        def __init__(
            self,
            edit: QtWidgets.QPlainTextEdit,
            *,
            session_manager_provider: Optional[Callable[[], Any]] = None,
            parent: Optional[QtCore.QObject] = None,
        ) -> None:
            super().__init__(parent or edit)
            self.edit = edit
            self._session_manager_provider = session_manager_provider
            self.popup = MentionPopup(edit.window())
            self.popup.item_activated.connect(self._on_item_activated)
            self.popup.cancelled.connect(self.close)
            self._mode = "categories"  # categories | items
            self._category_id = ""
            self._trigger_pos = -1  # document position of '@'
            self._active = False
            self._suppress_focus_close = False
            self.edit.textChanged.connect(self._on_text_changed)
            self.edit.cursorPositionChanged.connect(self._on_cursor_changed)
            self.edit.installEventFilter(self)

        def _sessions(self) -> Any:
            if not self._session_manager_provider:
                return None
            try:
                return self._session_manager_provider()
            except Exception:
                return None

        def is_open(self) -> bool:
            return bool(self._active and self.popup.isVisible())

        def close(self) -> None:
            self._active = False
            self._mode = "categories"
            self._category_id = ""
            self._trigger_pos = -1
            try:
                self.popup.hide()
            except Exception:
                pass

        def _mention_query(self) -> Optional[Tuple[int, str]]:
            cursor = self.edit.textCursor()
            pos = cursor.position()
            text = self.edit.toPlainText()
            if pos <= 0 or pos > len(text):
                return None
            i = pos - 1
            while i >= 0:
                ch = text[i]
                if ch == "@":
                    if i > 0 and not text[i - 1].isspace():
                        return None
                    return i, text[i + 1 : pos]
                if ch.isspace() or ch in "\n\r":
                    return None
                i -= 1
            return None

        def _on_text_changed(self) -> None:
            self._sync_from_editor()

        def _on_cursor_changed(self) -> None:
            if self._active:
                self._sync_from_editor()

        def _sync_from_editor(self) -> None:
            ctx = self._mention_query()
            if ctx is None:
                if self._active:
                    self.close()
                return
            at_pos, query = ctx
            self._trigger_pos = at_pos
            if re.match(
                r"^(工具|对象|会话|tool|object|obj|session|chat):",
                query,
                re.IGNORECASE,
            ):
                if ":" in query and not query.endswith(":"):
                    if self._mode != "items":
                        self.close()
                        return
            self._active = True
            if self._mode == "items" and self._category_id:
                self._show_items(self._category_id, query)
            else:
                self._mode = "categories"
                self._category_id = ""
                self._show_categories(query)
            self._reposition()

        def open_at_cursor(self) -> None:
            self._mode = "categories"
            self._category_id = ""
            self._sync_from_editor()

        def _keep_edit_focus(self) -> None:
            """Popup must never leave the composer unable to type."""
            try:
                if not self.edit.hasFocus():
                    self.edit.setFocus(QtCore.Qt.OtherFocusReason)
            except Exception:
                try:
                    self.edit.setFocus()
                except Exception:
                    pass

        def _show_popup(self) -> None:
            self._suppress_focus_close = True
            try:
                if not self.popup.isVisible():
                    self.popup.show()
                self._reposition()
            finally:
                # Defer focus restore: show() can still shuffle focus on some Qt builds.
                QtCore.QTimer.singleShot(0, self._finish_show_popup)

        def _finish_show_popup(self) -> None:
            self._keep_edit_focus()
            self._suppress_focus_close = False

        def _show_categories(self, query: str) -> None:
            # Bare "@" → category menu. Typing after "@" → cross-search
            # (tools / selection / scene / sessions), so "@adv" finds adv_* tools.
            items = search_mentions(query, session_manager=self._sessions())
            header = ""
            if (query or "").strip():
                header = t("mention.search_header")
            self.popup.set_header(header)
            self.popup.set_items(items)
            self._show_popup()

        def _show_items(self, category_id: str, query: str) -> None:
            items = list_mention_items(
                category_id, query=query, session_manager=self._sessions()
            )
            header_map = {
                "tools": t("mention.cat.tools"),
                "scene": t("mention.cat.scene"),
                "selection": t("mention.cat.selection"),
                "sessions": t("mention.cat.sessions"),
            }
            self.popup.set_header(header_map.get(category_id, category_id))
            if category_id == "selection" and not items and not (query or "").strip():
                self.popup.set_items([])
                self.popup._empty.setText(t("mention.no_selection"))
                self.popup._empty.show()
                self.popup.list.hide()
                self.popup.adjustSize()
            else:
                self.popup.set_items(items)
            self._show_popup()

        def _reposition(self) -> None:
            if not self._active and not self.popup.isVisible():
                return
            cursor = self.edit.textCursor()
            if self._trigger_pos >= 0:
                cursor.setPosition(self._trigger_pos)
            rect = self.edit.cursorRect(cursor)
            global_bl = self.edit.mapToGlobal(rect.bottomLeft())
            global_tl = self.edit.mapToGlobal(rect.topLeft())
            popup_h = max(self.popup.sizeHint().height(), self.popup.height())
            x = global_tl.x()
            y = global_tl.y() - popup_h - 4
            if y < 0:
                y = global_bl.y() + 4
            self.popup.move(x, max(0, y))

        def eventFilter(self, obj, event):  # noqa: N802
            if obj is self.edit and event.type() == QtCore.QEvent.FocusOut:
                if self._suppress_focus_close or not self._active:
                    return False
                # Close when focus leaves composer (click elsewhere). Clicks on the
                # non-activating popup usually do not steal edit focus.
                QtCore.QTimer.singleShot(0, self._close_if_edit_unfocused)
            return False

        def _close_if_edit_unfocused(self) -> None:
            if self._suppress_focus_close:
                return
            try:
                if self.edit.hasFocus():
                    return
            except Exception:
                return
            if self._active:
                self.close()

        def _on_item_activated(self, item: MentionItem) -> None:
            if item.is_category or item.has_children:
                self._mode = "items"
                self._category_id = item.category_id or item.key
                self._replace_query("")
                self._show_items(self._category_id, "")
                self._reposition()
                self.edit.setFocus()
                return
            self._insert_token(item.insert)
            self.close()
            self.edit.setFocus()

        def _replace_query(self, new_query: str) -> None:
            if self._trigger_pos < 0:
                return
            cursor = self.edit.textCursor()
            cursor.beginEditBlock()
            cursor.setPosition(self._trigger_pos)
            cursor.setPosition(
                self.edit.textCursor().position(), QtGui.QTextCursor.KeepAnchor
            )
            cursor.insertText("@" + new_query)
            cursor.endEditBlock()
            self.edit.setTextCursor(cursor)

        def _insert_token(self, token: str) -> None:
            if not token:
                return
            cursor = self.edit.textCursor()
            end = cursor.position()
            start = self._trigger_pos if self._trigger_pos >= 0 else end
            cursor.beginEditBlock()
            cursor.setPosition(start)
            cursor.setPosition(end, QtGui.QTextCursor.KeepAnchor)
            insert = token if token.endswith(" ") else token + " "
            cursor.insertText(insert)
            cursor.endEditBlock()
            self.edit.setTextCursor(cursor)

        def handle_key(self, event: QtGui.QKeyEvent) -> bool:
            key = event.key()
            if not self.is_open():
                return False

            if key == QtCore.Qt.Key_Escape:
                if self._mode == "items":
                    self._mode = "categories"
                    self._category_id = ""
                    self._replace_query("")
                    self._show_categories("")
                    self._reposition()
                else:
                    self.close()
                return True
            if key == QtCore.Qt.Key_Up:
                self.popup.move_selection(-1)
                return True
            if key == QtCore.Qt.Key_Down:
                self.popup.move_selection(1)
                return True
            if key in (QtCore.Qt.Key_Right, QtCore.Qt.Key_Tab):
                it = self.popup.current_item()
                if it and (it.is_category or it.has_children):
                    self._on_item_activated(it)
                    return True
                if key == QtCore.Qt.Key_Tab:
                    return self.popup.activate_current()
                return False
            if key == QtCore.Qt.Key_Left:
                if self._mode == "items":
                    self._mode = "categories"
                    self._category_id = ""
                    self._replace_query("")
                    self._show_categories("")
                    self._reposition()
                    return True
                return False
            if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                return self.popup.activate_current()
            return False

    MentionPopup = _MentionPopup
    MentionController = _MentionController
    return MentionPopup, MentionController


def __getattr__(name: str) -> Any:
    if name in ("MentionPopup", "MentionController"):
        popup, controller = _ensure_ui_classes()
        return popup if name == "MentionPopup" else controller
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

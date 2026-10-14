"""Shared layout helpers for settings-style panels."""

from __future__ import annotations

from maya_agent.ui.qt_bind import QtCore, QtWidgets
from maya_agent.ui.qt_wheel import redirect_wheel_to_parent_scroll


class _NoWheelValueFilter(QtCore.QObject):
    """Block wheel-driven value changes; forward wheel to the nearest scroll area."""

    # Intentionally omit QAbstractSlider — that includes QScrollBar and would
    # swallow page scrolling when the filter is installed on scrollbars.
    _TYPES = (
        QtWidgets.QComboBox,
        QtWidgets.QAbstractSpinBox,
    )

    def eventFilter(self, obj, event):
        if event.type() != QtCore.QEvent.Wheel:
            return False
        w = obj if isinstance(obj, QtWidgets.QWidget) else None
        hit = None
        while w is not None:
            if isinstance(w, self._TYPES):
                hit = w
                break
            w = w.parentWidget()
        if hit is None:
            return False
        if redirect_wheel_to_parent_scroll(hit, event):
            return True
        # No scrollable ancestor — still block value changes.
        try:
            event.accept()
        except Exception:
            pass
        return True


def suppress_wheel_value_changes(root: QtWidgets.QWidget) -> None:
    """Disable mouse-wheel value changes on combo / spin under ``root``."""
    if root is None:
        return
    filt = getattr(root, "_no_wheel_value_filter", None)
    if filt is None:
        filt = _NoWheelValueFilter(root)
        root._no_wheel_value_filter = filt
    seen = set()
    for w in root.findChildren(QtWidgets.QWidget):
        if not isinstance(w, _NoWheelValueFilter._TYPES):
            continue
        wid = id(w)
        if wid in seen:
            continue
        seen.add(wid)
        w.installEventFilter(filt)
        try:
            editor = w.lineEdit() if hasattr(w, "lineEdit") else None
        except Exception:
            editor = None
        if editor is not None:
            editor.installEventFilter(filt)


class SettingsFormMixin:
    """Scroll page / section / form helpers shared by LLM and UI settings panels."""

    def _scroll_page(self):
        page = QtWidgets.QWidget()
        page.setObjectName("settingsPage")
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        root = QtWidgets.QVBoxLayout(page)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)
        root.setAlignment(QtCore.Qt.AlignTop)
        return scroll, root

    def _section(self, title: str, hint: str = ""):
        box = QtWidgets.QFrame()
        box.setObjectName("settingsSection")
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(10)

        head = QtWidgets.QVBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(3)
        title_lbl = QtWidgets.QLabel(title)
        title_lbl.setObjectName("settingsSectionTitle")
        head.addWidget(title_lbl)
        if hint:
            hint_lbl = QtWidgets.QLabel(hint)
            hint_lbl.setObjectName("settingsSectionHint")
            hint_lbl.setWordWrap(True)
            head.addWidget(hint_lbl)
        lay.addLayout(head)
        return box, lay

    def _form(self, parent_layout):
        form = QtWidgets.QFormLayout()
        form.setContentsMargins(0, 2, 0, 0)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        form.setFormAlignment(QtCore.Qt.AlignTop)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        parent_layout.addLayout(form)
        return form

    def _field_label(self, text: str):
        lbl = QtWidgets.QLabel(text)
        lbl.setObjectName("settingsFieldLabel")
        return lbl

    def _option_row(self, checkbox, desc: str):
        row = QtWidgets.QWidget()
        row.setObjectName("settingsOptionRow")
        lay = QtWidgets.QVBoxLayout(row)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(2)
        checkbox.setObjectName("settingsCheck")
        lay.addWidget(checkbox)
        desc_lbl = QtWidgets.QLabel(desc)
        desc_lbl.setObjectName("settingsOptionHint")
        desc_lbl.setWordWrap(True)
        desc_lbl.setContentsMargins(22, 0, 0, 0)
        lay.addWidget(desc_lbl)
        return row

    def _stretch_end(self, layout) -> None:
        layout.addStretch(1)

    def _apply_no_wheel(self) -> None:
        """Call at end of panel build — combo / spin / slider ignore wheel."""
        suppress_wheel_value_changes(self)

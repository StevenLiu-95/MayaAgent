"""Wheel helpers: keep page scrolling without changing combo / spin values."""

from __future__ import annotations

from maya_agent.ui.qt_bind import QtWidgets


def redirect_wheel_to_parent_scroll(widget: QtWidgets.QWidget, event) -> bool:
    """
    Apply ``event`` delta to the nearest ancestor scroll area.

    Avoids ``sendEvent(viewport)`` (can re-hit the child under the cursor and
    swallow scrolling). Returns True if a scrollable ancestor consumed it.
    """
    if widget is None or event is None:
        return False
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QtWidgets.QAbstractScrollArea):
            # Skip nested editors (QTextBrowser / QPlainTextEdit inside bubbles).
            if parent is widget:
                parent = parent.parentWidget()
                continue
            if _scroll_area_by_wheel(parent, event):
                try:
                    event.accept()
                except Exception:
                    pass
                return True
            # Found a scroll area but it cannot move — keep walking upward.
        parent = parent.parentWidget()
    return False


def _scroll_area_by_wheel(area: QtWidgets.QAbstractScrollArea, event) -> bool:
    """Move vertical (else horizontal) bar by wheel delta. True if value changed."""
    moved = _nudge_bar(area.verticalScrollBar(), event, vertical=True)
    if moved:
        return True
    return _nudge_bar(area.horizontalScrollBar(), event, vertical=False)


def _nudge_bar(bar, event, *, vertical: bool) -> bool:
    if bar is None:
        return False
    try:
        if int(bar.maximum()) <= int(bar.minimum()):
            return False
    except Exception:
        return False

    delta = 0
    try:
        ad = event.angleDelta()
        delta = int(ad.y() if vertical else ad.x())
        if delta == 0:
            # Touchpads often put the primary delta on Y even for horizontal.
            delta = int(ad.y() if not vertical else ad.x())
    except Exception:
        delta = 0
    if delta == 0:
        try:
            pd = event.pixelDelta()
            delta = int(pd.y() if vertical else pd.x())
        except Exception:
            delta = 0
    if delta == 0:
        return False

    try:
        step = max(1, int(bar.singleStep() or 1))
        # 120° per notch → a few singleSteps; pixel deltas pass through scaled.
        if abs(delta) >= 120:
            nudge = -int(delta / 120) * step * 3
        else:
            nudge = -int(delta)
        before = int(bar.value())
        bar.setValue(before + nudge)
        return int(bar.value()) != before
    except Exception:
        return False

# -*- coding: utf-8 -*-
"""Unit tests for UV pure helpers (no Maya required)."""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_udim_offset():
    from maya_agent.tools._uv import udim_offset

    assert udim_offset(1001) == (0.0, 0.0)
    assert udim_offset(1002) == (1.0, 0.0)
    assert udim_offset(1011) == (0.0, 1.0)
    assert udim_offset(1001 + 10 + 2) == (2.0, 1.0)  # 1013
    assert udim_offset(999) == (0.0, 0.0)  # clamp


def test_aabb_and_tri_area():
    from maya_agent.tools._uv import _aabb_overlap, _tri_area_2d

    assert _aabb_overlap((0, 0, 1, 1), (0.5, 0.5, 1.5, 1.5))
    assert not _aabb_overlap((0, 0, 1, 1), (1.1, 1.1, 2, 2))
    area = _tri_area_2d((0, 0), (1, 0), (0, 1))
    assert math.isclose(area, 0.5, abs_tol=1e-9)
    assert _tri_area_2d((0, 0), (0, 1), (1, 0)) < 0


def test_cut_modes_constant():
    from maya_agent.tools._uv import CUT_MODES

    assert "hard" in CUT_MODES
    assert "none" in CUT_MODES
    assert "material" in CUT_MODES


if __name__ == "__main__":
    test_udim_offset()
    test_aabb_and_tri_area()
    test_cut_modes_constant()
    print("ok")

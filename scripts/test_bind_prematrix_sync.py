# -*- coding: utf-8 -*-
"""Offline checks for bindPreMatrix sync helpers (no Maya scene required)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maya_agent.tools.skin_weights import (
    _match_dest_influence_index,
    _matrix_flat,
)


def main() -> None:
    assert _matrix_flat(None) == []
    assert _matrix_flat(list(range(16))) == [float(i) for i in range(16)]
    assert _matrix_flat([list(range(16))]) == [float(i) for i in range(16)]
    assert _matrix_flat([[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11], [12, 13, 14, 15]]) == [
        float(i) for i in range(16)
    ]

    dst_by_long = {
        "|NS:Armature|NS:Hips": 0,
        "|NS:Armature|NS:Spine": 1,
    }
    dst_inf = ["|NS:Armature|NS:Hips", "|NS:Armature|NS:Spine"]
    assert _match_dest_influence_index("|NS:Armature|NS:Hips", dst_by_long, dst_inf) == 0
    assert _match_dest_influence_index("NS:Spine", dst_by_long, dst_inf) == 1
    assert _match_dest_influence_index("|Other|Missing", dst_by_long, dst_inf) is None

    # Ambiguous short names → None
    dst_inf2 = ["|A|Joint", "|B|Joint"]
    dst_by2 = {"|A|Joint": 0, "|B|Joint": 1}
    assert _match_dest_influence_index("Joint", dst_by2, dst_inf2) is None

    print("ok: bindPreMatrix helper unit checks passed")


if __name__ == "__main__":
    main()

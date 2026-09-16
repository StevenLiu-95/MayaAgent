"""Auto-generated skeleton template data (no ADV runtime dependency)."""
from __future__ import annotations

TEMPLATE_ID = "vehicle"
LABEL = "载具"
AVAILABLE = True
NEEDS_MIRROR = True

JOINTS = [
    {"name": "Root_M", "parent": None, "translate": (0.0, 2.0, 0.0), "orient": (90.0, 0.0, 90.0), "side": "M", "ik_role": "root", "radius": 1.435, "fat": 4.1},
    {"name": "frontWheel_R", "parent": "Root_M", "translate": (0.0, 6.0, -3.0), "orient": (90.0, 90.0, 0.0), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "frontWheelEnd_R", "parent": "frontWheel_R", "translate": (1.0, 0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "backWheel_R", "parent": "Root_M", "translate": (-0.0, -6.0, -3.0), "orient": (90.0, 90.0, 0.0), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "backWheelEnd_R", "parent": "backWheel_R", "translate": (1.0, 0.0, -0.0), "orient": (0.0, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "Body_M", "parent": "Root_M", "translate": (2.0, -0.0, -0.0), "orient": (0.0, 0.0, 0.0), "side": "M", "ik_role": "", "radius": 1.435, "fat": 4.1},
    {"name": "BodyEnd_R", "parent": "Body_M", "translate": (2.0, 0.0, -0.0), "orient": (0.0, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
]

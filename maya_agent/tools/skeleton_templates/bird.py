"""Auto-generated skeleton template data (no ADV runtime dependency)."""
from __future__ import annotations

TEMPLATE_ID = "bird"
LABEL = "鸟类"
AVAILABLE = True
NEEDS_MIRROR = True

JOINTS = [
    {"name": "Root_M", "parent": None, "translate": (0.0, 1.058026, -0.370068), "orient": (90.0, -61.038883, 90.0), "side": "M", "ik_role": "root", "radius": 0.35, "fat": 1.0},
    {"name": "Spine1_M", "parent": "Root_M", "translate": (0.257447, -0.0, 0.0), "orient": (0.0, 0.0, -1.82555), "side": "M", "ik_role": "spine", "radius": 0.35, "fat": 1.0},
    {"name": "Hip_R", "parent": "Root_M", "translate": (-0.047272, 0.421797, -0.217855), "orient": (180.0, 0.0, 146.986239), "side": "R", "ik_role": "hip", "radius": 0.3, "fat": 0.1},
    {"name": "Knee_R", "parent": "Hip_R", "translate": (0.326561, -0.0, -0.0), "orient": (0.0, 0.0, 47.74394), "side": "R", "ik_role": "knee", "radius": 0.3, "fat": 0.1},
    {"name": "Ankle_R", "parent": "Knee_R", "translate": (0.331316, -0.0, 0.0), "orient": (0.019148, 0.0, -19.718817), "side": "R", "ik_role": "foot", "radius": 0.35, "fat": 1.0},
    {"name": "Heel_R", "parent": "Ankle_R", "translate": (0.065233, -0.015703, 0.0), "orient": (-0.019137, -2.159915, -3.427792), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "Toes_R", "parent": "Ankle_R", "translate": (0.037175, 0.034224, -0.0), "orient": (0.0, 3.8e-05, 85.015929), "side": "R", "ik_role": "toes", "radius": 0.3, "fat": 0.1},
    {"name": "ToesEnd_R", "parent": "Toes_R", "translate": (0.322684, -0.0, -0.0), "orient": (-3.4e-05, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.1},
    {"name": "Tail1_M", "parent": "Root_M", "translate": (-0.338273, -0.032802, -0.0), "orient": (0.0, 180.0, 2.606711), "side": "M", "ik_role": "tail", "radius": 0.3, "fat": 0.2369},
    {"name": "Tail2_M", "parent": "Tail1_M", "translate": (0.456888, -0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "M", "ik_role": "tail", "radius": 0.35, "fat": 1.0},
    {"name": "Tail3_M", "parent": "Tail2_M", "translate": (0.958393, -0.0, -0.0), "orient": (0.0, 0.0, 0.0), "side": "M", "ik_role": "tail", "radius": 0.35, "fat": 1.0},
    {"name": "Tail3ASide_M", "parent": "Tail2_M", "translate": (0.170868, -0.00252, 0.817554), "orient": (-13.395523, -26.397872, 0.27637), "side": "M", "ik_role": "tail", "radius": 0.3, "fat": 0.1},
    {"name": "Tail3Side_M", "parent": "Tail3ASide_M", "translate": (0.583213, 0.0, -0.0), "orient": (0.0, 20.0, 0.0), "side": "M", "ik_role": "tail", "radius": 0.3, "fat": 0.1},
    {"name": "Tail3SideEnd_M", "parent": "Tail3Side_M", "translate": (0.15, -0.0, -0.0), "orient": (0.0, 0.0, 0.0), "side": "M", "ik_role": "tail", "radius": 0.3, "fat": 0.1},
    {"name": "Tail3End_M", "parent": "Tail3_M", "translate": (0.15, -0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "M", "ik_role": "tail", "radius": 0.35, "fat": 1.0},
    {"name": "Chest_M", "parent": "Spine1_M", "translate": (0.299118, 0.0, -0.0), "orient": (0.0, 0.0, -14.059998), "side": "M", "ik_role": "chest", "radius": 0.3, "fat": 0.301},
    {"name": "Neck_M", "parent": "Chest_M", "translate": (0.451955, 0.0, 0.0), "orient": (0.0, 0.0, -13.22716), "side": "M", "ik_role": "neck", "radius": 0.3, "fat": 0.1},
    {"name": "Scapula_R", "parent": "Chest_M", "translate": (0.230984, -0.092919, -0.394574), "orient": (175.54981, 89.999999, 104.904433), "side": "R", "ik_role": "scapula", "radius": 0.3, "fat": 0.1},
    {"name": "Shoulder_R", "parent": "Scapula_R", "translate": (0.164349, -0.0, -0.0), "orient": (0.0, 0.0, -15.0), "side": "R", "ik_role": "shoulder", "radius": 0.3, "fat": 0.1},
    {"name": "Elbow_R", "parent": "Shoulder_R", "translate": (0.643103, 0.0, -0.0), "orient": (0.0, 0.0, 25.0), "side": "R", "ik_role": "elbow", "radius": 0.3, "fat": 0.1},
    {"name": "Wrist_R", "parent": "Elbow_R", "translate": (0.979536, -0.0, 0.0), "orient": (0.0, 0.0, -15.0), "side": "R", "ik_role": "hand", "radius": 0.3, "fat": 0.1},
    {"name": "IndexFinger1_R", "parent": "Wrist_R", "translate": (0.583857, 0.0, 0.0), "orient": (0.0, 0.0, 15.0), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.1},
    {"name": "IndexFinger2_R", "parent": "IndexFinger1_R", "translate": (0.438199, 0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.1},
    {"name": "Head_M", "parent": "Neck_M", "translate": (0.326078, 0.0, 0.0), "orient": (0.0, 0.0, -31.926175), "side": "M", "ik_role": "head", "radius": 0.3, "fat": 0.1},
    {"name": "HeadEnd_M", "parent": "Head_M", "translate": (0.3, 0.0, -0.0), "orient": (0.0, 0.0, 0.0), "side": "M", "ik_role": "head", "radius": 0.3, "fat": 0.1},
    {"name": "Eye_R", "parent": "Head_M", "translate": (0.089355, 0.189208, -0.150288), "orient": (4.946743, 63.402558, 95.528754), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "EyeEnd_R", "parent": "Eye_R", "translate": (0.085788, 0.0, 0.0), "orient": (0.0, 90.0, 0.0), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "Jaw_M", "parent": "Head_M", "translate": (-0.061693, 0.172759, -0.0), "orient": (0.0, 0.0, 95.45211), "side": "M", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "JawEnd_M", "parent": "Jaw_M", "translate": (0.301002, -0.0, -0.0), "orient": (0.0, 0.0, 0.0), "side": "M", "ik_role": "", "radius": 0.35, "fat": 1.0},
]

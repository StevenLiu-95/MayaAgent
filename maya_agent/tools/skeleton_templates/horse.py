"""Auto-generated skeleton template data (no ADV runtime dependency)."""
from __future__ import annotations

TEMPLATE_ID = "horse"
LABEL = "四足有蹄"
AVAILABLE = True
NEEDS_MIRROR = True

JOINTS = [
    {"name": "Root_M", "parent": None, "translate": (0.0, 11.915606, -2.897327), "orient": (-90.0, -87.243231, -90.0), "side": "M", "ik_role": "root", "radius": 0.4464, "fat": 1.2754},
    {"name": "Spine1_M", "parent": "Root_M", "translate": (2.90442, 0.0, 0.0), "orient": (0.0, -0.0, -1.225672), "side": "M", "ik_role": "spine", "radius": 0.5771, "fat": 1.649},
    {"name": "Hip_R", "parent": "Root_M", "translate": (-1.820474, 1.562116, -1.071255), "orient": (-180.0, -0.0, 61.014529), "side": "R", "ik_role": "hip", "radius": 0.3527, "fat": 1.0076},
    {"name": "Knee_R", "parent": "Hip_R", "translate": (2.803497, -0.0, 0.0), "orient": (0.0, -0.0, -47.950252), "side": "R", "ik_role": "knee", "radius": 0.3546, "fat": 1.0131},
    {"name": "Ankle_R", "parent": "Knee_R", "translate": (4.459436, -0.0, -0.0), "orient": (-0.0, -0.0, 30.412364), "side": "R", "ik_role": "foot", "radius": 0.3, "fat": 0.4565},
    {"name": "Toes1_R", "parent": "Ankle_R", "translate": (2.369465, 0.0, -0.0), "orient": (0.0, 0.0, 20.21552), "side": "R", "ik_role": "toes", "radius": 0.3, "fat": 0.2657},
    {"name": "Toes2_R", "parent": "Toes1_R", "translate": (0.912165, 0.0, 0.0), "orient": (0.0, 1e-06, 14.644506), "side": "R", "ik_role": "toes", "radius": 0.3, "fat": 0.1857},
    {"name": "Toes3_R", "parent": "Toes2_R", "translate": (0.51171, -0.0, 0.0), "orient": (0.0, 1e-06, 14.933216), "side": "R", "ik_role": "toes", "radius": 0.3, "fat": 0.312},
    {"name": "Toes4_R", "parent": "Toes3_R", "translate": (0.524171, -0.0, 0.0), "orient": (0.0, -0.0, 0.0), "side": "R", "ik_role": "toes", "radius": 0.3, "fat": 0.122},
    {"name": "backFootSideOuter_R", "parent": "Toes3_R", "translate": (0.141866, -0.23136, 0.380466), "orient": (-0.0, -0.0, 0.0), "side": "R", "ik_role": "foot", "radius": 0.35, "fat": 1.0},
    {"name": "backFootSideInner_R", "parent": "Toes3_R", "translate": (0.141866, -0.23136, -0.360268), "orient": (-0.0, -0.0, 0.0), "side": "R", "ik_role": "foot", "radius": 0.35, "fat": 1.0},
    {"name": "backHeel_R", "parent": "Toes3_R", "translate": (0.022327, -0.306745, 0.0), "orient": (-0.0, -0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "Tail0_M", "parent": "Root_M", "translate": (-1.978909, 0.176876, -0.0), "orient": (-180.0, 0.0, 176.710655), "side": "M", "ik_role": "tail", "radius": 0.3, "fat": 0.6101},
    {"name": "Tail1_M", "parent": "Tail0_M", "translate": (0.8, -0.0, -0.0), "orient": (0.0, 0.0, 0.0), "side": "M", "ik_role": "tail", "radius": 0.3, "fat": 0.6101},
    {"name": "Tail2_M", "parent": "Tail1_M", "translate": (0.8, -0.0, -0.0), "orient": (0.0, 0.0, 0.0), "side": "M", "ik_role": "tail", "radius": 0.3, "fat": 0.6101},
    {"name": "Tail3_M", "parent": "Tail2_M", "translate": (0.8, 0.0, -0.0), "orient": (0.0, 0.0, 0.0), "side": "M", "ik_role": "tail", "radius": 0.3, "fat": 0.6101},
    {"name": "Tail4_M", "parent": "Tail3_M", "translate": (0.8, -0.0, -0.0), "orient": (0.0, 0.0, 0.0), "side": "M", "ik_role": "tail", "radius": 0.3, "fat": 0.6101},
    {"name": "Tail5_M", "parent": "Tail4_M", "translate": (0.8, 0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "M", "ik_role": "tail", "radius": 0.3, "fat": 0.6101},
    {"name": "Tail6_M", "parent": "Tail5_M", "translate": (0.8, -0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "M", "ik_role": "tail", "radius": 0.3, "fat": 0.6101},
    {"name": "Chest_M", "parent": "Spine1_M", "translate": (3.387249, -0.0, 0.0), "orient": (0.0, -0.0, 0.0), "side": "M", "ik_role": "chest", "radius": 0.7542, "fat": 2.1548},
    {"name": "Neck_M", "parent": "Chest_M", "translate": (2.048479, 0.878962, -0.0), "orient": (-0.0, -0.0, -49.543953), "side": "M", "ik_role": "neck", "radius": 0.4066, "fat": 1.1617},
    {"name": "Neck1_M", "parent": "Neck_M", "translate": (1.127281, -0.0, -0.0), "orient": (0.0, 0.0, -25.556283), "side": "M", "ik_role": "neck", "radius": 0.3, "fat": 0.6294},
    {"name": "Neck2_M", "parent": "Neck1_M", "translate": (1.345124, 0.0, -0.0), "orient": (0.0, -0.0, 5.296396), "side": "M", "ik_role": "neck", "radius": 0.3, "fat": 0.5971},
    {"name": "Neck3_M", "parent": "Neck2_M", "translate": (1.346524, -0.0, -0.0), "orient": (0.0, 0.0, 21.711524), "side": "M", "ik_role": "neck", "radius": 0.3, "fat": 0.5648},
    {"name": "Neck4_M", "parent": "Neck3_M", "translate": (1.153961, -0.0, -0.0), "orient": (-0.0, 0.0, 6.862521), "side": "M", "ik_role": "neck", "radius": 0.3, "fat": 0.5},
    {"name": "Head_M", "parent": "Neck4_M", "translate": (0.844041, 0.0, -0.0), "orient": (-0.0, -0.0, -27.871912), "side": "M", "ik_role": "head", "radius": 0.3, "fat": 0.69},
    {"name": "HeadEnd_M", "parent": "Head_M", "translate": (1.45699, -0.0, 0.0), "orient": (-0.0, -0.0, 0.0), "side": "M", "ik_role": "head", "radius": 0.3, "fat": 0.6101},
    {"name": "Jaw_M", "parent": "Head_M", "translate": (-0.240899, 0.524008, -0.0), "orient": (-0.0, -0.0, 113.92072), "side": "M", "ik_role": "", "radius": 0.3, "fat": 0.6101},
    {"name": "JawEnd_M", "parent": "Jaw_M", "translate": (3.501427, -0.0, -0.0), "orient": (0.0, 0.0, -0.0), "side": "M", "ik_role": "", "radius": 0.3, "fat": 0.6101},
    {"name": "Eye_R", "parent": "Head_M", "translate": (0.045551, 1.362091, -0.463049), "orient": (-5e-05, 34.638848, 67.570522), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.169},
    {"name": "EyeEnd_R", "parent": "Eye_R", "translate": (0.169031, -0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.169},
    {"name": "Scapula_R", "parent": "Chest_M", "translate": (0.212675, -0.206404, -1.071255), "orient": (180.0, 0.0, 53.301949), "side": "R", "ik_role": "scapula", "radius": 0.7303, "fat": 2.0866},
    {"name": "Shoulder_R", "parent": "Scapula_R", "translate": (3.45301, -0.0, 0.0), "orient": (0.0, -0.0, -73.061221), "side": "R", "ik_role": "shoulder", "radius": 0.4078, "fat": 1.1651},
    {"name": "Elbow_R", "parent": "Shoulder_R", "translate": (2.606707, 0.0, 0.0), "orient": (0.0, 0.0, 44.527481), "side": "R", "ik_role": "elbow", "radius": 0.3, "fat": 0.7452},
    {"name": "Wrist_R", "parent": "Elbow_R", "translate": (3.087907, 0.0, -0.0), "orient": (0.0, 0.0, -13.994292), "side": "R", "ik_role": "hand", "radius": 0.3, "fat": 0.5301},
    {"name": "Fingers1_R", "parent": "Wrist_R", "translate": (2.423499, -0.0, -0.0), "orient": (0.0, -0.0, 24.3533), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.2301},
    {"name": "Fingers2_R", "parent": "Fingers1_R", "translate": (0.883902, 0.0, 0.0), "orient": (-0.0, 0.0, 16.739009), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.2301},
    {"name": "Fingers3_R", "parent": "Fingers2_R", "translate": (0.469631, -0.0, 0.0), "orient": (-0.0, 0.0, 25.17584), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.352},
    {"name": "Fingers4_R", "parent": "Fingers3_R", "translate": (0.578028, 0.0, -0.0), "orient": (-0.0, -0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.122},
    {"name": "frontFootSideInner_R", "parent": "Fingers3_R", "translate": (0.191159, -0.235878, -0.355062), "orient": (-0.0, -0.0, 0.0), "side": "R", "ik_role": "foot", "radius": 0.35, "fat": 1.0},
    {"name": "frontFootSideOuter_R", "parent": "Fingers3_R", "translate": (0.191159, -0.235878, 0.382407), "orient": (-0.0, -0.0, 0.0), "side": "R", "ik_role": "foot", "radius": 0.35, "fat": 1.0},
    {"name": "frontHeel_R", "parent": "Fingers3_R", "translate": (0.066332, -0.306216, -0.0), "orient": (-0.0, -0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
]

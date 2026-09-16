"""Auto-generated skeleton template data (no ADV runtime dependency)."""
from __future__ import annotations

TEMPLATE_ID = "ue4"
LABEL = "UE4 Mannequin 风格"
AVAILABLE = True
NEEDS_MIRROR = True

JOINTS = [
    {"name": "Root_M", "parent": None, "translate": (0.0, 9.67506, -0.105615), "orient": (90.0, -4.713775, 90.0), "side": "M", "ik_role": "root", "radius": 0.546, "fat": 1.56},
    {"name": "Spine1_M", "parent": "Root_M", "translate": (1.084236, 0.0, 0.0), "orient": (0.0, 0.0, -8.736097), "side": "M", "ik_role": "spine", "radius": 0.546, "fat": 1.56},
    {"name": "Spine2_M", "parent": "Spine1_M", "translate": (1.925429, 0.0, 0.0), "orient": (0.0, 0.0, -4.473787), "side": "M", "ik_role": "spine", "radius": 0.546, "fat": 1.56},
    {"name": "Chest_M", "parent": "Spine2_M", "translate": (1.341391, 0.0, 0.0), "orient": (0.0, 0.0, 0.24616), "side": "M", "ik_role": "chest", "radius": 0.546, "fat": 1.56},
    {"name": "Neck_M", "parent": "Chest_M", "translate": (1.65626, 0.0, 0.0), "orient": (0.0, 0.0, 20.032494), "side": "M", "ik_role": "neck", "radius": 0.1127, "fat": 0.322},
    {"name": "Head_M", "parent": "Neck_M", "translate": (0.929075, 0.0, 0.0), "orient": (0.0, 0.0, -11.749319), "side": "M", "ik_role": "head", "radius": 0.1127, "fat": 0.322},
    {"name": "HeadEnd_M", "parent": "Head_M", "translate": (1.5153, 0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "M", "ik_role": "head", "radius": 0.11375, "fat": 0.325},
    {"name": "Eye_R", "parent": "Head_M", "translate": (0.570784, 0.257511, -0.33648), "orient": (0.0, 0.0, 90.0), "side": "R", "ik_role": "", "radius": 0.1085, "fat": 0.31},
    {"name": "EyeEnd_R", "parent": "Eye_R", "translate": (0.241617, 0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.1085, "fat": 0.31},
    {"name": "Jaw_M", "parent": "Head_M", "translate": (0.021906, 0.160929, 0.0), "orient": (0.0, 0.0, 114.343578), "side": "M", "ik_role": "", "radius": 0.1085, "fat": 0.31},
    {"name": "JawEnd_M", "parent": "Jaw_M", "translate": (0.526877, 0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "M", "ik_role": "", "radius": 0.1085, "fat": 0.31},
    {"name": "Scapula_R", "parent": "Chest_M", "translate": (1.193967, 0.247653, -0.3782), "orient": (63.623054, 118.163611, 74.658012), "side": "R", "ik_role": "scapula", "radius": 0.13825, "fat": 0.395},
    {"name": "Shoulder_R", "parent": "Scapula_R", "translate": (1.615305, 0.0, 0.0), "orient": (18.373543, 37.500161, 20.402176), "side": "R", "ik_role": "shoulder", "radius": 0.26425, "fat": 0.755},
    {"name": "Elbow_R", "parent": "Shoulder_R", "translate": (2.984005, 0.0, 0.0), "orient": (0.0, -0.0, 31.930485), "side": "R", "ik_role": "elbow", "radius": 0.21525, "fat": 0.615},
    {"name": "Wrist_R", "parent": "Elbow_R", "translate": (2.697525, 0.0, 0.0), "orient": (-20.569367, 6.658681, -5.33283), "side": "R", "ik_role": "hand", "radius": 0.10745, "fat": 0.307},
    {"name": "MiddleFinger1_R", "parent": "Wrist_R", "translate": (1.232551, 0.0, 0.0), "orient": (5.308495, 15.949915, -6.779454), "side": "R", "ik_role": "", "radius": 0.0497, "fat": 0.142},
    {"name": "MiddleFinger2_R", "parent": "MiddleFinger1_R", "translate": (0.464057, 0.0, 0.0), "orient": (2.901246, 12.081858, -2.479903), "side": "R", "ik_role": "", "radius": 0.0497, "fat": 0.142},
    {"name": "MiddleFinger3_R", "parent": "MiddleFinger2_R", "translate": (0.36489, 0.0, 0.0), "orient": (0.0, -0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.0497, "fat": 0.142},
    {"name": "MiddleFinger4_R", "parent": "MiddleFinger3_R", "translate": (0.3, 0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.0497, "fat": 0.142},
    {"name": "ThumbFinger1_R", "parent": "Wrist_R", "translate": (0.486238, 0.251284, -0.219142), "orient": (-87.993936, 21.322052, 39.616434), "side": "R", "ik_role": "", "radius": 0.0497, "fat": 0.142},
    {"name": "ThumbFinger2_R", "parent": "ThumbFinger1_R", "translate": (0.386957, 0.0, 0.0), "orient": (17.04395, 14.180064, 10.000632), "side": "R", "ik_role": "", "radius": 0.0497, "fat": 0.142},
    {"name": "ThumbFinger3_R", "parent": "ThumbFinger2_R", "translate": (0.406184, 0.0, 0.0), "orient": (-0.0, -0.0, -0.0), "side": "R", "ik_role": "", "radius": 0.0497, "fat": 0.142},
    {"name": "ThumbFinger4_R", "parent": "ThumbFinger3_R", "translate": (0.26, 0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.0497, "fat": 0.142},
    {"name": "IndexFinger1_R", "parent": "Wrist_R", "translate": (1.207563, 0.259058, -0.081472), "orient": (-7.862283, 19.136583, -3.84179), "side": "R", "ik_role": "", "radius": 0.0497, "fat": 0.142},
    {"name": "IndexFinger2_R", "parent": "IndexFinger1_R", "translate": (0.428769, 0.0, 0.0), "orient": (1.313915, 11.386939, -3.794421), "side": "R", "ik_role": "", "radius": 0.0497, "fat": 0.142},
    {"name": "IndexFinger3_R", "parent": "IndexFinger2_R", "translate": (0.33938, 0.0, 0.0), "orient": (-0.0, 0.0, -0.0), "side": "R", "ik_role": "", "radius": 0.0497, "fat": 0.142},
    {"name": "IndexFinger4_R", "parent": "IndexFinger3_R", "translate": (0.26, 0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.0497, "fat": 0.142},
    {"name": "Cup_R", "parent": "Wrist_R", "translate": (0.428833, -0.176888, -0.019836), "orient": (6.518452, -0.560584, 4.369984), "side": "R", "ik_role": "", "radius": 0.0497, "fat": 0.142},
    {"name": "PinkyFinger1_R", "parent": "Cup_R", "translate": (0.602413, -0.301382, -0.017788), "orient": (10.428725, 9.152071, -23.832855), "side": "R", "ik_role": "", "radius": 0.0497, "fat": 0.142},
    {"name": "PinkyFinger2_R", "parent": "PinkyFinger1_R", "translate": (0.357106, 0.0, 0.0), "orient": (2.94185, 10.811561, -3.224796), "side": "R", "ik_role": "", "radius": 0.0497, "fat": 0.142},
    {"name": "PinkyFinger3_R", "parent": "PinkyFinger2_R", "translate": (0.298542, 0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.0497, "fat": 0.142},
    {"name": "PinkyFinger4_R", "parent": "PinkyFinger3_R", "translate": (0.25, 0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.0497, "fat": 0.142},
    {"name": "RingFinger1_R", "parent": "Cup_R", "translate": (0.738264, -0.115735, 0.001285), "orient": (3.397202, 14.428562, -17.035293), "side": "R", "ik_role": "", "radius": 0.0497, "fat": 0.142},
    {"name": "RingFinger2_R", "parent": "RingFinger1_R", "translate": (0.442986, 0.0, 0.0), "orient": (2.61415, 12.984137, -3.412695), "side": "R", "ik_role": "", "radius": 0.0497, "fat": 0.142},
    {"name": "RingFinger3_R", "parent": "RingFinger2_R", "translate": (0.347666, 0.0, 0.0), "orient": (0.0, -0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.0497, "fat": 0.142},
    {"name": "RingFinger4_R", "parent": "RingFinger3_R", "translate": (0.26, 0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.0497, "fat": 0.142},
    {"name": "Hip_R", "parent": "Root_M", "translate": (-0.140244, 0.064354, -0.90058), "orient": (-158.174474, 7.032301, 177.011586), "side": "R", "ik_role": "hip", "radius": 0.27195, "fat": 0.777},
    {"name": "Knee_R", "parent": "Hip_R", "translate": (4.257225, 0.0, 0.0), "orient": (0.0, -0.0, -7.816259), "side": "R", "ik_role": "knee", "radius": 0.2625, "fat": 0.75},
    {"name": "Ankle_R", "parent": "Knee_R", "translate": (4.019665, 0.0, 0.0), "orient": (-18.881922, 7.168948, 6.802993), "side": "R", "ik_role": "foot", "radius": 0.25445, "fat": 0.727},
    {"name": "Heel_R", "parent": "Ankle_R", "translate": (1.347174, -0.359534, 0.01822), "orient": (0.033226, 92.901056, 90.0), "side": "R", "ik_role": "", "radius": 0.25445, "fat": 0.727},
    {"name": "Toes_R", "parent": "Ankle_R", "translate": (1.065398, 1.644761, 0.0), "orient": (-1.034196, 2.710548, 69.106638), "side": "R", "ik_role": "toes", "radius": 0.252, "fat": 0.72},
    {"name": "FootSideInner_R", "parent": "Toes_R", "translate": (0.09194, -0.264589, -0.38256), "orient": (-20.835668, 89.9999, 0.0), "side": "R", "ik_role": "foot", "radius": 0.252, "fat": 0.72},
    {"name": "FootSideOuter_R", "parent": "Toes_R", "translate": (0.100045, -0.261499, 0.438931), "orient": (-20.835668, 89.9999, 0.0), "side": "R", "ik_role": "foot", "radius": 0.252, "fat": 0.72},
    {"name": "ToesEnd_R", "parent": "Toes_R", "translate": (0.813255, 0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.252, "fat": 0.72},
]

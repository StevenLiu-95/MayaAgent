"""Auto-generated skeleton template data (no ADV runtime dependency)."""
from __future__ import annotations

TEMPLATE_ID = "biped_bendy"
LABEL = "双足 Bendy"
AVAILABLE = True
NEEDS_MIRROR = True

JOINTS = [
    {"name": "Root_M", "parent": None, "translate": (0.0, 9.82851, -0.177172), "orient": (90.0, 8.0, 90.0), "side": "M", "ik_role": "root", "radius": 0.595, "fat": 1.7},
    {"name": "Spine1_M", "parent": "Root_M", "translate": (1.756155, 0.0, -0.0), "orient": (0.0, 0.0, 3.106224), "side": "M", "ik_role": "spine", "radius": 0.595, "fat": 1.7},
    {"name": "Chest_M", "parent": "Spine1_M", "translate": (1.425906, -0.0, -0.0), "orient": (0.0, 0.0, 12.854442), "side": "M", "ik_role": "chest", "radius": 0.595, "fat": 1.7},
    {"name": "Neck_M", "parent": "Chest_M", "translate": (1.167656, 0.0, 0.0), "orient": (0.0, 0.0, 2.39566), "side": "M", "ik_role": "neck", "radius": 0.3, "fat": 0.32},
    {"name": "Head_M", "parent": "Neck_M", "translate": (1.555071, 0.0, -0.0), "orient": (0.0, 0.0, -10.323099), "side": "M", "ik_role": "head", "radius": 0.3, "fat": 0.32},
    {"name": "HeadEnd_M", "parent": "Head_M", "translate": (1.501697, -0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "M", "ik_role": "head", "radius": 0.3, "fat": 0.35},
    {"name": "Eye_R", "parent": "Head_M", "translate": (0.223536, 1.05188, -0.342301), "orient": (0.0, 0.0, 90.0), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.2},
    {"name": "EyeEnd_R", "parent": "Eye_R", "translate": (0.17087, -0.0, 0.0), "orient": (-3.98593, -89.738983, 168.042231), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "Jaw_M", "parent": "Head_M", "translate": (-0.28088, 0.405534, -0.0), "orient": (0.0, 0.0, 117.772215), "side": "M", "ik_role": "", "radius": 0.3, "fat": 0.2},
    {"name": "JawEnd_M", "parent": "Jaw_M", "translate": (1.082894, -0.0, -0.0), "orient": (0.0, 0.0, -4.314622), "side": "M", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "Scapula_R", "parent": "Chest_M", "translate": (0.764201, 0.275289, -0.436536), "orient": (57.954651, 90.021231, 50.020358), "side": "R", "ik_role": "scapula", "radius": 0.35, "fat": 1.0},
    {"name": "Shoulder_R", "parent": "Scapula_R", "translate": (1.092541, -0.0, -0.0), "orient": (0.000302, -0.011608, -2.98401), "side": "R", "ik_role": "shoulder", "radius": 0.3, "fat": 0.65},
    {"name": "Elbow_R", "parent": "Shoulder_R", "translate": (2.614252, -0.0, -0.0), "orient": (0.0, 0.0, 6.382189), "side": "R", "ik_role": "elbow", "radius": 0.3, "fat": 0.45},
    {"name": "Wrist_R", "parent": "Elbow_R", "translate": (2.282603, 0.0, 0.0), "orient": (0.0, 0.0, -3.380184), "side": "R", "ik_role": "hand", "radius": 0.3, "fat": 0.17},
    {"name": "MiddleFinger1_R", "parent": "Wrist_R", "translate": (0.963242, 0.003966, 0.0), "orient": (-0.069474, 4.775318, -0.834481), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.12},
    {"name": "MiddleFinger2_R", "parent": "MiddleFinger1_R", "translate": (0.310641, 0.0, -0.0), "orient": (0.036679, -2.519999, -0.002573), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.12},
    {"name": "MiddleFinger3_R", "parent": "MiddleFinger2_R", "translate": (0.17127, -0.0, -0.0), "orient": (0.053455, -3.671294, -0.001402), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.12},
    {"name": "MiddleFinger4_R", "parent": "MiddleFinger3_R", "translate": (0.209346, 0.0, 0.0), "orient": (89.968442, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "ThumbFinger1_R", "parent": "Wrist_R", "translate": (0.204023, 0.144856, -0.100919), "orient": (-52.264, 19.323321, 38.439956), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.12},
    {"name": "ThumbFinger2_R", "parent": "ThumbFinger1_R", "translate": (0.350882, 0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.12},
    {"name": "ThumbFinger3_R", "parent": "ThumbFinger2_R", "translate": (0.168686, 0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.12},
    {"name": "ThumbFinger4_R", "parent": "ThumbFinger3_R", "translate": (0.203289, -0.0, -0.0), "orient": (-12.991445, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "IndexFinger1_R", "parent": "Wrist_R", "translate": (0.860878, 0.23966, -0.017444), "orient": (0.903555, 3.174026, 15.899116), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.12},
    {"name": "IndexFinger2_R", "parent": "IndexFinger1_R", "translate": (0.263858, 0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.12},
    {"name": "IndexFinger3_R", "parent": "IndexFinger2_R", "translate": (0.175519, -0.0, -0.0), "orient": (-1.641834, -5.759621, 0.066225), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.12},
    {"name": "IndexFinger4_R", "parent": "IndexFinger3_R", "translate": (0.185478, -0.0, 0.0), "orient": (90.981953, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "Cup_R", "parent": "Wrist_R", "translate": (0.203647, -0.100773, -0.00114), "orient": (-0.055051, 0.678184, -4.640834), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.12},
    {"name": "PinkyFinger1_R", "parent": "Cup_R", "translate": (0.642298, -0.228969, -0.065383), "orient": (-2.952167, 7.916951, -15.886025), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.12},
    {"name": "PinkyFinger2_R", "parent": "PinkyFinger1_R", "translate": (0.232732, -0.0, -0.0), "orient": (0.266831, -0.719176, -0.034439), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.12},
    {"name": "PinkyFinger3_R", "parent": "PinkyFinger2_R", "translate": (0.142302, -0.0, -0.0), "orient": (2.158877, -5.754609, -0.249563), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.12},
    {"name": "PinkyFinger4_R", "parent": "PinkyFinger3_R", "translate": (0.177923, -0.0, 0.0), "orient": (90.328533, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "RingFinger1_R", "parent": "Cup_R", "translate": (0.697075, -0.073728, -0.037018), "orient": (-0.188747, 1.438183, -2.837041), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.12},
    {"name": "RingFinger2_R", "parent": "RingFinger1_R", "translate": (0.289524, 0.0, -0.0), "orient": (-0.283179, 2.159996, 0.004391), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.12},
    {"name": "RingFinger3_R", "parent": "RingFinger2_R", "translate": (0.17506, -0.0, 0.0), "orient": (0.567834, -4.319895, -0.030192), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.12},
    {"name": "RingFinger4_R", "parent": "RingFinger3_R", "translate": (0.193694, -0.0, -0.0), "orient": (89.832984, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "Hip_R", "parent": "Root_M", "translate": (-0.199689, -0.08224, -0.819687), "orient": (0.572038, 178.21078, 2.871794), "side": "R", "ik_role": "hip", "radius": 0.3045, "fat": 0.87},
    {"name": "Knee_R", "parent": "Hip_R", "translate": (4.974125, 0.0, 0.0), "orient": (0.0, 0.0, -9.430086), "side": "R", "ik_role": "knee", "radius": 0.3, "fat": 0.6},
    {"name": "Ankle_R", "parent": "Knee_R", "translate": (3.830179, -0.0, 0.0), "orient": (-1.42476, 1.730389, 4.248682), "side": "R", "ik_role": "foot", "radius": 0.3, "fat": 0.37},
    {"name": "Heel_R", "parent": "Ankle_R", "translate": (0.839623, -0.643484, -0.007792), "orient": (0.0, 89.30623, 90.0), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "Toes_R", "parent": "Ankle_R", "translate": (0.666117, 1.342418, -0.0), "orient": (0.093327, -0.68754, 82.269657), "side": "R", "ik_role": "toes", "radius": 0.3, "fat": 0.3},
    {"name": "FootSideInner_R", "parent": "Toes_R", "translate": (0.023336, -0.17193, -0.4), "orient": (180.0, 89.999925, -172.270217), "side": "R", "ik_role": "foot", "radius": 0.35, "fat": 1.0},
    {"name": "FootSideOuter_R", "parent": "Toes_R", "translate": (0.023337, -0.17193, 0.4), "orient": (180.0, 89.999925, -172.270217), "side": "R", "ik_role": "foot", "radius": 0.35, "fat": 1.0},
    {"name": "ToesEnd_R", "parent": "Toes_R", "translate": (0.626901, 0.0, 0.0), "orient": (179.999913, 1.4e-05, -15.357692), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
]

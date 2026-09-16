"""Auto-generated skeleton template data (no ADV runtime dependency)."""
from __future__ import annotations

TEMPLATE_ID = "bug"
LABEL = "昆虫"
AVAILABLE = True
NEEDS_MIRROR = True

JOINTS = [
    {"name": "Root_M", "parent": None, "translate": (0.0, 0.558269, -0.294544), "orient": (90.0, -84.2543, 90.0), "side": "M", "ik_role": "root", "radius": 0.3, "fat": 0.1},
    {"name": "Spine1_M", "parent": "Root_M", "translate": (0.208528, 0.0, 0.0), "orient": (3e-06, 5e-05, 7.196139), "side": "M", "ik_role": "spine", "radius": 0.3, "fat": 0.1},
    {"name": "BackLeg1_M", "parent": "Root_M", "translate": (-0.043689, 0.08871, -0.199613), "orient": (-45.367055, 43.064045, 133.26544), "side": "M", "ik_role": "", "radius": 0.3, "fat": 0.08},
    {"name": "BackLeg2_M", "parent": "BackLeg1_M", "translate": (0.293508, 0.0, -0.0), "orient": (0.0, 0.0, 70.944252), "side": "M", "ik_role": "", "radius": 0.3, "fat": 0.05},
    {"name": "BackLeg3_M", "parent": "BackLeg2_M", "translate": (0.205584, -0.0, -0.0), "orient": (0.0, 0.0, -98.423441), "side": "M", "ik_role": "", "radius": 0.3, "fat": 0.04},
    {"name": "BackLeg4_M", "parent": "BackLeg3_M", "translate": (0.469237, 0.0, -0.0), "orient": (0.0, 0.0, 63.359999), "side": "M", "ik_role": "", "radius": 0.3, "fat": 0.02},
    {"name": "BackLeg5_M", "parent": "BackLeg4_M", "translate": (0.1, -0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "M", "ik_role": "", "radius": 0.3, "fat": 0.02},
    {"name": "Tail1_M", "parent": "Root_M", "translate": (-0.120311, 0.010139, -0.0), "orient": (0.0, 180.0, 5.7457), "side": "M", "ik_role": "tail", "radius": 0.3, "fat": 0.1},
    {"name": "Tail2_M", "parent": "Tail1_M", "translate": (0.358355, -0.0, -0.0), "orient": (0.0, 8.2e-05, 5.884), "side": "M", "ik_role": "tail", "radius": 0.3, "fat": 0.1},
    {"name": "Tail3_M", "parent": "Tail2_M", "translate": (0.379736, -0.0, 0.0), "orient": (-9e-06, 9e-06, 6.122), "side": "M", "ik_role": "tail", "radius": 0.3, "fat": 0.1},
    {"name": "Tail4_M", "parent": "Tail3_M", "translate": (0.336567, 0.0, -0.0), "orient": (1.8e-05, 0.0, 0.0), "side": "M", "ik_role": "tail", "radius": 0.3, "fat": 0.05},
    {"name": "MiddleLeg1_R", "parent": "Spine1_M", "translate": (0.116209, 0.098576, -0.160935), "orient": (-84.082927, 42.416801, 92.589403), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.08},
    {"name": "MiddleLeg2_R", "parent": "MiddleLeg1_R", "translate": (0.299107, 0.0, -0.0), "orient": (0.0, 0.0, 78.754976), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.05},
    {"name": "MiddleLeg3_R", "parent": "MiddleLeg2_R", "translate": (0.30845, 0.0, 0.0), "orient": (0.0, 0.0, -89.740174), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.04},
    {"name": "MiddleLeg4_R", "parent": "MiddleLeg3_R", "translate": (0.489919, 0.0, 0.0), "orient": (0.0, 0.0, 59.400002), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.02},
    {"name": "MiddleLeg5_R", "parent": "MiddleLeg4_R", "translate": (0.1, 0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.02},
    {"name": "Spine2_M", "parent": "Spine1_M", "translate": (0.188246, 0.0, 0.0), "orient": (0.0, 2e-06, 5.589996), "side": "M", "ik_role": "spine", "radius": 0.3, "fat": 0.1},
    {"name": "Chest_M", "parent": "Spine2_M", "translate": (0.154435, -0.0, 0.0), "orient": (-0.000475, -0.000117, -4.844392), "side": "M", "ik_role": "chest", "radius": 0.3, "fat": 0.1},
    {"name": "Head_M", "parent": "Chest_M", "translate": (0.184106, 0.0, 0.0), "orient": (-3e-06, 0.000248, -1.478115), "side": "M", "ik_role": "head", "radius": 0.3, "fat": 0.05},
    {"name": "HeadEnd_M", "parent": "Head_M", "translate": (0.383898, -0.0, -0.0), "orient": (0.000486, -0.000171, 6.322507), "side": "M", "ik_role": "head", "radius": 0.3, "fat": 0.05},
    {"name": "FrontLeg1_R", "parent": "Chest_M", "translate": (-0.003071, 0.052892, -0.114811), "orient": (-119.192506, 47.550383, 63.188432), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.08},
    {"name": "FrontLeg2_R", "parent": "FrontLeg1_R", "translate": (0.265643, 0.0, 0.0), "orient": (0.0, 0.0, 61.039122), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.05},
    {"name": "FrontLeg3_R", "parent": "FrontLeg2_R", "translate": (0.156303, 0.0, 0.0), "orient": (0.0, 0.0, -80.602866), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.04},
    {"name": "FrontLeg4_R", "parent": "FrontLeg3_R", "translate": (0.476359, -0.0, 0.0), "orient": (0.0, 0.0, 58.564074), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.02},
    {"name": "FrontLeg5_R", "parent": "FrontLeg4_R", "translate": (0.096077, -0.0, 0.0), "orient": (0.0, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.02},
    {"name": "Antenna1_R", "parent": "Head_M", "translate": (0.118974, 0.099953, -0.100069), "orient": (8.333876, 45.168685, 8.567396), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.03},
    {"name": "Antenna2_R", "parent": "Antenna1_R", "translate": (0.1, -0.0, -0.0), "orient": (-0.0, -0.02382, -0.000286), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.03},
    {"name": "Antenna3_R", "parent": "Antenna2_R", "translate": (0.1, 0.0, 0.0), "orient": (0.0, 0.005704, 0.000286), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.03},
    {"name": "Antenna4_R", "parent": "Antenna3_R", "translate": (0.1, -0.0, 0.0), "orient": (-0.0, 0.02316, 0.000628), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.03},
    {"name": "Antenna5_R", "parent": "Antenna4_R", "translate": (0.1, 0.0, -0.0), "orient": (0.0, 0.0, 0.0), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.03},
]

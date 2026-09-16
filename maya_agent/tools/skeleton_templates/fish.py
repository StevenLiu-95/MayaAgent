"""Auto-generated skeleton template data (no ADV runtime dependency)."""
from __future__ import annotations

TEMPLATE_ID = "fish"
LABEL = "鱼类"
AVAILABLE = True
NEEDS_MIRROR = True

JOINTS = [
    {"name": "Root_M", "parent": None, "translate": (0.0, 4.365043, 5.928627), "orient": (90.0, 85.843421, 90.0), "side": "M", "ik_role": "root", "radius": 0.35, "fat": 1.0},
    {"name": "BackA_M", "parent": "Root_M", "translate": (2.651386, 0.0, -0.0), "orient": (0.0, -0.0, -0.0), "side": "M", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "BackB_M", "parent": "BackA_M", "translate": (2.651386, -0.0, -0.0), "orient": (0.0, -0.0, -0.0), "side": "M", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "BackC_M", "parent": "BackB_M", "translate": (2.651386, 0.0, -0.0), "orient": (0.0, -0.0, -0.0), "side": "M", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "BackD_M", "parent": "BackC_M", "translate": (2.651386, 0.0, -0.0), "orient": (0.0, -0.0, -0.0), "side": "M", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "BackE_M", "parent": "BackD_M", "translate": (2.651386, -0.0, -0.0), "orient": (0.0, -0.0, -0.0), "side": "M", "ik_role": "", "radius": 0.7, "fat": 2.0},
    {"name": "BackF_M", "parent": "BackE_M", "translate": (2.651386, 0.0, -0.0), "orient": (0.0, 0.0, 0.0), "side": "M", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "TailFinUpper_M", "parent": "BackF_M", "translate": (0.031906, 0.649129, -0.0), "orient": (0.0, -0.0, 6.738925), "side": "M", "ik_role": "tail", "radius": 0.35, "fat": 1.0},
    {"name": "TailFinUpperEnd_M", "parent": "TailFinUpper_M", "translate": (4.178143, 0.0, -0.0), "orient": (-10.895504, -90.0, 0.0), "side": "M", "ik_role": "tail", "radius": 0.35, "fat": 1.0},
    {"name": "TailFinLower_M", "parent": "BackF_M", "translate": (-0.184947, -0.474572, -0.0), "orient": (0.0, -0.0, -9.422419), "side": "M", "ik_role": "tail", "radius": 0.35, "fat": 1.0},
    {"name": "TailFinLowerEnd_M", "parent": "TailFinLower_M", "translate": (4.19759, 0.0, -0.0), "orient": (5.26584, -90.0, 0.0), "side": "M", "ik_role": "tail", "radius": 0.35, "fat": 1.0},
    {"name": "BodyFinLowerB_R", "parent": "BackD_M", "translate": (0.457356, -1.605274, -0.918127), "orient": (5.59453, 31.514329, -81.00218), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "BodyFinLowerAEnd1_R", "parent": "BodyFinLowerB_R", "translate": (1.93623, -0.0, -0.0), "orient": (34.114473, -90.0, 0.0), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "BodyFinUpperB_R", "parent": "BackC_M", "translate": (0.477463, 2.077439, -0.0), "orient": (0.0, 0.0, 83.302356), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "BodyFinUpperBEnd_R", "parent": "BodyFinUpperB_R", "translate": (2.2666, 0.0, -0.0), "orient": (-57.578935, -90.0, 0.0), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "BodyFinUpperA_R", "parent": "BackA_M", "translate": (-0.018203, 2.550679, -0.0), "orient": (0.0, 0.0, 90.035326), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "BodyFinUpperAEnd_R", "parent": "BodyFinUpperA_R", "translate": (2.976192, -0.0, -0.0), "orient": (-39.359451, -90.0, 0.0), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "BodyFinLowerA_R", "parent": "BackA_M", "translate": (0.755201, -2.145867, -0.0), "orient": (0.0, 0.0, -88.018312), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "BodyFinLowerAEnd_R", "parent": "BodyFinLowerA_R", "translate": (2.658594, 0.0, -0.0), "orient": (40.661733, -90.0, 0.0), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "BodyFinSide1_R", "parent": "Root_M", "translate": (1.492954, -0.675902, -2.442557), "orient": (0.0, 11.309932, -4.156579), "side": "R", "ik_role": "", "radius": 0.525, "fat": 1.5},
    {"name": "BodyFinSide2_R", "parent": "BodyFinSide1_R", "translate": (0.916907, 0.0, 0.0), "orient": (-0.0, 10.231043, 0.0), "side": "R", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "BodyFinSide3_R", "parent": "BodyFinSide2_R", "translate": (1.224378, -0.0, 0.0), "orient": (-0.0, 3.922369, 0.0), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.7},
    {"name": "BodyFinSide4_R", "parent": "BodyFinSide3_R", "translate": (1.39417, -0.0, -0.0), "orient": (0.0, 244.536655, 0.0), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.3},
    {"name": "Head_M", "parent": "Root_M", "translate": (-0.343219, -0.027154, 0.0), "orient": (0.0, 0.0, 180.0), "side": "M", "ik_role": "head", "radius": 0.35, "fat": 1.0},
    {"name": "HeadEnd_M", "parent": "Head_M", "translate": (2.0, 0.0, 0.0), "orient": (0.0, -0.0, -180.0), "side": "M", "ik_role": "head", "radius": 0.35, "fat": 1.0},
    {"name": "Eye_R", "parent": "Head_M", "translate": (2.877182, 0.135801, -1.092933), "orient": (3.285401, 26.773966, 3.105528), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.3},
    {"name": "Eye1_R", "parent": "Eye_R", "translate": (0.790267, -0.0, 0.0), "orient": (6.203448, 90.0, 0.0), "side": "R", "ik_role": "", "radius": 0.3, "fat": 0.3},
    {"name": "Jaw_M", "parent": "Head_M", "translate": (0.950313, 0.946613, 0.0), "orient": (0.0, -0.0, 6.988395), "side": "M", "ik_role": "", "radius": 0.35, "fat": 1.0},
    {"name": "JawEnd_M", "parent": "Jaw_M", "translate": (7.611443, -0.0, 0.0), "orient": (0.0, -0.0, 0.0), "side": "M", "ik_role": "", "radius": 0.3, "fat": 0.1},
]

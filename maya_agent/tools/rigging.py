"""Rigging and skinning tools."""

from __future__ import annotations

from typing import List, Optional

from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.tools._maya import cmds as _cmds

@tool(
    name="create_joint",
    description="在指定位置创建骨骼；可指定父骨骼。",
    parameters=obj_schema(
        {
            "name": {"type": "string", "default": "joint1"},
            "position": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[x,y,z]",
                "default": [0, 0, 0],
            },
            "parent": {"type": "string", "default": ""},
            "radius": {"type": "number", "default": 1.0},
        }
    ),
    category="rigging",
)
def create_joint(
    name: str = "joint1",
    position: Optional[List[float]] = None,
    parent: str = "",
    radius: float = 1.0,
) -> ToolResult:
    c = _cmds()
    position = position or [0, 0, 0]
    if parent and c.objExists(parent):
        c.select(parent, replace=True)
    else:
        c.select(clear=True)
    jnt = c.joint(name=name, position=position, radius=radius)
    return ToolResult(ok=True, data=jnt, message=f"已创建骨骼 {jnt}")

@tool(
    name="create_joint_chain",
    description="沿点列表创建骨骼链（游戏角色常用）。",
    parameters=obj_schema(
        {
            "name_prefix": {"type": "string", "default": "jnt"},
            "positions": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}},
                "description": "[[x,y,z], ...]",
            },
        },
        required=["positions"],
    ),
    category="rigging",
)
def create_joint_chain(name_prefix: str = "jnt", positions: Optional[List[List[float]]] = None) -> ToolResult:
    c = _cmds()
    if not positions or len(positions) < 1:
        return ToolResult(ok=False, error="需要至少一个位置")
    c.select(clear=True)
    joints = []
    for i, pos in enumerate(positions):
        j = c.joint(name=f"{name_prefix}_{i + 1:02d}", position=pos)
        joints.append(j)
    return ToolResult(ok=True, data=joints, message=f"已创建 {len(joints)} 根骨骼链")

@tool(
    name="orient_joints",
    description="自动定向骨骼链。",
    parameters=obj_schema(
        {
            "root_joint": {"type": "string"},
            "aim_axis": {"type": "string", "enum": ["x", "y", "z"], "default": "x"},
            "up_axis": {"type": "string", "enum": ["x", "y", "z"], "default": "y"},
        },
        required=["root_joint"],
    ),
    category="rigging",
)
def orient_joints(root_joint: str, aim_axis: str = "x", up_axis: str = "y") -> ToolResult:
    c = _cmds()
    if not c.objExists(root_joint):
        return ToolResult(ok=False, error="骨骼不存在")
    aim = {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}[aim_axis]
    upa = {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}[up_axis]
    c.joint(
        root_joint,
        edit=True,
        orientJoint="xyz",
        secondaryAxisOrient="yup",
        children=True,
        zeroScaleOrient=True,
    )
    # secondary params retained for API clarity
    _ = (aim, upa)
    return ToolResult(ok=True, data=root_joint, message="骨骼定向完成")

@tool(
    name="bind_skin",
    description="将网格蒙皮到骨骼（smooth bind）。",
    parameters=obj_schema(
        {
            "meshes": {"type": "array", "items": {"type": "string"}},
            "joints": {"type": "array", "items": {"type": "string"}},
            "max_influences": {"type": "integer", "default": 4},
            "bind_method": {
                "type": "integer",
                "default": 0,
                "description": "0=closest,1=heat map 等",
            },
        },
        required=["meshes", "joints"],
    ),
    category="rigging",
)
def bind_skin(
    meshes: List[str],
    joints: List[str],
    max_influences: int = 4,
    bind_method: int = 0,
) -> ToolResult:
    c = _cmds()
    c.select(clear=True)
    c.select(joints, replace=True)
    c.select(meshes, add=True)
    result = c.skinCluster(
        toSelectedBones=True,
        bindMethod=bind_method,
        normalizeWeights=1,
        maximumInfluences=max_influences,
        obeyMaxInfluences=True,
    )
    return ToolResult(ok=True, data=result, message=f"蒙皮完成: {result}")

@tool(
    name="unbind_skin",
    description=(
        "解除蒙皮（回到 bind pose 几何，不保留当前变形姿态）。"
        "若要保留当前姿势的静态模型，请用 bake_mesh_to_world 或 extract_skinned_geometry。"
    ),
    parameters=obj_schema({"mesh": {"type": "string"}}, required=["mesh"]),
    category="rigging",
    destructive=True,
)
def unbind_skin(mesh: str) -> ToolResult:
    c = _cmds()
    hist = c.listHistory(mesh) or []
    skins = c.ls(hist, type="skinCluster") or []
    if not skins:
        return ToolResult(ok=False, error="未找到 skinCluster")
    for s in skins:
        c.skinCluster(s, edit=True, unbind=True)
    return ToolResult(ok=True, data=skins, message="已解除蒙皮")

@tool(
    name="create_ik_handle",
    description="创建 IK 手柄。",
    parameters=obj_schema(
        {
            "start_joint": {"type": "string"},
            "end_effector": {"type": "string"},
            "solver": {
                "type": "string",
                "enum": ["ikRPsolver", "ikSCsolver", "ikSplineSolver"],
                "default": "ikRPsolver",
            },
            "name": {"type": "string", "default": "ikHandle1"},
        },
        required=["start_joint", "end_effector"],
    ),
    category="rigging",
)
def create_ik_handle(
    start_joint: str,
    end_effector: str,
    solver: str = "ikRPsolver",
    name: str = "ikHandle1",
) -> ToolResult:
    c = _cmds()
    result = c.ikHandle(
        startJoint=start_joint,
        endEffector=end_effector,
        solver=solver,
        name=name,
    )
    return ToolResult(ok=True, data=result, message=f"IK 已创建: {result[0]}")

@tool(
    name="create_control_curve",
    description="创建常用控制器曲线（circle/cube/square/diamond）。",
    parameters=obj_schema(
        {
            "shape": {
                "type": "string",
                "enum": ["circle", "cube", "square", "diamond"],
                "default": "circle",
            },
            "name": {"type": "string", "default": "ctrl"},
            "size": {"type": "number", "default": 1.0},
            "position": {
                "type": "array",
                "items": {"type": "number"},
                "default": [0, 0, 0],
            },
        }
    ),
    category="rigging",
)
def create_control_curve(
    shape: str = "circle",
    name: str = "ctrl",
    size: float = 1.0,
    position: Optional[List[float]] = None,
) -> ToolResult:
    c = _cmds()
    position = position or [0, 0, 0]
    if shape == "circle":
        ctrl = c.circle(name=name, radius=size, normal=(0, 1, 0))[0]
    elif shape == "square":
        ctrl = c.curve(
            name=name,
            degree=1,
            point=[
                (-size, 0, -size),
                (size, 0, -size),
                (size, 0, size),
                (-size, 0, size),
                (-size, 0, -size),
            ],
        )
    elif shape == "diamond":
        ctrl = c.curve(
            name=name,
            degree=1,
            point=[
                (0, size, 0),
                (size, 0, 0),
                (0, -size, 0),
                (-size, 0, 0),
                (0, size, 0),
            ],
        )
    else:  # cube wire
        s = size
        pts = [
            (-s, -s, -s), (s, -s, -s), (s, -s, s), (-s, -s, s), (-s, -s, -s),
            (-s, s, -s), (s, s, -s), (s, -s, -s), (s, s, -s), (s, s, s),
            (s, -s, s), (s, s, s), (-s, s, s), (-s, -s, s), (-s, s, s),
            (-s, s, -s),
        ]
        ctrl = c.curve(name=name, degree=1, point=pts)
    c.xform(ctrl, worldSpace=True, translation=position)
    return ToolResult(ok=True, data=ctrl, message=f"控制器已创建: {ctrl}")

@tool(
    name="constrain_objects",
    description="创建约束：parent / point / orient / scale / aim。",
    parameters=obj_schema(
        {
            "driver": {"type": "string"},
            "driven": {"type": "string"},
            "constraint_type": {
                "type": "string",
                "enum": ["parent", "point", "orient", "scale", "aim"],
                "default": "parent",
            },
            "maintain_offset": {"type": "boolean", "default": True},
        },
        required=["driver", "driven"],
    ),
    category="rigging",
)
def constrain_objects(
    driver: str,
    driven: str,
    constraint_type: str = "parent",
    maintain_offset: bool = True,
) -> ToolResult:
    c = _cmds()
    fn = {
        "parent": c.parentConstraint,
        "point": c.pointConstraint,
        "orient": c.orientConstraint,
        "scale": c.scaleConstraint,
        "aim": c.aimConstraint,
    }.get(constraint_type)
    if not fn:
        return ToolResult(ok=False, error="未知约束类型")
    result = fn(driver, driven, maintainOffset=maintain_offset)
    return ToolResult(ok=True, data=result, message=f"{constraint_type} 约束已创建")

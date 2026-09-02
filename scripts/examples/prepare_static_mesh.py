"""
示例：批量准备游戏资产（在 Maya Script Editor 中运行，或让 Agent 调用 execute_python）。

演示命名、冻结变换、碰撞体与 FBX 导出思路。
"""

from __future__ import annotations


def prepare_static_mesh(mesh: str, asset_name: str, export_dir: str = "") -> dict:
    import maya.cmds as cmds
    from maya_agent.tools.registry import ensure_tools_loaded, run_tool

    ensure_tools_loaded()
    cmds.select(mesh, replace=True)
    run_tool("freeze_transform", {"names": [mesh]})
    run_tool("center_pivot", {"names": [mesh]})
    renamed = run_tool(
        "apply_game_naming",
        {"name": mesh, "asset_type": "SM", "asset_name": asset_name},
    )
    new_name = (renamed.data if renamed.ok else mesh)
    col = run_tool(
        "create_collision_mesh",
        {"source": new_name, "collision_type": "box", "name": f"UCX_{asset_name}"},
    )
    result = {"mesh": new_name, "collision": col.data if col.ok else None}
    if export_dir:
        path = export_dir.rstrip("\\/") + f"/SM_{asset_name}.fbx"
        cmds.select([new_name, col.data] if col.ok else [new_name], replace=True)
        exp = run_tool("export_fbx", {"file_path": path, "selection_only": True})
        result["fbx"] = exp.data if exp.ok else exp.error
    return result


if __name__ == "__main__":
    print("在 Maya 中 import 后调用 prepare_static_mesh('pCube1', 'Crate', r'D:/export')")

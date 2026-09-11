"""Script execution tools."""

from __future__ import annotations

import io
import traceback
from contextlib import redirect_stdout, redirect_stderr

from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.utils.maya_compat import in_maya

@tool(
    name="execute_python",
    description="在 Maya 中执行 Python 代码片段（可访问 maya.cmds）。用于复杂或尚未封装的操作。",
    parameters=obj_schema(
        {
            "code": {"type": "string", "description": "Python 源码"},
            "undo_chunk_name": {"type": "string", "default": "MayaAgentExec"},
        },
        required=["code"],
    ),
    category="scripting",
    destructive=True,
)
def execute_python(code: str, undo_chunk_name: str = "MayaAgentExec") -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    import maya.cmds as cmds

    stdout = io.StringIO()
    stderr = io.StringIO()
    local_ns = {"cmds": cmds, "__name__": "__maya_agent__"}
    # If Agent turn already opened an undo chunk, avoid nested open/close here.
    own_chunk = True
    try:
        # Heuristic: if undo is enabled we still open a chunk when running
        # standalone; nested chunks inside MayaAgentTurn are OK but redundant.
        cmds.undoInfo(state=True)
        cmds.undoInfo(openChunk=True, chunkName=undo_chunk_name)
    except Exception:
        own_chunk = False
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exec(compile(code, "<maya_agent>", "exec"), local_ns, local_ns)
        result = local_ns.get("result", stdout.getvalue())
        return ToolResult(
            ok=True,
            data={"result": result, "stdout": stdout.getvalue(), "stderr": stderr.getvalue()},
            message="脚本执行成功",
        )
    except Exception as e:
        return ToolResult(
            ok=False,
            error=f"{type(e).__name__}: {e}",
            data={"traceback": traceback.format_exc(), "stdout": stdout.getvalue()},
        )
    finally:
        if own_chunk:
            try:
                cmds.undoInfo(closeChunk=True)
            except Exception:
                pass

@tool(
    name="execute_mel",
    description="执行 MEL 命令字符串。",
    parameters=obj_schema(
        {"command": {"type": "string"}},
        required=["command"],
    ),
    category="scripting",
    destructive=True,
)
def execute_mel(command: str) -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    from maya_agent.utils.maya_compat import mel

    try:
        result = mel().eval(command)
        return ToolResult(ok=True, data=result, message="MEL 执行成功")
    except Exception as e:
        return ToolResult(ok=False, error=str(e))

@tool(
    name="generate_python_snippet",
    description=(
        "根据任务描述生成可在 Maya 中运行的简易 Python 示例（不执行）。"
        "正式开发工具请优先用 scaffold_maya_tool（maya_dev）。"
    ),
    parameters=obj_schema(
        {
            "task": {"type": "string", "description": "任务描述"},
            "use_cmds": {"type": "boolean", "default": True},
        },
        required=["task"],
    ),
    category="scripting",
)
def generate_python_snippet(task: str, use_cmds: bool = True) -> ToolResult:
    # Lightweight template helper — the LLM usually writes code itself;
    # this tool provides a structured stub when needed.
    api = "maya.cmds" if use_cmds else "pymel.core"
    code = f'''"""
Auto stub for: {task}
"""
import maya.cmds as cmds

def run():
    # TODO: implement — {task}
    sel = cmds.ls(selection=True) or []
    print("selection:", sel)
    return sel

result = run()
'''
    return ToolResult(
        ok=True,
        data={"code": code, "api": api},
        message="已生成代码模板（可按需修改后用 execute_python 执行）",
    )

"""Script execution tools."""

from __future__ import annotations

import io
import os
import re
import sys
import traceback
from typing import Optional
from contextlib import redirect_stdout, redirect_stderr

from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.utils.maya_compat import in_maya


def _guess_fail_line(tb_text: str) -> Optional[int]:
    """Extract failing line number from traceback for <maya_agent> code."""
    if not tb_text:
        return None
    matches = re.findall(r'File "<maya_agent>", line (\d+)', tb_text)
    if not matches:
        return None
    try:
        return int(matches[-1])
    except ValueError:
        return None


def _ensure_agent_import_paths() -> list:
    """Put userScriptDir and MayaAgent_tools on sys.path so written scripts import."""
    inserted = []
    candidates = []
    if in_maya():
        try:
            import maya.cmds as cmds

            usd = cmds.internalVar(userScriptDir=True) or ""
            if usd:
                candidates.append(os.path.normpath(usd))
                candidates.append(os.path.normpath(os.path.join(usd, "MayaAgent_tools")))
        except Exception:
            pass
    for p in candidates:
        if p and os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
            inserted.append(p)
    return inserted


def _guess_fail_line(tb_text: str) -> Optional[int]:
    """Extract failing line number from traceback for <maya_agent> code."""
    if not tb_text:
        return None
    matches = re.findall(r'File "<maya_agent>", line (\d+)', tb_text)
    if not matches:
        return None
    try:
        return int(matches[-1])
    except ValueError:
        return None


@tool(
    name="execute_python",
    description=(
        "在 Maya 中执行 Python 代码片段（可访问 maya.cmds）。"
        "atomic=True（默认）时：异常会撤销本段 undo chunk（含中止前已成功的修改）；"
        "返回 rolled_back=true 且 stdout_is_stale=true——stdout 是回滚前打印，不代表当前场景。"
        "atomic=False 时保留已生效部分。userScriptDir 与 MayaAgent_tools 已在 sys.path 中，可直接 import。"
    ),
    parameters=obj_schema(
        {
            "code": {"type": "string", "description": "Python 源码"},
            "undo_chunk_name": {"type": "string", "default": "MayaAgentExec"},
            "atomic": {
                "type": "boolean",
                "default": True,
                "description": "异常时回滚本段 undo chunk（默认 True）",
            },
        },
        required=["code"],
    ),
    category="scripting",
    destructive=True,
)
def execute_python(
    code: str,
    undo_chunk_name: str = "MayaAgentExec",
    atomic: bool = True,
) -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    import maya.cmds as cmds

    _ensure_agent_import_paths()
    stdout = io.StringIO()
    stderr = io.StringIO()
    local_ns = {"cmds": cmds, "__name__": "__maya_agent__"}
    own_chunk = True
    try:
        cmds.undoInfo(state=True)
        cmds.undoInfo(openChunk=True, chunkName=undo_chunk_name)
    except Exception:
        own_chunk = False

    failed = False
    fail_line = None
    tb_text = ""
    err_msg = ""
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exec(compile(code, "<maya_agent>", "exec"), local_ns, local_ns)
        result = local_ns.get("result", stdout.getvalue())
        return ToolResult(
            ok=True,
            data={
                "result": result,
                "stdout": stdout.getvalue(),
                "stderr": stderr.getvalue(),
                "atomic": bool(atomic),
            },
            message="脚本执行成功",
        )
    except Exception as e:
        failed = True
        tb_text = traceback.format_exc()
        fail_line = _guess_fail_line(tb_text)
        err_msg = f"{type(e).__name__}: {e}"
        data = {
            "traceback": tb_text,
            "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(),
            "atomic": bool(atomic),
            "fail_line": fail_line,
            "rolled_back": False,
            "partial_applied": False,
        }
        # Close chunk first so undo can reverse the whole chunk
        if own_chunk:
            try:
                cmds.undoInfo(closeChunk=True)
            except Exception:
                pass
            own_chunk = False

        if atomic:
            try:
                cmds.undo()
                data["rolled_back"] = True
                data["stdout_is_stale"] = True
                data["rolled_back_ops"] = (
                    "本段 undo chunk 已全部撤销，包括中止前已成功的写权重/改属性等。"
                    "stdout 仅反映回滚前的 print，不代表当前场景。"
                )
                stale = (
                    "[注意] 下列 stdout 来自已回滚的执行，场景已还原为调用前状态。\n"
                )
                data["stdout"] = stale + (data.get("stdout") or "")
                note = "已回滚本段全部修改（含中止前已成功步骤，atomic=True）"
                if fail_line:
                    note = f"第 {fail_line} 行中止；{note}"
                return ToolResult(ok=False, error=f"{err_msg}。{note}", data=data)
            except Exception as undo_err:
                data["rolled_back"] = False
                data["partial_applied"] = True
                data["undo_error"] = str(undo_err)
                note = "回滚失败，前序步骤可能已生效"
                if fail_line:
                    note = f"第 {fail_line} 行中止；{note}"
                return ToolResult(ok=False, error=f"{err_msg}。{note}", data=data)

        data["partial_applied"] = True
        note = "前序步骤已生效（atomic=False，未回滚）"
        if fail_line:
            note = f"第 {fail_line} 行中止；{note}"
        return ToolResult(ok=False, error=f"{err_msg}。{note}", data=data)
    finally:
        if own_chunk and not failed:
            try:
                cmds.undoInfo(closeChunk=True)
            except Exception:
                pass
        elif own_chunk and failed:
            # Safety: ensure chunk closed if error path didn't
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

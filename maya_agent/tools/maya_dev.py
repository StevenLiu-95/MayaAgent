"""Maya tool-development helpers: API lookup, scripts, shelves, plugins, validation."""

from __future__ import annotations

import ast
import importlib
import os
import re
import sys
import traceback
from typing import Any, Dict, List, Optional

from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.tools._maya import cmds as _cmds, in_maya


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _scripts_roots() -> List[str]:
    """Maya-related script directories the agent may read/write."""
    roots: List[str] = []
    if in_maya():
        c = _cmds()
        try:
            for p in c.internalVar(userScriptDir=True), c.internalVar(userAppDir=True):
                if p and os.path.isdir(p) and p not in roots:
                    roots.append(os.path.normpath(p))
        except Exception:
            pass
        try:
            pref = c.internalVar(userPrefDir=True)
            if pref and os.path.isdir(pref) and pref not in roots:
                roots.append(os.path.normpath(pref))
        except Exception:
            pass
    # Always allow project-relative scripts/examples if present
    pkg_root = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )
    for sub in ("scripts", "scripts/examples"):
        p = os.path.join(pkg_root, sub.replace("/", os.sep))
        if os.path.isdir(p) and p not in roots:
            roots.append(p)
    return roots


def _resolve_script_path(path: str, *, must_exist: bool = False) -> str:
    path = os.path.expanduser(path.strip())
    if not os.path.isabs(path):
        # Prefer user script dir when relative
        if in_maya():
            try:
                base = _cmds().internalVar(userScriptDir=True)
                if base:
                    path = os.path.join(base, path)
            except Exception:
                pass
        if not os.path.isabs(path):
            path = os.path.abspath(path)
    path = os.path.normpath(path)
    if must_exist and not os.path.isfile(path):
        raise FileNotFoundError(f"文件不存在: {path}")
    return path


def _is_safe_script_path(path: str) -> bool:
    """Allow writes under known script roots or explicit absolute paths ending in .py/.mel."""
    path = os.path.normpath(path)
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".py", ".mel", ".json", ".txt", ".md"):
        return False
    roots = _scripts_roots()
    for root in roots:
        try:
            if os.path.commonpath([root, path]) == root:
                return True
        except ValueError:
            continue
    # Absolute path outside roots still allowed for .py/.mel (power-user tool write)
    return os.path.isabs(path) and ext in (".py", ".mel")


def _truncate(text: str, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n...[truncated, total {len(text)} chars]"


# ---------------------------------------------------------------------------
# Environment & API introspection
# ---------------------------------------------------------------------------

@tool(
    name="get_maya_dev_env",
    description=(
        "获取 Maya 工具开发环境信息：版本、Python、脚本路径、插件路径、当前工程。"
        "开始编写/调试 Maya 工具前建议先调用。"
    ),
    parameters=obj_schema({}),
    category="maya_dev",
)
def get_maya_dev_env() -> ToolResult:
    data: Dict[str, Any] = {
        "in_maya": in_maya(),
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "sys_path_head": [p for p in sys.path[:12] if p],
    }
    if not in_maya():
        return ToolResult(ok=True, data=data, message="未在 Maya 中，仅返回 Python 信息")
    c = _cmds()
    try:
        data.update(
            {
                "maya_version": c.about(version=True),
                "maya_api": c.about(apiVersion=True),
                "os": c.about(operatingSystemVersion=True),
                "user_script_dir": c.internalVar(userScriptDir=True),
                "user_shelf_dir": c.internalVar(userShelfDir=True),
                "user_bitmaps_dir": c.internalVar(userBitmapsDir=True),
                "user_app_dir": c.internalVar(userAppDir=True),
                "plugin_path": c.about(pluginPath=True),
                "scene": c.file(query=True, sceneName=True) or "(untitled)",
                "workspace": c.workspace(q=True, rootDirectory=True),
                "script_roots": _scripts_roots(),
            }
        )
    except Exception as e:
        data["error_partial"] = str(e)
    return ToolResult(ok=True, data=data, message="开发环境信息已获取")


@tool(
    name="lookup_cmds_help",
    description=(
        "查询 maya.cmds 命令的官方帮助（语法、标志、示例）。"
        "写工具前用此确认 API，避免猜错 flag 名称。"
    ),
    parameters=obj_schema(
        {
            "command": {
                "type": "string",
                "description": "cmds 命令名，如 polyCube、xform、file",
            },
            "language": {
                "type": "string",
                "enum": ["python", "mel"],
                "default": "python",
            },
        },
        required=["command"],
    ),
    category="maya_dev",
)
def lookup_cmds_help(command: str, language: str = "python") -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    c = _cmds()
    cmd = command.strip().lstrip("cmds.")
    if not cmd or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", cmd):
        return ToolResult(ok=False, error="无效命令名")
    try:
        help_text = c.help(cmd, language=language) or ""
    except Exception as e:
        return ToolResult(ok=False, error=f"无法获取帮助: {e}")
    # Extract short flag list for quick reference
    flags = sorted(set(re.findall(r"-([a-zA-Z][\w]*)\b", help_text)))
    return ToolResult(
        ok=True,
        data={
            "command": cmd,
            "language": language,
            "help": _truncate(help_text),
            "flags_mentioned": flags[:80],
        },
        message=f"已获取 cmds.{cmd} 帮助",
    )


@tool(
    name="search_cmds",
    description=(
        "按关键词搜索 maya.cmds 可用命令（名称包含关键词）。"
        "不确定用哪个 API 时先搜索，再 lookup_cmds_help。"
    ),
    parameters=obj_schema(
        {
            "keyword": {
                "type": "string",
                "description": "关键词，如 skin、uv、export、constraint",
            },
            "limit": {"type": "integer", "default": 40},
        },
        required=["keyword"],
    ),
    category="maya_dev",
)
def search_cmds(keyword: str, limit: int = 40) -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    c = _cmds()
    kw = keyword.strip().lower()
    if not kw:
        return ToolResult(ok=False, error="关键词为空")
    limit = max(1, min(int(limit), 200))
    all_cmds: List[str] = []
    try:
        from maya_agent.utils.maya_compat import mel

        listed = mel().eval("help -listCommands;") or []
        if isinstance(listed, str):
            listed = listed.split()
        all_cmds = list(listed)
    except Exception:
        pass
    if not all_cmds:
        all_cmds = [n for n in dir(c) if not n.startswith("_") and callable(getattr(c, n, None))]
    matches = [n for n in all_cmds if kw in str(n).lower()]
    matches.sort(key=lambda n: (0 if n.lower().startswith(kw) else 1, n.lower()))
    return ToolResult(
        ok=True,
        data={"keyword": kw, "total": len(matches), "commands": matches[:limit]},
        message=f"找到 {len(matches)} 个命令（返回前 {min(limit, len(matches))}）",
    )


@tool(
    name="inspect_node",
    description=(
        "检查节点/对象：类型、长名、父级、关键属性值。"
        "开发针对特定节点类型的工具时用于摸清属性与连接。"
    ),
    parameters=obj_schema(
        {
            "name": {
                "type": "string",
                "description": "节点名；空则用当前选择第一个",
                "default": "",
            },
            "include_attrs": {
                "type": "boolean",
                "default": True,
                "description": "是否列出 keyable/channelBox 属性",
            },
            "include_connections": {
                "type": "boolean",
                "default": False,
                "description": "是否列出输入/输出连接摘要",
            },
            "attr_limit": {"type": "integer", "default": 60},
        }
    ),
    category="maya_dev",
)
def inspect_node(
    name: str = "",
    include_attrs: bool = True,
    include_connections: bool = False,
    attr_limit: int = 60,
) -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    c = _cmds()
    target = name.strip()
    if not target:
        sel = c.ls(selection=True, long=True) or []
        if not sel:
            return ToolResult(ok=False, error="未指定 name 且无选择")
        target = sel[0]
    if not c.objExists(target):
        return ToolResult(ok=False, error=f"对象不存在: {target}")
    long_name = c.ls(target, long=True)[0]
    ntype = c.nodeType(long_name)
    data: Dict[str, Any] = {
        "name": long_name,
        "short": long_name.split("|")[-1],
        "node_type": ntype,
        "parents": c.listRelatives(long_name, parent=True, fullPath=True) or [],
        "children": (c.listRelatives(long_name, children=True, fullPath=True) or [])[:40],
        "shapes": c.listRelatives(long_name, shapes=True, fullPath=True) or [],
    }
    attr_limit = max(1, min(int(attr_limit), 200))
    if include_attrs:
        attrs = c.listAttr(long_name, keyable=True) or []
        cb = c.listAttr(long_name, channelBox=True) or []
        seen = []
        for a in attrs + cb:
            if a not in seen:
                seen.append(a)
        attr_vals = {}
        for a in seen[:attr_limit]:
            plug = f"{long_name}.{a}"
            try:
                if c.attributeQuery(a, node=long_name, exists=True):
                    attr_vals[a] = c.getAttr(plug)
            except Exception as e:
                attr_vals[a] = f"<error: {e}>"
        data["attributes"] = attr_vals
    if include_connections:
        try:
            data["inputs"] = (c.listConnections(long_name, source=True, destination=False, plugs=True) or [])[:40]
            data["outputs"] = (c.listConnections(long_name, source=False, destination=True, plugs=True) or [])[:40]
        except Exception as e:
            data["connections_error"] = str(e)
    return ToolResult(ok=True, data=data, message=f"已检查 {ntype}: {long_name}")


@tool(
    name="list_node_types",
    description="按关键词过滤 Maya 节点类型（用于确认工具应处理的 nodeType）。",
    parameters=obj_schema(
        {
            "keyword": {"type": "string", "default": ""},
            "limit": {"type": "integer", "default": 50},
        }
    ),
    category="maya_dev",
)
def list_node_types(keyword: str = "", limit: int = 50) -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    c = _cmds()
    limit = max(1, min(int(limit), 300))
    try:
        types = c.allNodeTypes() or []
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
    kw = keyword.strip().lower()
    if kw:
        types = [t for t in types if kw in t.lower()]
    types = sorted(types)
    return ToolResult(
        ok=True,
        data={"keyword": kw, "total": len(types), "types": types[:limit]},
        message=f"节点类型 {len(types)} 个（返回前 {min(limit, len(types))}）",
    )


# ---------------------------------------------------------------------------
# Code validation & file I/O
# ---------------------------------------------------------------------------

@tool(
    name="validate_python",
    description=(
        "语法检查 Python 代码（ast.parse，不执行）。"
        "写入文件或 execute_python 之前先验证，减少运行时 SyntaxError。"
    ),
    parameters=obj_schema(
        {
            "code": {"type": "string", "description": "待检查的 Python 源码"},
            "filename": {
                "type": "string",
                "default": "<tool>",
                "description": "报错时显示的文件名",
            },
        },
        required=["code"],
    ),
    category="maya_dev",
)
def validate_python(code: str, filename: str = "<tool>") -> ToolResult:
    try:
        tree = ast.parse(code, filename=filename or "<tool>")
    except SyntaxError as e:
        return ToolResult(
            ok=False,
            error=f"SyntaxError: {e.msg} (line {e.lineno}, col {e.offset})",
            data={
                "lineno": e.lineno,
                "offset": e.offset,
                "text": e.text,
                "filename": filename,
            },
        )
    funcs = [
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    imports = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imports.extend(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            imports.append(n.module or "")
    return ToolResult(
        ok=True,
        data={
            "filename": filename,
            "functions": funcs[:50],
            "classes": classes[:30],
            "imports": list(dict.fromkeys(imports))[:40],
            "lines": code.count("\n") + 1,
        },
        message="语法通过",
    )


@tool(
    name="read_script_file",
    description="读取本地脚本文件内容（.py/.mel 等）。用于审阅或在已有工具上迭代。",
    parameters=obj_schema(
        {
            "path": {
                "type": "string",
                "description": "绝对路径，或相对 userScriptDir 的路径",
            },
            "max_chars": {"type": "integer", "default": 20000},
        },
        required=["path"],
    ),
    category="maya_dev",
)
def read_script_file(path: str, max_chars: int = 20000) -> ToolResult:
    try:
        resolved = _resolve_script_path(path, must_exist=True)
    except FileNotFoundError as e:
        return ToolResult(ok=False, error=str(e))
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
    max_chars = max(500, min(int(max_chars), 100000))
    try:
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception as e:
        return ToolResult(ok=False, error=f"读取失败: {e}")
    truncated = len(text) > max_chars
    return ToolResult(
        ok=True,
        data={
            "path": resolved,
            "size": len(text),
            "truncated": truncated,
            "content": text[:max_chars],
        },
        message=f"已读取 {resolved}" + ("（已截断）" if truncated else ""),
    )


@tool(
    name="write_script_file",
    description=(
        "将 Python/MEL 脚本写入磁盘（默认 userScriptDir 或绝对路径）。"
        "开发 Maya 工具时用于落盘；覆盖已有文件前请确认。"
    ),
    parameters=obj_schema(
        {
            "path": {
                "type": "string",
                "description": "相对 userScriptDir 或绝对路径，建议以 .py/.mel 结尾",
            },
            "content": {"type": "string", "description": "文件完整内容"},
            "overwrite": {
                "type": "boolean",
                "default": False,
                "description": "若文件已存在是否覆盖",
            },
            "create_dirs": {"type": "boolean", "default": True},
        },
        required=["path", "content"],
    ),
    category="maya_dev",
    destructive=True,
)
def write_script_file(
    path: str,
    content: str,
    overwrite: bool = False,
    create_dirs: bool = True,
) -> ToolResult:
    try:
        resolved = _resolve_script_path(path, must_exist=False)
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
    if not _is_safe_script_path(resolved):
        return ToolResult(
            ok=False,
            error="路径不安全或不支持的扩展名（仅允许 .py/.mel/.json/.txt/.md）",
        )
    if os.path.exists(resolved) and not overwrite:
        return ToolResult(
            ok=False,
            error=f"文件已存在，未覆盖: {resolved}（设 overwrite=true 可覆盖）",
        )
    parent = os.path.dirname(resolved)
    if create_dirs and parent and not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except Exception as e:
            return ToolResult(ok=False, error=f"创建目录失败: {e}")
    # Soft syntax gate for .py
    if resolved.lower().endswith(".py"):
        try:
            ast.parse(content, filename=resolved)
        except SyntaxError as e:
            return ToolResult(
                ok=False,
                error=f"写入中止，语法错误: {e.msg} (line {e.lineno})",
                data={"lineno": e.lineno, "offset": e.offset},
            )
    try:
        with open(resolved, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
    except Exception as e:
        return ToolResult(ok=False, error=f"写入失败: {e}")
    return ToolResult(
        ok=True,
        data={"path": resolved, "bytes": len(content.encode("utf-8"))},
        message=f"已写入 {resolved}",
    )


@tool(
    name="list_script_files",
    description="列出脚本目录下的文件（默认 Maya userScriptDir）。",
    parameters=obj_schema(
        {
            "directory": {
                "type": "string",
                "default": "",
                "description": "目录；空则用 userScriptDir",
            },
            "pattern": {
                "type": "string",
                "default": ".py",
                "description": "扩展名过滤，如 .py / .mel；空则全部",
            },
            "recursive": {"type": "boolean", "default": False},
            "limit": {"type": "integer", "default": 80},
        }
    ),
    category="maya_dev",
)
def list_script_files(
    directory: str = "",
    pattern: str = ".py",
    recursive: bool = False,
    limit: int = 80,
) -> ToolResult:
    if directory.strip():
        root = os.path.normpath(os.path.expanduser(directory.strip()))
    elif in_maya():
        root = os.path.normpath(_cmds().internalVar(userScriptDir=True) or "")
    else:
        return ToolResult(ok=False, error="未指定 directory 且不在 Maya 中")
    if not os.path.isdir(root):
        return ToolResult(ok=False, error=f"目录不存在: {root}")
    limit = max(1, min(int(limit), 500))
    pat = (pattern or "").lower()
    files: List[str] = []
    if recursive:
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                if pat and not fn.lower().endswith(pat):
                    continue
                files.append(os.path.join(dirpath, fn))
                if len(files) >= limit:
                    break
            if len(files) >= limit:
                break
    else:
        for fn in sorted(os.listdir(root)):
            fp = os.path.join(root, fn)
            if not os.path.isfile(fp):
                continue
            if pat and not fn.lower().endswith(pat):
                continue
            files.append(fp)
            if len(files) >= limit:
                break
    return ToolResult(
        ok=True,
        data={"directory": root, "count": len(files), "files": files},
        message=f"列出 {len(files)} 个文件",
    )


@tool(
    name="run_python_file",
    description="在 Maya 中执行磁盘上的 .py 文件（exec 文件内容）。用于测试已落盘的工具脚本。",
    parameters=obj_schema(
        {
            "path": {"type": "string", "description": "脚本路径"},
            "as_main": {
                "type": "boolean",
                "default": True,
                "description": "是否以 __name__=='__main__' 方式执行",
            },
        },
        required=["path"],
    ),
    category="maya_dev",
    destructive=True,
)
def run_python_file(path: str, as_main: bool = True) -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    try:
        resolved = _resolve_script_path(path, must_exist=True)
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
    if not resolved.lower().endswith(".py"):
        return ToolResult(ok=False, error="仅支持 .py 文件")
    import io
    from contextlib import redirect_stdout, redirect_stderr
    import maya.cmds as cmds

    try:
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            code = f.read()
    except Exception as e:
        return ToolResult(ok=False, error=f"读取失败: {e}")

    stdout, stderr = io.StringIO(), io.StringIO()
    ns: Dict[str, Any] = {
        "cmds": cmds,
        "__file__": resolved,
        "__name__": "__main__" if as_main else os.path.splitext(os.path.basename(resolved))[0],
    }
    # Ensure script directory is importable
    script_dir = os.path.dirname(resolved)
    inserted = False
    if script_dir and script_dir not in sys.path:
        sys.path.insert(0, script_dir)
        inserted = True
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exec(compile(code, resolved, "exec"), ns, ns)
        return ToolResult(
            ok=True,
            data={
                "path": resolved,
                "stdout": stdout.getvalue(),
                "stderr": stderr.getvalue(),
                "result": ns.get("result"),
            },
            message=f"已执行 {resolved}",
        )
    except Exception as e:
        return ToolResult(
            ok=False,
            error=f"{type(e).__name__}: {e}",
            data={
                "path": resolved,
                "traceback": traceback.format_exc(),
                "stdout": stdout.getvalue(),
            },
        )
    finally:
        if inserted:
            try:
                sys.path.remove(script_dir)
            except ValueError:
                pass


@tool(
    name="reload_python_module",
    description=(
        "重新加载已导入的 Python 模块（importlib.reload）。"
        "修改工具脚本后热更新，无需重启 Maya。"
    ),
    parameters=obj_schema(
        {
            "module_name": {
                "type": "string",
                "description": "模块名，如 my_tools.renamer",
            }
        },
        required=["module_name"],
    ),
    category="maya_dev",
)
def reload_python_module(module_name: str) -> ToolResult:
    name = module_name.strip()
    if not name or not re.match(r"^[A-Za-z_][\w.]*$", name):
        return ToolResult(ok=False, error="无效模块名")
    if name not in sys.modules:
        try:
            mod = importlib.import_module(name)
        except Exception as e:
            return ToolResult(ok=False, error=f"导入失败: {e}")
        return ToolResult(
            ok=True,
            data={"module": name, "file": getattr(mod, "__file__", None), "action": "import"},
            message=f"模块首次导入: {name}",
        )
    try:
        mod = importlib.reload(sys.modules[name])
    except Exception as e:
        return ToolResult(
            ok=False,
            error=f"reload 失败: {e}",
            data={"traceback": traceback.format_exc()},
        )
    return ToolResult(
        ok=True,
        data={"module": name, "file": getattr(mod, "__file__", None), "action": "reload"},
        message=f"已重载: {name}",
    )


# ---------------------------------------------------------------------------
# Scaffold / shelf / plugin
# ---------------------------------------------------------------------------

@tool(
    name="scaffold_maya_tool",
    description=(
        "生成 Maya 工具脚手架代码（不写盘、不执行）："
        "cmds_script / shelf_tool / pyside_window / plugin_cmd。"
        "拿到模板后可用 write_script_file 落盘，再用 run_python_file 测试。"
    ),
    parameters=obj_schema(
        {
            "tool_name": {
                "type": "string",
                "description": "工具名（合法标识符），如 batch_renamer",
            },
            "template": {
                "type": "string",
                "enum": ["cmds_script", "shelf_tool", "pyside_window", "plugin_cmd"],
                "default": "cmds_script",
            },
            "description": {
                "type": "string",
                "default": "",
                "description": "工具功能简述，写入注释",
            },
        },
        required=["tool_name"],
    ),
    category="maya_dev",
)
def scaffold_maya_tool(
    tool_name: str,
    template: str = "cmds_script",
    description: str = "",
) -> ToolResult:
    name = tool_name.strip()
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        return ToolResult(ok=False, error="tool_name 须为合法 Python 标识符")
    desc = (description or f"Maya tool: {name}").replace('"""', "'").replace("\\", "\\\\")
    desc_q = desc.replace('"', '\\"')
    class_name = "".join(p.title() for p in name.split("_"))
    if not class_name.endswith("Tool"):
        class_name += "Tool"

    if template == "shelf_tool":
        code = f'''# -*- coding: utf-8 -*-
"""{desc}

Shelf / shelfButton 可直接调用: import {name}; {name}.run()
"""
from __future__ import annotations

import maya.cmds as cmds


def run(*_args, **_kwargs):
    sel = cmds.ls(selection=True, long=True) or []
    if not sel:
        cmds.warning("[{name}] 请先选择对象")
        return []
    # TODO: implement tool logic
    cmds.inViewMessage(
        amg=f"<hl>{name}</hl>: {{len(sel)}} selected",
        pos="midCenter",
        fade=True,
    )
    return sel


if __name__ == "__main__":
    run()
'''
    elif template == "pyside_window":
        code = f'''# -*- coding: utf-8 -*-
"""{desc}

PySide 工具窗口模板（兼容 PySide2 / PySide6）。
"""
from __future__ import annotations

import maya.cmds as cmds
import maya.OpenMayaUI as omui

try:
    from PySide6 import QtCore, QtWidgets
    from shiboken6 import wrapInstance
except ImportError:
    from PySide2 import QtCore, QtWidgets
    from shiboken2 import wrapInstance


def _maya_main_window():
    ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(ptr), QtWidgets.QWidget)


class {class_name}(QtWidgets.QDialog):
    WINDOW_OBJECT = "{name}_window"

    def __init__(self, parent=None):
        super({class_name}, self).__init__(parent or _maya_main_window())
        self.setObjectName(self.WINDOW_OBJECT)
        self.setWindowTitle("{name}")
        self.setMinimumWidth(360)
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        self.info = QtWidgets.QLabel("{desc_q}")
        self.run_btn = QtWidgets.QPushButton("Run")
        self.run_btn.clicked.connect(self.on_run)
        layout.addWidget(self.info)
        layout.addWidget(self.run_btn)

    def on_run(self):
        sel = cmds.ls(selection=True) or []
        cmds.inViewMessage(
            amg=f"<hl>{name}</hl>: {{len(sel)}} selected",
            pos="midCenter",
            fade=True,
        )


def show():
    for w in QtWidgets.QApplication.topLevelWidgets():
        if w.objectName() == {class_name}.WINDOW_OBJECT:
            w.close()
            w.deleteLater()
    dlg = {class_name}()
    dlg.show()
    return dlg


if __name__ == "__main__":
    show()
'''
    elif template == "plugin_cmd":
        code = f'''# -*- coding: utf-8 -*-
"""{desc}

Maya Python 插件命令模板。加载: cmds.loadPlugin(r"path/to/{name}.py")
"""
from __future__ import annotations

import sys
import maya.api.OpenMaya as om


def maya_useNewAPI():
    pass


class {class_name}(om.MPxCommand):
    CMD_NAME = "{name}"

    def __init__(self):
        super({class_name}, self).__init__()

    def doIt(self, args):
        # TODO: parse args / implement
        print("[{name}] executed")
        return self

    @staticmethod
    def creator():
        return {class_name}()


def initializePlugin(plugin):
    plugin_fn = om.MFnPlugin(plugin, "MayaAgent", "1.0", "Any")
    try:
        plugin_fn.registerCommand({class_name}.CMD_NAME, {class_name}.creator)
    except Exception:
        sys.stderr.write("Failed to register command: {name}\\n")
        raise


def uninitializePlugin(plugin):
    plugin_fn = om.MFnPlugin(plugin)
    try:
        plugin_fn.deregisterCommand({class_name}.CMD_NAME)
    except Exception:
        sys.stderr.write("Failed to deregister command: {name}\\n")
        raise
'''
    else:  # cmds_script
        code = f'''# -*- coding: utf-8 -*-
"""{desc}

可在 Script Editor 或 Agent 中 import 后调用 run()。
"""
from __future__ import annotations

import maya.cmds as cmds


def run(selection=None):
    """Main entry.

    Args:
        selection: 可选对象列表；默认用当前选择。
    Returns:
        处理结果列表
    """
    targets = selection or (cmds.ls(selection=True, long=True) or [])
    if not targets:
        cmds.warning("[{name}] 没有可处理的对象")
        return []

    results = []
    cmds.undoInfo(openChunk=True, chunkName="{name}")
    try:
        for node in targets:
            # TODO: implement per-node logic
            results.append(node)
    finally:
        cmds.undoInfo(closeChunk=True)
    return results


if __name__ == "__main__":
    result = run()
    print(result)
'''

    suggested = f"{name}.py"
    if in_maya():
        try:
            suggested = os.path.join(_cmds().internalVar(userScriptDir=True), f"{name}.py")
        except Exception:
            pass
    return ToolResult(
        ok=True,
        data={
            "tool_name": name,
            "template": template,
            "code": code,
            "suggested_path": suggested,
            "next_steps": [
                "用 validate_python 检查语法",
                "用 write_script_file 写入 suggested_path（或自定义路径）",
                "用 run_python_file 或 execute_python 测试",
                "需要快捷入口时用 create_shelf_button",
            ],
        },
        message=f"已生成 {template} 脚手架: {name}",
    )


@tool(
    name="create_shelf_button",
    description=(
        "在当前/指定 Shelf 上创建按钮，用于挂接刚写好的工具 "
        "（command 一般为 Python，如 import my_tool; my_tool.run()）。"
    ),
    parameters=obj_schema(
        {
            "label": {"type": "string", "description": "按钮显示名"},
            "command": {
                "type": "string",
                "description": "点击执行的代码（Python 或 MEL）",
            },
            "source_type": {
                "type": "string",
                "enum": ["python", "mel"],
                "default": "python",
            },
            "shelf": {
                "type": "string",
                "default": "",
                "description": "Shelf 名；空则用当前 Shelf",
            },
            "annotation": {"type": "string", "default": ""},
            "image": {
                "type": "string",
                "default": "commandButton.png",
                "description": "图标文件名或路径",
            },
        },
        required=["label", "command"],
    ),
    category="maya_dev",
    destructive=True,
)
def create_shelf_button(
    label: str,
    command: str,
    source_type: str = "python",
    shelf: str = "",
    annotation: str = "",
    image: str = "commandButton.png",
) -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    c = _cmds()
    shelf_name = shelf.strip()
    if not shelf_name:
        try:
            from maya_agent.utils.maya_compat import mel

            shelf_name = mel().eval("shelfTabLayout -q -selectTab $gShelfTopLevel;")
        except Exception:
            shelf_name = ""
    if not shelf_name:
        return ToolResult(ok=False, error="无法确定当前 Shelf，请传入 shelf 参数")
    if not c.shelfLayout(shelf_name, exists=True):
        return ToolResult(ok=False, error=f"Shelf 不存在: {shelf_name}")
    src = "python" if source_type != "mel" else "mel"
    try:
        btn = c.shelfButton(
            parent=shelf_name,
            label=label,
            command=command,
            sourceType=src,
            annotation=annotation or label,
            image=image or "commandButton.png",
            style="iconAndTextVertical",
        )
    except Exception as e:
        return ToolResult(ok=False, error=f"创建失败: {e}")
    return ToolResult(
        ok=True,
        data={"shelf": shelf_name, "button": btn, "label": label},
        message=f"已在 Shelf「{shelf_name}」创建按钮「{label}」",
    )


@tool(
    name="list_shelves",
    description="列出 Maya Shelf 名称，并可返回指定 Shelf 上的按钮标签。",
    parameters=obj_schema(
        {
            "shelf": {
                "type": "string",
                "default": "",
                "description": "若指定则列出该 Shelf 的按钮",
            }
        }
    ),
    category="maya_dev",
)
def list_shelves(shelf: str = "") -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    c = _cmds()
    try:
        from maya_agent.utils.maya_compat import mel

        shelves = mel().eval('shelfTabLayout -q -childArray $gShelfTopLevel;') or []
        if isinstance(shelves, str):
            shelves = [shelves]
    except Exception:
        shelves = []
    data: Dict[str, Any] = {"shelves": list(shelves)}
    target = shelf.strip()
    if target:
        if not c.shelfLayout(target, exists=True):
            return ToolResult(ok=False, error=f"Shelf 不存在: {target}", data=data)
        kids = c.shelfLayout(target, q=True, childArray=True) or []
        buttons = []
        for kid in kids:
            try:
                if c.objectTypeUI(kid) == "shelfButton":
                    buttons.append(
                        {
                            "name": kid,
                            "label": c.shelfButton(kid, q=True, label=True),
                            "annotation": c.shelfButton(kid, q=True, annotation=True),
                        }
                    )
            except Exception:
                continue
        data["shelf"] = target
        data["buttons"] = buttons
    return ToolResult(ok=True, data=data, message="Shelf 信息已获取")


@tool(
    name="list_plugins",
    description="列出已加载或全部插件；可用于工具依赖检查（如 fbxmaya、objExport）。",
    parameters=obj_schema(
        {
            "query": {
                "type": "string",
                "enum": ["loaded", "all"],
                "default": "loaded",
            },
            "keyword": {"type": "string", "default": ""},
            "limit": {"type": "integer", "default": 80},
        }
    ),
    category="maya_dev",
)
def list_plugins(query: str = "loaded", keyword: str = "", limit: int = 80) -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    c = _cmds()
    limit = max(1, min(int(limit), 300))
    try:
        if query == "all":
            plugins = c.pluginInfo(query=True, listPlugins=True) or []
        else:
            plugins = c.pluginInfo(query=True, listPlugins=True) or []
            plugins = [p for p in plugins if c.pluginInfo(p, query=True, loaded=True)]
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
    kw = keyword.strip().lower()
    if kw:
        plugins = [p for p in plugins if kw in p.lower()]
    plugins = sorted(plugins)
    details = []
    for p in plugins[:limit]:
        try:
            details.append(
                {
                    "name": p,
                    "loaded": bool(c.pluginInfo(p, query=True, loaded=True)),
                    "path": c.pluginInfo(p, query=True, path=True),
                }
            )
        except Exception:
            details.append({"name": p})
    return ToolResult(
        ok=True,
        data={"query": query, "total": len(plugins), "plugins": details},
        message=f"插件 {len(plugins)} 个（返回前 {min(limit, len(plugins))}）",
    )


@tool(
    name="load_or_unload_plugin",
    description="加载或卸载 Maya 插件（开发插件命令时常用）。",
    parameters=obj_schema(
        {
            "plugin": {
                "type": "string",
                "description": "插件名或 .py/.mll/.bundle 路径",
            },
            "action": {
                "type": "string",
                "enum": ["load", "unload", "reload"],
                "default": "load",
            },
        },
        required=["plugin"],
    ),
    category="maya_dev",
    destructive=True,
)
def load_or_unload_plugin(plugin: str, action: str = "load") -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    c = _cmds()
    name = plugin.strip()
    if not name:
        return ToolResult(ok=False, error="plugin 为空")
    try:
        if action == "unload":
            if c.pluginInfo(name, query=True, loaded=True):
                c.unloadPlugin(name)
            return ToolResult(ok=True, data={"plugin": name, "action": "unload"}, message=f"已卸载 {name}")
        if action == "reload":
            if c.pluginInfo(name, query=True, loaded=True):
                c.unloadPlugin(name)
            c.loadPlugin(name)
            return ToolResult(ok=True, data={"plugin": name, "action": "reload"}, message=f"已重载 {name}")
        c.loadPlugin(name)
        return ToolResult(ok=True, data={"plugin": name, "action": "load"}, message=f"已加载 {name}")
    except Exception as e:
        return ToolResult(ok=False, error=str(e))


@tool(
    name="eval_python_expr",
    description=(
        "在 Maya 中求值单个 Python 表达式并返回结果（只读探测用）。"
        "适合快速验证 cmds.ls(...) 等返回值；复杂逻辑请用 execute_python。"
    ),
    parameters=obj_schema(
        {
            "expression": {
                "type": "string",
                "description": "表达式，如 cmds.ls(type='mesh')[:5]",
            }
        },
        required=["expression"],
    ),
    category="maya_dev",
)
def eval_python_expr(expression: str) -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    import maya.cmds as cmds

    expr = expression.strip()
    if not expr:
        return ToolResult(ok=False, error="表达式为空")
    # Block obvious multi-statement / dangerous calls for this "read" tool
    lowered = expr.lower()
    if "\n" in expr or ";" in expr:
        return ToolResult(
            ok=False,
            error="仅允许单行表达式；写入/执行请用 execute_python 或 write_script_file",
        )
    banned = ("__import__", "exec(", "eval(", "open(", "compile(", "os.", "sys.", "subprocess")
    if any(b in lowered for b in banned):
        return ToolResult(ok=False, error="表达式包含不允许的调用")
    safe_builtins = {
        "True": True,
        "False": False,
        "None": None,
        "abs": abs,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "float": float,
        "int": int,
        "len": len,
        "list": list,
        "max": max,
        "min": min,
        "range": range,
        "repr": repr,
        "round": round,
        "set": set,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
    }
    try:
        result = eval(  # noqa: S307
            expr,
            {"__builtins__": safe_builtins, "cmds": cmds},
            {"cmds": cmds},
        )
    except Exception as e:
        return ToolResult(ok=False, error=f"{type(e).__name__}: {e}")
    # Keep payload small
    text = repr(result)
    if len(text) > 8000:
        text = text[:8000] + "...[truncated]"
    return ToolResult(
        ok=True,
        data={"expression": expr, "result_repr": text, "type": type(result).__name__},
        message="表达式求值成功",
    )

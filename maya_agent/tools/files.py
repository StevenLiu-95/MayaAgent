"""General local file tools for Maya Agent."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from maya_agent.tools import fsutil
from maya_agent.tools.registry import ToolResult, obj_schema, tool


def _err(exc: Exception) -> ToolResult:
    if isinstance(exc, fsutil.FsError):
        return ToolResult(ok=False, error=str(exc))
    return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")


@tool(
    name="list_directory",
    description=(
        "列出本地目录内容。相对路径相对于 maya_agent_files 工作区"
        "（与 MayaAgent 同级）。可用于浏览 chat_images / temp / 工程目录。"
    ),
    parameters=obj_schema(
        {
            "directory": {
                "type": "string",
                "description": "目录路径；相对路径基于 maya_agent_files",
                "default": "",
            },
            "pattern": {
                "type": "string",
                "default": "",
                "description": "过滤：扩展名如 .py / .png，或子串",
            },
            "recursive": {"type": "boolean", "default": False},
            "files_only": {"type": "boolean", "default": False},
            "limit": {"type": "integer", "default": 200},
        },
    ),
    category="files",
    main_thread=False,
)
def list_directory(
    directory: str = "",
    pattern: str = "",
    recursive: bool = False,
    files_only: bool = False,
    limit: int = 200,
) -> ToolResult:
    try:
        root = (directory or "").strip() or str(fsutil.workspace_root())
        data = fsutil.list_dir(
            root,
            pattern=pattern,
            recursive=recursive,
            limit=limit,
            files_only=files_only,
        )
        return ToolResult(
            ok=True,
            data=data,
            message=f"列出 {data.get('count', 0)} 项：{data.get('directory')}",
        )
    except Exception as e:
        return _err(e)


@tool(
    name="path_info",
    description="查询本地路径是否存在、类型、大小、是否在可写白名单内。",
    parameters=obj_schema(
        {"path": {"type": "string"}},
        required=["path"],
    ),
    category="files",
    main_thread=False,
)
def path_info(path: str) -> ToolResult:
    try:
        p = fsutil.resolve_path(path, must_exist=False)
        info = fsutil.file_info(p)
        return ToolResult(
            ok=True,
            data=info,
            message=("存在" if info.get("exists") else "不存在") + f"：{info.get('path')}",
        )
    except Exception as e:
        return _err(e)


@tool(
    name="read_text_file",
    description=(
        "读取本地文本文件（utf-8）。可用于脚本、配置、日志等。"
        "大文件会截断；默认上限约 500KB。"
    ),
    parameters=obj_schema(
        {
            "path": {"type": "string"},
            "max_chars": {"type": "integer", "default": 512000},
            "encoding": {"type": "string", "default": "utf-8"},
        },
        required=["path"],
    ),
    category="files",
    main_thread=False,
)
def read_text_file(
    path: str,
    max_chars: int = 512000,
    encoding: str = "utf-8",
) -> ToolResult:
    try:
        data = fsutil.read_text(path, max_chars=max_chars, encoding=encoding or "utf-8")
        return ToolResult(
            ok=True,
            data=data,
            message=f"已读取 {data['path']}"
            + ("（已截断）" if data.get("truncated") else ""),
        )
    except Exception as e:
        return _err(e)


@tool(
    name="write_text_file",
    description=(
        "写入本地文本文件。目标须在可写白名单内"
        "（maya_agent_files、meshy_downloads、Maya 脚本/工程/场景目录等）。"
        "覆盖已有文件需 overwrite=true。"
    ),
    parameters=obj_schema(
        {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "overwrite": {"type": "boolean", "default": False},
            "create_dirs": {"type": "boolean", "default": True},
            "encoding": {"type": "string", "default": "utf-8"},
        },
        required=["path", "content"],
    ),
    category="files",
    destructive=True,
    main_thread=False,
)
def write_text_file(
    path: str,
    content: str,
    overwrite: bool = False,
    create_dirs: bool = True,
    encoding: str = "utf-8",
) -> ToolResult:
    try:
        data = fsutil.write_text(
            path,
            content,
            overwrite=overwrite,
            create_dirs=create_dirs,
            encoding=encoding or "utf-8",
        )
        return ToolResult(ok=True, data=data, message=f"已写入 {data['path']}")
    except Exception as e:
        return _err(e)


@tool(
    name="copy_file",
    description="复制本地文件到可写白名单内的目标路径。",
    parameters=obj_schema(
        {
            "src": {"type": "string"},
            "dst": {"type": "string"},
            "overwrite": {"type": "boolean", "default": False},
        },
        required=["src", "dst"],
    ),
    category="files",
    destructive=True,
    main_thread=False,
)
def copy_file(src: str, dst: str, overwrite: bool = False) -> ToolResult:
    try:
        data = fsutil.copy_path(src, dst, overwrite=overwrite)
        return ToolResult(ok=True, data=data, message=f"已复制到 {data['dst']}")
    except Exception as e:
        return _err(e)


@tool(
    name="delete_path",
    description=(
        "删除白名单内的文件，或空目录。"
        "allow_nonempty_dir=true 时可递归删目录（危险）。"
    ),
    parameters=obj_schema(
        {
            "path": {"type": "string"},
            "allow_nonempty_dir": {"type": "boolean", "default": False},
        },
        required=["path"],
    ),
    category="files",
    destructive=True,
    main_thread=False,
)
def delete_path(path: str, allow_nonempty_dir: bool = False) -> ToolResult:
    try:
        data = fsutil.delete_path(path, allow_nonempty_dir=allow_nonempty_dir)
        return ToolResult(ok=True, data=data, message=f"已删除 {data['path']}")
    except Exception as e:
        return _err(e)


@tool(
    name="list_chat_images",
    description=(
        "列出最近对话中用户附图落盘后的本地路径（自动保存在 maya_agent_files/chat_images）。"
        "图生 3D 等工具可直接使用这些 path。"
    ),
    parameters=obj_schema(
        {"limit": {"type": "integer", "default": 8}},
    ),
    category="files",
    main_thread=False,
)
def list_chat_images(limit: int = 8) -> ToolResult:
    try:
        items = fsutil.list_staged_chat_images(limit=limit)
        return ToolResult(
            ok=True,
            data={
                "count": len(items),
                "images": items,
                "directory": str(fsutil.chat_images_dir()).replace("\\", "/"),
            },
            message=(
                f"共 {len(items)} 张对话附图"
                if items
                else "暂无落盘的对话附图（请先在输入框附带图片并发送）"
            ),
        )
    except Exception as e:
        return _err(e)


@tool(
    name="save_chat_images",
    description=(
        "将当前会话记忆中最近一条带图的用户消息落盘到 chat_images，"
        "并返回路径。发送消息时通常已自动落盘；本工具用于补救或再导出。"
    ),
    parameters=obj_schema(
        {
            "limit": {
                "type": "integer",
                "default": 4,
                "description": "最多返回多少张（从最近一批）",
            }
        },
    ),
    category="files",
    main_thread=False,
)
def save_chat_images(limit: int = 4) -> ToolResult:
    try:
        existing = fsutil.latest_chat_image_paths(limit=limit)
        if not existing:
            staged = fsutil.restage_last_chat_images()
            existing = [x["path"] for x in staged if x.get("path")]
        if existing:
            items = fsutil.list_staged_chat_images(limit=limit)
            return ToolResult(
                ok=True,
                data={"count": len(items), "images": items, "paths": existing[:limit]},
                message=f"已有 {len(existing[:limit])} 张对话附图可用",
            )
        return ToolResult(
            ok=False,
            error=(
                "没有可落盘的对话附图。请用户在输入框附带图片后发送，"
                "或提供本地 image_path / 公网 image_url。"
            ),
        )
    except Exception as e:
        return _err(e)


@tool(
    name="get_workspace_info",
    description=(
        "返回 Agent 文件工作区根路径、chat_images/temp 目录，以及可写白名单根列表。"
    ),
    parameters=obj_schema({}),
    category="files",
    main_thread=False,
)
def get_workspace_info() -> ToolResult:
    try:
        roots = [str(r).replace("\\", "/") for r in fsutil.allowed_write_roots()]
        data: Dict[str, Any] = {
            "workspace_root": str(fsutil.workspace_root()).replace("\\", "/"),
            "chat_images_dir": str(fsutil.chat_images_dir()).replace("\\", "/"),
            "temp_dir": str(fsutil.temp_dir()).replace("\\", "/"),
            "write_roots": roots,
        }
        return ToolResult(ok=True, data=data, message="文件工作区信息")
    except Exception as e:
        return _err(e)

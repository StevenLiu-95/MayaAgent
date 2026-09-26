# -*- coding: utf-8 -*-
"""
Maya Agent — in-Maya drag-drop installer.

Called by install_dragdrop.mel after the user drops that file into the viewport.
Performs persistent install for the running Maya version, then creates menu/shelf
immediately (no restart required for the current session).
"""
from __future__ import annotations

import importlib.util
import re
import sys
import traceback
from pathlib import Path


def _project_root() -> Path:
    here = Path(__file__).resolve()
    root = here.parents[1]
    if (root / "maya_agent" / "__init__.py").is_file():
        return root

    # Fallback: optionVar set by install_dragdrop.mel
    try:
        import maya.cmds as cmds

        info = cmds.optionVar(query="MayaAgent_dragInfo") or ""
        m = re.search(r"found in:\s*(.+)$", info)
        if m:
            mel_path = Path(m.group(1).strip().strip('"'))
            candidate = mel_path.parent
            if (candidate / "maya_agent" / "__init__.py").is_file():
                return candidate
    except Exception:
        pass

    raise RuntimeError("无法定位 MayaAgent 项目根目录（缺少 maya_agent 包）")


def _maya_version_str() -> str:
    import maya.cmds as cmds

    try:
        return str(int(float(cmds.about(version=True))))
    except Exception:
        return str(cmds.about(version=True) or "2025")


def _load_install_module(root: Path):
    path = root / "scripts" / "install.py"
    spec = importlib.util.spec_from_file_location("maya_agent_install_mod", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ensure_sys_path(root: Path) -> None:
    root_s = str(root).replace("\\", "/")
    if root_s not in sys.path:
        sys.path.insert(0, root_s)


def _reload_maya_agent() -> None:
    for name in list(sys.modules):
        if name == "maya_agent" or name.startswith("maya_agent."):
            sys.modules.pop(name, None)


def _load_or_reload_plugin() -> None:
    """Force-load Documents/maya/plug-ins/MayaAgent.py if present."""
    import maya.cmds as cmds

    plugin_name = "MayaAgent.py"
    try:
        if cmds.pluginInfo(plugin_name, query=True, loaded=True):
            try:
                cmds.unloadPlugin(plugin_name, force=True)
            except Exception:
                pass
        cmds.loadPlugin(plugin_name, quiet=True)
        try:
            cmds.pluginInfo(plugin_name, edit=True, autoload=True)
        except Exception:
            pass
        print("[Maya Agent] plug-in reloaded:", plugin_name)
    except Exception as e:
        print("[Maya Agent] plug-in load skipped:", e)


def _check_optional_runtime_deps() -> list:
    """Return missing optional packages needed for chat (not for menu/shelf)."""
    missing = []
    for mod, label in (("httpx", "httpx"), ("requests", "requests")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(label)
    return missing


def run_install() -> dict:
    import maya.cmds as cmds

    result = {"ok": False, "root": "", "version": "", "message": ""}
    try:
        root = _project_root()
        ver = _maya_version_str()
        result["root"] = str(root)
        result["version"] = ver
        print(f"[Maya Agent] 拖入式安装开始 — Maya {ver}")
        print(f"[Maya Agent] 项目路径: {root}")

        install_mod = _load_install_module(root)
        link_root = install_mod.install_version(ver, root, uninstall=False)
        install_mod.write_autoload_plugin(link_root, uninstall=False)

        load_path = Path(link_root).resolve()
        _ensure_sys_path(load_path)
        _ensure_sys_path(root)
        _reload_maya_agent()
        _load_or_reload_plugin()

        import maya_agent.plugin.menu as menu

        menu._INSTALL_ATTEMPTS = 0
        menu.install_menu()
        menu.install_shelf()
        try:
            from maya_agent.plugin.scene_hooks import install_scene_hooks

            install_scene_hooks()
        except Exception as e:
            print("[Maya Agent] scene hooks:", e)

        missing = _check_optional_runtime_deps()
        dep_note = ""
        if missing:
            dep_note = (
                f"\n\n注意: 对话依赖未就绪（缺 {', '.join(missing)}）。\n"
                f"请重新运行项目根目录 install.bat，或用 mayapy 安装 requirements.txt。"
            )
            print("[Maya Agent] 可选依赖缺失:", ", ".join(missing))

        result["ok"] = True
        result["message"] = (
            f"安装成功（Maya {ver}）\n\n"
            f"· 菜单栏应出现「Maya Agent」\n"
            f"· 工具架应出现「MayaAgent」页签\n"
            f"· 已写入自动加载插件，重启后仍可用\n\n"
            f"项目: {root}\n"
            f"加载路径: {load_path}"
            f"{dep_note}"
        )
        print("[Maya Agent] 拖入式安装完成")
    except Exception as e:
        traceback.print_exc()
        result["message"] = f"安装失败:\n{e}"
        print("[Maya Agent] 拖入式安装失败:", e)
        try:
            cmds.confirmDialog(
                title="Maya Agent",
                message=result["message"] + "\n\n请查看 Script Editor 红色报错。",
                button=["OK"],
            )
        except Exception:
            pass
        return result

    try:
        choice = cmds.confirmDialog(
            title="Maya Agent",
            message=result["message"],
            button=["打开面板", "关闭"],
            defaultButton="打开面板",
            cancelButton="关闭",
            dismissString="关闭",
        )
        if choice == "打开面板":
            import maya_agent

            maya_agent.launch()
    except Exception:
        pass
    return result


if __name__ == "__main__":
    run_install()

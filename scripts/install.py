"""
Install Maya Agent into Maya user scripts / modules path.

Usage:
  python scripts/install.py
  python scripts/install.py --maya-version 2025
  python scripts/install.py --uninstall
"""

from __future__ import annotations

import argparse
import os
import platform
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

USERSETUP_SNIPPET = '''
# >>> Maya Agent
def _maya_agent_bootstrap():
    import sys
    _maya_agent_root = r"{root}"
    if _maya_agent_root not in sys.path:
        sys.path.insert(0, _maya_agent_root)
    try:
        import maya_agent
        maya_agent.bootstrap()
    except Exception as _maya_agent_exc:
        print("[Maya Agent] load failed:", _maya_agent_exc)

try:
    import maya.utils as _maya_agent_utils
    _maya_agent_utils.executeDeferred(_maya_agent_bootstrap)
except Exception:
    _maya_agent_bootstrap()
# <<< Maya Agent
'''


def documents_dir() -> Path:
    if platform.system() == "Windows":
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Preferences" / "Autodesk" / "maya"
    return Path.home() / "maya"


def maya_versions_on_disk() -> list:
    versions = []
    maya_root = documents_dir() / "maya" if platform.system() != "Darwin" else documents_dir()
    if not maya_root.exists():
        return versions
    for child in maya_root.iterdir():
        if child.is_dir() and child.name.isdigit():
            versions.append(child.name)
    return sorted(versions)


def scripts_dir_for(version: str) -> Path:
    if platform.system() == "Darwin":
        return documents_dir() / version / "scripts"
    return documents_dir() / "maya" / version / "scripts"


def modules_dir_for(version: str) -> Path:
    if platform.system() == "Darwin":
        return documents_dir() / version / "modules"
    return documents_dir() / "maya" / version / "modules"


def ensure_junction_or_copy(version: str, root: Path) -> Path:
    """
    Prefer an ASCII-friendly path under Documents/maya/<ver>/MayaAgent
    (junction on Windows) so userSetup never breaks on non-ASCII project paths.
    """
    link = documents_dir() / "maya" / version / "MayaAgent"
    if platform.system() == "Darwin":
        link = documents_dir() / version / "MayaAgent"
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists():
        return link
    if platform.system() == "Windows":
        try:
            import subprocess

            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(root)],
                check=True,
                capture_output=True,
                text=True,
            )
            return link
        except Exception as e:
            print(f"junction failed ({e}), using project path directly")
            return root
    try:
        link.symlink_to(root, target_is_directory=True)
        return link
    except Exception:
        return root


def write_usersetup(scripts: Path, root: Path, uninstall: bool = False) -> None:
    scripts.mkdir(parents=True, exist_ok=True)
    path = scripts / "userSetup.py"
    # Always use forward slashes in generated Python source
    snippet = USERSETUP_SNIPPET.format(root=str(root).replace("\\", "/"))
    existing = path.read_text(encoding="utf-8") if path.exists() else ""

    start = existing.find("# >>> Maya Agent")
    end = existing.find("# <<< Maya Agent")
    if start != -1 and end != -1:
        end = existing.find("\n", end)
        existing = existing[:start] + existing[end + 1 if end != -1 else len(existing) :]

    if uninstall:
        path.write_text(existing.strip() + ("\n" if existing.strip() else ""), encoding="utf-8")
        print(f"Removed Maya Agent block from {path}")
        return

    content = existing.rstrip() + "\n\n" + snippet.lstrip("\n")
    path.write_text(content, encoding="utf-8")
    print(f"Updated {path}")


def write_module(modules: Path, root: Path, uninstall: bool = False) -> None:
    modules.mkdir(parents=True, exist_ok=True)
    mod = modules / "MayaAgent.mod"
    if uninstall:
        if mod.exists():
            mod.unlink()
            print(f"Removed {mod}")
        return
    root_fwd = str(root).replace("\\", "/")
    mod.write_text(
        f"+ MayaAgent 1.0.0 {root_fwd}\n"
        f"scripts: {root_fwd}\n"
        f"PYTHONPATH+:= {root_fwd}\n",
        encoding="utf-8",
    )
    print(f"Wrote {mod}")


def install_module_link(scripts: Path, uninstall: bool = False) -> None:
    launcher = scripts / "maya_agent_launch.py"
    if uninstall:
        if launcher.exists():
            launcher.unlink()
            print(f"Removed {launcher}")
        return
    launcher.write_text(
        "from maya_agent import launch\n\n"
        "if __name__ == '__main__':\n"
        "    launch()\n",
        encoding="utf-8",
    )
    print(f"Wrote {launcher}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Install Maya Agent into Maya")
    parser.add_argument("--maya-version", default="", help="e.g. 2025; default=all detected")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args(argv)

    versions = [args.maya_version] if args.maya_version else maya_versions_on_disk()
    if not versions:
        versions = ["2022", "2023", "2024", "2025", "2026"]
        print("未检测到 Maya 用户目录，将写入常见版本路径。")

    print(f"Project root: {PROJECT_ROOT}")

    for ver in versions:
        scripts = scripts_dir_for(ver)
        modules = modules_dir_for(ver)
        print(f"\n=== Maya {ver} → {scripts} ===")
        try:
            if args.uninstall:
                write_usersetup(scripts, PROJECT_ROOT, uninstall=True)
                write_module(modules, PROJECT_ROOT, uninstall=True)
                install_module_link(scripts, uninstall=True)
            else:
                link_root = ensure_junction_or_copy(ver, PROJECT_ROOT)
                print(f"Load path: {link_root}")
                write_usersetup(scripts, link_root, uninstall=False)
                write_module(modules, link_root, uninstall=False)
                install_module_link(scripts, uninstall=False)
        except OSError as e:
            print(f"Skip {ver}: {e}")

    if not args.uninstall:
        print(
            "\n安装完成。请重启 Maya。\n"
            "启动后应出现顶部菜单「Maya Agent」和工具架「MayaAgent」。\n"
            "若未出现，在 Script Editor 执行:\n"
            "  import maya_agent; maya_agent.plugin.menu._deferred_install()\n"
        )
    else:
        print("\n已卸载 userSetup / module 挂钩。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

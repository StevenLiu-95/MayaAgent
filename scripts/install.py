"""
Install Maya Agent into Maya user scripts / modules / plug-ins path.

Usage:
  python scripts/install.py
  python scripts/install.py --maya-version 2025
  python scripts/install.py --uninstall
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_TEMPLATE = PROJECT_ROOT / "resources" / "maya_plugin" / "MayaAgent.py"
PLUGIN_FILENAME = "MayaAgent.py"
PLUGIN_NAME = "MayaAgent"
AUTOLOAD_LINE = (
    f'evalDeferred("autoLoadPlugin(\\"\\", \\"{PLUGIN_FILENAME}\\", \\"{PLUGIN_NAME}\\")");'
)

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

USERSETUP_MEL_SNIPPET = '''
// >>> Maya Agent
global proc mayaAgentBootstrap() {{
    python("import sys; p=r\\"{root}\\";\\nsys.path.insert(0, p) if p not in sys.path else None;\\nimport maya_agent;\\nmaya_agent.bootstrap()");
}}
evalDeferred("mayaAgentBootstrap()");
// <<< Maya Agent
'''


def documents_dir() -> Path:
    if platform.system() == "Windows":
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Preferences" / "Autodesk" / "maya"
    return Path.home() / "maya"


def maya_app_dir() -> Path:
    if platform.system() == "Darwin":
        return documents_dir()
    return documents_dir() / "maya"


def maya_versions_on_disk() -> list:
    versions = []
    maya_root = maya_app_dir()
    if not maya_root.exists():
        return versions
    for child in maya_root.iterdir():
        if child.is_dir() and child.name.isdigit():
            versions.append(child.name)
    return sorted(versions)


def scripts_dir_for(version: str) -> Path:
    if platform.system() == "Darwin":
        return documents_dir() / version / "scripts"
    return maya_app_dir() / version / "scripts"


def modules_dir_for(version: str) -> Path:
    if platform.system() == "Darwin":
        return documents_dir() / version / "modules"
    return maya_app_dir() / version / "modules"


def shared_plugins_dir() -> Path:
    """Documents/maya/plug-ins — same place JYMod_autoLoad.py lives."""
    if platform.system() == "Darwin":
        return documents_dir() / "plug-ins"
    return maya_app_dir() / "plug-ins"


def ensure_junction_or_copy(version: str, root: Path) -> Path:
    """
    Prefer an ASCII-friendly path under Documents/maya/<ver>/MayaAgent
    (junction on Windows) so startup never breaks on non-ASCII project paths.
    """
    link = maya_app_dir() / version / "MayaAgent"
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


def _strip_marked_block(text: str, start_mark: str, end_mark: str) -> str:
    start = text.find(start_mark)
    end = text.find(end_mark)
    if start != -1 and end != -1:
        end = text.find("\n", end)
        text = text[:start] + text[end + 1 if end != -1 else len(text) :]
    return text


def write_usersetup(scripts: Path, root: Path, uninstall: bool = False) -> None:
    scripts.mkdir(parents=True, exist_ok=True)
    path = scripts / "userSetup.py"
    snippet = USERSETUP_SNIPPET.format(root=str(root).replace("\\", "/"))
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    existing = _strip_marked_block(existing, "# >>> Maya Agent", "# <<< Maya Agent")

    if uninstall:
        path.write_text(existing.strip() + ("\n" if existing.strip() else ""), encoding="utf-8")
        print(f"Removed Maya Agent block from {path}")
        return

    content = existing.rstrip() + "\n\n" + snippet.lstrip("\n")
    path.write_text(content, encoding="utf-8")
    print(f"Updated {path}")


def write_usersetup_mel(scripts: Path, root: Path, uninstall: bool = False) -> None:
    """MEL fallback — some Maya security setups still run userSetup.mel."""
    scripts.mkdir(parents=True, exist_ok=True)
    path = scripts / "userSetup.mel"
    root_fwd = str(root).replace("\\", "/")
    snippet = USERSETUP_MEL_SNIPPET.format(root=root_fwd)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    existing = _strip_marked_block(existing, "// >>> Maya Agent", "// <<< Maya Agent")

    if uninstall:
        path.write_text(existing.strip() + ("\n" if existing.strip() else ""), encoding="utf-8")
        if path.exists() and not path.read_text(encoding="utf-8").strip():
            path.unlink()
            print(f"Removed {path}")
        else:
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
        f"+ MayaAgent 1.1.0 {root_fwd}\n"
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


def write_autoload_plugin(root: Path, uninstall: bool = False) -> None:
    """
    Install MayaAgent.py into Documents/maya/plug-ins (same mechanism as JYMod).
    This is the primary startup path — userSetup.py is often blocked by Maya Safe Mode.
    """
    plugins = shared_plugins_dir()
    plugins.mkdir(parents=True, exist_ok=True)
    dest = plugins / PLUGIN_FILENAME

    if uninstall:
        if dest.exists():
            dest.unlink()
            print(f"Removed {dest}")
        return

    if not PLUGIN_TEMPLATE.exists():
        raise FileNotFoundError(f"Missing plug-in template: {PLUGIN_TEMPLATE}")

    text = PLUGIN_TEMPLATE.read_text(encoding="utf-8")
    root_fwd = str(root).replace("\\", "/")
    # Only rewrite the MODULE_ROOT assignment (avoid clobbering other placeholders)
    if 'MODULE_ROOT = r"__MAYA_AGENT_ROOT__"' not in text:
        raise RuntimeError("plug-in template missing MODULE_ROOT placeholder")
    text = text.replace(
        'MODULE_ROOT = r"__MAYA_AGENT_ROOT__"',
        f'MODULE_ROOT = r"{root_fwd}"',
        1,
    )
    dest.write_text(text, encoding="utf-8")
    print(f"Wrote auto-load plug-in {dest}")
    print(f"  MODULE_ROOT = {root_fwd}")


def _prefs_dirs_for(version: str) -> list:
    """Locale-aware prefs folders, e.g. 2025/zh_CN/prefs and 2025/prefs."""
    base = maya_app_dir() / version
    if platform.system() == "Darwin":
        base = documents_dir() / version
    found = []
    if (base / "prefs").is_dir():
        found.append(base / "prefs")
    for child in sorted(base.glob("*/prefs")):
        if child.is_dir() and child not in found:
            found.append(child)
    return found


def patch_plugin_prefs(version: str, uninstall: bool = False) -> None:
    """Ensure MayaAgent.py is in autoLoadPlugin list (pluginPrefs.mel)."""
    prefs_dirs = _prefs_dirs_for(version)
    if not prefs_dirs:
        # Create zh_CN prefs if Chinese Maya is common; else plain prefs
        fallback = maya_app_dir() / version / "prefs"
        fallback.mkdir(parents=True, exist_ok=True)
        prefs_dirs = [fallback]

    for prefs in prefs_dirs:
        path = prefs / "pluginPrefs.mel"
        if path.exists():
            existing, original = _read_text_prefer(path)
        else:
            existing, original = "//Maya Preference\n//\n//\n", None

        # Remove any previous MayaAgent autoload lines
        lines = existing.splitlines(keepends=True)
        kept = [
            ln
            for ln in lines
            if "MayaAgent.py" not in ln and not re.search(r'autoLoadPlugin\(.*"MayaAgent"', ln)
        ]
        text = "".join(kept).rstrip() + "\n"

        if uninstall:
            _write_text_prefer(path, text, original)
            print(f"Removed MayaAgent autoload from {path}")
            continue

        if AUTOLOAD_LINE not in text:
            text = text.rstrip() + "\n" + AUTOLOAD_LINE + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_text_prefer(path, text, original)
        print(f"Patched autoload in {path}")


def _read_text_prefer(path: Path) -> tuple[str, bytes]:
    raw = path.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "gbk", "cp936", "latin-1"):
        try:
            return raw.decode(enc), raw
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), raw


def _write_text_prefer(path: Path, text: str, original: bytes | None = None) -> None:
    """Preserve original encoding when possible (Maya prefs on CN Windows are often GBK)."""
    enc = "utf-8"
    if original is not None:
        for candidate in ("utf-8", "utf-8-sig", "gbk", "cp936"):
            try:
                original.decode(candidate)
                enc = candidate
                break
            except UnicodeDecodeError:
                continue
    path.write_text(text, encoding=enc)


def enable_usersetup_security_pref(version: str) -> None:
    """Best-effort: ensure SafeModeExecUserSetupScript=1 in userPrefs.mel."""
    for prefs in _prefs_dirs_for(version):
        path = prefs / "userPrefs.mel"
        if not path.exists():
            continue
        try:
            text, original = _read_text_prefer(path)
        except OSError as e:
            print(f"Skip security pref {path}: {e}")
            continue
        if "SafeModeExecUserSetupScript" in text:
            text2 = re.sub(
                r'-iv\s+"SafeModeExecUserSetupScript"\s+\d+',
                '-iv "SafeModeExecUserSetupScript" 1',
                text,
            )
            if text2 != text:
                _write_text_prefer(path, text2, original)
                print(f"Enabled SafeModeExecUserSetupScript in {path}")
            continue
        marker = 'optionVar -cat "Security"'
        if marker in text:
            insert = marker + '\n -iv "SafeModeExecUserSetupScript" 1'
            text = text.replace(marker, insert, 1)
            _write_text_prefer(path, text, original)
            print(f"Added SafeModeExecUserSetupScript to {path}")


def remove_shelf_prefs(version: str) -> None:
    """
    Delete persisted MayaAgent shelf tab and Agent buttons from other shelves.

    Maya stores shelves as prefs/.../shelves/shelf_<Name>.mel — leaving these
    behind makes the MayaAgent tab reappear after uninstall + restart.
    """
    shelf_file_names = (
        "shelf_MayaAgent.mel",
        "shelf_Maya Agent.mel",
    )
    button_marker = "Maya Agent"

    for prefs in _prefs_dirs_for(version):
        shelves = prefs / "shelves"
        if not shelves.is_dir():
            continue

        for name in shelf_file_names:
            path = shelves / name
            if path.exists():
                try:
                    path.unlink()
                    print(f"Removed shelf file {path}")
                except OSError as e:
                    print(f"Failed to remove {path}: {e}")

        # Strip Agent buttons that install_shelf may have added to other tabs
        for path in sorted(shelves.glob("shelf_*.mel")):
            if path.name in shelf_file_names:
                continue
            try:
                text, original = _read_text_prefer(path)
            except OSError:
                continue
            if button_marker not in text and "maya_agent.launch" not in text:
                continue
            cleaned = _strip_shelf_buttons(text, markers=(button_marker, "maya_agent.launch"))
            if cleaned != text:
                _write_text_prefer(path, cleaned, original)
                print(f"Cleaned Agent buttons from {path}")


def _strip_shelf_buttons(mel_text: str, markers: tuple) -> str:
    """Remove shelfButton … ; blocks that contain any marker string.

    Maya shelf MEL uses flag style (not braces), ending with a line that is only `;`.
    """
    pattern = re.compile(
        r"^[ \t]*shelfButton\b[\s\S]*?^[ \t]*;[ \t]*(?:\r?\n)?",
        re.MULTILINE,
    )

    def _keep(match: re.Match) -> str:
        block = match.group(0)
        if any(m in block for m in markers):
            return ""
        return block

    return pattern.sub(_keep, mel_text)


def remove_project_junction(version: str) -> None:
    """Remove Documents/maya/<ver>/MayaAgent junction/symlink (not the real project)."""
    link = maya_app_dir() / version / "MayaAgent"
    if platform.system() == "Darwin":
        link = documents_dir() / version / "MayaAgent"
    if not link.exists() and not link.is_symlink():
        return
    try:
        # Junction / symlink: rmdir removes the link, not the target tree
        if link.is_dir():
            link.rmdir()
        else:
            link.unlink()
        print(f"Removed load path link {link}")
    except OSError as e:
        print(f"Could not remove {link}: {e} (safe to delete manually if it is only a junction)")


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

    # Shared plug-in is version-agnostic; write once using first version's junction
    shared_root = None

    for ver in versions:
        scripts = scripts_dir_for(ver)
        modules = modules_dir_for(ver)
        print(f"\n=== Maya {ver} → {scripts} ===")
        try:
            if args.uninstall:
                write_usersetup(scripts, PROJECT_ROOT, uninstall=True)
                write_usersetup_mel(scripts, PROJECT_ROOT, uninstall=True)
                write_module(modules, PROJECT_ROOT, uninstall=True)
                install_module_link(scripts, uninstall=True)
                patch_plugin_prefs(ver, uninstall=True)
                remove_shelf_prefs(ver)
                remove_project_junction(ver)
            else:
                link_root = ensure_junction_or_copy(ver, PROJECT_ROOT)
                shared_root = shared_root or link_root
                print(f"Load path: {link_root}")
                write_usersetup(scripts, link_root, uninstall=False)
                write_usersetup_mel(scripts, link_root, uninstall=False)
                write_module(modules, link_root, uninstall=False)
                install_module_link(scripts, uninstall=False)
                patch_plugin_prefs(ver, uninstall=False)
                try:
                    enable_usersetup_security_pref(ver)
                except Exception as e:
                    print(f"Security pref skip ({e})")
        except OSError as e:
            print(f"Skip {ver}: {e}")

    # Primary startup: Documents/maya/plug-ins/MayaAgent.py
    try:
        if args.uninstall:
            write_autoload_plugin(PROJECT_ROOT, uninstall=True)
        else:
            write_autoload_plugin(shared_root or PROJECT_ROOT, uninstall=False)
    except OSError as e:
        print(f"Plug-in install error: {e}")

    if not args.uninstall:
        print(
            "\n安装完成。请完全退出并重启 Maya。\n"
            "启动后 Script Editor 应出现:\n"
            "  [Maya Agent] plug-in loading…\n"
            "  [Maya Agent] menu OK: …\n"
            "顶部菜单应有「Maya Agent」，工具架有「MayaAgent」。\n"
            "若仍没有，在 Script Editor 执行:\n"
            "  import maya_agent; maya_agent.reload()\n"
            "或检查 Windows > Settings/Preferences > Plug-in Manager 中 MayaAgent.py 是否勾选 Loaded/Auto load。\n"
        )
    else:
        print(
            "\n已卸载：plug-in / userSetup / module / 工具架偏好 / 目录联接。\n"
            "若 Maya 正在运行，请再执行一次以清理当前会话 UI：\n"
            "  import maya_agent; maya_agent.plugin.menu.uninstall_ui()\n"
            "或在 Plug-in Manager 中卸载 MayaAgent.py，然后重启 Maya。\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Install Maya Agent into Maya user scripts / modules / plug-ins path.

Usage:
  python scripts/install.py
  python scripts/install.py --maya-version 2025
  python scripts/install.py --uninstall
  python scripts/install.py --skip-deps
  python scripts/install.py --force-deps
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import platform
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from maya_discover import (  # noqa: E402
    KNOWN_VERSIONS,
    documents_dir as _discover_documents_dir,
    documents_maya_root as _discover_documents_maya_root,
    discover_maya_versions,
    find_mayapy,
    is_valid_project_root,
    list_maya_user_versions,
    version_junction_path,
)

PLUGIN_TEMPLATE = PROJECT_ROOT / "resources" / "maya_plugin" / "MayaAgent.py"
PLUGIN_FILENAME = "MayaAgent.py"
PLUGIN_NAME = "MayaAgent"
AUTOLOAD_LINE = (
    f'evalDeferred("autoLoadPlugin(\\"\\", \\"{PLUGIN_FILENAME}\\", \\"{PLUGIN_NAME}\\")");'
)


@dataclass
class VersionInstallResult:
    version: str
    hooks_ok: bool = False
    deps_ok: Optional[bool] = None
    mayapy: str = ""
    load_path: str = ""
    error: str = ""


@dataclass
class InstallReport:
    project_root: str
    versions: List[VersionInstallResult] = field(default_factory=list)
    plugin_ok: bool = False
    plugin_path: str = ""
    dry_run: bool = False

    def print_summary(self) -> None:
        print("\n---------- Install Report ----------")
        print(f"Project root: {self.project_root}")
        if self.dry_run:
            print("Mode: dry-run (no files written)")
        print(f"Shared plug-in: {'OK' if self.plugin_ok else 'FAIL'} {self.plugin_path}")
        for row in self.versions:
            deps = (
                "n/a"
                if row.deps_ok is None
                else ("OK" if row.deps_ok else "FAIL")
            )
            hooks = "OK" if row.hooks_ok else "FAIL"
            print(
                f"  Maya {row.version}: hooks={hooks} deps={deps} "
                f"mayapy={row.mayapy or '(not found)'} "
                f"load_path={row.load_path or '-'}"
            )
            if row.error:
                print(f"    error: {row.error}")
        hooks_fail = [r for r in self.versions if not r.hooks_ok]
        deps_fail = [r for r in self.versions if r.deps_ok is False]
        if hooks_fail:
            print(f"⚠ Hooks failed for: {', '.join(r.version for r in hooks_fail)}")
        if deps_fail:
            print(
                f"⚠ Deps failed for: {', '.join(r.version for r in deps_fail)} "
                "(chat needs httpx; run doctor / install.bat force / --vendor-only)"
            )
        if not hooks_fail and not deps_fail:
            print("All reported versions OK.")
        print("------------------------------------")
        print("Diagnose anytime: python scripts/doctor.py")

    @property
    def hooks_all_failed(self) -> bool:
        if not self.versions:
            return not self.plugin_ok
        return all(not r.hooks_ok for r in self.versions)

    @property
    def any_deps_failed(self) -> bool:
        return any(r.deps_ok is False for r in self.versions)

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
    return _discover_documents_dir()


def maya_app_dir() -> Path:
    return _discover_documents_maya_root()


def maya_versions_on_disk() -> list:
    return list_maya_user_versions()


def scripts_dir_for(version: str) -> Path:
    return maya_app_dir() / version / "scripts"


def modules_dir_for(version: str) -> Path:
    return maya_app_dir() / version / "modules"


def shared_plugins_dir() -> Path:
    """Documents/maya/plug-ins — same place JYMod_autoLoad.py lives."""
    if platform.system() == "Darwin":
        return documents_dir() / "plug-ins"
    return maya_app_dir() / "plug-ins"


def project_root_for_plugin(root: Path) -> Path:
    """Absolute real project root written into shared MayaAgent.py MODULE_ROOT."""
    resolved = Path(root).resolve()
    if is_valid_project_root(resolved):
        return resolved
    return PROJECT_ROOT.resolve()

def _path_lexists(path: Path) -> bool:
    """True if path exists as a directory entry, including broken junctions."""
    import os

    try:
        return os.path.lexists(path)
    except OSError:
        return path.exists()


def _is_usable_load_link(link: Path, root: Path) -> bool:
    """Return True when link exists and points at (or contains) the project."""
    if not link.exists():
        return False
    try:
        resolved = link.resolve()
        return resolved == root.resolve() or (resolved / "maya_agent" / "__init__.py").is_file()
    except OSError:
        return False


def _remove_link_path(link: Path) -> None:
    """Remove a junction/symlink without deleting the real project tree."""
    import os
    import subprocess

    if platform.system() == "Windows":
        try:
            subprocess.run(
                ["cmd", "/c", "rmdir", str(link)],
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception:
            pass
        if not _path_lexists(link):
            return
    try:
        if link.is_symlink() or link.is_dir():
            link.rmdir()
        elif link.exists():
            link.unlink()
    except OSError:
        try:
            os.unlink(link)
        except OSError as e:
            print(f"Could not remove stale link {link}: {e}")


def ensure_junction_or_copy(version: str, root: Path) -> Path:
    """
    Prefer an ASCII-friendly path under Documents/maya/<ver>/MayaAgent
    (junction on Windows) so startup never breaks on non-ASCII project paths.
    """
    link = version_junction_path(version)
    link.parent.mkdir(parents=True, exist_ok=True)

    if _is_usable_load_link(link, root):
        return link

    # Broken / stale junction (target missing or wrong) — remove then recreate
    if _path_lexists(link):
        print(f"Removing stale load path link: {link}")
        _remove_link_path(link)

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
        f"+ MayaAgent 1.5.1 {root_fwd}\n"
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
    link = version_junction_path(version)
    if not _path_lexists(link):
        return
    _remove_link_path(link)
    if not _path_lexists(link):
        print(f"Removed load path link {link}")
    else:
        print(f"Could not remove {link} (safe to delete manually if it is only a junction)")


def _dry_run_paths(version: str, root: Path) -> None:
    scripts = scripts_dir_for(version)
    modules = modules_dir_for(version)
    link = version_junction_path(version)
    print(f"\n=== [dry-run] Maya {version} ===")
    print(f"  junction : {link} -> {root}")
    print(f"  userSetup: {scripts / 'userSetup.py'}")
    print(f"  userSetup.mel: {scripts / 'userSetup.mel'}")
    print(f"  module   : {modules / 'MayaAgent.mod'}")
    print(f"  launcher : {scripts / 'maya_agent_launch.py'}")
    for prefs in _prefs_dirs_for(version) or [maya_app_dir() / version / "prefs"]:
        print(f"  pluginPrefs: {prefs / 'pluginPrefs.mel'}")


def install_version(
    version: str,
    project_root: Path | None = None,
    *,
    uninstall: bool = False,
    dry_run: bool = False,
) -> Path:
    """
    Install (or uninstall) Maya Agent hooks for one Maya version.

    Returns the load path used for userSetup / PYTHONPATH (junction or project).
    Shared plug-in MODULE_ROOT uses the real project root (see install_all).
    """
    root = Path(project_root or PROJECT_ROOT).resolve()
    scripts = scripts_dir_for(version)
    modules = modules_dir_for(version)
    print(f"\n=== Maya {version} → {scripts} ===")

    if dry_run:
        _dry_run_paths(version, root)
        return version_junction_path(version)

    if uninstall:
        write_usersetup(scripts, root, uninstall=True)
        write_usersetup_mel(scripts, root, uninstall=True)
        write_module(modules, root, uninstall=True)
        install_module_link(scripts, uninstall=True)
        patch_plugin_prefs(version, uninstall=True)
        remove_shelf_prefs(version)
        remove_project_junction(version)
        return root

    link_root = ensure_junction_or_copy(version, root)
    print(f"Load path: {link_root}")
    write_usersetup(scripts, link_root, uninstall=False)
    write_usersetup_mel(scripts, link_root, uninstall=False)
    write_module(modules, link_root, uninstall=False)
    install_module_link(scripts, uninstall=False)
    patch_plugin_prefs(version, uninstall=False)
    try:
        enable_usersetup_security_pref(version)
    except Exception as e:
        print(f"Security pref skip ({e})")
    return Path(link_root)


def install_all(
    versions: list[str] | None = None,
    project_root: Path | None = None,
    *,
    uninstall: bool = False,
    dry_run: bool = False,
    report: InstallReport | None = None,
) -> Path:
    """Install for multiple versions; write shared plug-in once with real project root."""
    root = project_root_for_plugin(Path(project_root or PROJECT_ROOT))
    vers = list(versions or [])
    if not vers:
        vers = discover_maya_versions()
    if not vers:
        vers = list(KNOWN_VERSIONS[1:])  # 2022–2026
        print("未检测到 Maya，将写入常见版本路径。")

    print(f"Project root: {root}")
    if report is not None:
        report.project_root = str(root)
        report.dry_run = dry_run

    for ver in vers:
        row = VersionInstallResult(version=ver)
        mp = find_mayapy(ver)
        row.mayapy = str(mp) if mp else ""
        try:
            link = install_version(ver, root, uninstall=uninstall, dry_run=dry_run)
            row.load_path = str(link)
            row.hooks_ok = True
        except OSError as e:
            print(f"Skip {ver}: {e}")
            row.hooks_ok = False
            row.error = str(e)
        if report is not None:
            # Merge with existing deps row if present
            existing = next((r for r in report.versions if r.version == ver), None)
            if existing is None:
                report.versions.append(row)
            else:
                existing.hooks_ok = row.hooks_ok
                existing.load_path = row.load_path
                existing.mayapy = row.mayapy or existing.mayapy
                if row.error:
                    existing.error = row.error

    plugin_root = root
    try:
        if dry_run:
            dest = shared_plugins_dir() / PLUGIN_FILENAME
            print(f"\n=== [dry-run] shared plug-in ===\n  {dest}")
            print(f"  MODULE_ROOT = {plugin_root}")
            if report is not None:
                report.plugin_ok = True
                report.plugin_path = str(dest)
        elif uninstall:
            write_autoload_plugin(plugin_root, uninstall=True)
            if report is not None:
                report.plugin_ok = True
                report.plugin_path = str(shared_plugins_dir() / PLUGIN_FILENAME)
        else:
            write_autoload_plugin(plugin_root, uninstall=False)
            if report is not None:
                report.plugin_ok = True
                report.plugin_path = str(shared_plugins_dir() / PLUGIN_FILENAME)
    except OSError as e:
        print(f"Plug-in install error: {e}")
        if report is not None:
            report.plugin_ok = False
            report.plugin_path = str(shared_plugins_dir() / PLUGIN_FILENAME)

    return plugin_root


def install_python_deps(
    versions: list[str] | None = None,
    *,
    force: bool = False,
    report: InstallReport | None = None,
) -> int:
    """
    Install httpx / requests / PyYAML into each Maya mayapy (and .vendor fallback).

    Returns number of version failures (0 = all ok).
    """
    path = Path(__file__).resolve().parent / "install_deps.py"
    spec = importlib.util.spec_from_file_location("maya_agent_install_deps", path)
    if spec is None or spec.loader is None:
        print(f"[警告] 无法加载 {path}")
        return 1
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    vers = list(versions or [])
    if not vers:
        vers = discover_maya_versions() or list(KNOWN_VERSIONS[1:])
    print("\n---------- Python 依赖 (mayapy / .vendor) ----------")
    failures = 0
    for ver in vers:
        row = None
        if report is not None:
            row = next((r for r in report.versions if r.version == ver), None)
            if row is None:
                row = VersionInstallResult(version=ver)
                report.versions.append(row)
            mp = find_mayapy(ver)
            row.mayapy = str(mp) if mp else ""
        mayapy = find_mayapy(ver)
        print(f"\n=== Maya {ver} 依赖 ===")
        if not mayapy:
            print("  [跳过] 未找到 mayapy.exe，仅会写入脚本挂钩")
            if row is not None:
                row.deps_ok = None  # skipped — not a hard fail if vendor works later
            continue
        ok = bool(mod.install_for_mayapy(mayapy, force=force, allow_vendor=True))
        if row is not None:
            row.deps_ok = ok
            row.mayapy = str(mayapy)
        if not ok:
            failures += 1
    if failures and report is not None:
        # Last-resort vendor already attempted inside install_for_mayapy
        pass
    if not any(find_mayapy(v) for v in vers):
        print("\n[警告] 未找到任何 mayapy。")
        print("  将尝试写入项目 .vendor，供 Maya 启动时加载。")
        if mod.install_to_vendor(mod.REQUIREMENTS, force=force):
            for r in report.versions if report else []:
                if r.deps_ok is None:
                    r.deps_ok = True
            return 0
        print("  [警告] 依赖未安装。菜单仍可出现，但对话功能需要 httpx。")
        if report is not None:
            for r in report.versions:
                if r.deps_ok is None:
                    r.deps_ok = False
        return 1
    return failures


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Install Maya Agent into Maya")
    parser.add_argument("--maya-version", default="", help="e.g. 2025; default=all detected")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument(
        "--skip-deps",
        action="store_true",
        help="Skip mayapy dependency install (hooks only)",
    )
    parser.add_argument(
        "--force-deps",
        action="store_true",
        help="Force reinstall Python deps even if already present",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print paths that would be written; do not modify the system",
    )
    parser.add_argument(
        "--list-versions",
        action="store_true",
        help="Print discovered Maya versions and exit",
    )
    args = parser.parse_args(argv)

    if args.list_versions:
        vers = discover_maya_versions()
        print(" ".join(vers) if vers else "")
        return 0 if vers else 1

    versions = [args.maya_version] if args.maya_version else None
    if versions is None:
        versions = discover_maya_versions() or list(KNOWN_VERSIONS[1:])

    report = InstallReport(project_root=str(PROJECT_ROOT.resolve()))

    dep_failures = 0
    if not args.uninstall and not args.skip_deps and not args.dry_run:
        try:
            dep_failures = install_python_deps(
                versions, force=args.force_deps, report=report
            )
        except Exception as e:
            dep_failures = 1
            print(f"[警告] 依赖安装异常: {e}")

    install_all(
        versions,
        PROJECT_ROOT,
        uninstall=args.uninstall,
        dry_run=args.dry_run,
        report=report,
    )

    if not args.uninstall:
        report.print_summary()
        dep_hint = ""
        if dep_failures or report.any_deps_failed:
            dep_hint = (
                "\n⚠ 部分 mayapy 依赖未装好。对话需要 httpx。\n"
                "  请重新运行 install.bat，或:\n"
                "  python scripts/install_deps.py --force\n"
                "  python scripts/install_deps.py --vendor-only\n"
                "  诊断: python scripts/doctor.py\n"
            )
        print(
            "\n安装完成。请完全退出并重启 Maya。\n"
            "启动后 Script Editor 应出现:\n"
            "  [Maya Agent] plug-in loading…\n"
            "  [Maya Agent] menu OK: …\n"
            "顶部菜单应有「Maya Agent」，工具架有「MayaAgent」。\n"
            f"{dep_hint}"
            "若仍没有菜单，可把项目根目录的 install_dragdrop.mel 拖进 Maya 视口，\n"
            "或在 Script Editor（Python）执行:\n"
            "  import maya_agent; maya_agent.reload()\n"
            "并检查 Plug-in Manager 中 MayaAgent.py 是否勾选 Loaded/Auto load。\n"
        )
    else:
        report.print_summary()
        print(
            "\n已卸载：plug-in / userSetup / module / 工具架偏好 / 目录联接。\n"
            "若 Maya 正在运行，请再执行一次以清理当前会话 UI：\n"
            "  import maya_agent; maya_agent.plugin.menu.uninstall_ui()\n"
            "或在 Plug-in Manager 中卸载 MayaAgent.py，然后重启 Maya。\n"
        )

    if args.uninstall or args.dry_run:
        return 0
    # Hooks all failed → hard fail; deps-only failure → 0 (usable menu) matching install.bat
    if report.hooks_all_failed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

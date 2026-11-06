"""
Unified install/uninstall engine for bat + Inno Setup (run under mayapy).

Usage (from mayapy or any Python that can import sibling scripts):
  mayapy scripts/install_engine.py
  mayapy scripts/install_engine.py --maya-version 2025 --maya-version 2024
  mayapy scripts/install_engine.py --uninstall
  mayapy scripts/install_engine.py --dry-run
  mayapy scripts/install_engine.py --list-versions
  mayapy scripts/install_engine.py --write-versions-file path.txt

Does not require system Python when invoked via mayapy.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path
from typing import List, Optional, Sequence

_SCRIPTS = Path(__file__).resolve().parent
_PROJECT = _SCRIPTS.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from maya_abi import abi_tags_for_maya_versions  # noqa: E402
from maya_discover import (  # noqa: E402
    KNOWN_VERSIONS,
    discover_maya_versions,
    find_mayapy,
    is_valid_project_root,
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _resolve_project_root(explicit: str = "") -> Path:
    if explicit:
        root = Path(explicit).resolve()
    else:
        root = _PROJECT.resolve()
    if not is_valid_project_root(root):
        raise SystemExit(f"Invalid project root (missing maya_agent): {root}")
    return root


def _default_versions() -> List[str]:
    found = discover_maya_versions()
    if found:
        return found
    return list(KNOWN_VERSIONS[1:])  # 2022–2026


def run_install(
    versions: Sequence[str],
    project_root: Path,
    *,
    uninstall: bool = False,
    skip_deps: bool = False,
    force_deps: bool = False,
    dry_run: bool = False,
    vendor_cache: Optional[Path] = None,
    log_path: Optional[Path] = None,
) -> int:
    install_mod = _load_module(
        "maya_agent_install_mod", project_root / "scripts" / "install.py"
    )
    deps_mod = _load_module(
        "maya_agent_install_deps_mod", project_root / "scripts" / "install_deps.py"
    )

    # Ensure deps module sees this project root for VENDOR_DIR / cache defaults
    deps_mod.PROJECT_ROOT = project_root
    deps_mod.REQUIREMENTS = project_root / "requirements.txt"
    deps_mod.VENDOR_DIR = project_root / ".vendor"
    deps_mod.VENDOR_CACHE_DIR = (
        Path(vendor_cache) if vendor_cache else project_root / "vendor_cache"
    )

    report = install_mod.InstallReport(project_root=str(project_root))
    vers = list(versions)
    cache = Path(vendor_cache) if vendor_cache else (project_root / "vendor_cache")
    if not cache.is_dir():
        cache = None

    log_lines: List[str] = []

    def _log(msg: str) -> None:
        print(msg)
        log_lines.append(msg)

    _log(f"Maya Agent install engine")
    _log(f"  project: {project_root}")
    _log(f"  versions: {', '.join(vers)}")
    _log(f"  uninstall={uninstall} dry_run={dry_run} skip_deps={skip_deps}")
    if cache:
        _log(f"  vendor_cache: {cache}")

    # Copy vendor_cache tags needed by selected versions (before mayapy pip)
    if not uninstall and not dry_run and cache is not None:
        tags = abi_tags_for_maya_versions(vers)
        _log(f"  applying vendor_cache tags: {', '.join(tags)}")
        deps_mod.apply_vendor_cache(tags, vendor_cache=cache, force=force_deps)

    dep_failures = 0
    if not uninstall and not skip_deps and not dry_run:
        try:
            for ver in vers:
                row = install_mod.VersionInstallResult(version=ver)
                mp = find_mayapy(ver)
                row.mayapy = str(mp) if mp else ""
                report.versions.append(row)
                if not mp:
                    row.deps_ok = None
                    _log(f"  Maya {ver}: mayapy not found (hooks only / vendor copy)")
                    continue
                ok = bool(
                    deps_mod.install_for_mayapy(
                        mp,
                        deps_mod.REQUIREMENTS,
                        force=force_deps,
                        allow_vendor=True,
                        maya_version=ver,
                        vendor_cache=cache,
                    )
                )
                row.deps_ok = ok
                if not ok:
                    dep_failures += 1
        except Exception as e:
            dep_failures = 1
            _log(f"[警告] 依赖安装异常: {e}")

    # Hooks + shared plug-in (install_all does not install deps)
    install_mod.install_all(
        vers,
        project_root,
        uninstall=uninstall,
        dry_run=dry_run,
        report=report,
    )

    # Persist versions for uninstaller
    versions_file = project_root / "unins_versions.txt"
    if not dry_run:
        if uninstall:
            if versions_file.exists():
                try:
                    versions_file.unlink()
                except OSError:
                    pass
        else:
            try:
                versions_file.write_text("\n".join(vers) + "\n", encoding="utf-8")
            except OSError as e:
                _log(f"[警告] 无法写入 {versions_file}: {e}")

    report.print_summary()
    if log_path:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            # Append report text by capturing a second summary into file
            with log_path.open("w", encoding="utf-8") as fh:
                fh.write("\n".join(log_lines) + "\n")
                fh.write(f"hooks_all_failed={report.hooks_all_failed}\n")
                fh.write(f"any_deps_failed={report.any_deps_failed}\n")
                fh.write(f"dep_failures={dep_failures}\n")
                for row in report.versions:
                    fh.write(
                        f"{row.version}: hooks={row.hooks_ok} deps={row.deps_ok} "
                        f"mayapy={row.mayapy} load={row.load_path} err={row.error}\n"
                    )
            _log(f"Log written: {log_path}")
        except OSError as e:
            _log(f"[警告] 无法写日志 {log_path}: {e}")

    if uninstall or dry_run:
        return 0
    if report.hooks_all_failed:
        return 1
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Maya Agent install engine (mayapy-friendly)"
    )
    parser.add_argument(
        "--project-root",
        default="",
        help="Install tree root (default: parent of scripts/)",
    )
    parser.add_argument(
        "--maya-version",
        action="append",
        dest="versions",
        default=[],
        help="Maya version (repeatable)",
    )
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--skip-deps", action="store_true")
    parser.add_argument("--force-deps", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--list-versions",
        action="store_true",
        help="Print discovered versions and exit",
    )
    parser.add_argument(
        "--vendor-cache",
        default="",
        help="Path to vendor_cache (default: <project>/vendor_cache)",
    )
    parser.add_argument(
        "--log-file",
        default="",
        help="Write install summary to this path",
    )
    parser.add_argument(
        "--write-versions-file",
        default="",
        help="Write space-separated discovered versions to file and exit",
    )
    parser.add_argument(
        "--versions-from-file",
        default="",
        help="Read versions from file (newline or space separated)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.list_versions or args.write_versions_file:
        vers = discover_maya_versions()
        text = " ".join(vers) if vers else ""
        if args.write_versions_file:
            path = Path(args.write_versions_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + ("\n" if text else ""), encoding="utf-8")
        if args.list_versions:
            print(text)
        return 0 if vers else 1

    root = _resolve_project_root(args.project_root)
    versions: List[str] = list(args.versions)

    if args.versions_from_file:
        raw = Path(args.versions_from_file).read_text(encoding="utf-8")
        for part in raw.replace(",", " ").split():
            part = part.strip()
            if part and part not in versions:
                versions.append(part)

    if not versions and args.uninstall:
        # Prefer previously installed list
        vf = root / "unins_versions.txt"
        if vf.is_file():
            for part in vf.read_text(encoding="utf-8").replace(",", " ").split():
                if part.strip():
                    versions.append(part.strip())
        if not versions:
            versions = _default_versions()

    if not versions:
        versions = _default_versions()

    cache = Path(args.vendor_cache) if args.vendor_cache else None
    log_path = Path(args.log_file) if args.log_file else None
    if log_path is None and not args.dry_run:
        # Default log under user config-ish location next to install
        log_path = root / "install_engine.log"

    return run_install(
        versions,
        root,
        uninstall=args.uninstall,
        skip_deps=args.skip_deps,
        force_deps=args.force_deps,
        dry_run=args.dry_run,
        vendor_cache=cache,
        log_path=log_path,
    )


if __name__ == "__main__":
    raise SystemExit(main())

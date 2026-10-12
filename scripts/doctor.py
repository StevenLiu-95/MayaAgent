"""
Maya Agent install / runtime health check (read-only).

Usage:
  python scripts/doctor.py
  python scripts/doctor.py --maya-version 2025
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

_SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _SCRIPTS_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from maya_discover import (  # noqa: E402
    discover_maya_versions,
    documents_maya_root,
    find_mayapy,
    is_valid_project_root,
    version_junction_path,
)


def _load_install_mod():
    path = _SCRIPTS_DIR / "install.py"
    spec = importlib.util.spec_from_file_location("maya_agent_install_doctor", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    # Required before exec_module so @dataclass can resolve the module dict
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _ok(label: str, detail: str = "") -> Tuple[str, str, str]:
    return ("OK", label, detail)


def _warn(label: str, detail: str = "") -> Tuple[str, str, str]:
    return ("WARN", label, detail)


def _fail(label: str, detail: str = "") -> Tuple[str, str, str]:
    return ("FAIL", label, detail)


def _check_usersetup(scripts: Path) -> List[Tuple[str, str, str]]:
    rows = []
    py = scripts / "userSetup.py"
    if py.is_file() and "# >>> Maya Agent" in py.read_text(encoding="utf-8", errors="replace"):
        rows.append(_ok("userSetup.py", str(py)))
    else:
        rows.append(_warn("userSetup.py", f"missing Maya Agent block ({py})"))
    mel = scripts / "userSetup.mel"
    if mel.is_file() and "// >>> Maya Agent" in mel.read_text(encoding="utf-8", errors="replace"):
        rows.append(_ok("userSetup.mel", str(mel)))
    else:
        rows.append(_warn("userSetup.mel", f"missing Maya Agent block ({mel})"))
    return rows


def _check_module(modules: Path) -> Tuple[str, str, str]:
    mod = modules / "MayaAgent.mod"
    if mod.is_file():
        return _ok("MayaAgent.mod", str(mod))
    return _warn("MayaAgent.mod", f"missing ({mod})")


def _check_junction(version: str) -> Tuple[str, str, str]:
    import os

    link = version_junction_path(version)
    if not os.path.lexists(link):
        return _warn("junction", f"missing ({link})")
    if not link.exists():
        return _fail("junction", f"broken ({link})")
    try:
        resolved = link.resolve()
        if is_valid_project_root(resolved):
            return _ok("junction", f"{link} -> {resolved}")
        if is_valid_project_root(link):
            return _ok("junction", str(link))
        return _fail("junction", f"exists but no maya_agent package: {link}")
    except OSError as e:
        return _fail("junction", f"{link}: {e}")


def _check_plugin_prefs(install_mod, version: str) -> Tuple[str, str, str]:
    prefs_dirs = install_mod._prefs_dirs_for(version)
    if not prefs_dirs:
        return _warn("pluginPrefs.mel", "no prefs dir")
    hits = []
    for prefs in prefs_dirs:
        path = prefs / "pluginPrefs.mel"
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "MayaAgent.py" in text or re.search(r'autoLoadPlugin\(.*"MayaAgent"', text):
            hits.append(str(path))
    if hits:
        return _ok("pluginPrefs autoload", "; ".join(hits))
    return _warn("pluginPrefs autoload", "MayaAgent not listed (plug-in may still load manually)")


def _check_shared_plugin(install_mod) -> List[Tuple[str, str, str]]:
    rows = []
    dest = install_mod.shared_plugins_dir() / "MayaAgent.py"
    if not dest.is_file():
        rows.append(_fail("shared plug-in", f"missing ({dest})"))
        return rows
    rows.append(_ok("shared plug-in", str(dest)))
    text = dest.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'^MODULE_ROOT\s*=\s*r?["\'](.+?)["\']', text, re.M)
    configured = (m.group(1) if m else "").replace("\\", "/")
    if configured.startswith("__") or not configured:
        rows.append(_fail("MODULE_ROOT", "placeholder not replaced — re-run install"))
    elif is_valid_project_root(configured):
        rows.append(_ok("MODULE_ROOT", configured))
    else:
        # Runtime resolve may still work via junction
        rows.append(
            _warn(
                "MODULE_ROOT",
                f"configured path invalid ({configured}); "
                "plug-in will try version junction / sys.path at load",
            )
        )
    if "executeDeferred(_bootstrap)" in text and "resolve_module_root" in text:
        # Success path must return before evalDeferred fallback (no dual schedule)
        after = text.split("executeDeferred(_bootstrap)", 1)[1][:500]
        if "return" in after.split("evalDeferred")[0]:
            rows.append(_ok("plug-in schedule", "single primary deferred path"))
        else:
            rows.append(_warn("plug-in schedule", "executeDeferred may not return before fallback"))
    else:
        rows.append(_warn("plug-in schedule", "missing executeDeferred(_bootstrap) / resolve_module_root"))
    return rows


def _probe_httpx(mayapy: Optional[Path], vendor: Path) -> Tuple[str, str, str]:
    vendor_s = str(vendor.resolve()) if vendor.is_dir() else ""
    if mayapy and mayapy.is_file():
        code = (
            (f"import sys; sys.path.insert(0, r'{vendor_s}'); " if vendor_s else "")
            + "import httpx; print('ok')"
        )
        try:
            proc = subprocess.run(
                [str(mayapy), "-c", code],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            if proc.returncode == 0:
                return _ok("httpx (mayapy)", str(mayapy))
            return _fail("httpx (mayapy)", (proc.stderr or proc.stdout or "import failed")[:200])
        except Exception as e:
            return _fail("httpx (mayapy)", str(e))
    # Host process + vendor
    if vendor_s and vendor_s not in sys.path:
        sys.path.insert(0, vendor_s)
    try:
        import httpx  # noqa: F401

        return _ok("httpx (host/.vendor)", vendor_s or "(site-packages)")
    except ImportError:
        return _fail("httpx", "not importable — run install.bat force or --vendor-only")


def run_doctor(versions: Optional[Sequence[str]] = None) -> int:
    rows: List[Tuple[str, str, str]] = []
    print("Maya Agent doctor")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Documents Maya: {documents_maya_root()}")

    print("\n--- Global ---")
    if not is_valid_project_root(PROJECT_ROOT):
        rows.append(_fail("project", "maya_agent package missing"))
    else:
        rows.append(_ok("project", str(PROJECT_ROOT)))

    vendor = PROJECT_ROOT / ".vendor"
    if vendor.is_dir():
        rows.append(_ok(".vendor", str(vendor)))
    else:
        rows.append(_warn(".vendor", "not present (ok if mayapy site-packages has httpx)"))

    install_mod = _load_install_mod()
    rows.extend(_check_shared_plugin(install_mod))

    for status, label, detail in rows:
        print(f"  [{status:4}] {label}: {detail}")

    vers = list(versions) if versions else discover_maya_versions()
    if not vers:
        rows.append(_warn("versions", "none discovered — try MAYA_AGENT_MAYAPY_ROOTS"))
        print(f"  [WARN] versions: none discovered — try MAYA_AGENT_MAYAPY_ROOTS")
        vers = []

    for ver in vers:
        print(f"\n--- Maya {ver} ---")
        vrows: List[Tuple[str, str, str]] = []
        mp = find_mayapy(ver)
        if mp:
            vrows.append(_ok("mayapy", str(mp)))
        else:
            vrows.append(_warn("mayapy", "not found"))
        vrows.append(_check_junction(ver))
        scripts = install_mod.scripts_dir_for(ver)
        modules = install_mod.modules_dir_for(ver)
        vrows.extend(_check_usersetup(scripts))
        vrows.append(_check_module(modules))
        vrows.append(_check_plugin_prefs(install_mod, ver))
        vrows.append(_probe_httpx(mp, vendor))
        for status, label, detail in vrows:
            print(f"  [{status:4}] {label}: {detail}")
            rows.append((status, f"{ver}/{label}", detail))

    print("\n========== Summary ==========")
    fails = [r for r in rows if r[0] == "FAIL"]
    warns = [r for r in rows if r[0] == "WARN"]
    oks = [r for r in rows if r[0] == "OK"]
    print(f"OK={len(oks)}  WARN={len(warns)}  FAIL={len(fails)}")
    if fails:
        print("Failures:")
        for _, label, detail in fails:
            print(f"  - {label}: {detail}")
    print("=============================")
    return 1 if fails else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose Maya Agent install")
    parser.add_argument("--maya-version", action="append", dest="versions", default=[])
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return run_doctor(args.versions or None)
    except Exception as e:
        print(f"doctor error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

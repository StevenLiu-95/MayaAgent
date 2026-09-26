"""
Offline install / bootstrap regression checks (no Maya UI required).

Run: python scripts/test_install_chain.py
"""

from __future__ import annotations

import ast
import builtins
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _ok(name: str) -> None:
    print(f"  OK  {name}")


def _fail(name: str, detail: str) -> None:
    raise SystemExit(f"  FAIL {name}: {detail}")


def test_default_config_json() -> None:
    path = ROOT / "config" / "default_config.json"
    if not path.is_file():
        _fail("default_config.json", "missing")
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    if "providers" not in data or "llm" not in data:
        _fail("default_config.json", "missing providers/llm")
    _ok("default_config.json")


def test_config_without_yaml() -> None:
    """Config / logger / menu must work even when PyYAML is unavailable."""
    real_import = builtins.__import__

    def _blocked(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
        if name == "yaml" or name.startswith("yaml."):
            raise ImportError("yaml blocked for test")
        return real_import(name, globals, locals, fromlist, level)

    for name in list(sys.modules):
        if name == "yaml" or name.startswith("yaml."):
            sys.modules.pop(name, None)
        if name == "maya_agent" or name.startswith("maya_agent."):
            sys.modules.pop(name, None)

    builtins.__import__ = _blocked
    try:
        from maya_agent.utils.logger import get_logger
        from maya_agent.utils.config import get_config
        from maya_agent.plugin import menu as menu_mod

        get_logger("test_install_chain").info("logger ok")
        cfg = get_config()
        if not cfg.get("llm.active_provider"):
            _fail("config_without_yaml", "active_provider empty")
        if not hasattr(menu_mod, "bootstrap"):
            _fail("config_without_yaml", "menu.bootstrap missing")
        _ok("config/logger/menu import without yaml")
    finally:
        builtins.__import__ = real_import
        for name in list(sys.modules):
            if name == "maya_agent" or name.startswith("maya_agent."):
                sys.modules.pop(name, None)


def test_install_dragdrop_mel() -> None:
    mel = (ROOT / "install_dragdrop.mel").read_text(encoding="utf-8")
    if "MayaAgent_dragDropInstall" not in mel:
        _fail("install_dragdrop.mel", "missing proc")
    if "runpy.run_path" not in mel:
        _fail("install_dragdrop.mel", "missing runpy")
    if "string $py =" not in mel:
        _fail("install_dragdrop.mel", "missing $py build")
    if " + " not in mel:
        _fail("install_dragdrop.mel", "missing MEL + concatenation")
    _ok("install_dragdrop.mel structure")


def test_install_modules_syntax() -> None:
    for rel in (
        "scripts/install.py",
        "scripts/install_deps.py",
        "scripts/drag_install.py",
        "maya_agent/utils/paths.py",
        "maya_agent/utils/config.py",
        "resources/maya_plugin/MayaAgent.py",
    ):
        path = ROOT / rel
        src = path.read_text(encoding="utf-8")
        try:
            ast.parse(src, filename=str(path))
        except SyntaxError as e:
            _fail(rel, str(e))
        _ok(f"syntax {rel}")


def test_install_deps_proxy_detect() -> None:
    spec = importlib.util.spec_from_file_location(
        "maya_agent_install_deps", ROOT / "scripts" / "install_deps.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    proxy = mod.detect_http_proxy()
    print(f"  info proxy detect -> {proxy!r}")
    mayapy = mod.find_mayapy("2023")
    print(f"  info mayapy 2023 -> {mayapy}")
    ascii_req = mod.ascii_requirements(ROOT / "requirements.txt")
    body = ascii_req.read_text(encoding="ascii")
    if "httpx" not in body:
        _fail("ascii_requirements", "httpx missing")
    try:
        body.encode("ascii")
    except UnicodeEncodeError as e:
        _fail("ascii_requirements", str(e))
    _ok("install_deps helpers")


def test_smoke_config_tools() -> None:
    from maya_agent.utils.config import get_config
    from maya_agent.tools.registry import ensure_tools_loaded, tool_specs

    cfg = get_config()
    ensure_tools_loaded()
    specs = tool_specs()
    if len(specs) < 10:
        _fail("smoke", f"too few tools: {len(specs)}")
    print(f"  info tools={len(specs)} provider={cfg.get('llm.active_provider')}")
    _ok("smoke config+tools")


def main() -> int:
    print("Maya Agent install-chain tests")
    test_default_config_json()
    test_install_modules_syntax()
    test_install_dragdrop_mel()
    test_install_deps_proxy_detect()
    test_config_without_yaml()
    test_smoke_config_tools()
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

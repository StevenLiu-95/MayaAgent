"""Regression: force-reload must not wipe tools that sort before ``registry``."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_iter_skips_registry() -> None:
    from maya_agent.tools.registry import _iter_public_tool_modules

    names = [full.rsplit(".", 1)[-1] for full in _iter_public_tool_modules()]
    assert "registry" not in names
    assert "meshy" in names
    assert "tripo" in names


def test_force_reload_keeps_pre_registry_tools() -> None:
    """Simulate empty registry + already-imported modules (the Maya reload path)."""
    from maya_agent.tools import registry as reg

    reg._REGISTRY.clear()
    reg.ensure_tools_loaded()
    before = set(reg._REGISTRY)
    assert "create_primitive" in before, "modeling tools must register"
    assert "get_scene_info" in before
    assert any(n.startswith("meshy_") for n in before), "meshy_* must be in registry"
    assert any(n.startswith("hunyuan_") for n in before), "hunyuan_* must be in registry"

    # Empty registry again while modules stay in sys.modules → force_reload path
    reg._REGISTRY.clear()
    assert len(reg._REGISTRY) == 0
    reg.ensure_tools_loaded()
    after = set(reg._REGISTRY)

    assert "create_primitive" in after
    assert "get_scene_info" in after
    assert "execute_python" in after
    assert "export_fbx" in after
    assert any(n.startswith("meshy_") for n in after)
    assert any(n.startswith("hunyuan_") for n in after)
    assert len(after) >= reg._MIN_HEALTHY_TOOLS
    # Incomplete canary must pass
    assert not reg._registry_incomplete()


def test_heal_restores_missing_canaries() -> None:
    from maya_agent.tools import registry as reg

    reg.ensure_tools_loaded()
    # Simulate wipe of pre-registry tools only (historical bug residue)
    for name in list(reg._REGISTRY):
        if name.startswith(("meshy_", "hunyuan_", "create_")) or name in (
            "export_fbx",
            "capture_viewport",
        ):
            reg._REGISTRY.pop(name, None)
    assert reg._registry_incomplete()
    # ensure_tools_loaded / heal both detect canary gaps and hard-reset
    heal = reg.heal_tools_if_needed()
    assert "create_primitive" in reg._REGISTRY
    assert "export_fbx" in reg._REGISTRY
    assert any(n.startswith("meshy_") for n in reg._REGISTRY)
    assert not reg._registry_incomplete()
    assert heal["tool_count"] >= reg._MIN_HEALTHY_TOOLS


def test_filter_system_prompt_meshy_single_hash() -> None:
    from maya_agent.tools import meshy_client as mc

    text = "# AdvancedSkeleton\nok\n# Meshy\n- tip\n# Tripo\ntripo tip\n"
    old_fp = mc._invalid_key_fp
    orig = mc.meshy_tools_available
    try:
        mc.meshy_tools_available = lambda: False  # type: ignore[assignment]
        out = mc.filter_system_prompt_meshy(text)
        assert "# Meshy" not in out
        assert "- tip" not in out
        assert "# Tripo" in out
        assert "tripo tip" in out
        assert "# AdvancedSkeleton" in out
    finally:
        mc._invalid_key_fp = old_fp
        mc.meshy_tools_available = orig  # type: ignore[assignment]


def main() -> None:
    test_iter_skips_registry()
    test_force_reload_keeps_pre_registry_tools()
    test_heal_restores_missing_canaries()
    test_filter_system_prompt_meshy_single_hash()
    print("OK test_registry_reload_unit")


if __name__ == "__main__":
    main()

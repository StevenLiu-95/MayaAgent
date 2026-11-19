"""Unit tests for bundled skills hard-split (no Maya required)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPECTED = {
    "procedural-modeling",
    "game-asset-uv",
    "character-rigging",
    "advanced-skeleton",
    "meshy-3d",
    "tripo-3d",
    "hunyuan-3d",
    "maya-tool-dev",
    "data-visualization",
}


def main() -> None:
    from maya_agent.core import skills_manager
    from maya_agent.core.tool_exposure import (
        ALWAYS_ON_TOOLS,
        EXPOSURE_LAYERED,
        ToolRouter,
    )

    skills_manager.reload_skills()
    bundled = skills_manager.bundled_skills_root()
    assert bundled.is_dir(), f"missing {bundled}"
    for name in EXPECTED:
        assert (bundled / name / "SKILL.md").is_file(), f"missing skill {name}"

    found = {s.name: s for s in skills_manager.discover_skills(force_reload=True)}
    for name in EXPECTED:
        assert name in found, f"not discovered: {name}"

    # Parse / metadata
    uv = found["game-asset-uv"]
    assert uv.metadata.get("category") == "uv"
    rig = found["character-rigging"]
    cats = rig.metadata.get("categories") or ""
    assert "rigging" in cats and "animation" in cats
    assert found["meshy-3d"].metadata.get("requires") == "meshy"

    # Multi-category activate
    router = ToolRouter(exposure=EXPOSURE_LAYERED)
    r = router.activate_from_skill(rig)
    assert r.get("activated_via") == "metadata.categories"
    assert "rigging" in router.active_categories
    assert "animation" in router.active_categories

    # Single category
    router2 = ToolRouter(exposure=EXPOSURE_LAYERED)
    r2 = router2.activate_from_skill(uv)
    assert r2.get("activated_via") == "metadata.category"
    assert "uv" in router2.active_categories

    # requires filter: force unmet
    class _Fake:
        metadata = {"requires": "meshy"}
        disable_model_invocation = False
        name = "x"
        description = "x"

    # skill_requirement_met uses real clients; just ensure API exists
    assert callable(skills_manager.skill_requirement_met)
    adv = found["advanced-skeleton"]
    # If ADV unavailable in this environment, skill should be filtered from catalog
    catalog = skills_manager.get_skills_catalog_for_prompt(max_chars=20000)
    if not skills_manager.skill_requirement_met(adv):
        assert "advanced-skeleton" not in catalog
    if not skills_manager.skill_requirement_met(found["meshy-3d"]):
        assert "meshy-3d:" not in catalog and "- meshy-3d:" not in catalog

    # system_zh slimmed
    prompt = (ROOT / "resources" / "prompts" / "system_zh.md").read_text(encoding="utf-8")
    for banned in (
        "### UV",
        "### 建模",
        "### 骨骼绑定",
        "# Meshy",
        "# Tripo",
        "# 混元3D",
        "### 数据可视化",
        "### 工具开发",
    ):
        assert banned not in prompt, f"system_zh still contains {banned!r}"
    assert "available_skills" in prompt or "read_skill" in prompt

    # generate_chart no longer always-on
    assert "generate_chart" not in ALWAYS_ON_TOOLS

    print("OK test_bundled_skills_unit")


if __name__ == "__main__":
    main()

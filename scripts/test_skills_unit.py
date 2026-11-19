# -*- coding: utf-8 -*-
"""Offline unit tests for Agent Skills (agentskills.io format)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maya_agent.core import skills_manager as sm
from maya_agent.core.skills_manager import (
    get_skills_catalog_for_prompt,
    load_skill,
    parse_skill_md,
    read_skill_resource,
    skill_info_from_dir,
    validate_skill_name,
)
from maya_agent.utils.paths import default_agent_skills_root


class TestSkillNameValidation(unittest.TestCase):
    def test_valid_names(self):
        for name in ("pdf-processing", "game-asset-uv", "a", "a1-b2"):
            ok, err = validate_skill_name(name)
            self.assertTrue(ok, msg=f"{name}: {err}")

    def test_invalid_names(self):
        for name in ("PDF", "-bad", "bad-", "bad--name", "", "Has Space"):
            ok, _ = validate_skill_name(name)
            self.assertFalse(ok, msg=name)


class TestFrontmatter(unittest.TestCase):
    def test_parse_roundtrip(self):
        text = (
            "---\n"
            "name: demo-skill\n"
            "description: Demo skill for unit tests. Use when testing.\n"
            "disable-model-invocation: true\n"
            "---\n\n"
            "# Demo\n\nDo the thing.\n"
        )
        fm, body = parse_skill_md(text)
        self.assertEqual(fm.get("name"), "demo-skill")
        self.assertIn("Demo skill", str(fm.get("description") or ""))
        self.assertTrue(sm._truthy(fm.get("disable-model-invocation")))
        self.assertIn("Do the thing", body)

    def test_missing_frontmatter(self):
        with self.assertRaises(ValueError):
            parse_skill_md("# No frontmatter\n")


class TestDiscovery(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        sm.reload_skills()

    def tearDown(self):
        sm.reload_skills()
        self._tmp.cleanup()
        # Clear any skills_dir override left in config memory if present
        try:
            from maya_agent.utils.config import get_config

            get_config().set("agent.skills_dir", "")
            get_config().set("agent.skills_enabled", True)
        except Exception:
            pass

    def _write_skill(
        self,
        dirname: str,
        name: str,
        description: str,
        *,
        body: str = "# Body\n",
        extra_fm: str = "",
    ) -> Path:
        d = self.root / dirname
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n{extra_fm}---\n\n{body}",
            encoding="utf-8",
        )
        return d

    def _use_root(self):
        from maya_agent.utils.config import get_config

        cfg = get_config()
        cfg.set("agent.skills_dir", str(self.root).replace("\\", "/"))
        cfg.set("agent.skills_enabled", True)
        sm.reload_skills()

    def test_default_path_sibling(self):
        p = default_agent_skills_root()
        self.assertEqual(p.name, "MayaAgentSkills")
        self.assertEqual(p.parent, ROOT.parent)

    def test_skip_underscore_draft(self):
        self._write_skill(
            "_draft",
            "draft",
            "Draft skill that should be skipped.",
        )
        self._write_skill(
            "visible-skill",
            "visible-skill",
            "Visible skill for discovery tests.",
        )
        self._use_root()
        # Avoid ensure writing example into temp by scanning only
        found = sm._scan_skills(self.root)
        names = {s.name for s in found}
        self.assertIn("visible-skill", names)
        self.assertNotIn("draft", names)
        self.assertNotIn("_draft", names)

    def test_disable_model_invocation_omitted_from_catalog(self):
        self._write_skill(
            "auto-skill",
            "auto-skill",
            "Auto skill used in catalog tests.",
        )
        self._write_skill(
            "manual-skill",
            "manual-skill",
            "Manual skill used in catalog tests.",
            extra_fm="disable-model-invocation: true\n",
        )
        self._use_root()

        # Patch discover to use our scan without ensure_skills_dir side effects
        skills = sm._scan_skills(self.root)
        sm._skills_cache = skills
        catalog = get_skills_catalog_for_prompt(max_chars=8000)
        self.assertIn("auto-skill", catalog)
        self.assertNotIn("manual-skill", catalog)
        self.assertIn("<available_skills>", catalog)

    def test_name_mismatch_uses_directory(self):
        d = self._write_skill(
            "dir-name",
            "other-name",
            "Skill with mismatched frontmatter name.",
        )
        info = skill_info_from_dir(d)
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info.name, "dir-name")
        self.assertTrue(info.name_mismatch)

    def test_load_and_resource(self):
        d = self._write_skill(
            "pack",
            "pack",
            "Skill with a reference file for resource tests.",
            body="# Pack\n\nSee references/note.md\n",
        )
        ref = d / "references"
        ref.mkdir()
        (ref / "note.md").write_text("hello resource\n", encoding="utf-8")
        self._use_root()
        sm._skills_cache = sm._scan_skills(self.root)

        payload = load_skill("pack")
        self.assertIn("See references", payload["instructions"])

        res = read_skill_resource("pack", "references/note.md")
        self.assertIn("hello resource", res["content"])

        with self.assertRaises(ValueError):
            read_skill_resource("pack", "../pack/SKILL.md")
        with self.assertRaises(ValueError):
            read_skill_resource("pack", "..\\..\\etc\\passwd")

    def test_catalog_truncation(self):
        long_desc = "x" * 800
        for i in range(12):
            name = f"skill-{i:02d}"
            self._write_skill(name, name, f"{long_desc} trigger-{i}")
        self._use_root()
        sm._skills_cache = sm._scan_skills(self.root)
        catalog = get_skills_catalog_for_prompt(max_chars=600)
        self.assertIn("truncated", catalog.lower())
        self.assertLessEqual(len(catalog), 700)


class TestSystemPromptIntegration(unittest.TestCase):
    def test_prompt_includes_skills_and_rules_order(self):
        from maya_agent.utils.config import get_config

        cfg = get_config()
        cfg.set("agent.skills_enabled", True)
        cfg.set("agent.user_rules_enabled", True)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "order-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\n"
                "name: order-skill\n"
                "description: Ordering test skill for system prompt.\n"
                "---\n\n# Order\n",
                encoding="utf-8",
            )
            cfg.set("agent.skills_dir", str(root).replace("\\", "/"))
            sm.reload_skills()
            sm._skills_cache = sm._scan_skills(root)

            # Inject a fake UI rule via user_rules file is heavy; call builders directly.
            skills = get_skills_catalog_for_prompt()
            self.assertIn("order-skill", skills)

            from maya_agent.core.system_prompt import build_system_prompt

            # build_system_prompt may pull real user rules; just ensure skills section present
            # and that when both exist skills appear before user_rules marker if rules exist.
            full = build_system_prompt(mode="agent")
            self.assertIn("<available_skills>", full)
            if "<user_rules>" in full:
                self.assertLess(
                    full.index("<available_skills>"),
                    full.index("<user_rules>"),
                )

        cfg.set("agent.skills_dir", "")
        sm.reload_skills()

    def test_skills_disabled(self):
        from maya_agent.utils.config import get_config

        cfg = get_config()
        cfg.set("agent.skills_enabled", False)
        try:
            self.assertEqual(get_skills_catalog_for_prompt(), "")
        finally:
            cfg.set("agent.skills_enabled", True)


class TestSkillToolsRegistered(unittest.TestCase):
    def test_tools_exist(self):
        from maya_agent.tools.registry import ensure_tools_loaded, get_tool

        ensure_tools_loaded()
        for name in ("list_skills", "read_skill", "read_skill_resource"):
            self.assertIsNotNone(get_tool(name), msg=name)


if __name__ == "__main__":
    unittest.main()

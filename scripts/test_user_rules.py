"""Unit tests for User Rules (no Maya required)."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_ui_enable_disable_and_prompt():
    import maya_agent.core.rules_manager as rm

    with tempfile.TemporaryDirectory() as td:
        rules_path = Path(td) / "user_rules.json"
        rules_dir = Path(td) / "rules"
        rules_dir.mkdir()
        with mock.patch.object(rm, "user_rules_path", return_value=rules_path), mock.patch.object(
            rm, "project_rules_dir", return_value=rules_dir
        ):
            rm.reload_rules()
            r = rm.add_rule(title="Naming", content="Use SM_ prefix")
            text = rm.get_rules_for_prompt(max_chars=8000)
            assert "<user_rules>" in text
            assert "SM_ prefix" in text
            assert "## Naming" in text

            rm.update_rule(r["id"], enabled=False)
            rm.reload_rules()
            assert rm.get_rules_for_prompt(max_chars=8000) == ""


def test_file_rules_skip_underscore():
    import maya_agent.core.rules_manager as rm

    with tempfile.TemporaryDirectory() as td:
        rules_path = Path(td) / "user_rules.json"
        rules_path.write_text("[]", encoding="utf-8")
        rules_dir = Path(td) / "rules"
        rules_dir.mkdir()
        (rules_dir / "_draft.md").write_text("DRAFT_ONLY", encoding="utf-8")
        (rules_dir / "naming.md").write_text("FILE_RULE_BODY", encoding="utf-8")
        with mock.patch.object(rm, "user_rules_path", return_value=rules_path), mock.patch.object(
            rm, "project_rules_dir", return_value=rules_dir
        ):
            rm.reload_rules()
            all_r = rm.get_all_rules(force_reload=True)
            titles = {r["title"] for r in all_r}
            assert "naming" in titles
            assert "_draft" not in titles and "draft" not in titles
            text = rm.get_rules_for_prompt(max_chars=8000)
            assert "FILE_RULE_BODY" in text
            assert "DRAFT_ONLY" not in text


def test_build_system_prompt_includes_rules():
    import maya_agent.core.rules_manager as rm
    from maya_agent.core.system_prompt import build_system_prompt
    from maya_agent.utils.config import get_config

    cfg = get_config()
    cfg.set("agent.user_rules_enabled", True)
    with tempfile.TemporaryDirectory() as td:
        rules_path = Path(td) / "user_rules.json"
        rules_dir = Path(td) / "rules"
        rules_dir.mkdir()
        with mock.patch.object(rm, "user_rules_path", return_value=rules_path), mock.patch.object(
            rm, "project_rules_dir", return_value=rules_dir
        ):
            rm.reload_rules()
            rm.add_rule(title="T", content="MUST_FOLLOW_XYZ")
            prompt = build_system_prompt(mode="agent")
            assert "<user_rules>" in prompt
            assert "MUST_FOLLOW_XYZ" in prompt

            cfg.set("agent.user_rules_enabled", False)
            rm.reload_rules()
            prompt2 = build_system_prompt(mode="agent")
            assert "<user_rules>" not in prompt2
            cfg.set("agent.user_rules_enabled", True)


def test_truncate_long_rules():
    import maya_agent.core.rules_manager as rm

    with tempfile.TemporaryDirectory() as td:
        rules_path = Path(td) / "user_rules.json"
        rules_dir = Path(td) / "rules"
        rules_dir.mkdir()
        with mock.patch.object(rm, "user_rules_path", return_value=rules_path), mock.patch.object(
            rm, "project_rules_dir", return_value=rules_dir
        ):
            rm.reload_rules()
            rm.add_rule(title="Long", content="Z" * 5000)
            text = rm.get_rules_for_prompt(max_chars=800)
            assert "truncated" in text
            assert len(text) <= 850


def main():
    test_ui_enable_disable_and_prompt()
    test_file_rules_skip_underscore()
    test_build_system_prompt_includes_rules()
    test_truncate_long_rules()
    print("test_user_rules: OK")


if __name__ == "__main__":
    main()

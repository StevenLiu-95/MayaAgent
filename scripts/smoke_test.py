"""
Smoke test outside Maya: tool registration + config + provider listing.
Run: python scripts/smoke_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from maya_agent import __app_name__, __version__
    from maya_agent.llm.registry import list_providers
    from maya_agent.tools.registry import ensure_tools_loaded, tool_specs, tools_by_category
    from maya_agent.utils.config import get_config

    print(f"{__app_name__} v{__version__}")
    cfg = get_config()
    print("active_provider:", cfg.get("llm.active_provider"))
    print("providers:", len(list_providers()))
    for p in list_providers():
        print(f"  - {p['id']}: {p['label']} ({len(p['models'])} models)")

    ensure_tools_loaded()
    specs = tool_specs()
    cats = tools_by_category()
    print(f"tools registered: {len(specs)}")
    for cat, items in sorted(cats.items()):
        print(f"  [{cat}] {len(items)}")
    print("system prompt chars:", len(cfg.system_prompt()))
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

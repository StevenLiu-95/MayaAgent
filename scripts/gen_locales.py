# -*- coding: utf-8 -*-
"""
Generate / sync resources/locales/*.json for Maya Agent UI i18n.

Delegates to ``sync_locales.py`` (safe merge; does not wipe translations).
Edit JSON files or NEW_* / TW_OVERRIDES in sync_locales.py, then re-run.
"""
from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    sync = Path(__file__).resolve().with_name("sync_locales.py")
    runpy.run_path(str(sync), run_name="__main__")

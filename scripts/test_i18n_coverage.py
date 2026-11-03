# -*- coding: utf-8 -*-
"""Offline check: locale key parity + t() keys resolve in zh-CN / en-US."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "resources" / "locales"
LANGS = [
    "zh-CN",
    "zh-TW",
    "en-US",
    "ja-JP",
    "ko-KR",
    "fr-FR",
    "de-DE",
    "es-ES",
    "pt-BR",
    "ru-RU",
]


def load(code: str) -> dict:
    return json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))


def collect_t_keys() -> set:
    pat = re.compile(r"""(?<![A-Za-z0-9_])t\(\s*(['"])([a-z][a-z0-9_.]+)\1""")
    used = set()
    for p in (ROOT / "maya_agent").rglob("*.py"):
        used.update(m.group(2) for m in pat.finditer(p.read_text(encoding="utf-8", errors="ignore")))
    return used


def main() -> int:
    catalogs = {L: load(L) for L in LANGS}
    master = set(catalogs["zh-CN"]) | set(catalogs["en-US"])
    errors = []

    for L in LANGS:
        missing = sorted(master - set(catalogs[L]))
        if missing:
            errors.append(f"{L} missing {len(missing)} keys (e.g. {missing[:5]})")

    if set(catalogs["zh-CN"]) != set(catalogs["en-US"]):
        only_zh = sorted(set(catalogs["zh-CN"]) - set(catalogs["en-US"]))
        only_en = sorted(set(catalogs["en-US"]) - set(catalogs["zh-CN"]))
        errors.append(f"zh-CN/en-US key mismatch only_zh={only_zh[:5]} only_en={only_en[:5]}")

    used = collect_t_keys()
    for code in ("zh-CN", "en-US"):
        miss = sorted(k for k in used if k not in catalogs[code])
        if miss:
            errors.append(f"t() keys missing in {code}: {miss[:20]}")

    required = [
        "composer.clear_title",
        "composer.clear_confirm",
        "chat.thinking",
        "viewer.title",
        "help.rules.title",
        "status.chat_images_saved",
    ]
    for k in required:
        for L in LANGS:
            if k not in catalogs[L]:
                errors.append(f"{L} missing required {k}")

    if errors:
        print("FAIL")
        for e in errors:
            print(" -", e)
        return 1
    print(
        f"OK: {len(LANGS)} locales × {len(catalogs['zh-CN'])} keys; "
        f"{len(used)} t() keys covered"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

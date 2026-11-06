"""
Bump Maya Agent version (writes ``VERSION`` then syncs all copies).

  python scripts/bump_version.py 1.5.7
  python scripts/bump_version.py --patch
  python scripts/bump_version.py --minor
  python scripts/bump_version.py --major
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from version_utils import read_version, sync_version_files, write_version  # noqa: E402


def _bump(ver: str, which: str) -> str:
    parts = ver.split(".")
    while len(parts) < 3:
        parts.append("0")
    major, minor, patch = (int(parts[0]), int(parts[1]), int(parts[2].split("-")[0].split("+")[0]))
    if which == "major":
        major, minor, patch = major + 1, 0, 0
    elif which == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    return f"{major}.{minor}.{patch}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bump Maya Agent VERSION")
    parser.add_argument("version", nargs="?", default="", help="Explicit version e.g. 1.5.7")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--major", action="store_true")
    g.add_argument("--minor", action="store_true")
    g.add_argument("--patch", action="store_true")
    args = parser.parse_args(argv)

    current = read_version()
    if args.version:
        new = args.version.strip().lstrip("vV")
    elif args.major:
        new = _bump(current, "major")
    elif args.minor:
        new = _bump(current, "minor")
    elif args.patch:
        new = _bump(current, "patch")
    else:
        parser.error("Provide VERSION or --major/--minor/--patch")
        return 2

    write_version(new)
    synced = sync_version_files(new)
    print(f"{current} → {synced}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

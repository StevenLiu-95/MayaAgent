"""
Sync project version from root ``VERSION`` into pyproject / iss / configs / docs.

  python scripts/sync_version.py
  python scripts/sync_version.py --print
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from version_utils import read_version, sync_version_files  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Sync VERSION into project files")
    parser.add_argument(
        "--print",
        action="store_true",
        help="Print current VERSION and exit (no write)",
    )
    args = parser.parse_args(argv)
    if args.print:
        print(read_version())
        return 0
    ver = sync_version_files()
    print(f"Synced version {ver}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

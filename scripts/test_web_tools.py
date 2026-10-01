"""Smoke-test web research tools (no Maya required)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _print(title: str, result) -> None:
    print(f"\n=== {title} ===")
    print("ok:", result.ok)
    if result.message:
        print("message:", result.message)
    if result.error:
        print("error:", result.error)
    if result.data is not None:
        text = json.dumps(result.data, ensure_ascii=False, indent=2, default=str)
        if len(text) > 2000:
            text = text[:2000] + "\n…(truncated)"
        print(text)
    if result.images:
        print("images:", len(result.images), [getattr(i, "name", "") for i in result.images])


def main() -> int:
    from maya_agent.tools.web import (
        fetch_image,
        fetch_webpage,
        search_images,
        web_search,
    )

    r1 = web_search(query="Unreal Engine FBX export skeletal mesh", limit=3)
    _print("web_search", r1)

    url = ""
    if r1.ok and isinstance(r1.data, dict):
        results = r1.data.get("results") or []
        if results:
            url = results[0].get("url") or ""
    if not url:
        url = "https://docs.unrealengine.com/5.3/en-US/fbx-skeletal-mesh-pipeline-in-unreal-engine/"
    r2 = fetch_webpage(url=url, max_chars=1500)
    _print("fetch_webpage", r2)

    r3 = search_images(query="game character T-pose reference", limit=3)
    _print("search_images", r3)

    img_url = ""
    thumb = ""
    referer = ""
    if r3.ok and isinstance(r3.data, dict):
        imgs = r3.data.get("results") or []
        # Prefer a non-wikimedia host for the smoke path when possible.
        pick = None
        for item in imgs:
            host = (item.get("image_url") or "").lower()
            if "wikimedia.org" not in host and "wikipedia.org" not in host:
                pick = item
                break
        if pick is None and imgs:
            pick = imgs[0]
        if pick:
            img_url = pick.get("image_url") or ""
            thumb = pick.get("thumbnail") or ""
            referer = pick.get("source_url") or ""
    if img_url:
        r4 = fetch_image(
            url=img_url,
            fallback_url=thumb,
            referer=referer,
            note="smoke",
        )
        _print("fetch_image", r4)
        if not r4.ok:
            print("fetch_image soft-fail (network/CDN); search still OK")
    else:
        print("\n=== fetch_image skipped (no image url) ===")

    # SSRF guard
    r5 = fetch_webpage(url="http://127.0.0.1/")
    _print("ssrf_localhost", r5)

    failed = [name for name, r in (("web_search", r1), ("fetch_webpage", r2), ("search_images", r3)) if not r.ok]
    if failed:
        print("\nFAILED:", ", ".join(failed))
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""Unit checks for Meshy data-URI upload timeout sizing (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maya_agent.tools.meshy_client import (
    estimate_data_uri_payload_bytes,
    httpx_timeout_for_payload,
    meshy_cfg,
)


def main() -> None:
    conf = meshy_cfg()
    assert conf["upload_timeout"] >= 60
    assert conf["upload_retries"] >= 1

    small = {"model_url": "https://example.com/a.fbx", "target_formats": ["glb"]}
    assert estimate_data_uri_payload_bytes(small) == 0
    t_small = httpx_timeout_for_payload(0)
    # Scalar / equal timeouts for small payloads
    assert float(t_small.read) == float(conf["timeout"])
    assert float(t_small.write) == float(conf["timeout"])

    fake_uri = "data:application/octet-stream;base64," + ("A" * (10 * 1024 * 1024))
    body = {"model_url": fake_uri, "target_formats": ["glb"]}
    nbytes = estimate_data_uri_payload_bytes(body)
    assert nbytes >= 10 * 1024 * 1024

    t_big = httpx_timeout_for_payload(nbytes)
    write = float(t_big.write)
    assert write >= float(conf["upload_timeout"])
    # ~10MB * 15s/MB = 150, but floor is upload_timeout (180)
    assert write >= 150
    assert write <= float(conf["upload_timeout_max"])

    # 33MB-class payload should get a generous write budget
    n33 = int(44 * 1024 * 1024)  # ~33MB file as base64 ≈ 44MB
    t33 = httpx_timeout_for_payload(n33)
    assert float(t33.write) >= 180
    print(
        "ok:",
        f"small_timeout={t_small!r}",
        f"10MB_write={write:.0f}s",
        f"44MB_write={float(t33.write):.0f}s",
        f"retries={conf['upload_retries']}",
    )


if __name__ == "__main__":
    main()

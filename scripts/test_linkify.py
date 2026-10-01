"""Quick checks for linkify / markdown anchors."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from maya_agent.ui.chat_format import escape_wrap, linkify_plain, markdown_to_html

s = linkify_plain("见 https://docs.unrealengine.com/5.3/en-US/ 文档。")
assert "<a " in s and "href=" in s, s

h = markdown_to_html(
    "参考 [UE文档](https://dev.epicgames.com/doc) 与 https://example.com/a"
)
assert "https://dev.epicgames.com/doc" in h, h
assert "https://example.com/a" in h, h

ew = escape_wrap("url https://a.com/x?y=1&z=2 ok")
assert "href=" in ew and "&amp;" in ew, ew
print("OK")

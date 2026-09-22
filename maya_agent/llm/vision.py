"""Detect whether the active model can accept image input."""

from __future__ import annotations

import re
from typing import Optional

from maya_agent.utils.config import get_config

# Names that commonly imply a vision-capable checkpoint.
# Text-only ids such as deepseek-v4-pro / qwen-max / glm-4-plus do not match.
_VISION_RE = re.compile(
    r"(?:"
    r"gpt-4o|gpt-4\.1|gpt-4-turbo|gpt-4-vision|gpt-5|"
    r"claude-(?:3|4|sonnet|opus|haiku)|"
    r"gemini|"
    r"pixtral|llava|"
    r"glm-4v|glm-4\.\d+v|"
    r"qwen[\w.-]*vl|(?:^|[-_/])vl(?:[-_.]|$)|"
    r"vision|"
    r"grok[\w.-]*vision|"
    r"moonshot[\w.-]*vision|"
    r"deepseek[\w.-]*(?:vl|vision)"
    r")",
    re.IGNORECASE,
)


def model_supports_vision(
    provider_id: Optional[str],
    model: Optional[str],
    cfg=None,
) -> bool:
    """
    True when this provider/model should receive image parts.

    Resolution order:
    1. providers.<id>.vision_policy = on | off  (user override)
    2. providers.<id>.vision = true             (whole provider, e.g. Gemini)
    3. providers.<id>.vision_models              (explicit id list)
    4. model-name heuristic (gpt-4o, claude, gemini, *vision*, *vl*, …)
    """
    cfg = cfg or get_config()
    pid = provider_id or cfg.get("llm.active_provider", "")
    pconf = cfg.get(f"providers.{pid}", {}) or {}
    policy = str(pconf.get("vision_policy") or "auto").strip().lower()
    if policy in ("on", "true", "1", "yes"):
        return True
    if policy in ("off", "false", "0", "no"):
        return False
    if pconf.get("vision") is True:
        return True
    name = (model or "").strip()
    explicit = pconf.get("vision_models") or []
    if name and name in {str(x) for x in explicit}:
        return True
    return bool(name and _VISION_RE.search(name))

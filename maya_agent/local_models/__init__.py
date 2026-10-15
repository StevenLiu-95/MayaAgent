"""Local model catalog, download, and runtime client (Maya side)."""

from maya_agent.local_models.availability import (
    backend_ready,
    filter_system_prompt_local,
    list_backend_status,
    local_cfg,
    local_enabled,
    local_tools_gate,
)
from maya_agent.local_models.catalog import get_backend, list_backends, load_catalog

__all__ = [
    "backend_ready",
    "filter_system_prompt_local",
    "get_backend",
    "list_backend_status",
    "list_backends",
    "load_catalog",
    "local_cfg",
    "local_enabled",
    "local_tools_gate",
]

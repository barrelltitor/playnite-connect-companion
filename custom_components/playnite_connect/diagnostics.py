"""Diagnostics for Playnite Connect Companion."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    CONF_CACHE_COVERS,
    CONF_COVER_API_TOKEN,
    CONF_COVER_API_URL,
    CONF_COVER_TRANSPORT,
    CONF_DEVICE_ID,
)
from .runtime_data import PlayniteConnectConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PlayniteConnectConfigEntry
) -> dict[str, Any]:
    """Return state without exposing local addresses or credentials."""
    runtime_data = entry.runtime_data
    return {
        "config": {
            "device_id_configured": bool(entry.data.get(CONF_DEVICE_ID)),
            "cover_transport": entry.data.get(CONF_COVER_TRANSPORT, "mqtt"),
            "cover_api_configured": bool(
                entry.data.get(CONF_COVER_API_URL)
                and entry.data.get(CONF_COVER_API_TOKEN)
            ),
            "cache_covers": bool(entry.data.get(CONF_CACHE_COVERS, False)),
            "cover_api_token_configured": bool(
                entry.data.get(CONF_COVER_API_TOKEN)
            ),
        },
        "runtime": {
            "loaded": runtime_data is not None,
            "playnite_available": (
                runtime_data["library"].available
                if runtime_data is not None
                else False
            ),
            "game_count": (
                len(runtime_data["library"].games)
                if runtime_data is not None
                else 0
            ),
        },
    }

"""Typed runtime data for Playnite Connect Companion."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypedDict

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntry

from .connect_library import PlayniteConnectLibrary


class PlayniteConnectRuntimeData(TypedDict):
    """Data owned by one Playnite Connect config entry."""

    device: DeviceEntry
    device_id: str
    library: PlayniteConnectLibrary
    cache_covers: bool
    cover_transport: str
    cover_api_url: str
    cover_api_token: str
    cached_cover_paths: dict[str, str]
    remove_lifecycle_listener: Callable[[], None]
    remove_device_version_listener: Callable[[], None]


PlayniteConnectConfigEntry = ConfigEntry[PlayniteConnectRuntimeData]


def get_runtime_data(
    entry: PlayniteConnectConfigEntry,
) -> PlayniteConnectRuntimeData:
    """Return initialized runtime data or raise on invalid lifecycle use."""
    if entry.runtime_data is None:
        raise RuntimeError(
            "Playnite Connect entry runtime data is not initialized"
        )
    return entry.runtime_data

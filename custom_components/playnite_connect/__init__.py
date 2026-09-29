"""Set up Playnite Connect Companion."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import mqtt
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_CACHE_COVERS,
    CONF_COVER_API_TOKEN,
    CONF_COVER_API_URL,
    CONF_COVER_TRANSPORT,
    CONF_DEVICE_ID,
    DEFAULT_NAME,
    DOMAIN,
    PLATFORMS,
)
from .cover import PlayniteCoverView
from .game_tools import (
    DEFAULT_SEARCH_LIMIT,
    DEFAULT_SEARCH_OFFSET,
    FAVORITE_STATES,
    INSTALLATION_STATES,
    MAX_SEARCH_LIMIT,
    RUNNING_STATES,
    SEARCH_SORTS,
    async_launch_game,
    async_search_and_play,
    async_search_games,
)
from .connect_library import PlayniteLifecycleEvent, PlayniteConnectLibrary
from .runtime_data import (
    PlayniteConnectConfigEntry,
    PlayniteConnectRuntimeData,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_SEARCH_GAMES = "search_games"
SERVICE_LAUNCH_GAME = "launch_game"
SERVICE_SEARCH_AND_PLAY = "search_and_play"
ATTR_QUERY = "query"
ATTR_GAME_NAME = "game_name"
ATTR_GAME_ID = "game_id"
ATTR_DEVICE_ID = "device_id"
ATTR_LIMIT = "limit"
ATTR_OFFSET = "offset"
ATTR_INSTALLATION_STATE = "installation_state"
ATTR_FAVORITE_STATE = "favorite_state"
ATTR_RUNNING_STATE = "running_state"
ATTR_SOURCE = "source"
ATTR_PLATFORM = "platform"
ATTR_CATEGORY = "category"
ATTR_TAG = "tag"
ATTR_GENRE = "genre"
ATTR_FEATURE = "feature"
ATTR_SORT_BY = "sort_by"

_SEARCH_FILTER_SCHEMA = {
    vol.Optional(ATTR_INSTALLATION_STATE, default="both"): vol.In(
        INSTALLATION_STATES
    ),
    vol.Optional(ATTR_FAVORITE_STATE, default="both"): vol.In(FAVORITE_STATES),
    vol.Optional(ATTR_RUNNING_STATE, default="both"): vol.In(RUNNING_STATES),
    vol.Optional(ATTR_SOURCE): cv.string,
    vol.Optional(ATTR_PLATFORM): cv.string,
    vol.Optional(ATTR_CATEGORY): cv.string,
    vol.Optional(ATTR_TAG): cv.string,
    vol.Optional(ATTR_GENRE): cv.string,
    vol.Optional(ATTR_FEATURE): cv.string,
}

_SEARCH_GAMES_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_QUERY, default=""): cv.string,
        vol.Optional(ATTR_DEVICE_ID): cv.string,
        vol.Optional(ATTR_LIMIT, default=DEFAULT_SEARCH_LIMIT): vol.All(
            cv.positive_int, vol.Range(max=MAX_SEARCH_LIMIT)
        ),
        vol.Optional(ATTR_OFFSET, default=DEFAULT_SEARCH_OFFSET): vol.All(
            vol.Coerce(int), vol.Range(min=0)
        ),
        vol.Optional(ATTR_SORT_BY, default="relevance"): vol.In(SEARCH_SORTS),
        **_SEARCH_FILTER_SCHEMA,
    }
)
_LAUNCH_GAME_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GAME_ID): cv.string,
        vol.Optional(ATTR_DEVICE_ID): cv.string,
    }
)
_SEARCH_AND_PLAY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GAME_NAME): vol.All(cv.string, vol.Length(min=1)),
        vol.Optional(ATTR_DEVICE_ID): cv.string,
        **_SEARCH_FILTER_SCHEMA,
    }
)


def _search_filter_kwargs(
    data: Mapping[str, Any], *, include_sort: bool = True
) -> dict[str, Any]:
    """Map validated HA service fields to shared search helper arguments."""
    filters = {
        "installation_state": data.get(ATTR_INSTALLATION_STATE, "both"),
        "favorite_state": data.get(ATTR_FAVORITE_STATE, "both"),
        "running_state": data.get(ATTR_RUNNING_STATE, "both"),
        "source": data.get(ATTR_SOURCE),
        "platform": data.get(ATTR_PLATFORM),
        "category": data.get(ATTR_CATEGORY),
        "tag": data.get(ATTR_TAG),
        "genre": data.get(ATTR_GENRE),
        "feature": data.get(ATTR_FEATURE),
    }
    if include_sort:
        filters["sort_by"] = data.get(ATTR_SORT_BY, "relevance")
    return filters


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register search and launch services independently of a loaded entry."""

    async def handle_search_games(call: ServiceCall) -> ServiceResponse:
        return await async_search_games(
            hass,
            call.data[ATTR_QUERY],
            call.data.get(ATTR_DEVICE_ID),
            call.data[ATTR_LIMIT],
            call.data[ATTR_OFFSET],
            **_search_filter_kwargs(call.data),
        )

    async def handle_launch_game(call: ServiceCall) -> ServiceResponse | None:
        result = await async_launch_game(
            hass,
            call.data[ATTR_GAME_ID],
            call.data.get(ATTR_DEVICE_ID),
        )
        return result if call.return_response else None

    async def handle_search_and_play(call: ServiceCall) -> ServiceResponse:
        """Find a title and launch it only when there is one safe match."""
        return await async_search_and_play(
            hass,
            call.data[ATTR_GAME_NAME],
            call.data.get(ATTR_DEVICE_ID),
            **_search_filter_kwargs(call.data, include_sort=False),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEARCH_GAMES,
        handle_search_games,
        schema=_SEARCH_GAMES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LAUNCH_GAME,
        handle_launch_game,
        schema=_LAUNCH_GAME_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEARCH_AND_PLAY,
        handle_search_and_play,
        schema=_SEARCH_AND_PLAY_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_migrate_entry(
    hass: HomeAssistant, config_entry: PlayniteConnectConfigEntry
) -> bool:
    """Migrate direct local entries to the latest local protocol options."""
    if config_entry.version < 6:
        data = dict(config_entry.data)
        data.setdefault(CONF_CACHE_COVERS, False)
        data.setdefault(CONF_COVER_API_URL, "")
        data.setdefault(CONF_COVER_API_TOKEN, "")
        # Entries created during the temporary HTTP-only release preserve that
        # deliberate choice. Older entries safely default to MQTT.
        data.setdefault(
            CONF_COVER_TRANSPORT,
            "http" if config_entry.version >= 5 else "mqtt",
        )
        hass.config_entries.async_update_entry(
            config_entry, data=data, version=6
        )
        _LOGGER.info(
            "Migrated Playnite Connect Companion entry; choose MQTT or HTTP "
            "covers when reconfiguring it."
        )
    return True


async def _create_entry_runtime_data(
    hass: HomeAssistant,
    entry: PlayniteConnectConfigEntry,
    device_id: str,
) -> PlayniteConnectRuntimeData:
    """Build the device and MQTT library owned by this config entry."""
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device_id)},
        name=DEFAULT_NAME,
        manufacturer="Playnite",
        model="Connect library sync",
    )
    library = PlayniteConnectLibrary(hass, device_id)

    def fire_lifecycle_event(event: PlayniteLifecycleEvent) -> None:
        hass.bus.async_fire(
            f"{DOMAIN}.{event.event_type}",
            event.as_event_data(device_id),
        )

    remove_lifecycle_listener = library.async_add_lifecycle_listener(
        fire_lifecycle_event
    )

    def update_device_version() -> None:
        # The retained status message carries Playnite version information.
        if library.playnite_version:
            device_registry.async_update_device(
                device.id, sw_version=library.playnite_version
            )

    remove_device_version_listener = library.async_add_listener(
        update_device_version
    )
    return PlayniteConnectRuntimeData(
        device=device,
        device_id=device_id,
        library=library,
        cache_covers=bool(entry.data.get(CONF_CACHE_COVERS, False)),
        cover_transport=str(entry.data.get(CONF_COVER_TRANSPORT, "mqtt")),
        cover_api_url=str(entry.data.get(CONF_COVER_API_URL, "")),
        cover_api_token=str(entry.data.get(CONF_COVER_API_TOKEN, "")),
        remove_lifecycle_listener=remove_lifecycle_listener,
        remove_device_version_listener=remove_device_version_listener,
    )


async def _cleanup_failed_setup(entry: PlayniteConnectConfigEntry) -> None:
    """Remove callbacks and subscriptions after entry setup fails."""
    runtime_data = entry.runtime_data
    if runtime_data is None:
        return
    runtime_data["remove_lifecycle_listener"]()
    runtime_data["remove_device_version_listener"]()
    await runtime_data["library"].async_stop()
    entry.runtime_data = None


async def async_setup_entry(
    hass: HomeAssistant, entry: PlayniteConnectConfigEntry
) -> bool:
    """Set up one browseable Playnite library from MQTT."""
    if not mqtt.is_connected(hass):
        raise ConfigEntryNotReady(
            "Home Assistant's MQTT broker is not connected"
        )

    device_id = entry.data.get(CONF_DEVICE_ID)
    if not isinstance(device_id, str) or not device_id:
        _LOGGER.error(
            "This Playnite entry needs reconfiguration with an MQTT device ID."
        )
        return False

    if not hass.data.get(f"{DOMAIN}_cover_view_registered"):
        hass.http.register_view(PlayniteCoverView(hass))
        hass.data[f"{DOMAIN}_cover_view_registered"] = True

    runtime_data = await _create_entry_runtime_data(hass, entry, device_id)
    entry.runtime_data = runtime_data
    try:
        await runtime_data["library"].async_start()
    except Exception as err:
        await _cleanup_failed_setup(entry)
        raise ConfigEntryNotReady(
            "Could not subscribe to the Home Assistant MQTT broker"
        ) from err

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await _cleanup_failed_setup(entry)
        raise
    _LOGGER.info(
        "Configured Playnite Connect Companion for device %s", device_id
    )
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: PlayniteConnectConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )
    if unload_ok and entry.runtime_data is not None:
        runtime_data = entry.runtime_data
        runtime_data["remove_lifecycle_listener"]()
        runtime_data["remove_device_version_listener"]()
        await runtime_data["library"].async_stop()
        entry.runtime_data = None
    return unload_ok

"""Set up Playnite Connect Companion."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_CACHE_COVERS,
    CONF_COVER_API_TOKEN,
    CONF_COVER_API_URL,
    CONF_COVER_TRANSPORT,
    CONF_DEVICE_ID,
    DATA_CACHE_COVERS,
    DATA_COVER_API_TOKEN,
    DATA_COVER_API_URL,
    DATA_COVER_TRANSPORT,
    DATA_DEVICE_ID,
    DATA_LIBRARY,
    DEFAULT_NAME,
    DOMAIN,
    PLATFORMS,
)
from .cover import PlayniteCoverView
from .game_tools import (
    async_launch_game,
    async_search_and_play,
    async_search_games,
)
from .connect_library import PlayniteLifecycleEvent, PlayniteConnectLibrary

_LOGGER = logging.getLogger(__name__)

SERVICE_SEARCH_GAMES = "search_games"
SERVICE_LAUNCH_GAME = "launch_game"
SERVICE_SEARCH_AND_PLAY = "search_and_play"
ATTR_QUERY = "query"
ATTR_GAME_NAME = "game_name"
ATTR_GAME_ID = "game_id"
ATTR_DEVICE_ID = "device_id"

_SEARCH_GAMES_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_QUERY): vol.All(cv.string, vol.Length(min=1)),
        vol.Optional(ATTR_DEVICE_ID): cv.string,
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
    }
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register search and launch services independently of a loaded entry."""



    async def handle_search_games(call: ServiceCall) -> ServiceResponse:
        return await async_search_games(
            hass,
            call.data[ATTR_QUERY],
            call.data.get(ATTR_DEVICE_ID),
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
    hass: HomeAssistant, config_entry: ConfigEntry
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
            "Migrated Playnite Connect Companion entry; choose MQTT or HTTP covers "
            "when reconfiguring it."
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one browseable Playnite library from MQTT."""
    device_id = entry.data.get(CONF_DEVICE_ID)
    if not isinstance(device_id, str) or not device_id:
        _LOGGER.error(
            "This Playnite entry needs reconfiguration with an MQTT device ID."
        )
        return False

    if not hass.data.get(f"{DOMAIN}_cover_view_registered"):
        hass.http.register_view(PlayniteCoverView(hass))
        hass.data[f"{DOMAIN}_cover_view_registered"] = True

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
        # The retained status packet carries the real Playnite application
        # version.
        if library.playnite_version:
            device_registry.async_update_device(
                device.id, sw_version=library.playnite_version
            )

    remove_device_version_listener = library.async_add_listener(
        update_device_version
    )
    await library.async_start()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "device": device,
        DATA_DEVICE_ID: device_id,
        DATA_LIBRARY: library,
        DATA_CACHE_COVERS: bool(entry.data.get(CONF_CACHE_COVERS, False)),
        DATA_COVER_TRANSPORT: str(
            entry.data.get(CONF_COVER_TRANSPORT, "mqtt")
        ),
        DATA_COVER_API_URL: str(entry.data.get(CONF_COVER_API_URL, "")),
        DATA_COVER_API_TOKEN: str(entry.data.get(CONF_COVER_API_TOKEN, "")),
        "remove_lifecycle_listener": remove_lifecycle_listener,
        "remove_device_version_listener": remove_device_version_listener,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info("Configured Playnite Connect Companion for device %s", device_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        data["remove_lifecycle_listener"]()
        data["remove_device_version_listener"]()
        await data[DATA_LIBRARY].async_stop()
    return unload_ok

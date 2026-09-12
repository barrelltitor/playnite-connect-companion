"""Native status entities for Playnite Connect."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DATA_LIBRARY, DOMAIN
from .connect_library import PlayniteGame, PlayniteConnectLibrary


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Add status entities to the configured Playnite Connect device."""
    async_add_entities(
        [
            PlaynitePlayingGameSensor(hass, entry),
            PlayniteActiveViewSensor(hass, entry),
        ]
    )


class _PlayniteConnectSensor(SensorEntity):
    """Base class for push-updated entities owned by Playnite Connect."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._library: PlayniteConnectLibrary = hass.data[DOMAIN][
            entry.entry_id
        ][DATA_LIBRARY]

    @property
    def device_info(self):
        device = self.hass.data[DOMAIN][self._entry.entry_id]["device"]
        return {"identifiers": device.identifiers}

    @property
    def available(self) -> bool:
        return self._library.available

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._library.async_add_listener(self.async_write_ha_state)
        )


class PlaynitePlayingGameSensor(_PlayniteConnectSensor):
    """Show Playnite's actual current game, not a requested command."""

    _attr_name = "Playing Game"
    _attr_icon = "mdi:gamepad"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_playing_game"

    @property
    def _active_game(self) -> PlayniteGame | None:
        return next(
            (
                game
                for game in self._library.games
                if game.is_running or game.is_launching
            ),
            None,
        )

    @property
    def native_value(self) -> str:
        game = self._active_game
        return game.display_name if game else "Not running"

    @property
    def extra_state_attributes(self) -> dict[str, object] | None:
        game = self._active_game
        if game is None:
            return None
        return {
            "game_id": game.id,
            "is_running": game.is_running,
            "is_launching": game.is_launching,
            "is_installed": game.is_installed,
            "source": game.source,
            "platforms": list(game.platforms),
        }


class PlayniteActiveViewSensor(_PlayniteConnectSensor):
    """Expose Playnite's public, read-only desktop-view value."""

    _attr_name = "Active View"
    _attr_icon = "mdi:view-carousel"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_active_view"

    @property
    def native_value(self) -> str:
        return self._library.active_desktop_view or "Unknown"

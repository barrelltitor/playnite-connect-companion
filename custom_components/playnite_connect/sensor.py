"""Native status entities for Playnite Connect."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant

from .connect_library import PlayniteGame, PlayniteConnectLibrary
from .const import DOMAIN
from .runtime_data import PlayniteConnectConfigEntry, get_runtime_data

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: PlayniteConnectConfigEntry, async_add_entities
) -> None:
    """Add status entities to the configured Playnite Connect device."""
    async_add_entities(
        [
            PlaynitePlayingGameSensor(hass, entry),
            PlayniteLastPlayedGameSensor(hass, entry),
            PlayniteActiveViewSensor(hass, entry),
        ]
    )


class _PlayniteConnectSensor(SensorEntity):
    """Base class for push-updated entities owned by Playnite Connect."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, hass: HomeAssistant, entry: PlayniteConnectConfigEntry
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._runtime_data = get_runtime_data(entry)
        self._library: PlayniteConnectLibrary = self._runtime_data["library"]

    @property
    def device_info(self):
        device = self._runtime_data["device"]
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

    def __init__(
        self, hass: HomeAssistant, entry: PlayniteConnectConfigEntry
    ) -> None:
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

    def __init__(
        self, hass: HomeAssistant, entry: PlayniteConnectConfigEntry
    ) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_active_view"

    @property
    def native_value(self) -> str:
        return self._library.active_desktop_view or "Unknown"


class PlayniteLastPlayedGameSensor(_PlayniteConnectSensor):
    """Expose the most recent game and its publishing metadata."""

    _attr_name = "Last Played Game"
    _attr_icon = "mdi:history"

    def __init__(
        self, hass: HomeAssistant, entry: PlayniteConnectConfigEntry
    ) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_played_game"

    @property
    def _last_played_game(self) -> PlayniteGame | None:
        return next(
            (
                game
                for game in self._library.recent_games
                if game.last_activity is not None
            ),
            None,
        )

    @property
    def native_value(self) -> str | None:
        game = self._last_played_game
        return game.display_name if game is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, object] | None:
        game = self._last_played_game
        if game is None:
            return None

        attributes: dict[str, object] = {
            "game_id": game.id,
            "last_activity": game.last_activity.isoformat(),
            "playtime": game.playtime,
            "play_count": game.play_count,
            "source": game.source,
            "platforms": list(game.platforms),
            "cover_url": (
                f"/api/playnite_connect/{self._entry.entry_id}/cover/{game.id}"
            ),
        }
        if self._runtime_data.get("cache_covers", False):
            attributes["cover_cache_file_pattern"] = self.hass.config.path(
                f"{DOMAIN}_covers", f"{game.id}.*"
            )
        return attributes

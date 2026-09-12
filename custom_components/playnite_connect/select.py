"""Native Playnite selection control for Home Assistant."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import DATA_LIBRARY, DOMAIN
from .connect_library import PlayniteGame, PlayniteConnectLibrary


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Add the real Playnite selection control."""
    async_add_entities([PlayniteSelectedGameSelect(hass, entry)])


class PlayniteSelectedGameSelect(SelectEntity):
    """Select a game in Playnite through its public SelectGame API."""

    _attr_has_entity_name = True
    _attr_name = "Selected Game"
    _attr_icon = "mdi:selection"
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._library: PlayniteConnectLibrary = hass.data[DOMAIN][
            entry.entry_id
        ][DATA_LIBRARY]
        self._attr_unique_id = f"{entry.entry_id}_selected_game"

    @property
    def device_info(self):
        device = self.hass.data[DOMAIN][self._entry.entry_id]["device"]
        return {"identifiers": device.identifiers}

    @property
    def available(self) -> bool:
        return self._library.available

    @property
    def _options_by_name(self) -> dict[str, PlayniteGame]:
        """Give duplicate game names a stable short-ID suffix."""
        options: dict[str, PlayniteGame] = {}
        for game in self._library.games:
            label = game.display_name
            if label in options:
                label = f"{label} [{game.id[:8]}]"
            options[label] = game
        return options

    @property
    def options(self) -> list[str]:
        return list(self._options_by_name)

    @property
    def current_option(self) -> str | None:
        selected_game_id = self._library.selected_game_id
        return next(
            (
                label
                for label, game in self._options_by_name.items()
                if game.id == selected_game_id
            ),
            None,
        )

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Expose the selected game UUID for fixed HA automations.

        The visible select value is intentionally the human-readable title;
        ``game_id`` is the Playnite UUID accepted by ``launch_game``.
        """
        selected_game_id = self._library.selected_game_id
        if selected_game_id is None:
            return None
        return {"game_id": selected_game_id}
    async def async_select_option(self, option: str) -> None:
        game = self._options_by_name.get(option)
        if game is None:
            raise HomeAssistantError(
                "That Playnite game is no longer available"
            )
        await self._library.async_command("select", game.id)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._library.async_add_listener(self.async_write_ha_state)
        )

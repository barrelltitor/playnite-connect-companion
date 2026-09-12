"""Current-game artwork entities owned by Playnite Connect."""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DATA_LIBRARY, DOMAIN
from .cover import async_get_playnite_image
from .connect_library import PlayniteGame, PlayniteConnectLibrary

_IMAGE_TYPES = ("cover", "background", "icon")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Add dynamic artwork only for the game Playnite is currently running."""
    async_add_entities(
        [
            PlayniteCurrentGameImage(hass, entry, image_type)
            for image_type in _IMAGE_TYPES
        ]
    )


class PlayniteCurrentGameImage(ImageEntity):
    """Fetch an active game's image only when HA asks to display it."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, image_type: str
    ) -> None:
        super().__init__(hass)
        self.hass = hass
        self._entry = entry
        self._image_type = image_type
        self._library: PlayniteConnectLibrary = hass.data[DOMAIN][
            entry.entry_id
        ][DATA_LIBRARY]
        self._attr_name = f"Playing Game {image_type.title()}"
        self._attr_unique_id = f"{entry.entry_id}_playing_game_{image_type}"
        self._image_game_id: str | None = None
        self._image_bytes: bytes | None = None
        self._content_type = "image/jpeg"

    @property
    def device_info(self):
        device = self.hass.data[DOMAIN][self._entry.entry_id]["device"]
        return {"identifiers": device.identifiers}

    @property
    def available(self) -> bool:
        return self._library.available

    @property
    def content_type(self) -> str:
        return self._content_type

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

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._library.async_add_listener(self._handle_library_update)
        )
        self._handle_library_update()

    def _handle_library_update(self) -> None:
        """Invalidate the image when the active game changes."""
        game = self._active_game
        game_id = game.id if game else None
        if game_id == self._image_game_id:
            return
        self._image_game_id = game_id
        self._image_bytes = None
        self._attr_image_last_updated = (
            datetime.now(timezone.utc) if game_id is not None else None
        )
        self.async_write_ha_state()

    async def async_image(self) -> bytes | None:
        """Request the current image only when HA's frontend asks for it."""
        game = self._active_game
        if game is None:
            return None
        if self._image_bytes is None or self._image_game_id != game.id:
            image = await async_get_playnite_image(
                self.hass,
                self.hass.data[DOMAIN][self._entry.entry_id],
                game.id,
                self._image_type,
            )
            self._image_game_id = game.id
            self._image_bytes = image.data
            self._content_type = image.content_type
        return self._image_bytes

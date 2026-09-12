"""A browseable Playnite library media player backed by local MQTT."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, unquote

from homeassistant.components.media_player import (
    BrowseError,
    BrowseMedia,
    MediaClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    SearchMedia,
    SearchMediaQuery,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import DATA_LIBRARY, DEFAULT_NAME, DOMAIN
from .connect_library import PlayniteGame, PlayniteConnectLibrary
from .cover import async_get_playnite_image
from .game_tools import find_games

_FILTER_PREFIX = "playnite-filter:"
_DIRECT_FILTERS = {
    "recent": "Recent Activity",
    "all": "All Games (A-Z)",
    "installed": "Installed",
    "not-installed": "Not Installed",
    "favorites": "Favorites",
}
_GROUP_FILTERS = {
    "genres": "Genres",
    "platforms": "Platforms",
    "categories": "Categories",
    "tags": "Tags",
    "features": "Features",
    "sources": "Sources",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up one library media-player entity for this Playnite device."""
    async_add_entities([PlayniteLibraryPlayer(hass, entry)])


class PlayniteLibraryPlayer(MediaPlayerEntity):
    """Browse and control Playnite games without creating game entities."""

    _attr_has_entity_name = True
    _attr_name = "Library"
    _attr_supported_features = (
        MediaPlayerEntityFeature.BROWSE_MEDIA
        | MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.SEARCH_MEDIA
    )

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the library player."""
        self.hass = hass
        self._entry = entry
        self._library: PlayniteConnectLibrary = hass.data[DOMAIN][
            entry.entry_id
        ][DATA_LIBRARY]
        self._remove_listener = None
        self._attr_unique_id = f"{entry.entry_id}_library"

    @property
    def device_info(self):
        """Return the Playnite device this library belongs to."""
        device = self.hass.data[DOMAIN][self._entry.entry_id]["device"]
        return {"identifiers": device.identifiers}

    @property
    def available(self) -> bool:
        """Return whether the local Playnite plugin is online on MQTT."""
        return self._library.available

    @property
    def state(self) -> MediaPlayerState:
        """Report Playnite's actual running/launching game state."""
        return (
            MediaPlayerState.PLAYING
            if self._active_game is not None
            else MediaPlayerState.IDLE
        )

    @property
    def media_title(self) -> str | None:
        """Return the running game title."""
        return self._active_game.display_name if self._active_game else None

    @property
    def media_content_id(self) -> str | None:
        """Return the active Playnite GUID."""
        return self._active_game.id if self._active_game else None

    @property
    def media_content_type(self) -> MediaType | None:
        """Return the active media type."""
        return MediaType.GAME if self._active_game else None

    @property
    def media_image_url(self) -> str | None:
        """Use HA's authenticated cover route for the active game artwork."""
        game = self._active_game
        if game is None:
            return None
        return f"/api/{DOMAIN}/{self._entry.entry_id}/cover/{game.id}"

    async def async_get_media_image(self) -> tuple[bytes | None, str | None]:
        """Return current artwork through the selected Playnite transport."""
        game = self._active_game
        if game is None:
            return None, None

        # Do not let MediaPlayerEntity fetch our authenticated HA cover route.
        # Its internal HTTP client has no logged-in browser session, while this
        # helper retrieves from the configured MQTT or token-authenticated API.
        try:
            image = await async_get_playnite_image(
                self.hass,
                self.hass.data[DOMAIN][self._entry.entry_id],
                game.id,
                "cover",
            )
        except HomeAssistantError:
            return None, None
        return image.data, image.content_type

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
        """Refresh state whenever an MQTT snapshot or update arrives."""
        self._remove_listener = self._library.async_add_listener(
            self.async_write_ha_state
        )
        self.async_on_remove(self._remove_listener)

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Browse Playnite's recent library and metadata filter folders."""
        await self._library.async_wait_for_library()
        if not media_content_id:
            return self._browse_root()

        filter_data = self._parse_filter_id(media_content_id)
        if filter_data is None:
            raise BrowseError(f"Unknown Playnite library item: {media_content_id}")
        filter_name, filter_value = filter_data
        return self._browse_filter(filter_name, filter_value)

    async def async_search_media(self, query: SearchMediaQuery) -> SearchMedia:
        """Return playable game results for HA's search_media action."""
        await self._library.async_wait_for_library()
        return SearchMedia(
            result=[
                self._browse_game(game)
                for game in find_games(self._library, query.search_query)
            ]
        )

    async def async_play_media(
        self,
        media_type: MediaType | str,
        media_id: str,
        **kwargs: Any,
    ) -> None:
        """Start a game selected from Home Assistant's media browser."""
        if media_type != MediaType.GAME:
            raise HomeAssistantError("Only Playnite games can be played")
        await self._library.async_wait_for_library()
        game = next(
            (item for item in self._library.games if item.id == media_id), None
        )
        if game is None or game.hidden:
            raise HomeAssistantError(
                "The selected game is no longer available"
            )
        await self._library.async_command("start", game.id)

    async def async_media_stop(self) -> None:
        """Stop only when Playnite can safely match its local process."""
        game = self._active_game
        if game is not None:
            await self._library.async_command("stop", game.id)

    def _browse_root(self) -> BrowseMedia:
        """Build the filter menu from metadata already synced from Playnite."""
        children = [
            self._browse_folder(title, self._filter_id(name))
            for name, title in {**_DIRECT_FILTERS, **_GROUP_FILTERS}.items()
        ]
        return BrowseMedia(
            title=DEFAULT_NAME,
            media_class=MediaClass.DIRECTORY,
            media_content_id="",
            media_content_type=MediaType.GAME,
            can_play=False,
            can_expand=True,
            can_search=True,
            children=children,
            children_media_class=MediaClass.DIRECTORY,
        )

    def _browse_filter(
        self, filter_name: str, filter_value: str | None
    ) -> BrowseMedia:
        """Return a direct game page or a metadata-value index page."""
        visible_games = tuple(
            game for game in self._library.games if not game.hidden
        )
        if filter_name == "recent" and filter_value is None:
            games = tuple(
                game for game in self._library.recent_games if not game.hidden
            )
            return self._browse_games_page(
                _DIRECT_FILTERS[filter_name], self._filter_id(filter_name), games
            )
        if filter_name == "all" and filter_value is None:
            return self._browse_games_page(
                _DIRECT_FILTERS[filter_name],
                self._filter_id(filter_name),
                self._sort_games(visible_games),
            )
        if filter_name == "installed" and filter_value is None:
            return self._browse_games_page(
                _DIRECT_FILTERS[filter_name],
                self._filter_id(filter_name),
                self._sort_games(
                    game for game in visible_games if game.is_installed
                ),
            )
        if filter_name == "not-installed" and filter_value is None:
            return self._browse_games_page(
                _DIRECT_FILTERS[filter_name],
                self._filter_id(filter_name),
                self._sort_games(
                    game for game in visible_games if not game.is_installed
                ),
            )
        if filter_name == "favorites" and filter_value is None:
            return self._browse_games_page(
                _DIRECT_FILTERS[filter_name],
                self._filter_id(filter_name),
                self._sort_games(game for game in visible_games if game.favorite),
            )
        if filter_name not in _GROUP_FILTERS:
            raise BrowseError(f"Unknown Playnite filter: {filter_name}")

        values = self._group_values(filter_name, visible_games)
        if filter_value is None:
            return BrowseMedia(
                title=_GROUP_FILTERS[filter_name],
                media_class=MediaClass.DIRECTORY,
                media_content_id=self._filter_id(filter_name),
                media_content_type=MediaType.GAME,
                can_play=False,
                can_expand=True,
                can_search=True,
                children=[
                    self._browse_folder(
                        f"{value} ({self._group_game_count(filter_name, value, visible_games)})",
                        self._filter_id(filter_name, value),
                    )
                    for value in values
                ],
                children_media_class=MediaClass.DIRECTORY,
            )
        if filter_value not in values:
            raise BrowseError(f"Unknown Playnite {filter_name}: {filter_value}")
        return self._browse_games_page(
            filter_value,
            self._filter_id(filter_name, filter_value),
            self._sort_games(
                game
                for game in visible_games
                if self._game_has_group_value(game, filter_name, filter_value)
            ),
        )

    @staticmethod
    def _sort_games(games: Any) -> tuple[PlayniteGame, ...]:
        """Sort non-recent filter results alphabetically by displayed title."""
        return tuple(sorted(games, key=lambda game: game.display_name.casefold()))

    @staticmethod
    def _group_values(
        filter_name: str, games: tuple[PlayniteGame, ...]
    ) -> tuple[str, ...]:
        """Return sorted unique values for a groupable Playnite field."""
        values = {
            value
            for game in games
            for value in PlayniteLibraryPlayer._game_group_values(
                game, filter_name
            )
        }
        return tuple(sorted(values, key=str.casefold))

    @staticmethod
    def _game_group_values(
        game: PlayniteGame, filter_name: str
    ) -> tuple[str, ...]:
        """Return the appropriate metadata field without exposing empty values."""
        if filter_name == "sources":
            return (game.source,) if game.source else ()
        return getattr(game, filter_name)

    @classmethod
    def _game_has_group_value(
        cls, game: PlayniteGame, filter_name: str, value: str
    ) -> bool:
        """Test one game against a metadata folder's stable visible value."""
        return value in cls._game_group_values(game, filter_name)

    @classmethod
    def _group_game_count(
        cls,
        filter_name: str,
        value: str,
        games: tuple[PlayniteGame, ...],
    ) -> int:
        """Return an honest count for a group folder's label."""
        return sum(
            cls._game_has_group_value(game, filter_name, value) for game in games
        )

    @staticmethod
    def _filter_id(filter_name: str, value: str | None = None) -> str:
        """Encode virtual browse IDs without trusting metadata as a path."""
        if value is None:
            return f"{_FILTER_PREFIX}{filter_name}"
        return f"{_FILTER_PREFIX}{filter_name}:{quote(value, safe='')}"

    @staticmethod
    def _parse_filter_id(
        media_content_id: str,
    ) -> tuple[str, str | None] | None:
        """Decode one virtual folder ID into its filter and optional value."""
        if not media_content_id.startswith(_FILTER_PREFIX):
            return None
        raw_filter = media_content_id.removeprefix(_FILTER_PREFIX)
        filter_name, separator, raw_value = raw_filter.partition(":")
        return filter_name, unquote(raw_value) if separator else None

    def _browse_folder(self, title: str, media_content_id: str) -> BrowseMedia:
        """Build one non-playable virtual media-browser folder."""
        return BrowseMedia(
            title=title,
            media_class=MediaClass.DIRECTORY,
            media_content_id=media_content_id,
            media_content_type=MediaType.GAME,
            can_play=False,
            can_expand=True,
        )

    def _browse_games_page(
        self,
        title: str,
        media_content_id: str,
        games: tuple[PlayniteGame, ...],
    ) -> BrowseMedia:
        """Build one filter result page with real game covers on demand."""
        return BrowseMedia(
            title=title,
            media_class=MediaClass.DIRECTORY,
            media_content_id=media_content_id,
            media_content_type=MediaType.GAME,
            can_play=False,
            can_expand=True,
            can_search=True,
            children=[self._browse_game(game) for game in games],
            children_media_class=MediaClass.GAME,
        )

    def _browse_game(self, game: PlayniteGame) -> BrowseMedia:
        """Create one playable result with its protected Playnite cover."""
        return BrowseMedia(
            title=game.display_name,
            media_class=MediaClass.GAME,
            media_content_id=game.id,
            media_content_type=MediaType.GAME,
            can_play=True,
            can_expand=False,
            thumbnail=f"/api/{DOMAIN}/{self._entry.entry_id}/cover/{game.id}",
        )
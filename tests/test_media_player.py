"""Tests for Home Assistant media browsing, search, and playback."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import homeassistant.components.media_player as ha_media_player

# Local HA 2024.10 predates SearchMedia. This shim lets the unit tests run,
# but does not verify compatibility with the integration's minimum version.
if not hasattr(ha_media_player, "SearchMedia"):

    class _BrowseMedia:
        def __init__(self, **values):
            self.__dict__.update(values)

    ha_media_player.BrowseMedia = _BrowseMedia

    class _SearchMedia:
        def __init__(self, *, result):
            self.result = result

    class _SearchMediaQuery:
        pass

    ha_media_player.SearchMedia = _SearchMedia
    ha_media_player.SearchMediaQuery = _SearchMediaQuery
if not hasattr(ha_media_player.MediaPlayerEntityFeature, "SEARCH_MEDIA"):
    ha_media_player.MediaPlayerEntityFeature.SEARCH_MEDIA = 1 << 22

from homeassistant.components.media_player import MediaType
from homeassistant.exceptions import HomeAssistantError

from custom_components.playnite_connect.connect_library import PlayniteGame
from custom_components.playnite_connect.media_player import (
    PlayniteLibraryPlayer,
)


def make_game(
    game_id,
    name,
    *,
    installed=True,
    favorite=False,
    hidden=False,
    last_activity=None
):
    return PlayniteGame(
        id=game_id,
        name=name,
        hidden=hidden,
        favorite=favorite,
        is_installed=installed,
        is_installing=False,
        is_uninstalling=False,
        is_running=False,
        is_launching=False,
        install_size=None,
        last_activity=last_activity,
        source="Steam",
        platforms=("PC",),
        categories=(),
        tags=(),
        features=(),
        genres=(),
    )


class FakeLibrary:
    def __init__(self, games, recent_games=None):
        self.games = tuple(games)
        self.recent_games = tuple(recent_games or games)
        self.commands = []
        self.waited = False
        self.available = False

    async def async_wait_for_library(self):
        self.waited = True

    async def async_command(self, action, game_id):
        self.commands.append((action, game_id))


def make_player(games, recent_games=None):
    library = FakeLibrary(games, recent_games)
    entry = SimpleNamespace(
        entry_id="entry-1",
        runtime_data={
            "library": library,
            "device": SimpleNamespace(
                identifiers={("playnite_connect", "test")}
            ),
        },
    )
    hass = SimpleNamespace(data={})
    player = PlayniteLibraryPlayer(hass, entry)
    return player, library


def test_library_player_availability_tracks_playnite_connection():
    player, library = make_player([])

    assert player.available is False
    library.available = True
    assert player.available is True
    library.available = False
    assert player.available is False


def test_root_browse_shows_recent_folder_with_recent_game_cover():
    recent = make_game("recent-game", "Recently Played")
    older = make_game("older-game", "Older")
    player, _library = make_player([older, recent], [recent, older])

    root = asyncio.run(player.async_browse_media())

    recent_folder = next(
        child for child in root.children if child.title == "Recent Activity"
    )
    assert (
        recent_folder.thumbnail
        == "/api/playnite_connect/entry-1/cover/recent-game"
    )


def test_recent_activity_browse_keeps_playnite_order_and_excludes_hidden():
    newest = make_game("newest", "Zulu")
    older = make_game("older", "Alpha")
    hidden = make_game("hidden", "Hidden", hidden=True)
    player, library = make_player(
        [hidden, older, newest], [newest, hidden, older]
    )

    result = asyncio.run(
        player.async_browse_media(media_content_id="playnite-filter:recent")
    )

    assert library.waited
    assert [game.media_content_id for game in result.children] == [
        "newest",
        "older",
    ]


def test_search_in_recent_activity_preserves_recent_order():
    now = datetime.now(timezone.utc)
    recently_played = make_game("recent", "Spider-Man 2", last_activity=now)
    older = make_game("older", "Spider-Man Remastered", last_activity=None)
    player, _library = make_player(
        [older, recently_played], [recently_played, older]
    )

    result = asyncio.run(
        player.async_search_media(
            SimpleNamespace(
                search_query="spider",
                media_content_id="playnite-filter:recent",
            )
        )
    )

    assert [game.media_content_id for game in result.result] == [
        "recent",
        "older",
    ]


def test_installed_folder_only_contains_installed_visible_games():
    games = [
        make_game("installed", "Installed", installed=True),
        make_game("missing", "Missing", installed=False),
        make_game("hidden", "Hidden", installed=True, hidden=True),
    ]
    player, _library = make_player(games)

    result = asyncio.run(
        player.async_browse_media(media_content_id="playnite-filter:installed")
    )

    assert [game.media_content_id for game in result.children] == ["installed"]


def test_play_media_sends_start_for_exact_game_id():
    player, library = make_player([make_game("exact-uuid", "Game")])

    asyncio.run(player.async_play_media(MediaType.GAME, "exact-uuid"))

    assert library.commands == [("start", "exact-uuid")]


@pytest.mark.parametrize(
    "media_type,media_id",
    [(MediaType.MUSIC, "id"), (MediaType.GAME, "missing")],
)
def test_play_media_rejects_unsupported_or_missing_game(media_type, media_id):
    player, library = make_player([make_game("hidden", "Secret", hidden=True)])

    with pytest.raises(HomeAssistantError):
        asyncio.run(player.async_play_media(media_type, media_id))
    assert library.commands == []

"""Tests for Playnite search, filtering, paging, and launch actions."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.playnite_connect import game_tools
from custom_components.playnite_connect.connect_library import PlayniteGame


def make_game(
    game_id,
    name,
    *,
    hidden=False,
    favorite=False,
    installed=False,
    running=False,
    launching=False,
    source=None,
    platforms=(),
    categories=(),
    tags=(),
    genres=(),
    features=(),
    last_activity=None,
):
    return PlayniteGame(
        id=game_id,
        name=name,
        hidden=hidden,
        favorite=favorite,
        is_installed=installed,
        is_installing=False,
        is_uninstalling=False,
        is_running=running,
        is_launching=launching,
        install_size=None,
        last_activity=last_activity,
        source=source,
        platforms=platforms,
        categories=categories,
        tags=tags,
        features=features,
        genres=genres,
    )


class FakeLibrary:
    def __init__(self, games):
        self.games = games
        self.commands = []
        self.waited = False

    async def async_wait_for_library(self):
        self.waited = True

    async def async_command(self, command, game_id):
        self.commands.append((command, game_id))


def make_hass(library, device_id="living-room-pc"):
    entry = SimpleNamespace(
        runtime_data={"device_id": device_id, "library": library}
    )
    return SimpleNamespace(
        config_entries=SimpleNamespace(async_entries=lambda _domain: [entry])
    )


def test_find_games_matches_all_terms_and_excludes_hidden_games():
    games = [
        make_game("1", "Halo: Combat Evolved"),
        make_game("2", "Halo Infinite"),
        make_game("3", "Halo: Combat Evolved", hidden=True),
    ]

    matches = game_tools.find_games(FakeLibrary(games), " COMBAT halo ")

    assert [game.id for game in matches] == ["1"]


def test_find_games_applies_install_favorite_running_and_metadata_filters():
    games = [
        make_game(
            "match",
            "Portal",
            favorite=True,
            installed=True,
            launching=True,
            source="Steam",
            platforms=("PC",),
            categories=("Puzzle",),
            tags=("Co-op",),
            genres=("Action",),
            features=("Controller",),
        ),
        make_game(
            "wrong-source",
            "Portal",
            favorite=True,
            installed=True,
            source="GOG",
            platforms=("PC",),
            categories=("Puzzle",),
            tags=("Co-op",),
            genres=("Action",),
            features=("Controller",),
        ),
        make_game(
            "not-running",
            "Portal",
            favorite=True,
            installed=True,
            running=False,
            source="Steam",
            platforms=("PC",),
            categories=("Puzzle",),
            tags=("Co-op",),
            genres=("Action",),
            features=("Controller",),
        ),
    ]

    matches = game_tools.find_games(
        FakeLibrary(games),
        "portal",
        installation_state="installed",
        favorite_state="favorite",
        running_state="running",
        source=" STEAM ",
        platform="pc",
        category="puzzle",
        tag="co-op",
        genre="action",
        feature="controller",
    )

    assert [game.id for game in matches] == ["match"]


def test_find_games_sorts_by_recent_activity_then_name():
    now = datetime.now(timezone.utc)
    games = [
        make_game("old", "Older", last_activity=now - timedelta(days=2)),
        make_game("zulu", "Zulu", last_activity=now),
        make_game("alpha", "Alpha", last_activity=now),
        make_game("never", "Never"),
    ]

    matches = game_tools.find_games(
        FakeLibrary(games), "", sort_by="recent_activity"
    )

    assert [game.id for game in matches] == ["alpha", "zulu", "old", "never"]


@pytest.mark.parametrize("limit", [0, -1, 101, True, 1.5])
def test_find_games_rejects_invalid_limits(limit):
    with pytest.raises(ServiceValidationError):
        game_tools.find_games(FakeLibrary([]), "", limit=limit)


def test_async_search_games_returns_total_and_next_page_metadata():
    library = FakeLibrary(
        [
            make_game(str(i), name)
            for i, name in enumerate(("Delta", "Alpha", "Charlie", "Bravo"))
        ]
    )

    result = asyncio.run(
        game_tools.async_search_games(
            make_hass(library), "", limit=2, offset=1, sort_by="name"
        )
    )

    assert library.waited
    assert result["device_id"] == "living-room-pc"
    assert result["total_matches"] == 4
    assert result["returned_count"] == 2
    assert result["next_offset"] == 3
    assert result["truncated"] is True
    assert [game["display_name"] for game in result["games"]] == [
        "Bravo",
        "Charlie",
    ]


def test_launch_game_sends_exact_game_id():
    library = FakeLibrary([make_game("uuid-123", "Portal")])

    result = asyncio.run(
        game_tools.async_launch_game(make_hass(library), "uuid-123")
    )

    assert library.commands == [("start", "uuid-123")]
    assert result["game"]["game_id"] == "uuid-123"


@pytest.mark.parametrize("game_id", ["missing", "hidden"])
def test_launch_game_rejects_missing_or_hidden_games(game_id):
    library = FakeLibrary([make_game("hidden", "Secret", hidden=True)])

    with pytest.raises(ServiceValidationError):
        asyncio.run(game_tools.async_launch_game(make_hass(library), game_id))
    assert library.commands == []


def test_search_and_play_launches_one_exact_match():
    library = FakeLibrary([make_game("uuid-portal", "Portal")])

    result = asyncio.run(
        game_tools.async_search_and_play(make_hass(library), "portal")
    )

    assert result["success"] is True
    assert result["reason"] == "launched"
    assert result["game"]["game_id"] == "uuid-portal"
    assert library.commands == [("start", "uuid-portal")]


def test_search_and_play_returns_ambiguous_matches_without_launching():
    library = FakeLibrary(
        [make_game("one", "Portal"), make_game("two", "Portal 2")]
    )

    result = asyncio.run(
        game_tools.async_search_and_play(make_hass(library), "portal")
    )

    assert result["success"] is False
    assert result["reason"] == "ambiguous"
    assert result["total_matches"] == 2
    assert library.commands == []


def test_search_and_play_returns_no_match_without_launching():
    library = FakeLibrary([make_game("one", "Portal")])

    result = asyncio.run(
        game_tools.async_search_and_play(make_hass(library), "half-life")
    )

    assert result["success"] is False
    assert result["reason"] == "no_matches"
    assert result["games"] == []
    assert library.commands == []

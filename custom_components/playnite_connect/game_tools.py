"""Shared game search/launch helpers for services, LLMs, and media browsing."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import DATA_DEVICE_ID, DATA_LIBRARY, DOMAIN
from .connect_library import PlayniteGame, PlayniteConnectLibrary


def _search_score(game: PlayniteGame, query: str) -> tuple[int, str]:
    """Rank exact and prefix name matches above less specific matches."""
    name = game.display_name.casefold()
    if name == query:
        return (0, name)
    if name.startswith(query):
        return (1, name)
    if query in name:
        return (2, name)
    return (3, name)


def find_games(
    library: PlayniteConnectLibrary, query: str, limit: int = 20
) -> list[PlayniteGame]:
    """Return visible games whose display name contains the supplied words."""
    terms = [term for term in query.casefold().split() if term]
    if not terms:
        return []
    matches = [
        game
        for game in library.games
        if not game.hidden
        and all(term in game.display_name.casefold() for term in terms)
    ]
    return sorted(
        matches, key=lambda game: _search_score(game, " ".join(terms))
    )[:limit]


def game_as_result(game: PlayniteGame) -> dict[str, Any]:
    """Return the stable, minimal game identity an automation or LLM needs."""
    return {
        "game_id": game.id,
        "name": game.name,
        "display_name": game.display_name,
        "is_installed": game.is_installed,
        "is_running": game.is_running,
        "favorite": game.favorite,
        "source": game.source,
        "platforms": list(game.platforms),
    }


def get_library(
    hass: HomeAssistant, device_id: str | None = None
) -> tuple[str, PlayniteConnectLibrary]:
    """Resolve a loaded Playnite Connect device, rejecting ambiguous calls."""
    entries = hass.data.get(DOMAIN, {})
    matches = [
        (entry_data[DATA_DEVICE_ID], entry_data[DATA_LIBRARY])
        for entry_data in entries.values()
        if device_id is None or entry_data[DATA_DEVICE_ID] == device_id
    ]
    if not matches:
        raise ServiceValidationError(
            "No loaded Playnite Connect device matches that device ID"
        )
    if len(matches) > 1:
        raise ServiceValidationError(
            "Multiple Playnite Connect devices are loaded; specify device_id"
        )
    return matches[0]


async def async_search_games(
    hass: HomeAssistant,
    query: str,
    device_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search a library and return exact IDs for a follow-up launch."""
    resolved_device_id, library = get_library(hass, device_id)
    await library.async_wait_for_library()
    games = find_games(library, query, limit)
    return {
        "device_id": resolved_device_id,
        "query": query,
        "games": [game_as_result(game) for game in games],
    }


async def async_launch_game(
    hass: HomeAssistant, game_id: str, device_id: str | None = None
) -> dict[str, Any]:
    """Start an exact search result through Playnite's command protocol."""
    resolved_device_id, library = get_library(hass, device_id)
    await library.async_wait_for_library()
    game = next((item for item in library.games if item.id == game_id), None)
    if game is None or game.hidden:
        raise ServiceValidationError(
            "The selected Playnite game is not available"
        )
    await library.async_command("start", game.id)
    return {
        "device_id": resolved_device_id,
        "game": game_as_result(game),
        "message": (
            "Start requested. Playnite requests installation first when "
            "needed."
        ),
    }


async def async_search_and_play(
    hass: HomeAssistant, game_name: str, device_id: str | None = None
) -> dict[str, Any]:
    """Search by title, launching only a single unambiguous match.

    This deliberately returns no-match, ambiguous, and operational failures
    as data. That makes it usable as one HA automation action with a
    ``response_variable`` instead of forcing users to catch a service error.
    """
    try:
        search = await async_search_games(hass, game_name, device_id)
    except HomeAssistantError as err:
        return {
            "success": False,
            "reason": "error",
            "message": str(err),
            "game_name": game_name,
            "games": [],
        }

    matches = search["games"]
    response: dict[str, Any] = {
        "success": False,
        "device_id": search["device_id"],
        "game_name": game_name,
        "games": matches,
    }
    if not matches:
        response.update(
            reason="no_matches",
            message=f"No visible Playnite games matched {game_name!r}.",
        )
        return response

    if len(matches) != 1:
        response.update(
            reason="ambiguous",
            message=(
                f"{len(matches)} Playnite games matched {game_name!r}; "
                "nothing was launched."
            ),
        )
        return response

    game = matches[0]
    try:
        launch = await async_launch_game(
            hass, game["game_id"], search["device_id"]
        )
    except HomeAssistantError as err:
        response.update(reason="error", message=str(err), game=game)
        return response

    response.update(
        success=True,
        reason="launched",
        message=launch["message"],
        game=launch["game"],
    )
    return response
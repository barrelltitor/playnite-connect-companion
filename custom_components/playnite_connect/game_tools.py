"""Shared game search/launch helpers for services, LLMs, and media browsing."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import DATA_DEVICE_ID, DATA_LIBRARY, DOMAIN
from .connect_library import PlayniteGame, PlayniteConnectLibrary


DEFAULT_SEARCH_LIMIT = 20
DEFAULT_SEARCH_OFFSET = 0
MAX_SEARCH_LIMIT = 100
INSTALLATION_STATES = ("both", "installed", "uninstalled")
FAVORITE_STATES = ("both", "favorite", "not_favorite")
RUNNING_STATES = ("both", "running", "not_running")
SEARCH_SORTS = ("relevance", "name", "recent_activity")


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


def _normalise_filter_value(value: str | None) -> str | None:
    """Return a case-insensitive metadata match value or no filter."""
    if value is None:
        return None
    normalised = value.strip().casefold()
    return normalised or None


def _matches_metadata_filter(
    values: tuple[str, ...], requested: str | None
) -> bool:
    """Return whether a metadata collection contains an exact filter value."""
    return requested is None or any(
        value.casefold() == requested for value in values
    )


def _validate_filter_choice(
    value: str, choices: tuple[str, ...], label: str
) -> None:
    """Reject invalid direct helper calls with the same clear service error."""
    if value not in choices:
        raise ServiceValidationError(
            f"Unsupported {label}: {value!r}. Expected one of: "
            f"{', '.join(choices)}"
        )


def _validate_limit(limit: int | None) -> None:
    """Reject an invalid result limit before searching a library."""
    if limit is not None and (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_SEARCH_LIMIT
    ):
        raise ServiceValidationError(
            f"Search limit must be between 1 and {MAX_SEARCH_LIMIT}"
        )


def _validate_offset(offset: int) -> None:
    """Reject an invalid page offset before searching a library."""
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ServiceValidationError(
            "Search offset must be a whole number greater than or equal to 0"
        )


def _matches_search_filters(
    game: PlayniteGame,
    *,
    installation_state: str,
    favorite_state: str,
    running_state: str,
    source: str | None,
    platform: str | None,
    category: str | None,
    tag: str | None,
    genre: str | None,
    feature: str | None,
) -> bool:
    """Return whether one visible game matches every requested filter."""
    if installation_state == "installed" and not game.is_installed:
        return False
    if installation_state == "uninstalled" and game.is_installed:
        return False
    if favorite_state == "favorite" and not game.favorite:
        return False
    if favorite_state == "not_favorite" and game.favorite:
        return False
    is_running = game.is_running or game.is_launching
    if running_state == "running" and not is_running:
        return False
    if running_state == "not_running" and is_running:
        return False
    if source is not None and (
        game.source is None or game.source.casefold() != source
    ):
        return False
    return (
        _matches_metadata_filter(game.platforms, platform)
        and _matches_metadata_filter(game.categories, category)
        and _matches_metadata_filter(game.tags, tag)
        and _matches_metadata_filter(game.genres, genre)
        and _matches_metadata_filter(game.features, feature)
    )


def _sort_search_results(
    games: list[PlayniteGame], query: str, sort_by: str
) -> list[PlayniteGame]:
    """Sort search results by relevance, name, or recent Playnite activity."""
    if sort_by == "name":
        return sorted(games, key=lambda game: game.display_name.casefold())
    if sort_by == "recent_activity":
        return sorted(
            games,
            key=lambda game: (
                -game.last_activity.timestamp()
                if game.last_activity is not None
                else float("inf"),
                game.display_name.casefold(),
            ),
        )
    return sorted(games, key=lambda game: _search_score(game, query))


def find_games(
    library: PlayniteConnectLibrary,
    query: str,
    limit: int | None = DEFAULT_SEARCH_LIMIT,
    *,
    installation_state: str = "both",
    favorite_state: str = "both",
    running_state: str = "both",
    source: str | None = None,
    platform: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    genre: str | None = None,
    feature: str | None = None,
    sort_by: str = "relevance",
) -> list[PlayniteGame]:
    """Return visible games matching title text and the requested filters."""
    _validate_limit(limit)
    _validate_filter_choice(
        installation_state, INSTALLATION_STATES, "installation_state"
    )
    _validate_filter_choice(favorite_state, FAVORITE_STATES, "favorite_state")
    _validate_filter_choice(running_state, RUNNING_STATES, "running_state")
    _validate_filter_choice(sort_by, SEARCH_SORTS, "sort_by")

    terms = [term for term in query.casefold().split() if term]
    source = _normalise_filter_value(source)
    platform = _normalise_filter_value(platform)
    category = _normalise_filter_value(category)
    tag = _normalise_filter_value(tag)
    genre = _normalise_filter_value(genre)
    feature = _normalise_filter_value(feature)
    matches = [
        game
        for game in library.games
        if not game.hidden
        and (
            not terms
            or all(term in game.display_name.casefold() for term in terms)
        )
        and _matches_search_filters(
            game,
            installation_state=installation_state,
            favorite_state=favorite_state,
            running_state=running_state,
            source=source,
            platform=platform,
            category=category,
            tag=tag,
            genre=genre,
            feature=feature,
        )
    ]
    results = _sort_search_results(matches, " ".join(terms), sort_by)
    return results if limit is None else results[:limit]


def game_as_result(game: PlayniteGame) -> dict[str, Any]:
    """Return the stable, minimal game identity an automation or LLM needs."""
    return {
        "game_id": game.id,
        "name": game.name,
        "display_name": game.display_name,
        "is_installed": game.is_installed,
        "is_installing": game.is_installing,
        "is_uninstalling": game.is_uninstalling,
        "is_running": game.is_running,
        "is_launching": game.is_launching,
        "is_active": game.is_running or game.is_launching,
        "favorite": game.favorite,
        "last_activity": (
            game.last_activity.isoformat()
            if game.last_activity is not None
            else None
        ),
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
    limit: int | None = DEFAULT_SEARCH_LIMIT,
    offset: int = DEFAULT_SEARCH_OFFSET,
    *,
    installation_state: str = "both",
    favorite_state: str = "both",
    running_state: str = "both",
    source: str | None = None,
    platform: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    genre: str | None = None,
    feature: str | None = None,
    sort_by: str = "relevance",
) -> dict[str, Any]:
    """Search a library and make result truncation explicit to callers."""
    _validate_limit(limit)
    _validate_offset(offset)
    resolved_device_id, library = get_library(hass, device_id)
    await library.async_wait_for_library()
    query = query.strip()
    source = _normalise_filter_value(source)
    platform = _normalise_filter_value(platform)
    category = _normalise_filter_value(category)
    tag = _normalise_filter_value(tag)
    genre = _normalise_filter_value(genre)
    feature = _normalise_filter_value(feature)
    matches = find_games(
        library,
        query,
        limit=None,
        installation_state=installation_state,
        favorite_state=favorite_state,
        running_state=running_state,
        source=source,
        platform=platform,
        category=category,
        tag=tag,
        genre=genre,
        feature=feature,
        sort_by=sort_by,
    )
    if limit is None:
        games = matches[offset:]
    else:
        games = matches[offset : offset + limit]
    next_offset = (
        offset + len(games)
        if offset + len(games) < len(matches)
        else None
    )
    return {
        "device_id": resolved_device_id,
        "query": query,
        "filters": {
            "installation_state": installation_state,
            "favorite_state": favorite_state,
            "running_state": running_state,
            "source": source,
            "platform": platform,
            "category": category,
            "tag": tag,
            "genre": genre,
            "feature": feature,
            "sort_by": sort_by,
        },
        "limit": limit,
        "offset": offset,
        "next_offset": next_offset,
        "total_matches": len(matches),
        "returned_count": len(games),
        "truncated": next_offset is not None,
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
    hass: HomeAssistant,
    game_name: str,
    device_id: str | None = None,
    *,
    installation_state: str = "both",
    favorite_state: str = "both",
    running_state: str = "both",
    source: str | None = None,
    platform: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    genre: str | None = None,
    feature: str | None = None,
) -> dict[str, Any]:
    """Search by title, launching only a single unambiguous match.

    This deliberately returns no-match, ambiguous, and operational failures
    as data. That makes it usable as one HA automation action with a
    ``response_variable`` instead of forcing users to catch a service error.
    """
    try:
        search = await async_search_games(
            hass,
            game_name,
            device_id,
            installation_state=installation_state,
            favorite_state=favorite_state,
            running_state=running_state,
            source=source,
            platform=platform,
            category=category,
            tag=tag,
            genre=genre,
            feature=feature,
        )
    except HomeAssistantError as err:
        return {
            "success": False,
            "reason": "error",
            "message": str(err),
            "game_name": game_name,
            "games": [],
        }

    matches = search["games"]
    total_matches = search["total_matches"]
    response: dict[str, Any] = {
        "success": False,
        "device_id": search["device_id"],
        "game_name": game_name,
        "filters": search["filters"],
        "total_matches": total_matches,
        "returned_count": search["returned_count"],
        "truncated": search["truncated"],
        "games": matches,
    }
    if total_matches == 0:
        response.update(
            reason="no_matches",
            message=f"No visible Playnite games matched {game_name!r}.",
        )
        return response

    if total_matches != 1:
        response.update(
            reason="ambiguous",
            message=(
                f"{total_matches} Playnite games matched {game_name!r}; "
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
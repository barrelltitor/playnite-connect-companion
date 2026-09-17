"""Dedicated Playnite Connect tools for Home Assistant LLM APIs."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import llm
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.llm import LLMContext, ToolInput
from homeassistant.util.json import JsonObjectType

from .const import DOMAIN
from .game_tools import (
    DEFAULT_SEARCH_LIMIT,
    DEFAULT_SEARCH_OFFSET,
    FAVORITE_STATES,
    INSTALLATION_STATES,
    MAX_SEARCH_LIMIT,
    RUNNING_STATES,
    SEARCH_SORTS,
    async_launch_game,
    async_search_and_play,
    async_search_games,
)


_SEARCH_FILTER_PARAMETERS = {
    vol.Optional("installation_state", default="both"): vol.In(
        INSTALLATION_STATES
    ),
    vol.Optional("favorite_state", default="both"): vol.In(FAVORITE_STATES),
    vol.Optional("running_state", default="both"): vol.In(RUNNING_STATES),
    vol.Optional("source"): str,
    vol.Optional("platform"): str,
    vol.Optional("category"): str,
    vol.Optional("tag"): str,
    vol.Optional("genre"): str,
    vol.Optional("feature"): str,
}


def _tool_search_filter_kwargs(
    tool_args: dict[str, Any], *, include_sort: bool = True
) -> dict[str, Any]:
    """Map validated LLM tool fields to shared search helper arguments."""
    filters = {
        "installation_state": tool_args.get("installation_state", "both"),
        "favorite_state": tool_args.get("favorite_state", "both"),
        "running_state": tool_args.get("running_state", "both"),
        "source": tool_args.get("source"),
        "platform": tool_args.get("platform"),
        "category": tool_args.get("category"),
        "tag": tool_args.get("tag"),
        "genre": tool_args.get("genre"),
        "feature": tool_args.get("feature"),
    }
    if include_sort:
        filters["sort_by"] = tool_args.get("sort_by", "relevance")
    return filters


class SearchAndPlayPlayniteGameTool(llm.Tool):
    """Safely launch a game from a human title in one LLM tool call."""

    name = "SearchAndPlayPlayniteGame"
    description = (
        "Search the local Playnite library by game title and start it only "
        "when exactly one visible game matches. Returns candidate games when "
        "there are none or multiple matches; never chooses between them. "
        "Use installation_state=installed or uninstalled to narrow duplicate "
        "titles, and use source, platform, genre, category, tag, feature, "
        "favorite_state, or running_state for further exact filters."
    )
    parameters = vol.Schema(
        {
            vol.Required("game_name"): vol.All(str, vol.Length(min=1)),
            vol.Optional("device_id"): str,
            **_SEARCH_FILTER_PARAMETERS,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: ToolInput,
        llm_context: LLMContext,
    ) -> JsonObjectType:
        filters = _tool_search_filter_kwargs(
            tool_input.tool_args, include_sort=False
        )
        return await async_search_and_play(
            hass,
            tool_input.tool_args["game_name"],
            tool_input.tool_args.get("device_id"),
            **filters,
        )


class SearchPlayniteGamesTool(llm.Tool):
    """Find games and return the exact IDs required to launch them."""

    name = "SearchPlayniteGames"
    description = (
        "Search the local Playnite library by game name and return exact "
        "game IDs. Use this to look up games without launching them. Results "
        "are limited to 20 by default and 100 maximum; the response includes "
        "total_matches and truncated, so never describe a truncated result as "
        "the complete library. Use next_offset to request another page. "
        "Query may be blank for a filter-only search. Use "
        "installation_state=installed or uninstalled, plus optional "
        "favorite_state, running_state, source, platform, genre, category, "
        "tag, feature, and sort_by=relevance, name, or recent_activity."
    )
    parameters = vol.Schema(
        {
            vol.Optional("query", default=""): str,
            vol.Optional("device_id"): str,
            vol.Optional("limit", default=DEFAULT_SEARCH_LIMIT): vol.All(
                int, vol.Range(min=1, max=MAX_SEARCH_LIMIT)
            ),
            vol.Optional("offset", default=DEFAULT_SEARCH_OFFSET): vol.All(
                int, vol.Range(min=0)
            ),
            vol.Optional("sort_by", default="relevance"): vol.In(SEARCH_SORTS),
            **_SEARCH_FILTER_PARAMETERS,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: ToolInput,
        llm_context: LLMContext,
    ) -> JsonObjectType:
        return await async_search_games(
            hass,
            tool_input.tool_args.get("query", ""),
            tool_input.tool_args.get("device_id"),
            tool_input.tool_args.get("limit", DEFAULT_SEARCH_LIMIT),
            tool_input.tool_args.get("offset", DEFAULT_SEARCH_OFFSET),
            **_tool_search_filter_kwargs(tool_input.tool_args),
        )


class LaunchPlayniteGameTool(llm.Tool):
    """Launch one exact game result from SearchPlayniteGames."""

    name = "LaunchPlayniteGame"
    description = (
        "Launch exactly one game by its Playnite game_id. The game_id must "
        "come from SearchPlayniteGames; never guess or invent an ID."
    )
    parameters = vol.Schema(
        {
            vol.Required("game_id"): str,
            vol.Optional("device_id"): str,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: ToolInput,
        llm_context: LLMContext,
    ) -> JsonObjectType:
        return await async_launch_game(
            hass,
            tool_input.tool_args["game_id"],
            tool_input.tool_args.get("device_id"),
        )


@callback
def async_get_tools(
    hass: HomeAssistant, llm_context: LLMContext, api_id: str
) -> llm.LLMTools | None:
    """Expose safe Playnite game controls to configured HA LLM APIs."""
    if not hass.data.get(DOMAIN):
        return None
    return llm.LLMTools(
        tools=[
            SearchAndPlayPlayniteGameTool(),
            SearchPlayniteGamesTool(),
            LaunchPlayniteGameTool(),
        ],
        prompt=(
            "For a request to start a Playnite game by name, call "
            "SearchAndPlayPlayniteGame. It launches only an exactly-one-match "
            "result. If it reports ambiguous or no matches, tell the user the "
            "candidate titles and ask for clarification; never choose a "
            "match. Use installation_state=installed when the user asks "
            "for installed games, uninstalled for uninstalled games, and "
            "both otherwise. SearchPlayniteGames is a bounded lookup: it "
            "returns 20 results by default, up to 100 when limit is "
            "specified, plus total_matches and truncated. If truncated is "
            "true, refine the query or filters, request a larger limit, or "
            "use next_offset to request the next page; never claim the "
            "returned subset is the complete library. Use "
            "SearchPlayniteGames only for lookup without launch, and use "
            "LaunchPlayniteGame only with a game_id returned by that search."
        ),
    )
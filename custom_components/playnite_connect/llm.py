"""Dedicated Playnite Connect tools for Home Assistant LLM APIs."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components import llm
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.llm import LLMContext, ToolInput
from homeassistant.util.json import JsonObjectType

from .const import DOMAIN
from .game_tools import (
    async_launch_game,
    async_search_and_play,
    async_search_games,
)


class SearchAndPlayPlayniteGameTool(llm.Tool):
    """Safely launch a game from a human title in one LLM tool call."""

    name = "SearchAndPlayPlayniteGame"
    description = (
        "Search the local Playnite library by game title and start it only "
        "when exactly one visible game matches. Returns candidate games when "
        "there are none or multiple matches; never chooses between them."
    )
    parameters = vol.Schema(
        {
            vol.Required("game_name"): vol.All(str, vol.Length(min=1)),
            vol.Optional("device_id"): str,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: ToolInput,
        llm_context: LLMContext,
    ) -> JsonObjectType:
        return await async_search_and_play(
            hass,
            tool_input.tool_args["game_name"],
            tool_input.tool_args.get("device_id"),
        )


class SearchPlayniteGamesTool(llm.Tool):
    """Find games and return the exact IDs required to launch them."""

    name = "SearchPlayniteGames"
    description = (
        "Search the local Playnite library by game name and return exact "
        "game IDs. Use this to look up games without launching them."
    )
    parameters = vol.Schema(
        {
            vol.Required("query"): vol.All(str, vol.Length(min=1)),
            vol.Optional("device_id"): str,
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
            tool_input.tool_args["query"],
            tool_input.tool_args.get("device_id"),
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
            "candidate titles and ask for clarification; never choose a match. "
            "Use SearchPlayniteGames only for lookup without launch, and use "
            "LaunchPlayniteGame only with a game_id returned by that search."
        ),
    )
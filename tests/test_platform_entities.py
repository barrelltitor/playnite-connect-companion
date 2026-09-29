"""Tests for Playnite status and selection entities."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.playnite_connect import select, sensor
from custom_components.playnite_connect.connect_library import PlayniteGame


def _game(game_id: str, *, running: bool = False, launching: bool = False):
    return PlayniteGame(
        id=game_id,
        name="Same Game" if game_id != "other" else "Other Game",
        hidden=False,
        favorite=False,
        is_installed=True,
        is_installing=False,
        is_uninstalling=False,
        is_running=running,
        is_launching=launching,
        install_size=None,
        last_activity=None,
        source="Steam",
        platforms=(),
        categories=(),
        tags=(),
        features=(),
        genres=(),
    )


class _Library:
    def __init__(self):
        self.available = True
        self.games = (_game("first"), _game("second"))
        self.selected_game_id = "second"
        self.active_desktop_view = "recent_activity"
        self.async_command = AsyncMock()
        self.listeners = []

    def async_add_listener(self, listener):
        self.listeners.append(listener)

        def remove():
            self.listeners.remove(listener)

        return remove


def _entry(library):
    return SimpleNamespace(
        entry_id="entry-id",
        runtime_data={
            "library": library,
            "device": SimpleNamespace(
                identifiers={("playnite_connect", "playnite")}
            ),
        },
    )


def test_select_entity_exposes_uuid_and_disambiguates_duplicate_names():
    library = _Library()
    entry = _entry(library)
    entities = []
    asyncio.run(
        select.async_setup_entry(
            SimpleNamespace(), entry, lambda added: entities.extend(added)
        )
    )
    entity = entities[0]

    assert entity.unique_id == "entry-id_selected_game"
    assert entity.options == ["Same Game", "Same Game [second]"]
    assert entity.current_option == "Same Game [second]"
    assert entity.extra_state_attributes == {"game_id": "second"}
    assert entity.available is True
    assert entity.device_info == {
        "identifiers": {("playnite_connect", "playnite")}
    }

    asyncio.run(entity.async_select_option("Same Game"))
    library.async_command.assert_awaited_once_with("select", "first")
    with pytest.raises(HomeAssistantError):
        asyncio.run(entity.async_select_option("Removed Game"))


def test_select_entity_refreshes_and_exposes_missing_selection():
    library = _Library()
    library.selected_game_id = "not-in-library"
    entity = select.PlayniteSelectedGameSelect(
        SimpleNamespace(), _entry(library)
    )
    assert entity.current_option is None
    assert entity.extra_state_attributes == {"game_id": "not-in-library"}

    removers = []
    entity.async_on_remove = removers.append
    asyncio.run(entity.async_added_to_hass())
    assert library.listeners == [entity.async_write_ha_state]
    removers[0]()
    assert library.listeners == []


def test_sensor_entities_report_game_and_view_state():
    library = _Library()
    library.games = (_game("other", running=True),)
    entry = _entry(library)
    entities = []
    asyncio.run(
        sensor.async_setup_entry(
            SimpleNamespace(), entry, lambda added: entities.extend(added)
        )
    )
    playing, active_view = entities

    assert playing.native_value == "Other Game"
    assert playing.extra_state_attributes == {
        "game_id": "other",
        "is_running": True,
        "is_launching": False,
        "is_installed": True,
        "source": "Steam",
        "platforms": [],
    }
    assert active_view.native_value == "recent_activity"
    assert all(entity.available for entity in entities)

    library.games = (_game("other"),)
    library.active_desktop_view = None
    assert playing.native_value == "Not running"
    assert playing.extra_state_attributes is None
    assert active_view.native_value == "Unknown"

    for entity in entities:
        entity.async_on_remove = lambda callback: None
        asyncio.run(entity.async_added_to_hass())
    assert len(library.listeners) == 2
    library.available = False
    assert not any(entity.available for entity in entities)

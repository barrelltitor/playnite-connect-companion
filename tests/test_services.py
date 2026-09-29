"""Tests for Playnite Connect service schemas and registration."""

import asyncio
from types import SimpleNamespace

import pytest
import voluptuous as vol
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.playnite_connect import async_setup as integration_setup
from custom_components.playnite_connect import async_setup_entry
from custom_components.playnite_connect import (
    ATTR_CATEGORY,
    ATTR_DEVICE_ID,
    ATTR_FEATURE,
    ATTR_FAVORITE_STATE,
    ATTR_GAME_ID,
    ATTR_GAME_NAME,
    ATTR_GENRE,
    ATTR_INSTALLATION_STATE,
    ATTR_LIMIT,
    ATTR_OFFSET,
    ATTR_PLATFORM,
    ATTR_QUERY,
    ATTR_RUNNING_STATE,
    ATTR_SORT_BY,
    ATTR_SOURCE,
    ATTR_TAG,
    DOMAIN,
    SERVICE_LAUNCH_GAME,
    SERVICE_SEARCH_AND_PLAY,
    SERVICE_SEARCH_GAMES,
    _LAUNCH_GAME_SCHEMA,
    _SEARCH_AND_PLAY_SCHEMA,
    _SEARCH_GAMES_SCHEMA,
)

ALL_FILTER_FIELDS = {
    ATTR_INSTALLATION_STATE,
    ATTR_FAVORITE_STATE,
    ATTR_RUNNING_STATE,
    ATTR_SOURCE,
    ATTR_PLATFORM,
    ATTR_CATEGORY,
    ATTR_TAG,
    ATTR_GENRE,
    ATTR_FEATURE,
}


def test_search_games_schema_accepts_every_documented_option():
    data = {
        ATTR_QUERY: "portal",
        ATTR_DEVICE_ID: "gaming-pc",
        ATTR_LIMIT: 30,
        ATTR_OFFSET: 20,
        ATTR_SORT_BY: "recent_activity",
        ATTR_INSTALLATION_STATE: "installed",
        ATTR_FAVORITE_STATE: "favorite",
        ATTR_RUNNING_STATE: "not_running",
        ATTR_SOURCE: "Steam",
        ATTR_PLATFORM: "PC",
        ATTR_CATEGORY: "Puzzle",
        ATTR_TAG: "Co-op",
        ATTR_GENRE: "Action",
        ATTR_FEATURE: "Controller",
    }

    validated = _SEARCH_GAMES_SCHEMA(data)

    assert validated == data
    assert ALL_FILTER_FIELDS <= set(validated)


def test_search_games_schema_defaults_to_unfiltered_search_and_bounded_page():
    validated = _SEARCH_GAMES_SCHEMA({})

    assert validated[ATTR_QUERY] == ""
    assert validated[ATTR_LIMIT] == 20
    assert validated[ATTR_OFFSET] == 0
    assert validated[ATTR_SORT_BY] == "relevance"
    assert validated[ATTR_INSTALLATION_STATE] == "both"
    assert validated[ATTR_FAVORITE_STATE] == "both"
    assert validated[ATTR_RUNNING_STATE] == "both"


@pytest.mark.parametrize(
    "data",
    [
        {ATTR_LIMIT: 101},
        {ATTR_OFFSET: -1},
        {ATTR_SORT_BY: "random"},
        {ATTR_INSTALLATION_STATE: "unknown"},
    ],
)
def test_search_games_schema_rejects_invalid_paging_and_filter_values(data):
    with pytest.raises(vol.Invalid):
        _SEARCH_GAMES_SCHEMA(data)


def test_launch_game_schema_requires_exact_game_id():
    assert _LAUNCH_GAME_SCHEMA({ATTR_GAME_ID: "game-uuid"}) == {
        ATTR_GAME_ID: "game-uuid"
    }
    with pytest.raises(vol.Invalid):
        _LAUNCH_GAME_SCHEMA({})


def test_search_and_play_schema_accepts_supported_filters_but_not_sort():
    data = {
        ATTR_GAME_NAME: "portal",
        ATTR_DEVICE_ID: "gaming-pc",
        ATTR_INSTALLATION_STATE: "uninstalled",
        ATTR_FAVORITE_STATE: "not_favorite",
        ATTR_RUNNING_STATE: "running",
        ATTR_SOURCE: "Steam",
        ATTR_PLATFORM: "PC",
        ATTR_CATEGORY: "Puzzle",
        ATTR_TAG: "Co-op",
        ATTR_GENRE: "Action",
        ATTR_FEATURE: "Controller",
    }

    validated = _SEARCH_AND_PLAY_SCHEMA(data)

    assert validated == data
    assert ALL_FILTER_FIELDS <= set(validated)
    assert ATTR_SORT_BY not in validated


def test_search_and_play_schema_rejects_blank_name():
    with pytest.raises(vol.Invalid):
        _SEARCH_AND_PLAY_SCHEMA({ATTR_GAME_NAME: ""})


def test_setup_registers_three_response_aware_services():
    registrations = {}

    class Services:
        def async_register(self, domain, name, handler, **kwargs):
            registrations[name] = {
                "domain": domain,
                "handler": handler,
                **kwargs,
            }

    hass = SimpleNamespace(services=Services())

    assert asyncio.run(integration_setup(hass, {})) is True
    assert set(registrations) == {
        SERVICE_SEARCH_GAMES,
        SERVICE_LAUNCH_GAME,
        SERVICE_SEARCH_AND_PLAY,
    }
    assert all(item["domain"] == DOMAIN for item in registrations.values())
    assert (
        registrations[SERVICE_SEARCH_GAMES]["supports_response"]
        is SupportsResponse.ONLY
    )
    assert (
        registrations[SERVICE_LAUNCH_GAME]["supports_response"]
        is SupportsResponse.OPTIONAL
    )
    assert (
        registrations[SERVICE_SEARCH_AND_PLAY]["supports_response"]
        is SupportsResponse.OPTIONAL
    )


def test_setup_entry_retries_when_mqtt_broker_is_unavailable(monkeypatch):
    from custom_components.playnite_connect import mqtt as mqtt_module
    from custom_components.playnite_connect.const import CONF_DEVICE_ID

    monkeypatch.setattr(mqtt_module, "is_connected", lambda _hass: False)
    entry = SimpleNamespace(data={CONF_DEVICE_ID: "playnite"})

    with pytest.raises(ConfigEntryNotReady, match="MQTT broker"):
        asyncio.run(async_setup_entry(SimpleNamespace(), entry))


def _setup_entry_harness(monkeypatch, *, start_error=None, forward_error=None):
    from unittest.mock import AsyncMock, Mock

    import custom_components.playnite_connect as integration

    from custom_components.playnite_connect.const import CONF_DEVICE_ID

    library = SimpleNamespace(
        playnite_version=None,
        async_start=AsyncMock(side_effect=start_error),
        async_stop=AsyncMock(),
        async_add_listener=lambda listener: _add_callback(library, listener),
        async_add_lifecycle_listener=lambda listener: _add_callback(
            library, listener
        ),
        callbacks=[],
    )
    device = SimpleNamespace(
        id="registered-device", identifiers={(DOMAIN, "pc")}
    )
    registry = SimpleNamespace(
        async_get_or_create=lambda **_kwargs: device,
        async_update_device=Mock(),
    )
    registered_views = []
    hass = SimpleNamespace(
        data={},
        http=SimpleNamespace(register_view=registered_views.append),
        bus=SimpleNamespace(async_fire=Mock()),
        config_entries=SimpleNamespace(
            async_forward_entry_setups=AsyncMock(side_effect=forward_error),
            async_unload_platforms=AsyncMock(return_value=True),
        ),
    )
    entry = SimpleNamespace(
        entry_id="entry-id",
        data={CONF_DEVICE_ID: "pc"},
        runtime_data=None,
    )
    monkeypatch.setattr(integration.mqtt, "is_connected", lambda _hass: True)
    monkeypatch.setattr(integration.dr, "async_get", lambda _hass: registry)
    monkeypatch.setattr(
        integration,
        "PlayniteConnectLibrary",
        lambda *_args: library,
    )
    monkeypatch.setattr(
        integration,
        "PlayniteCoverView",
        lambda *_args: object(),
    )
    return (
        hass,
        entry,
        library,
        registry,
        registered_views,
        integration.async_unload_entry,
    )


def _add_callback(library, listener):
    library.callbacks.append(listener)
    return lambda: library.callbacks.remove(listener)


def test_setup_entry_initializes_runtime_and_unload_cleans_callbacks(
    monkeypatch,
):
    (
        hass,
        entry,
        library,
        registry,
        registered_views,
        unload_entry,
    ) = _setup_entry_harness(monkeypatch)

    assert asyncio.run(async_setup_entry(hass, entry)) is True
    assert entry.runtime_data["device_id"] == "pc"
    assert entry.runtime_data["library"] is library
    assert len(registered_views) == 1
    assert hass.data["playnite_connect_cover_view_registered"] is True
    assert hass.config_entries.async_forward_entry_setups.await_count == 1

    library.playnite_version = "10.40"
    library.callbacks[1]()
    registry.async_update_device.assert_called_once_with(
        "registered-device", sw_version="10.40"
    )
    lifecycle_event = SimpleNamespace(
        event_type="game_started",
        as_event_data=lambda device_id: {"device_id": device_id},
    )
    library.callbacks[0](lifecycle_event)
    hass.bus.async_fire.assert_called_once_with(
        "playnite_connect.game_started", {"device_id": "pc"}
    )

    assert asyncio.run(unload_entry(hass, entry)) is True
    library.async_stop.assert_awaited_once()
    assert library.callbacks == []
    assert entry.runtime_data is None


def test_setup_entry_cleans_up_when_mqtt_subscription_fails(monkeypatch):
    hass, entry, library, _, _, _ = _setup_entry_harness(
        monkeypatch, start_error=RuntimeError("subscribe")
    )

    with pytest.raises(ConfigEntryNotReady, match="subscribe"):
        asyncio.run(async_setup_entry(hass, entry))

    library.async_stop.assert_awaited_once()
    assert library.callbacks == []
    assert entry.runtime_data is None

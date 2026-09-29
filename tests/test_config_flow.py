"""Tests for Playnite Connect configuration validation and setup flow."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from homeassistant.exceptions import HomeAssistantError

from custom_components.playnite_connect import config_flow
from custom_components.playnite_connect.const import (
    CONF_CACHE_COVERS,
    CONF_COVER_API_TOKEN,
    CONF_COVER_API_URL,
    CONF_COVER_TRANSPORT,
    CONF_DEVICE_ID,
)


def _flow(monkeypatch, *, broker_connected=True):
    flow = config_flow.PlayniteConnectConfigFlow()
    flow.hass = SimpleNamespace()
    monkeypatch.setattr(
        config_flow, "async_test_connection", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        config_flow.mqtt, "is_connected", lambda _hass: broker_connected
    )
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()
    flow.async_create_entry = Mock(return_value={"type": "create_entry"})
    return flow


def _mqtt_input():
    return {
        CONF_DEVICE_ID: "playnite",
        CONF_COVER_TRANSPORT: "mqtt",
        CONF_CACHE_COVERS: False,
    }


def test_initial_setup_requires_connected_mqtt_broker(monkeypatch):
    flow = _flow(monkeypatch, broker_connected=False)

    result = asyncio.run(flow.async_step_user(_mqtt_input()))

    assert result["type"] == "form"
    assert result["errors"] == {"base": "mqtt_not_connected"}
    flow.async_create_entry.assert_not_called()


def test_initial_setup_creates_mqtt_entry_when_broker_connected(monkeypatch):
    flow = _flow(monkeypatch)

    result = asyncio.run(flow.async_step_user(_mqtt_input()))

    assert result == {"type": "create_entry"}
    flow.async_set_unique_id.assert_awaited_once_with("playnite")
    flow._abort_if_unique_id_configured.assert_called_once_with()
    flow.async_create_entry.assert_called_once()
    config_flow.async_test_connection.assert_awaited_once_with(
        flow.hass, "playnite"
    )


def test_http_cover_setup_rejects_invalid_url_and_missing_token(monkeypatch):
    flow = _flow(monkeypatch)
    data = {
        **_mqtt_input(),
        CONF_COVER_TRANSPORT: "http",
        CONF_COVER_API_URL: "not-a-url",
        CONF_COVER_API_TOKEN: " ",
    }

    result = asyncio.run(flow.async_step_user(data))

    assert result["errors"] == {
        CONF_COVER_API_URL: "invalid_cover_api_url",
        CONF_COVER_API_TOKEN: "missing_cover_api_token",
    }
    flow.async_create_entry.assert_not_called()


def test_http_cover_setup_accepts_valid_url_and_token(monkeypatch):
    flow = _flow(monkeypatch)
    data = {
        **_mqtt_input(),
        CONF_COVER_TRANSPORT: "http",
        CONF_COVER_API_URL: "http://playnite.local:8844",
        CONF_COVER_API_TOKEN: "secret-token",
    }

    result = asyncio.run(flow.async_step_user(data))

    assert result == {"type": "create_entry"}
    flow.async_create_entry.assert_called_once()


def test_reconfigure_validates_http_settings(monkeypatch):
    flow = _flow(monkeypatch)
    entry = SimpleNamespace(data=_mqtt_input())
    flow._get_reconfigure_entry = Mock(return_value=entry)
    flow._abort_if_unique_id_mismatch = Mock()
    flow.async_update_reload_and_abort = Mock(return_value={"type": "abort"})
    data = {
        **_mqtt_input(),
        CONF_COVER_TRANSPORT: "http",
        CONF_COVER_API_URL: "https://playnite.local",
        CONF_COVER_API_TOKEN: "secret-token",
    }

    result = asyncio.run(flow.async_step_reconfigure(data))

    assert result == {"type": "abort"}
    flow._abort_if_unique_id_mismatch.assert_called_once_with()
    flow.async_update_reload_and_abort.assert_called_once()


def test_reconfigure_shows_errors_for_invalid_http_settings(monkeypatch):
    flow = _flow(monkeypatch)
    flow._get_reconfigure_entry = Mock(
        return_value=SimpleNamespace(data=_mqtt_input())
    )
    data = {**_mqtt_input(), CONF_COVER_TRANSPORT: "http"}

    result = asyncio.run(flow.async_step_reconfigure(data))

    assert result["errors"] == {
        CONF_COVER_API_URL: "invalid_cover_api_url",
        CONF_COVER_API_TOKEN: "missing_cover_api_token",
    }


def test_cover_settings_require_no_http_credentials_for_mqtt():
    assert (
        config_flow.PlayniteConnectConfigFlow._validate_cover_settings(
            _mqtt_input()
        )
        == {}
    )


def test_config_schema_reuses_submitted_defaults():
    defaults = {
        **_mqtt_input(),
        CONF_COVER_API_URL: "http://playnite.local",
        CONF_COVER_API_TOKEN: "token",
    }
    schema = config_flow.PlayniteConnectConfigFlow._schema(defaults)

    assert schema({**defaults}) == defaults


def test_initial_setup_rejects_offline_playnite_plugin(monkeypatch):
    flow = _flow(monkeypatch)
    connection_check = AsyncMock(
        side_effect=HomeAssistantError(
            "The Playnite Connect plugin is offline"
        )
    )
    monkeypatch.setattr(config_flow, "async_test_connection", connection_check)

    result = asyncio.run(flow.async_step_user(_mqtt_input()))

    assert result["errors"] == {"base": "cannot_connect"}
    flow.async_create_entry.assert_not_called()
    connection_check.assert_awaited_once_with(flow.hass, "playnite")

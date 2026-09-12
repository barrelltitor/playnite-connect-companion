"""Configuration flow for the local Playnite Connect protocol."""

from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant import config_entries

from .const import (
    CONF_CACHE_COVERS,
    CONF_COVER_API_TOKEN,
    CONF_COVER_API_URL,
    CONF_COVER_TRANSPORT,
    CONF_DEVICE_ID,
    DOMAIN,
)

_TRANSPORT_MQTT = "mqtt"
_TRANSPORT_HTTP = "http"
_TRANSPORT_OPTIONS = {
    _TRANSPORT_MQTT: "MQTT (default; no HTTP API required)",
    _TRANSPORT_HTTP: "HTTP Cover API (faster; requires URL and token)",
}


class PlayniteConnectConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure one local Playnite Connect instance."""

    VERSION = 6

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle initial setup."""
        if user_input is not None:
            errors = self._validate_cover_settings(user_input)
            if not errors:
                device_id = user_input[CONF_DEVICE_ID]
                await self.async_set_unique_id(device_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Playnite Connect", data=user_input
                )
            return self.async_show_form(
                step_id="user",
                data_schema=self._schema(user_input),
                errors=errors,
            )
        return self.async_show_form(step_id="user", data_schema=self._schema())

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ):
        """Update direct MQTT and cover transport settings."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            errors = self._validate_cover_settings(user_input)
            if not errors:
                device_id = user_input[CONF_DEVICE_ID]
                await self.async_set_unique_id(device_id)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input, title="Playnite Connect"
                )
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=self._schema(user_input),
                errors=errors,
            )
        return self.async_show_form(
            step_id="reconfigure", data_schema=self._schema(entry.data)
        )

    @staticmethod
    def _validate_cover_settings(user_input: dict[str, Any]) -> dict[str, str]:
        """Require credentials only when the user selected HTTP covers."""
        if user_input.get(CONF_COVER_TRANSPORT) != _TRANSPORT_HTTP:
            return {}
        cover_url = user_input.get(CONF_COVER_API_URL, "")
        token = user_input.get(CONF_COVER_API_TOKEN, "")
        parsed = urlparse(cover_url) if isinstance(cover_url, str) else None
        errors: dict[str, str] = {}
        if (
            not parsed
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
        ):
            errors[CONF_COVER_API_URL] = "invalid_cover_api_url"
        if not isinstance(token, str) or not token.strip():
            errors[CONF_COVER_API_TOKEN] = "missing_cover_api_token"
        return errors

    @staticmethod
    def _schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
        """Return MQTT settings plus a selectable cover delivery method."""
        defaults = defaults or {}
        return vol.Schema(
            {
                vol.Required(
                    CONF_DEVICE_ID,
                    default=defaults.get(CONF_DEVICE_ID, "playnite"),
                ): vol.All(str, vol.Length(min=1)),
                vol.Required(
                    CONF_COVER_TRANSPORT,
                    default=defaults.get(
                        CONF_COVER_TRANSPORT, _TRANSPORT_MQTT
                    ),
                ): vol.In(_TRANSPORT_OPTIONS),
                vol.Optional(
                    CONF_COVER_API_URL,
                    default=defaults.get(CONF_COVER_API_URL, ""),
                ): str,
                vol.Optional(
                    CONF_COVER_API_TOKEN,
                    default=defaults.get(CONF_COVER_API_TOKEN, ""),
                ): str,
                vol.Required(
                    CONF_CACHE_COVERS,
                    default=defaults.get(CONF_CACHE_COVERS, False),
                ): bool,
            }
        )

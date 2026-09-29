"""Tests for secret-safe Playnite Connect diagnostics."""

import asyncio
from types import SimpleNamespace

from custom_components.playnite_connect.const import (
    CONF_CACHE_COVERS,
    CONF_COVER_API_TOKEN,
    CONF_COVER_API_URL,
    CONF_COVER_TRANSPORT,
    CONF_DEVICE_ID,
)
from custom_components.playnite_connect.diagnostics import (
    async_get_config_entry_diagnostics,
)


def test_diagnostics_never_include_cover_url_or_token():
    library = SimpleNamespace(available=True, games=(object(), object()))
    entry = SimpleNamespace(
        data={
            CONF_DEVICE_ID: "living-room-pc",
            CONF_COVER_TRANSPORT: "http",
            CONF_COVER_API_URL: "http://192.168.1.20:8844",
            CONF_COVER_API_TOKEN: "must-not-leak",
            CONF_CACHE_COVERS: True,
        },
        runtime_data={"library": library},
    )

    result = asyncio.run(async_get_config_entry_diagnostics(None, entry))
    serialized = repr(result)

    assert "must-not-leak" not in serialized
    assert "192.168.1.20" not in serialized
    assert result["config"]["cover_api_configured"] is True
    assert result["config"]["cover_api_token_configured"] is True
    assert result["runtime"] == {
        "loaded": True,
        "playnite_available": True,
        "game_count": 2,
    }

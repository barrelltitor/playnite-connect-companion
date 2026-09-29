"""Tests for MQTT-driven Playnite library state and lifecycle events."""

import asyncio
import json

import pytest
from types import SimpleNamespace

from custom_components.playnite_connect import connect_library
from custom_components.playnite_connect.const import PROTOCOL_VERSION


def message(payload):
    return SimpleNamespace(payload=payload)


def game_payload(game_id="game-1", name="Example Game", **values):
    return {
        "id": game_id,
        "name": name,
        "hidden": False,
        "favorite": False,
        "isInstalled": True,
        **values,
    }


def encode(payload):
    return json.dumps(payload)


def test_game_parser_rejects_missing_identity_and_non_dict_payloads():
    assert connect_library.PlayniteGame.from_payload(None) is None
    assert connect_library.PlayniteGame.from_payload({"id": "id"}) is None
    assert connect_library.PlayniteGame.from_payload({"name": "Game"}) is None


def test_game_parser_normalizes_metadata_platforms_and_activity():
    game = connect_library.PlayniteGame.from_payload(
        game_payload(
            platforms=[{"name": "PC"}, {"name": ""}, "invalid"],
            categories=["RPG", None],
            tags=["Co-op"],
            lastActivity="2026-09-20T12:30:00Z",
            installSize=1234,
        )
    )

    assert game is not None
    assert game.display_name == "Example Game (PC)"
    assert game.platforms == ("PC",)
    assert game.categories == ("RPG",)
    assert game.tags == ("Co-op",)
    assert game.last_activity.isoformat() == "2026-09-20T12:30:00+00:00"
    assert game.install_size == 1234


def test_snapshot_activates_only_after_all_chunks_arrive():
    library = connect_library.PlayniteConnectLibrary(
        SimpleNamespace(), "living-room-pc"
    )
    notifications = []
    library.async_add_listener(lambda: notifications.append("changed"))
    revision = "revision-1"

    asyncio.run(
        library._async_handle_manifest(
            message(
                encode(
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "revision": revision,
                        "chunkCount": 2,
                    }
                )
            )
        )
    )
    asyncio.run(
        library._async_handle_chunk(
            message(
                encode(
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "revision": revision,
                        "index": 1,
                        "games": [game_payload("two", "Second")],
                    }
                )
            )
        )
    )

    assert library.games == ()
    assert notifications == []

    asyncio.run(
        library._async_handle_chunk(
            message(
                encode(
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "revision": revision,
                        "index": 0,
                        "games": [game_payload("one", "First")],
                    }
                )
            )
        )
    )

    assert [game.id for game in library.games] == ["one", "two"]
    assert library._library_ready.is_set()
    assert notifications == ["changed"]


def test_snapshot_replaces_old_games_and_ignores_wrong_protocol():
    library = connect_library.PlayniteConnectLibrary(
        SimpleNamespace(), "living-room-pc"
    )
    first_revision = "revision-1"

    async def activate(revision, games):
        await library._async_handle_chunk(
            message(
                encode(
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "revision": revision,
                        "index": 0,
                        "games": games,
                    }
                )
            )
        )
        await library._async_handle_manifest(
            message(
                encode(
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "revision": revision,
                        "chunkCount": 1,
                    }
                )
            )
        )

    asyncio.run(activate(first_revision, [game_payload("old", "Old")]))
    asyncio.run(activate("revision-2", [game_payload("new", "New")]))
    asyncio.run(
        library._async_handle_manifest(
            message(
                encode(
                    {
                        "protocolVersion": PROTOCOL_VERSION + 1,
                        "revision": "bad",
                        "chunkCount": 0,
                    }
                )
            )
        )
    )

    assert [game.id for game in library.games] == ["new"]


def test_update_notifies_library_and_lifecycle_listeners():
    library = connect_library.PlayniteConnectLibrary(
        SimpleNamespace(), "living-room-pc"
    )
    changes = []
    events = []
    library.async_add_listener(lambda: changes.append(True))
    library.async_add_lifecycle_listener(events.append)

    asyncio.run(
        library._async_handle_update(
            message(
                encode(
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "event": "game_started",
                        "game": game_payload("game-id", "Example"),
                    }
                )
            )
        )
    )

    assert [game.id for game in library.games] == ["game-id"]
    assert changes == [True]
    assert len(events) == 1
    assert events[0].event_type == "game_started"
    assert events[0].game.id == "game-id"
    assert (
        events[0].as_event_data("living-room-pc")["device_id"]
        == "living-room-pc"
    )


def test_status_and_connection_messages_update_availability_fields():
    library = connect_library.PlayniteConnectLibrary(
        SimpleNamespace(), "living-room-pc"
    )

    asyncio.run(library._async_handle_connection(message(" ONLINE ")))
    asyncio.run(
        library._async_handle_status(
            message(
                encode(
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "selectedGameId": "selected-id",
                        "activeDesktopView": "recent_activity",
                        "playniteVersion": "10.40",
                    }
                )
            )
        )
    )

    assert library.available is True
    assert library.selected_game_id == "selected-id"
    assert library.active_desktop_view == "recent_activity"
    assert library.playnite_version == "10.40"

    asyncio.run(library._async_handle_connection(message("offline")))
    asyncio.run(library._async_handle_connection(message(b"offline")))
    assert library.available is False
    asyncio.run(library._async_handle_connection(message(b" online ")))
    assert library.available is True
    assert connect_library.PlayniteConnectLibrary._decode(b'{"ok": true}') == {
        "ok": True
    }
    assert connect_library.PlayniteConnectLibrary._decode(b"\xff") is None

    assert library.available is True


def test_startup_failure_unsubscribes_every_completed_subscription(
    monkeypatch,
):
    library = connect_library.PlayniteConnectLibrary(
        SimpleNamespace(), "living-room-pc"
    )
    unsubscribed = []
    subscription_count = 0

    async def subscribe(_hass, _topic, _handler, qos):
        nonlocal subscription_count
        assert qos == 1
        subscription_count += 1
        if subscription_count == 3:
            raise RuntimeError("broker rejected subscription")
        return lambda: unsubscribed.append(subscription_count)

    async def publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr(connect_library, "async_subscribe", subscribe)
    monkeypatch.setattr(connect_library, "async_publish", publish)

    async def start():
        with pytest.raises(RuntimeError, match="broker rejected"):
            await library.async_start()

    asyncio.run(start())

    assert len(unsubscribed) == 2
    assert library._unsubscribers == []


def test_connection_logs_only_on_state_transitions(caplog):
    caplog.set_level("INFO")
    library = connect_library.PlayniteConnectLibrary(
        SimpleNamespace(), "living-room-pc"
    )
    changes = []
    library.async_add_listener(lambda: changes.append(library.available))

    asyncio.run(library._async_handle_connection(message("offline")))
    asyncio.run(library._async_handle_connection(message("offline")))
    asyncio.run(library._async_handle_connection(message("online")))
    asyncio.run(library._async_handle_connection(message("online")))

    assert [record.levelname for record in caplog.records] == ["INFO", "INFO"]
    assert changes == [True]


def test_stop_marks_library_offline_and_notifies_listeners():
    library = connect_library.PlayniteConnectLibrary(
        SimpleNamespace(), "living-room-pc"
    )
    changes = []
    library._online = True
    library.async_add_listener(lambda: changes.append(library.available))

    asyncio.run(library.async_stop())

    assert library.available is False
    assert changes == [False]


def test_config_connection_probe_uses_retained_status_and_unsubscribes(
    monkeypatch,
):
    unsubscribed = []

    async def subscribe(_hass, topic, handler, qos):
        assert topic == "playnite/living-room-pc/connection"
        assert qos == 1
        await handler(message("online"))
        return lambda: unsubscribed.append(True)

    monkeypatch.setattr(connect_library, "async_subscribe", subscribe)
    asyncio.run(
        connect_library.async_test_connection(
            SimpleNamespace(), "living-room-pc"
        )
    )
    assert unsubscribed == [True]


def test_config_connection_probe_accepts_retained_byte_status(monkeypatch):
    async def subscribe(_hass, _topic, handler, qos):
        await handler(message(b"online"))
        return lambda: None

    monkeypatch.setattr(connect_library, "async_subscribe", subscribe)
    asyncio.run(
        connect_library.async_test_connection(SimpleNamespace(), "playnite")
    )


def test_config_connection_probe_rejects_offline_status_and_unsubscribes(
    monkeypatch,
):
    unsubscribed = []

    async def subscribe(_hass, _topic, handler, qos):
        await handler(message("offline"))
        return lambda: unsubscribed.append(True)

    monkeypatch.setattr(connect_library, "async_subscribe", subscribe)
    with pytest.raises(connect_library.HomeAssistantError, match="offline"):
        asyncio.run(
            connect_library.async_test_connection(
                SimpleNamespace(), "living-room-pc"
            )
        )
    assert unsubscribed == [True]


def test_config_connection_probe_times_out_without_retained_status(
    monkeypatch,
):
    async def subscribe(*_args, **_kwargs):
        return lambda: None

    monkeypatch.setattr(connect_library, "async_subscribe", subscribe)
    with pytest.raises(connect_library.HomeAssistantError, match="retained"):
        asyncio.run(
            connect_library.async_test_connection(
                SimpleNamespace(), "living-room-pc", timeout=0.001
            )
        )

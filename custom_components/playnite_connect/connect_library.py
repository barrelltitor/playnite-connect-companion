"""MQTT client for the local Playnite Connect library-sync protocol."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any
from uuid import uuid4

from homeassistant.components.mqtt import (
    ReceiveMessage,
    async_publish,
    async_subscribe,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    LIBRARY_CHUNK_TOPIC,
    LIBRARY_COMMAND_TOPIC,
    LIBRARY_COVER_CHUNK_TOPIC,
    LIBRARY_COVER_REQUEST_TOPIC,
    LIBRARY_MANIFEST_TOPIC,
    LIBRARY_REQUEST_TOPIC,
    LIBRARY_RESPONSE_TOPIC,
    LIBRARY_UPDATE_TOPIC,
    LIBRARY_STATUS_TOPIC,
    MQTT_TOPIC_PREFIX,
    PROTOCOL_VERSION,
)

_MAX_COVER_BYTES = 10 * 1024 * 1024
_MAX_COVER_CHUNKS = 256


@dataclass(frozen=True, slots=True)
class PlayniteGame:
    """A game received from the local Playnite Connect plugin."""

    id: str
    name: str
    hidden: bool
    favorite: bool
    is_installed: bool
    is_installing: bool
    is_uninstalling: bool
    is_running: bool
    is_launching: bool
    install_size: int | None
    last_activity: datetime | None
    source: str | None
    platforms: tuple[str, ...]
    categories: tuple[str, ...]
    tags: tuple[str, ...]
    features: tuple[str, ...]
    genres: tuple[str, ...]

    @property
    def display_name(self) -> str:
        """Return a name that distinguishes releases on multiple platforms."""
        if not self.platforms:
            return self.name
        return f"{self.name} ({', '.join(self.platforms)})"

    @classmethod
    def from_payload(cls, raw: Any) -> PlayniteGame | None:
        """Parse an untrusted MQTT game payload."""
        if not isinstance(raw, dict):
            return None
        game_id = raw.get("id")
        name = raw.get("name")
        if not isinstance(game_id, str) or not game_id:
            return None
        if not isinstance(name, str) or not name:
            return None

        def names(value: Any) -> tuple[str, ...]:
            if not isinstance(value, list):
                return ()
            return tuple(
                item for item in value if isinstance(item, str) and item
            )

        platforms_raw = raw.get("platforms")
        platforms = ()
        if isinstance(platforms_raw, list):
            platforms = tuple(
                item["name"]
                for item in platforms_raw
                if isinstance(item, dict)
                and isinstance(item.get("name"), str)
                and item["name"]
            )

        last_activity_raw = raw.get("lastActivity")
        try:
            last_activity = (
                datetime.fromisoformat(
                    last_activity_raw.replace("Z", "+00:00")
                )
                if isinstance(last_activity_raw, str)
                else None
            )
        except ValueError:
            last_activity = None

        install_size = raw.get("installSize")
        return cls(
            id=game_id,
            name=name,
            hidden=bool(raw.get("hidden")),
            favorite=bool(raw.get("favorite")),
            is_installed=bool(raw.get("isInstalled")),
            is_installing=bool(raw.get("isInstalling")),
            is_uninstalling=bool(raw.get("isUninstalling")),
            is_running=bool(raw.get("isRunning")),
            is_launching=bool(raw.get("isLaunching")),
            install_size=(
                install_size if isinstance(install_size, int) else None
            ),
            last_activity=last_activity,
            source=(
                raw.get("source")
                if isinstance(raw.get("source"), str)
                else None
            ),
            platforms=platforms,
            categories=names(raw.get("categories")),
            tags=names(raw.get("tags")),
            features=names(raw.get("features")),
            genres=names(raw.get("genres")),
        )


@dataclass(frozen=True, slots=True)
class PlayniteCover:
    """One image returned by Playnite in bounded MQTT chunks."""

    data: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class PlayniteLifecycleEvent:
    """A lifecycle transition reported by a real Playnite callback."""

    event_type: str
    game: PlayniteGame

    def as_event_data(self, device_id: str) -> dict[str, Any]:
        """Return data suitable for the Home Assistant event bus."""
        return {
            "device_id": device_id,
            "game_id": self.game.id,
            "name": self.game.name,
            "hidden": self.game.hidden,
            "favorite": self.game.favorite,
            "is_installed": self.game.is_installed,
            "is_installing": self.game.is_installing,
            "is_uninstalling": self.game.is_uninstalling,
            "is_running": self.game.is_running,
            "is_launching": self.game.is_launching,
            "install_size": self.game.install_size,
            "source": self.game.source,
            "platforms": list(self.game.platforms),
            "categories": list(self.game.categories),
            "tags": list(self.game.tags),
            "features": list(self.game.features),
            "genres": list(self.game.genres),
        }


class PlayniteConnectLibrary:
    """Maintain a local, browseable Playnite library from MQTT messages."""

    def __init__(self, hass: HomeAssistant, device_id: str) -> None:
        """Initialize the MQTT protocol client."""
        self._hass = hass
        self._device_id = device_id
        self._base_topic = f"{MQTT_TOPIC_PREFIX}/{device_id}"
        self._games: dict[str, PlayniteGame] = {}
        self._chunks: dict[str, dict[int, tuple[PlayniteGame, ...]]] = {}
        self._manifests: dict[str, dict[str, Any]] = {}
        self._command_waiters: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._cover_waiters: dict[str, asyncio.Future[PlayniteCover]] = {}
        self._cover_chunks: dict[str, dict[int, bytes]] = {}
        self._cover_metadata: dict[str, tuple[int, str, str]] = {}
        self._selected_game_id: str | None = None
        self._active_desktop_view: str | None = None
        self._playnite_version: str | None = None
        self._listeners: list[Callable[[], None]] = []
        self._lifecycle_listeners: list[
            Callable[[PlayniteLifecycleEvent], None]
        ] = []
        self._unsubscribers: list[Callable[[], None]] = []
        self._library_ready = asyncio.Event()
        self._online = False

    @property
    def available(self) -> bool:
        """Return whether the Playnite plugin is connected to MQTT."""
        return self._online

    @property
    def games(self) -> tuple[PlayniteGame, ...]:
        """Return the current library in display order."""
        return tuple(
            sorted(
                self._games.values(),
                key=lambda game: game.display_name.casefold(),
            )
        )

    @property
    def recent_games(self) -> tuple[PlayniteGame, ...]:
        """Match Playnite's Recent activity order: newest activity first."""
        return tuple(
            sorted(
                self._games.values(),
                key=lambda game: (
                    (
                        -game.last_activity.timestamp()
                        if game.last_activity is not None
                        else float("inf")
                    ),
                    game.display_name.casefold(),
                ),
            )
        )

    @property
    def selected_game_id(self) -> str | None:
        """Return the first selected game Playnite reported."""
        return self._selected_game_id

    @property
    def active_desktop_view(self) -> str | None:
        """Return Playnite's read-only desktop view status."""
        return self._active_desktop_view

    @property
    def playnite_version(self) -> str | None:
        """Return the Playnite version from the retained status update."""
        return self._playnite_version

    def async_add_listener(
        self, listener: Callable[[], None]
    ) -> Callable[[], None]:
        """Register for library, availability, and game-state changes."""
        self._listeners.append(listener)

        def remove_listener() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove_listener

    def async_add_lifecycle_listener(
        self, listener: Callable[[PlayniteLifecycleEvent], None]
    ) -> Callable[[], None]:
        """Register for a real Playnite game lifecycle transition."""
        self._lifecycle_listeners.append(listener)

        def remove_listener() -> None:
            if listener in self._lifecycle_listeners:
                self._lifecycle_listeners.remove(listener)

        return remove_listener

    async def async_start(self) -> None:
        """Subscribe before requesting a complete retained library snapshot."""
        self._unsubscribers = [
            await async_subscribe(
                self._hass,
                self._topic(LIBRARY_MANIFEST_TOPIC),
                self._async_handle_manifest,
                qos=1,
            ),
            await async_subscribe(
                self._hass,
                f"{self._topic(LIBRARY_CHUNK_TOPIC)}/#",
                self._async_handle_chunk,
                qos=1,
            ),
            await async_subscribe(
                self._hass,
                self._topic(LIBRARY_UPDATE_TOPIC),
                self._async_handle_update,
                qos=1,
            ),
            await async_subscribe(
                self._hass,
                self._topic(LIBRARY_STATUS_TOPIC),
                self._async_handle_status,
                qos=1,
            ),
            await async_subscribe(
                self._hass,
                self._topic(LIBRARY_RESPONSE_TOPIC),
                self._async_handle_response,
                qos=1,
            ),
            await async_subscribe(
                self._hass,
                f"{self._topic(LIBRARY_COVER_CHUNK_TOPIC)}/#",
                self._async_handle_cover_chunk,
                qos=1,
            ),
            await async_subscribe(
                self._hass,
                self._topic("connection"),
                self._async_handle_connection,
                qos=1,
            ),
        ]
        await self.async_request_snapshot()

    async def async_stop(self) -> None:
        """Remove MQTT subscriptions and fail outstanding requests."""
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        for future in (
            *self._command_waiters.values(),
            *self._cover_waiters.values(),
        ):
            if not future.done():
                future.set_exception(
                    HomeAssistantError("Playnite Connect stopped")
                )
        self._command_waiters.clear()
        self._cover_waiters.clear()
        self._cover_chunks.clear()
        self._cover_metadata.clear()

    async def async_request_snapshot(self) -> None:
        """Ask Playnite to publish chunks followed by a retained manifest."""
        await async_publish(
            self._hass,
            self._topic(LIBRARY_REQUEST_TOPIC),
            json.dumps({"requestId": str(uuid4())}),
            qos=1,
        )

    async def async_wait_for_library(self, timeout: float = 10) -> None:
        """Wait for a complete snapshot, requesting a fresh one."""
        if self._library_ready.is_set():
            return
        await self.async_request_snapshot()
        try:
            await asyncio.wait_for(self._library_ready.wait(), timeout)
        except TimeoutError as err:
            raise HomeAssistantError(
                "Playnite did not return a complete library snapshot"
            ) from err

    async def async_command(self, action: str, game_id: str) -> None:
        """Send a command and wait for Playnite's explicit acknowledgement."""
        request_id = str(uuid4())
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self._command_waiters[request_id] = future
        try:
            await async_publish(
                self._hass,
                self._topic(LIBRARY_COMMAND_TOPIC),
                json.dumps(
                    {
                        "requestId": request_id,
                        "action": action,
                        "gameId": game_id,
                    }
                ),
                qos=1,
            )
            response = await asyncio.wait_for(future, timeout=15)
        except TimeoutError as err:
            raise HomeAssistantError(
                "Playnite did not acknowledge the command"
            ) from err
        finally:
            self._command_waiters.pop(request_id, None)

        if not response.get("success"):
            raise HomeAssistantError(
                str(response.get("message") or "Playnite rejected the command")
            )

    async def async_get_cover(
        self, game_id: str, image_type: str = "cover"
    ) -> PlayniteCover:
        """Request one local image outside the library snapshot."""
        request_id = str(uuid4())
        future: asyncio.Future[PlayniteCover] = (
            asyncio.get_running_loop().create_future()
        )
        self._cover_waiters[request_id] = future
        try:
            await async_publish(
                self._hass,
                self._topic(LIBRARY_COVER_REQUEST_TOPIC),
                json.dumps(
                    {
                        "requestId": request_id,
                        "gameId": game_id,
                        "imageType": image_type,
                    }
                ),
                qos=1,
            )
            return await asyncio.wait_for(future, timeout=30)
        except TimeoutError as err:
            raise HomeAssistantError(
                "Playnite did not return this cover image"
            ) from err
        finally:
            self._cover_waiters.pop(request_id, None)
            self._cover_chunks.pop(request_id, None)
            self._cover_metadata.pop(request_id, None)

    async def _async_handle_connection(self, message: ReceiveMessage) -> None:
        self._online = message.payload.strip().casefold() == "online"
        self._notify_listeners()

    async def _async_handle_manifest(self, message: ReceiveMessage) -> None:
        raw = self._decode(message.payload)
        if raw is None or raw.get("protocolVersion") != PROTOCOL_VERSION:
            return
        revision = raw.get("revision")
        chunk_count = raw.get("chunkCount")
        if not isinstance(revision, str) or not revision:
            return
        if not isinstance(chunk_count, int) or chunk_count < 0:
            return
        self._manifests[revision] = raw
        self._try_activate_snapshot(revision)

    async def _async_handle_chunk(self, message: ReceiveMessage) -> None:
        raw = self._decode(message.payload)
        if raw is None or raw.get("protocolVersion") != PROTOCOL_VERSION:
            return
        revision = raw.get("revision")
        index = raw.get("index")
        games_raw = raw.get("games")
        if not isinstance(revision, str) or not isinstance(index, int):
            return
        if index < 0 or not isinstance(games_raw, list):
            return
        games = tuple(
            game
            for item in games_raw
            if (game := PlayniteGame.from_payload(item))
        )
        self._chunks.setdefault(revision, {})[index] = games
        self._try_activate_snapshot(revision)

    async def _async_handle_update(self, message: ReceiveMessage) -> None:
        raw = self._decode(message.payload)
        if raw is None or raw.get("protocolVersion") != PROTOCOL_VERSION:
            return
        game = PlayniteGame.from_payload(raw.get("game"))
        if game is None:
            return
        self._games[game.id] = game
        self._notify_listeners()
        event_type = raw.get("event")
        if event_type in {
            "game_installed",
            "game_starting",
            "game_started",
            "game_stopped",
            "game_uninstalled",
        }:
            self._notify_lifecycle_listeners(
                PlayniteLifecycleEvent(event_type, game)
            )

    async def _async_handle_status(self, message: ReceiveMessage) -> None:
        """Apply the plugin's retained selected-game and view status."""
        raw = self._decode(message.payload)
        if raw is None or raw.get("protocolVersion") != PROTOCOL_VERSION:
            return
        selected_game_id = raw.get("selectedGameId")
        active_desktop_view = raw.get("activeDesktopView")
        playnite_version = raw.get("playniteVersion")
        self._selected_game_id = (
            selected_game_id
            if isinstance(selected_game_id, str) and selected_game_id
            else None
        )
        self._active_desktop_view = (
            active_desktop_view
            if isinstance(active_desktop_view, str) and active_desktop_view
            else None
        )
        self._playnite_version = (
            playnite_version
            if isinstance(playnite_version, str) and playnite_version
            else None
        )
        self._notify_listeners()

    async def _async_handle_response(self, message: ReceiveMessage) -> None:
        raw = self._decode(message.payload)
        if raw is None:
            return
        request_id = raw.get("requestId")
        if not isinstance(request_id, str):
            return
        future = self._command_waiters.get(request_id)
        if future is not None and not future.done():
            future.set_result(raw)

    async def _async_handle_cover_chunk(self, message: ReceiveMessage) -> None:
        raw = self._decode(message.payload)
        if raw is None or raw.get("protocolVersion") != PROTOCOL_VERSION:
            return
        request_id = raw.get("requestId")
        future = (
            self._cover_waiters.get(request_id)
            if isinstance(request_id, str)
            else None
        )
        if future is None or future.done():
            return

        error = raw.get("error")
        if isinstance(error, str) and error:
            future.set_exception(HomeAssistantError(error))
            return

        index = raw.get("index")
        chunk_count = raw.get("chunkCount")
        content_type = raw.get("contentType")
        image_type = raw.get("imageType", "cover")
        data = raw.get("data")
        if (
            not isinstance(index, int)
            or not isinstance(chunk_count, int)
            or not isinstance(content_type, str)
            or not isinstance(image_type, str)
            or image_type not in {"cover", "background", "icon"}
            or not isinstance(data, str)
            or index < 0
            or chunk_count <= 0
            or chunk_count > _MAX_COVER_CHUNKS
            or index >= chunk_count
            or not content_type.startswith("image/")
        ):
            future.set_exception(
                HomeAssistantError("Playnite sent an invalid cover response")
            )
            return
        try:
            decoded = base64.b64decode(data, validate=True)
        except (ValueError, TypeError):
            future.set_exception(
                HomeAssistantError("Playnite sent invalid cover data")
            )
            return

        metadata = self._cover_metadata.setdefault(
            request_id, (chunk_count, content_type, image_type)
        )
        if metadata != (chunk_count, content_type, image_type):
            future.set_exception(
                HomeAssistantError("Playnite sent inconsistent cover chunks")
            )
            return
        chunks = self._cover_chunks.setdefault(request_id, {})
        chunks[index] = decoded
        if sum(len(chunk) for chunk in chunks.values()) > _MAX_COVER_BYTES:
            future.set_exception(
                HomeAssistantError(
                    "Playnite cover exceeds the 10 MB transfer limit"
                )
            )
            return
        if len(chunks) == chunk_count:
            future.set_result(
                PlayniteCover(
                    b"".join(chunks[i] for i in range(chunk_count)),
                    content_type,
                )
            )

    def _try_activate_snapshot(self, revision: str) -> None:
        manifest = self._manifests.get(revision)
        if manifest is None:
            return
        chunk_count = manifest["chunkCount"]
        chunks = self._chunks.get(revision, {})
        if any(index not in chunks for index in range(chunk_count)):
            return

        games: dict[str, PlayniteGame] = {}
        for index in range(chunk_count):
            for game in chunks[index]:
                games[game.id] = game
        self._games = games
        self._library_ready.set()
        self._prune_snapshots(revision)
        self._notify_listeners()

    def _prune_snapshots(self, current_revision: str) -> None:
        """Keep the active snapshot and a few in-flight messages."""
        revisions = list(self._chunks)
        for revision in revisions[:-3]:
            if revision != current_revision:
                self._chunks.pop(revision, None)
                self._manifests.pop(revision, None)

    @staticmethod
    def _decode(payload: str) -> dict[str, Any] | None:
        try:
            raw = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            return None
        return raw if isinstance(raw, dict) else None

    def _topic(self, subtopic: str) -> str:
        return f"{self._base_topic}/{subtopic}"

    def _notify_listeners(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    def _notify_lifecycle_listeners(
        self, event: PlayniteLifecycleEvent
    ) -> None:
        for listener in tuple(self._lifecycle_listeners):
            listener(event)

"""Authenticated HA cover endpoint for Playnite Connect."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from aiohttp import ClientTimeout, web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DATA_CACHE_COVERS,
    DATA_COVER_API_TOKEN,
    DATA_COVER_API_URL,
    DATA_COVER_TRANSPORT,
    DATA_LIBRARY,
    DOMAIN,
)

_CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
}
_TRANSPORT_MQTT = "mqtt"
_TRANSPORT_HTTP = "http"
_BROWSER_CACHE_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class CachedCover:
    """A cover held only while HA proxies or writes it."""

    data: bytes
    content_type: str


async def async_get_playnite_image(
    hass: HomeAssistant,
    entry_data: dict,
    game_id: str,
    image_type: str,
) -> CachedCover:
    """Fetch one requested Playnite image through the configured transport."""
    if image_type not in {"cover", "background", "icon"}:
        raise HomeAssistantError("Unsupported Playnite image type")

    transport = entry_data.get(DATA_COVER_TRANSPORT, _TRANSPORT_MQTT)
    if transport == _TRANSPORT_MQTT:
        return_cover = await entry_data[DATA_LIBRARY].async_get_cover(
            game_id, image_type
        )
        return CachedCover(return_cover.data, return_cover.content_type)

    if transport != _TRANSPORT_HTTP:
        raise HomeAssistantError("Choose MQTT or HTTP for Playnite images")
    base_url = entry_data[DATA_COVER_API_URL]
    token = entry_data[DATA_COVER_API_TOKEN]
    if not base_url or not token:
        raise HomeAssistantError(
            "Configure the Playnite Connect Cover API URL and token"
        )
    path = (
        f"/api/covers/{game_id}"
        if image_type == "cover"
        else f"/api/images/{image_type}/{game_id}"
    )
    session = async_get_clientsession(hass)
    try:
        async with session.get(
            f"{base_url.rstrip('/')}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=ClientTimeout(total=45),
        ) as upstream:
            if upstream.status == 401:
                raise HomeAssistantError(
                    "Playnite Connect rejected the Cover API token"
                )
            if upstream.status == 404:
                raise HomeAssistantError(
                    "Playnite has no accessible "
                    f"{image_type} image for this game"
                )
            if upstream.status != 200:
                raise HomeAssistantError(
                    "Playnite Connect returned "
                    f"HTTP {upstream.status} for this image"
                )
            if not upstream.content_type.startswith("image/"):
                raise HomeAssistantError(
                    "Playnite Connect returned a non-image response"
                )
            return CachedCover(await upstream.read(), upstream.content_type)
    except HomeAssistantError:
        raise
    except Exception as err:
        raise HomeAssistantError("Could not fetch the Playnite image") from err


class PlayniteCoverView(HomeAssistantView):
    """Serve covers through HA without exposing the Playnite HTTP token."""

    url = "/api/playnite_connect/{entry_id}/cover/{game_id}"
    name = "api:playnite_connect:cover"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(
        self, request: web.Request, entry_id: str, game_id: str
    ) -> web.StreamResponse:
        entry_data = self.hass.data.get(DOMAIN, {}).get(entry_id)
        if entry_data is None:
            raise web.HTTPNotFound()
        try:
            UUID(game_id)
        except ValueError as err:
            raise web.HTTPNotFound() from err

        cache_covers = entry_data[DATA_CACHE_COVERS]
        cache_dir = self.hass.config.path(f"{DOMAIN}_covers")
        if cache_covers:
            cached_cover = await self.hass.async_add_executor_job(
                _read_cached_cover, cache_dir, game_id
            )
            if cached_cover is not None:
                return _browser_cached_cover_response(request, cached_cover)

        transport = entry_data.get(DATA_COVER_TRANSPORT, _TRANSPORT_MQTT)
        if transport == _TRANSPORT_MQTT:
            return await self._get_mqtt_cover(
                request, entry_data, cache_covers, cache_dir, game_id
            )
        if transport == _TRANSPORT_HTTP:
            return await self._get_http_cover(
                request, entry_data, cache_covers, cache_dir, game_id
            )
        raise web.HTTPServiceUnavailable(
            text="Choose MQTT or HTTP for Playnite covers."
        )

    async def _get_mqtt_cover(
        self,
        request: web.Request,
        entry_data: dict,
        cache_covers: bool,
        cache_dir: str,
        game_id: str,
    ) -> web.Response:
        """Retrieve a requested image over bounded MQTT chunks."""
        try:
            cover = await entry_data[DATA_LIBRARY].async_get_cover(game_id)
        except HomeAssistantError as err:
            raise web.HTTPBadGateway(text=str(err)) from err

        cached_cover = CachedCover(cover.data, cover.content_type)
        if cache_covers:
            await self.hass.async_add_executor_job(
                _write_cached_cover, cache_dir, game_id, cached_cover
            )
        return _browser_cached_cover_response(request, cached_cover)

    async def _get_http_cover(
        self,
        request: web.Request,
        entry_data: dict,
        cache_covers: bool,
        cache_dir: str,
        game_id: str,
    ) -> web.StreamResponse:
        """Stream an authenticated cover from Playnite's optional local API."""
        base_url = entry_data[DATA_COVER_API_URL]
        token = entry_data[DATA_COVER_API_TOKEN]
        if not base_url or not token:
            raise web.HTTPServiceUnavailable(
                text="Configure the Playnite Connect Cover API URL and token."
            )
        cover_url = f"{base_url.rstrip('/')}/api/covers/{game_id}"
        session = async_get_clientsession(self.hass)
        headers = {"Authorization": f"Bearer {token}"}
        timeout = ClientTimeout(total=45)

        async with session.get(
            cover_url, headers=headers, timeout=timeout
        ) as upstream:
            if upstream.status == 401:
                raise web.HTTPUnauthorized(
                    text="Playnite Connect rejected the Cover API token."
                )
            if upstream.status == 404:
                raise web.HTTPNotFound(
                    text="Playnite has no accessible cover for this game."
                )
            if upstream.status != 200:
                raise web.HTTPBadGateway(
                    text=f"Playnite Connect returned HTTP {upstream.status}."
                )
            content_type = upstream.content_type
            if not content_type.startswith("image/"):
                raise web.HTTPBadGateway(
                    text=(
                        "Playnite Connect returned a non-image cover response."
                    )
                )

            if cache_covers:
                cover = CachedCover(await upstream.read(), content_type)
                await self.hass.async_add_executor_job(
                    _write_cached_cover, cache_dir, game_id, cover
                )
                return _browser_cached_cover_response(request, cover)

            # With caching disabled, relay the image in chunks and discard it.
            # HA's authenticated endpoint is the only browser-visible URL.
            response = web.StreamResponse(
                content_type=content_type,
                headers={"Cache-Control": _browser_cache_control()},
            )
            await response.prepare(request)
            async for chunk in upstream.content.iter_chunked(64 * 1024):
                await response.write(chunk)
            await response.write_eof()
            return response


def _browser_cached_cover_response(
    request: web.Request, cover: CachedCover
) -> web.Response:
    """Serve a cover with private browser caching and disk-cache revalidation."""
    etag = f'"{sha256(cover.data).hexdigest()}"'
    headers = {"Cache-Control": _browser_cache_control(), "ETag": etag}
    if request.headers.get("If-None-Match") in {etag, "*"}:
        return web.Response(status=304, headers=headers)
    return web.Response(
        body=cover.data,
        content_type=cover.content_type,
        headers=headers,
    )


def _browser_cache_control() -> str:
    """Keep authenticated covers in this browser, never in a shared proxy."""
    return f"private, max-age={_BROWSER_CACHE_SECONDS}"

def _read_cached_cover(cache_dir: str, game_id: str) -> CachedCover | None:
    """Read a previously fetched cover from HA's configuration directory."""
    root = Path(cache_dir)
    for extension, content_type in _CONTENT_TYPES.items():
        path = root / f"{game_id}.{extension}"
        if path.is_file():
            return CachedCover(path.read_bytes(), content_type)
    return None


def _write_cached_cover(
    cache_dir: str, game_id: str, cover: CachedCover
) -> None:
    """Persist one cover only when the user opted into HA disk caching."""
    extension = next(
        (
            suffix
            for suffix, content_type in _CONTENT_TYPES.items()
            if content_type == cover.content_type
        ),
        "jpg",
    )
    root = Path(cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{game_id}.{extension}").write_bytes(cover.data)

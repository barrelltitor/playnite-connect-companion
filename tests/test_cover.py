"""Tests for Playnite Connect cover caching and HTTP streaming."""

import asyncio
from types import SimpleNamespace

from aiohttp import web
import pytest

from custom_components.playnite_connect import cover


@pytest.mark.parametrize(
    ("content_type", "extension"),
    [
        ("image/jpeg", "jpg"),
        ("image/png", "png"),
        ("image/webp", "webp"),
        ("image/gif", "gif"),
        ("image/bmp", "bmp"),
    ],
)
def test_cached_cover_round_trip(tmp_path, content_type, extension):
    cached = cover.CachedCover(b"cover", content_type)

    cover._write_cached_cover(str(tmp_path), "game", cached)

    assert (tmp_path / f"game.{extension}").read_bytes() == b"cover"
    assert cover._read_cached_cover(str(tmp_path), "game") == cached


def test_cached_http_response_sets_private_cache_headers():
    cached = cover.CachedCover(b"cover", "image/jpeg")
    response = cover._browser_cached_cover_response(
        SimpleNamespace(headers={}), cached
    )

    assert response.status == 200
    assert response.body == cached.data
    assert response.content_type == cached.content_type
    assert response.headers["Cache-Control"].startswith("private, max-age=")
    assert response.headers["ETag"]


@pytest.mark.parametrize("wildcard", [False, True])
def test_cached_http_response_revalidates_etag(wildcard):
    cached = cover.CachedCover(b"cover", "image/jpeg")
    first = cover._browser_cached_cover_response(
        SimpleNamespace(headers={}), cached
    )
    etag = "*" if wildcard else first.headers["ETag"]
    response = cover._browser_cached_cover_response(
        SimpleNamespace(headers={"If-None-Match": etag}), cached
    )

    assert response.status == 304
    assert response.body is None
    assert response.headers["ETag"] == first.headers["ETag"]


class FakeUpstream:
    status = 200
    content_type = "image/jpeg"

    def __init__(self):
        self.content = SimpleNamespace(iter_chunked=self.iter_chunked)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def iter_chunked(self, _size):
        yield b"cover"


class FakeSession:
    def get(self, *_args, **_kwargs):
        return FakeUpstream()


def test_mqtt_image_uses_the_configured_library():
    class FakeLibrary:
        async def async_get_cover(self, game_id, image_type):
            return cover.CachedCover(
                f"{game_id}:{image_type}".encode(), "image/jpeg"
            )

    result = asyncio.run(
        cover.async_get_playnite_image(
            SimpleNamespace(),
            {"library": FakeLibrary()},
            "game-id",
            "cover",
        )
    )

    assert result == cover.CachedCover(b"game-id:cover", "image/jpeg")


def test_http_cover_stream_without_disk_cache_sets_content_type(
    monkeypatch, tmp_path
):
    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        cover, "async_get_clientsession", lambda _hass: FakeSession()
    )
    monkeypatch.setattr(web.StreamResponse, "prepare", noop)
    monkeypatch.setattr(web.StreamResponse, "write", noop)
    monkeypatch.setattr(web.StreamResponse, "write_eof", noop)
    view = cover.PlayniteCoverView(SimpleNamespace())
    entry_data = {
        "cover_api_url": "http://playnite.local:8000",
        "cover_api_token": "test-token",
    }

    response = asyncio.run(
        view._get_http_cover(
            SimpleNamespace(), entry_data, False, str(tmp_path), "game"
        )
    )

    assert isinstance(response, web.StreamResponse)
    assert response.headers["Content-Type"] == "image/jpeg"
    assert response.headers["Cache-Control"].startswith("private, max-age=")

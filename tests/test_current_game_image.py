"""Regression tests for active-game artwork state and request races."""

import asyncio
from types import SimpleNamespace

from custom_components.playnite_connect.connect_library import PlayniteGame
from custom_components.playnite_connect.image import PlayniteCurrentGameImage


def game(game_id):
    return PlayniteGame(
        id=game_id,
        name=game_id.title(),
        hidden=False,
        favorite=False,
        is_installed=True,
        is_installing=False,
        is_uninstalling=False,
        is_running=True,
        is_launching=False,
        install_size=None,
        last_activity=None,
        source="Steam",
        platforms=(),
        categories=(),
        tags=(),
        features=(),
        genres=(),
    )


class FakeLibrary:
    def __init__(self, games):
        self.games = tuple(games)
        self.available = True
        self.listeners = []

    def async_add_listener(self, listener):
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener)


def make_image(library, monkeypatch):
    monkeypatch.setattr(
        "homeassistant.components.image.ImageEntity.__init__",
        lambda self, hass: None,
    )
    entry = SimpleNamespace(
        entry_id="entry-1",
        runtime_data={
            "library": library,
            "device": SimpleNamespace(
                identifiers={("playnite_connect", "test")}
            ),
        },
    )
    hass = SimpleNamespace(data={})
    return PlayniteCurrentGameImage(hass, entry, "cover")


def test_image_state_refreshes_when_availability_changes_without_game_change(
    monkeypatch,
):
    library = FakeLibrary([game("same-game")])
    image = make_image(library, monkeypatch)
    image.async_write_ha_state = lambda: None
    writes = []
    image.async_write_ha_state = lambda: writes.append(True)

    image._handle_library_update()
    library.available = False
    image._handle_library_update()

    assert image.available is False
    assert writes == [True, True]


def test_stale_in_flight_image_does_not_replace_new_active_game(monkeypatch):
    library = FakeLibrary([game("first-game")])
    image = make_image(library, monkeypatch)
    image.async_write_ha_state = lambda: None
    started = asyncio.Event()
    finish_request = asyncio.Event()

    async def delayed_image(*_args):
        started.set()
        await finish_request.wait()
        return SimpleNamespace(data=b"stale", content_type="image/jpeg")

    monkeypatch.setattr(
        "custom_components.playnite_connect.image.async_get_playnite_image",
        delayed_image,
    )

    async def exercise_race():
        request = asyncio.create_task(image.async_image())
        await started.wait()
        library.games = (game("second-game"),)
        image._handle_library_update()
        finish_request.set()
        return await request

    result = asyncio.run(exercise_race())

    assert result is None
    assert image._image_game_id == "second-game"
    assert image._image_bytes is None

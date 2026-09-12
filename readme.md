# Playnite Connect Companion for Home Assistant

Playnite Connect Companion is the Home Assistant custom integration for the
[Playnite Connect](https://github.com/barrelltitor/playnite-connect) extension.
It connects a Playnite library to Home Assistant through MQTT.

## Features

- Browse the Playnite library from one `media_player` entity.
- Search, launch, stop, install, uninstall, and restart games.
- Show the current game, selected game, active view, and game artwork.
- Publish Playnite game lifecycle events for Home Assistant automations.
- Let Assist, automations, dashboards, and Home Assistant LLM tools search for
  and launch games.

## Installation

1. Install the [Playnite Connect](https://github.com/barrelltitor/playnite-connect)
   extension in Playnite and configure its MQTT broker settings and Device ID.
   The default Device ID is `playnite`.
2. Copy this repository's `custom_components/playnite_connect` directory into
   your Home Assistant configuration directory.
3. Restart Home Assistant.
4. In **Settings → Devices & services**, add **Playnite Connect Companion**
   and enter the extension's Device ID.
5. Open the Playnite Connect media player and choose **Browse Media**.

The integration requests a library snapshot when it starts and uses the
extension's retained snapshot when available.

## Game artwork

Artwork can be delivered in either of two ways:

- **MQTT** (default): images are transferred in bounded MQTT chunks only when
  Home Assistant requests them.
- **HTTP Cover API**: enable **Cover API** and network access in the Playnite
  Connect extension settings, then enter its URL and token in the integration
  options.

Artwork caching is optional. When enabled, Home Assistant stores cached covers
under `playnite_connect_covers` in its configuration directory. A large
library can use significant disk space.

## Events

The integration emits these Home Assistant events when Playnite reports a game
lifecycle change:

- `playnite_connect.game_installed`
- `playnite_connect.game_starting`
- `playnite_connect.game_started`
- `playnite_connect.game_stopped`
- `playnite_connect.game_uninstalled`

Each event includes the device ID, game ID, game name, installation and
running state, and the game's Playnite metadata.

## Search and launch

The media player supports the standard `search_media` and `play_media` calls.
The integration also provides these services:

- `playnite_connect.search_games` — finds games and returns their exact
  Playnite game IDs.
- `playnite_connect.launch_game` — launches a game by exact `game_id`.
- `playnite_connect.search_and_play` — searches by name and launches a game
  only when there is exactly one match.

`search_and_play` is useful in automations and Assist sentence-trigger
automations: it avoids launching a game when the requested title is ambiguous.

## Data shown for each game

The library includes the Playnite game ID, name, installation and running
state, favourite and hidden flags, install size, playtime, activity and
library timestamps, version, source, platforms, categories, tags, features,
and genres. Hidden games are not shown in Browse Media.

## Stop behaviour

Playnite does not expose a generic stop-game method for extensions. The
extension only stops processes whose executable path is inside the selected
game's configured installation directory. If it cannot identify such a
process, it returns a failure instead of stopping an unrelated process.
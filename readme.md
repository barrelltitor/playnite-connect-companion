# Playnite Connect for Home Assistant

A direct Home Assistant integration for the companion **Playnite Connect**
plugin. It deliberately does **not** depend on Playnite Web, Docker, a GraphQL
server, or a database.

It exposes one Playnite library `media_player`. Browse Media lists the games in
your real local Playnite library; choosing a game starts it. The Stop control
asks the plugin to stop the active game. Starting an uninstalled game requests
installation, and the protocol also supports explicit install, uninstall, and
restart commands for a future UI/service.

## How it works

The custom Playnite Connect publishes a compact, chunked library snapshot
to the MQTT broker and sends small live updates when a game changes. Home
Assistant keeps the received snapshot in memory for its media browser. It does
not store the library in Home Assistant's recorder database or write game
metadata to disk.

```text
Playnite Connect  --MQTT-->  Home Assistant MQTT integration
       library snapshot                Browse Media / controls
       true lifecycle events            start / stop commands
```

Topics are scoped to the plugin Device ID:

```text
playnite/<device-id>/library/manifest
playnite/<device-id>/library/chunk/<n>
playnite/<device-id>/library/update
playnite/<device-id>/library/request
playnite/<device-id>/library/command
playnite/<device-id>/library/response
playnite/<device-id>/library/cover/request
playnite/<device-id>/library/cover/chunk/<request-id>/<index>
```

The plugin publishes 25 game records per chunk, then publishes the manifest
last. This works with large libraries without one giant MQTT payload. Covers,
background images, and install paths are never sent.


## Actual Playnite covers (optional)

HA lets you choose the delivery method when adding or reconfiguring **Playnite
Connect**:

- **MQTT (default):** Playnite sends the requested local cover as bounded,
  non-retained MQTT chunks. No HTTP server, LAN rule, or token is needed.
- **HTTP Cover API:** optionally faster. In Playnite Connect settings, enable
  **Cover API**, enter this HA host's IPv4 address, and choose **Enable network
  access for Home Assistant**. Then paste into HA:
  - Cover API URL: `http://<playnite-pc-ip>:19829`
  - Cover API token: the value copied from Playnite Connect.

The HTTP API is disabled by default. HA sends its token only to the Playnite
PC; HA's authenticated `/api/.../cover` route is the only URL the browser sees.
With caching disabled, HA streams HTTP covers then discards them (MQTT images
are assembled in memory for that request). With caching enabled, either method
stores covers under `playnite_connect_covers` in the HA configuration directory;
large libraries can use substantial disk space.
## Native Playnite Connect device entities

Besides the browseable library media player, the integration creates these
entities directly under the same **Playnite Connect** device — no generic MQTT
Discovery device is created:

- **Playing Game** sensor with the actual running/launching game and its ID.
- **Playing Game Cover**, **Background**, and **Icon** image entities, fetched
  only when Home Assistant displays them through the selected MQTT or HTTP path.
- **Selected Game** select, which genuinely selects the game in Playnite.
- **Active View** sensor and the real Playnite version in Device info. Active
  View is read-only because Playnite has no public setter for it.
## Real Playnite events for automations

The plugin publishes an unretained update only when Playnite calls one of its
real lifecycle callbacks. The integration turns those messages into Home
Assistant events; they are **not** inferred from a command acknowledgement or
a retained library snapshot.

- `playnite_connect.game_installed`
- `playnite_connect.game_starting`
- `playnite_connect.game_started`
- `playnite_connect.game_stopped`
- `playnite_connect.game_uninstalled`

Every event includes `device_id`, `game_id`, `name`, installation and running
state, source, platforms, categories, tags, features, genres, and install size.
For example, an automation that starts lights only after Playnite reports the
game as started is:

```yaml
trigger:
  - platform: event
    event_type: playnite_connect.game_started
    event_data:
      game_id: "your-playnite-game-guid"
action:
  - service: light.turn_off
    target:
      area_id: game_room
```

These events are notifications, not blocking hooks: an HA automation cannot
pause Playnite's launch flow before the game starts.

## Requirements

- Playnite Connect **1.0.5 or newer** from this fork, installed in
  Playnite and connected to your MQTT broker.
- Home Assistant's built-in MQTT integration connected to that same broker.
- This custom integration.

## Setup

1. Build/install the Playnite Connect 1.0.5 extension and configure its
   normal MQTT broker settings and Device ID in Playnite.
2. Install this directory as `custom_components/playnite_connect` and restart
   Home Assistant.
3. Add **Playnite Connect** in Devices & services.
4. Enter the exact Playnite Connect Device ID (the default is `playnite`).
5. Open the library media-player entity and choose **Browse Media**.

The integration requests a fresh snapshot when it starts. It also accepts the
plugin's retained snapshot, so Home Assistant can populate the browser before
Playnite has sent another library change.

## Search and launch — UI, automations, and Assist

The normal media-player path remains available to everyone:

- `media_player.search_media` searches this library by name and returns playable
  game results.
- `media_player.play_media` starts a result using its exact Playnite game ID.
- `playnite_connect.search_games` is a response-only service for automations,
  scripts, dashboards, and callers that need the exact matching IDs.
- `playnite_connect.launch_game` starts one exact `game_id`; it can be used
  normally in an automation and optionally returns its result.

For Home Assistant LLM APIs, the integration contributes
`SearchAndPlayPlayniteGame`, `SearchPlayniteGames`, and
`LaunchPlayniteGame`. The one-step tool launches only an exactly-one-match
result; the lookup and exact-ID tools remain available when an agent needs a
separate selection step. When Home Assistant's MCP Server integration is
configured, it exposes these registered LLM API tools automatically.

## Custom Assist sentence automation

For a normal Assist sentence without an LLM, use a Home Assistant sentence-trigger
automation that calls `playnite_connect.search_and_play`. It receives the spoken
game title as `trigger.slots.game_name`, launches only an unambiguous match, and
returns matching games for an automation to speak or handle however you prefer.
## Data exposed per game

The library snapshot provides the Playnite game ID, name, hidden/favourite and
installation/running state, install size, playtime/count, activity and library
timestamps, version, source, plus platforms, categories, tags, features and
genres. Hidden games are not shown in Browse Media. No inferred installation
status is used: `isInstalled` is Playnite's own flag.

## Safety of Stop

Playnite's public extension API provides start, install, and uninstall methods
but no generic stop method. The plugin only stops processes whose executable
path is inside the selected game's configured installation directory. If it
cannot identify such a process, it returns a failure instead of killing an
unrelated launcher or process. Restart uses that same safe stop, waits three
seconds, then requests Playnite start.

## Migration from Playnite Web Library 1.0.0

Remove the previous config entry and add the new one with only the MQTT Client
Device ID. The earlier Playnite Web URL and library ID are intentionally no
longer used.
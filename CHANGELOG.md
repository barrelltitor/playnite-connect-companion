# Changelog

## 1.0.0b1 - 2026-09-12 (Beta 1)

Initial public beta of Playnite Connect Companion.

- Connects the local Playnite extension to Home Assistant over MQTT.
- Provides a browseable media-player library with real covers, current-game state, media search, and safe game launch/stop controls.
- Provides folders for Recent Activity, installed state, favourites, genres, platforms, categories, tags, features, and sources.
- Supports MQTT covers by default, plus an optional authenticated HTTP cover transport and optional Home Assistant disk cache.
- Provides normal automation services: `search_games`, `launch_game`, and safe name-based `search_and_play`.
- Contributes Home Assistant LLM tools for game lookup and safe name-based launch; these are available through HA's LLM API and MCP Server when configured.
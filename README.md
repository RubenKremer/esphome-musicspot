# MusicSpot

> 🚧 **Work in progress** — not usable yet. See [PLAN.md](PLAN.md) for the roadmap and progress.

A touch-panel music controller for Home Assistant: ESPHome + LVGL firmware for the
**Guition ESP32-4848S040** (4" 480×480 square display that fits a standard wall box),
with a HACS integration that connects each panel to a Spotify account.

## Planned features
- Now playing with album art, playback and volume controls
- Browse your playlists, Liked Songs and recently played
- Long-press a track to add it to the queue
- Pick which Spotify Connect device plays
- Several panels, each linked to its own Spotify account

## How it works
- **Firmware (`esphome/`):** a thin client — screens and touch only, no Spotify logic.
- **Integration (`custom_components/musicspot/`):** talks to the Spotify Web API, keeps browse state
  per panel, serves resized album art, and pushes updates to the panel through ESPHome API actions.

## Requirements
- Home Assistant with [HACS](https://hacs.xyz/)
- A Guition ESP32-4848S040 flashed with ESPHome
- Spotify Premium, and your own app in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)

## Installing the integration (development builds)
1. HACS → ⋮ → **Custom repositories** → add `https://github.com/RubenKremer/esphome-musicspot`, type **Integration**.
2. Download **MusicSpot** from HACS and restart Home Assistant.
3. **Settings → Devices & services → Add integration → MusicSpot.** When asked, enter your Spotify app's
   Client ID and Client Secret (you can reuse the app from the core Spotify integration), then sign in.
4. Optional, to see what it polls: add to `configuration.yaml`
   ```yaml
   logger:
     logs:
       custom_components.musicspot: debug
   ```

## Known limitations (Spotify Web API)
- No true "play next": tracks can only be added to the end of the queue, and the queue can't be reordered.
- Development-mode Spotify apps allow at most 5 users.
- Devices may disappear from the device list while paused or idle.

## Disclaimer
MusicSpot is an independent community project. It is not affiliated with or endorsed by Spotify,
ESPHome, the Open Home Foundation or Home Assistant. Spotify is a trademark of Spotify AB.

## License
[MIT](LICENSE)

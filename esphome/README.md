# MusicSpot firmware

ESPHome config for the Guition ESP32-S3-4848S040.

| File | Purpose |
|---|---|
| `musicspot.yaml` | Device config (name, Wi-Fi, API, OTA) |
| `musicspot-packages/hardware/guition-esp32-s3-4848s040.yaml` | Board: display, touch, backlight, PSRAM |
| `musicspot-packages/musicspot/core.yaml` | Design C screens (PLAYING, LIBRARY, SETUP, idle clock), API actions, input events |
| `musicspot-packages/musicspot/theme.yaml` | Colours, IBM Plex fonts, icons and shared styles |
| `musicspot-packages/musicspot/{list_row,tile,device_row,segment}.yaml`, `widgets/` | Templates for list rows, album tiles, device rows and bar segments |
| `musicspot-packages/musicspot/icons/` | Design C icons (SVG, recoloured on the panel) |
| `secrets.yaml.example` | Template for your `secrets.yaml` (never commit the real one) |

## Setup
1. Copy `secrets.yaml.example` to `secrets.yaml` and fill it in.
2. Validate: `esphome config musicspot.yaml`
3. In Home Assistant, enable **Allow the device to perform Home Assistant actions** for the panel
   (ESPHome integration → device → Configure), so touches reach Home Assistant.

## Using it from the ESPHome dashboard (Home Assistant app / server)
Instead of copying files, create a new config in the dashboard that pulls the packages from GitHub.
Put the same keys as `secrets.yaml.example` into the dashboard's own `secrets.yaml`.

```yaml
substitutions:
  name: musicspot-1
  friendly_name: MusicSpot 1
  pclk_frequency: 12MHz

packages:
  musicspot:
    url: https://github.com/RubenKremer/esphome-musicspot
    ref: main
    files:
      - esphome/musicspot.yaml
    refresh: 1min   # while developing; raise later
```

The included `musicspot.yaml` brings in the board and MusicSpot packages relative to itself.

## First flash over a board that already runs ESPHome
The device name changes, so OTA the first time by address of the *old* device:

```
esphome run musicspot.yaml --device <old-hostname>.local
```

(or its IP). Afterwards, Home Assistant discovers `musicspot-1` as a new device — remove the old
device from the ESPHome integration and adopt the new one with the new API key.

## Testing the screens
See [docs/panel-protocol.md](../docs/panel-protocol.md) for the actions and events, with ready-to-paste
Developer Tools examples. (The Phase 1 bring-up page was removed once these screens existed; it is in git history.)

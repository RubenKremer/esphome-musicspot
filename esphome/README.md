# MusicSpot firmware

ESPHome config for the Guition ESP32-S3-4848S040.

| File | Purpose |
|---|---|
| `musicspot.yaml` | Device config (name, Wi-Fi, API, OTA) |
| `packages/hardware/guition-esp32-s3-4848s040.yaml` | Board: display, touch, backlight, PSRAM |
| `packages/test/bringup.yaml` | Temporary P1 test page (touch, brightness, image stress test) |
| `secrets.yaml.example` | Template for your `secrets.yaml` (never commit the real one) |

## Setup
1. Copy `secrets.yaml.example` to `secrets.yaml` and fill it in.
2. For the bring-up stress test, put any **baseline** JPEG in Home Assistant's `/config/www/musicspot/test.jpg`
   and point `musicspot_test_image_url` at `http://<ha>:8123/local/musicspot/test.jpg`.
3. Validate: `esphome config musicspot.yaml`

## Using it from the ESPHome dashboard (Home Assistant app / server)
Instead of copying files, create a new config in the dashboard that pulls the packages from GitHub.
Put the same keys as `secrets.yaml.example` into the dashboard's own `secrets.yaml`.

```yaml
substitutions:
  name: musicspot-1
  friendly_name: MusicSpot 1
  pclk_frequency: 12MHz
  stress_image_url: !secret musicspot_test_image_url

packages:
  musicspot:
    url: https://github.com/RubenKremer/esphome-musicspot
    ref: main
    files:
      - esphome/musicspot.yaml
    refresh: 1min   # while developing; raise later
```

The included `musicspot.yaml` brings in the board and bring-up packages relative to itself.

## First flash over a board that already runs ESPHome
The device name changes, so OTA the first time by address of the *old* device:

```
esphome run musicspot.yaml --device <old-hostname>.local
```

(or its IP). Afterwards, Home Assistant discovers `musicspot-1` as a new device — remove the old
device from the ESPHome integration and adopt the new one with the new API key.

## Bring-up checks (PLAN.md Phase 1)
- **P1.2** Touch the corners: the coordinates shown should be ~0 and ~479 on each axis.
- **P1.3** The slider dims the backlight.
- **P1.4** The page renders and the button counts taps.
- **P1.5** Turn on the switch: the image re-downloads every 3 s while the spinner keeps turning.
  Watch for flicker or image drift, and check the free-memory line stays stable for several minutes.

# MusicSpot

Touch-panel music controller for the Guition ESP32-4848S040: ESPHome + LVGL thin client (`esphome/`)
driven by a HACS custom integration `musicspot` (`custom_components/musicspot/`, at repo root as HACS requires).
GitHub: `RubenKremer/esphome-musicspot` (public).

## Naming
- Product name is **MusicSpot**. Never put "Spotify" (or variants) in the product, repo or integration name;
  describing compatibility ("for Spotify") in docs is fine.
- Don't present it as an official ESPHome or Home Assistant product.

## Working rules
- `PLAN.md` is the source of truth. Pick the next unticked task in order unless told otherwise.
- Tick a box only after it is verified (compiled, tested on hardware, or tested in HA). Say how it was verified.
- New decisions go in the Decisions table; versions, pinouts and API surprises go in Findings (dated).
- Reference task IDs in commit messages, e.g. `P2.3: now playing screen`.
- Never commit secrets: `secrets.yaml`, Spotify Client ID/Secret, HA tokens.
- `github.com/RubenKremer/artemis-esphome-config` is read-only reference material: never modify, commit to or push it.
- No local ESPHome/Docker toolchain: Ruben validates and flashes from the ESPHome dashboard on his home server.

## Constraints
- Spotify Web API dev mode: Premium owner, max 5 users, shared quota, search max 10/page,
  no true "play next" (add-to-queue only), queue is read-only.
- ESPHome `online_image`: baseline JPEG only; the integration serves pre-resized art.
- The device holds no Spotify logic and no HA entity IDs.

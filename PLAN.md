# MusicSpot — Build Plan

A wall-mounted Spotify controller on a **Guition ESP32-4848S040** (4" 480×480, ESP32-S3, 8 MB PSRAM),
running **ESPHome + LVGL** as a thin client, driven by a **HACS custom integration** (`musicspot`)
that links each panel to a Spotify account.

**How to use this file**
- Work top to bottom; a phase is done when every box *and* its **Done when** check is ticked.
- Tick a box (`- [x]`) only when it's verified, not when code is merely written.
- Record decisions in the [Decisions](#decisions) table and surprises in [Findings](#findings).
- Task IDs (`P2.3`) are stable — reference them in commits, e.g. `P2.3: add show_page action`.

**Repository:** `github.com/RubenKremer/esphome-musicspot` (public)

**Repository layout** (HACS requires `custom_components/` and `hacs.json` at the root)
```
custom_components/musicspot/     Home Assistant integration (HACS)
hacs.json
esphome/                         ESPHome firmware (thin client)
  musicspot.yaml                 device config (board-specific)
  packages/                      reusable pieces (screens, actions);
                                 users pull via github://RubenKremer/esphome-musicspot/esphome/packages/...
README.md  PLAN.md  CLAUDE.md
```

---

## Architecture (reference)

```
ESP32-4848S040 (ESPHome + LVGL)  ── screens only, no entity IDs
   ▲ API actions: show_now_playing / show_page / show_devices / set_busy
   │ HA event:    esphome.musicspot_input {type, arg, value} (tap/queue/back/page/device/control/awake/hello)
Home Assistant: custom integration "musicspot"
   • config entry  = Spotify account (own OAuth, application_credentials)
   • subentry      = panel  ↔ ESPHome device
   • coordinator   = fast poll while a panel is awake, slow when idle
   • HTTP view     = pre-resized baseline JPEG art (300px / 64px)
   ▼ HTTPS
Spotify Web API (dev mode: Premium owner, max 5 users, shared quota)
```

**Hard API limits (accepted):** no true "play next" (only add-to-queue, appended after queued items);
queue cannot be reordered/removed; no browse/new-releases/top-tracks; search max 10 results/page.

---

## Phase 0 — Prerequisites
- [x] P0.1 Spotify Developer app created, owned by a Premium account; Client ID/Secret stored safely — verified: confirmed by Ruben 2026-10-22
- [x] P0.2 Redirect URI `https://my.home-assistant.io/redirect/oauth` added to the Spotify app — verified: confirmed by Ruben 2026-10-22
- [x] P0.3 Home Assistant dev instance available (version noted in Findings) — verified: HA 2026.10.2 reported by Ruben
- [x] P0.4 ESPHome version with `mipi_rgb` + `GUITION-4848S040` preset (version noted in Findings) — verified: ESPHome 2026.10.0 reported by Ruben
- [x] P0.5 Board pinout confirmed (touch GT911 I²C pins, backlight pin) and noted in Findings — verified: taken from working unit `touch-control-2`
- [x] P0.6 `git init`, `.gitignore` (secrets.yaml, .esphome/, __pycache__) — verified: initial commit on `main`

**Done when:** board on the desk, HA reachable, ESPHome can compile a blank config.

## Phase 1 — Board bring-up (`esphome/`)
- [x] P1.1 Display working, PSRAM enabled (`st7701s` per D7; `mipi_rgb` preset still to try) — verified: unit boots and renders, 2026-10-22
- [x] P1.2 GT911 touchscreen working (tap coordinates match screen) — verified: on-screen controls respond where tapped, 2026-10-22
- [x] P1.3 Backlight as `light` with brightness — verified: slider dims backlight on device, 2026-10-22
- [x] P1.4 LVGL hello page: label + button + brightness slider — verified: on device, 2026-10-22
- [x] P1.5 Stress test: continuous `online_image` download while animating — no drift/flicker
      (tune `pclk_frequency`, `buffer_size` if needed; record result) — verified 2026-10-22: 30 ok / 0 fail,
      no drift/flicker, memory stable; spinner stutters during each download (see Findings, D9)

**Done when:** stable screen and touch during heavy Wi-Fi traffic.

## Phase 2 — Thin-client firmware (`esphome/packages/`)
- [x] P2.1 Screen navigation: Now Playing / Browse / Devices (tab bar or swipe) — verified on device via Developer Tools, 2026-10-23
- [x] P2.2 API action `show_now_playing(title, artist, album, art_url, state, position_ms, duration_ms, volume, shuffle, repeat)` — verified on device with real Spotify data, 2026-10-23
- [x] P2.3 Now Playing screen: 220×220 art via `online_image` (JPEG, placeholder + `on_error`), text, controls — verified on device with real Spotify data, 2026-10-23
- [x] P2.4 Local progress-bar interpolation between updates — verified on device during playback, 2026-10-23 (seek jump-back fixed afterwards)
- [x] P2.5 API action `show_page(breadcrumb, page, pages, can_back, titles[], subtitles[], thumbs[])` (no ids: D11) — verified on device via Developer Tools, 2026-10-23
- [x] P2.6 Browse screen: 6 fixed rows (48px thumb + 2 lines), hide empty rows, Back, ◀ x/y ▶ — verified on device via Developer Tools, 2026-10-23
- [ ] P2.7 API action `show_devices(names[], active)` + Devices screen (5 rows + volume slider)
- [ ] P2.8 API action `set_busy(bool)` + spinner overlay
- [x] P2.9 Outgoing events `esphome.musicspot_input`: tap/queue (slot), back, page(±1), device (slot), control(cmd, value), awake, hello — verified: awake, tap, queue, back, page events seen with device_id, 2026-10-23
      — all pass the device's own identity
- [ ] P2.10 Fallback screens: no connection to HA / nothing playing / no devices
- [ ] P2.11 Test everything from HA Developer Tools with fake data (no integration yet)

**Done when:** every screen can be driven by hand from Developer Tools, and taps show up as HA action calls.

## Phase 3 — Integration skeleton (`custom_components/musicspot/`)
- [x] P3.1 HACS layout: `custom_components/musicspot/`, `manifest.json`, `hacs.json`, `README.md` — verified: installed via HACS custom repo, 2026-10-22
- [x] P3.2 `application_credentials` + OAuth2 config flow (account = config entry) — verified: account added via UI (Spotify sign-in), 2026-10-22
- [x] P3.3 Spotify API client (own aiohttp client, D12), token refresh — verified: `/me` + `/me/player` calls succeed, 2026-10-22 (token refresh not yet observed)
- [x] P3.4 Account coordinator: playback state; fast/slow polling; 429 `QUOTA_EXCEEDED` back-off — verified: debug log shows playback polled (0.2 s fetch), 2026-10-22 (fast mode and 429 path not yet exercised)
- [ ] P3.5 Reauth flow when the token is revoked
- [x] P3.6 Diagnostics (redacted) — verified: downloaded from HA 2026-10-22; tokens, ids, names redacted. Gap found and fixed: `external_urls` leaked Spotify ids

**Done when:** account adds via UI, playback state visible in logs, survives HA restart.

## Phase 4 — Panel subentry + Now Playing push
- [x] P4.1 Panel subentry: pick ESPHome device, optional default playback device — verified on device with real Spotify data, 2026-10-23
- [x] P4.2 Listen to `esphome.musicspot_input`; resolve event `device_id` → panel → account — verified on device with real Spotify data, 2026-10-23
- [x] P4.3 Image view `/api/musicspot/art/{token}/{name}`: per-panel random token (D13), Pillow resize, baseline JPEG, cache — verified on device with real Spotify data, 2026-10-23
- [x] P4.4 Push `show_now_playing` on state change (debounced) and on panel wake — verified on device with real Spotify data, 2026-10-23
- [x] P4.5 Controls: play/pause, next, prev, seek, volume, shuffle, repeat — verified on device with real Spotify data, 2026-10-23
- [x] P4.6 `set_awake` switches coordinator between fast and slow polling — verified on device with real Spotify data, 2026-10-23

**Done when:** panel follows phone playback within ~5 s, art correct, all controls work.

## Phase 5 — Browse
- [ ] P5.1 Root menu: Playlists, Liked Songs, Recently Played, Albums
- [ ] P5.2 Per-panel browse state (path stack, page) — survives a panel reboot
- [ ] P5.3 Paging (6 per page) with lazy fetch from Spotify (respect API page sizes)
- [ ] P5.4 Tap: folder → drill in; track → play in context (playlist/album) where possible
- [ ] P5.5 Long press on track → add to queue + toast on device
- [ ] P5.6 Thumbnails via image view (64px)

**Done when:** can start a playlist and queue a song entirely from the panel.

## Phase 6 — Devices, queue, search
- [ ] P6.1 Device list push + transfer playback (implemented early in Phase 4 for P2.7; verify here)
- [ ] P6.2 Queue view (read-only, `GET /me/player/queue`)
- [ ] P6.3 Search: LVGL keyboard → `search` input event → results as a browse page (10/page)

## Phase 7 — Polish & release
- [ ] P7.1 Dim/screensaver after inactivity; wake on touch (optional LD2410 presence)
- [ ] P7.2 Release images when leaving Browse; check free PSRAM over 24 h
- [ ] P7.3 Translations (en, nl)
- [ ] P7.4 GitHub Actions: `hassfest` + HACS validation; ESPHome config compile check
- [ ] P7.5 README: setup (Spotify app, HACS install, flashing), limits, screenshots
- [ ] P7.6 First tagged release

## Phase 8 — Optional: Music Assistant backend (later)
Why: Spotify forgets idle Google Cast speakers and the Web API can't wake them (Findings 2026-10-23).
Music Assistant streams Spotify to Cast speakers itself, so speakers never disappear. Trade-off: playback
started this way is not Spotify Connect, so the Spotify app doesn't see it; Now Playing must come from the
Music Assistant player instead of the Spotify API. Same firmware and panel protocol (D11).
- [ ] P8.1 Spike: Music Assistant (HA core integration) actions/attributes for now playing, browse, queue, play on a Cast player
- [ ] P8.2 Second subentry/backend type: panel ↔ Music Assistant player(s) instead of a Spotify account
- [ ] P8.3 Now Playing + controls from the Music Assistant `media_player`
- [ ] P8.4 Browse + "play on speaker" via Music Assistant
- [ ] P8.5 Decide: mixed mode (Spotify account, Cast speakers handed to Music Assistant) or separate panels

---

## Decisions

| # | Decision | Status | Notes |
|---|----------|--------|-------|
| D1 | Integration has its **own Spotify OAuth** (not reusing core Spotify integration) | Proposed | Avoids depending on another integration's internals; each user brings their own Spotify app (dev mode: 5 users) |
| D2 | Device is a thin client; HA pushes via ESPHome API actions | Agreed | One generic firmware for all panels |
| D3 | 6 items per browse page | Proposed | Revisit after P2.6 on real hardware |
| D4 | Name: product **MusicSpot**, repo `esphome-musicspot`, domain `musicspot` | Agreed | No "Spotify" in names (Spotify brand terms); "ESPHome" only in repo slug, not product name |
| D5 | Single public repo, integration at root, firmware in `esphome/` | Agreed | HACS needs `custom_components/` at root; firmware consumed as remote ESPHome packages |
| D6 | MIT licence | Agreed | Don't publish pre-built firmware `.bin` files (ESPHome C++ runtime is GPLv3); users compile from YAML |
| D7 | P1 uses the proven `st7701s` config, not the `mipi_rgb` preset | Proposed | Lowest risk on the test unit; try the preset after P1 passes and switch if equal |
| D8 | `touch-control-2` is dedicated to MusicSpot (reflashed as `musicspot-1`) | Agreed | Its old dashboard config lives in artemis-esphome-config, which this project must not modify |
| D9 | Integration serves art over **plain HTTP on the LAN**, **pre-sized to the exact widget size** (no device-side `resize`), small baseline JPEGs | Proposed | Downloads + decode block the ESPHome main loop, so LVGL stutters; TLS handshake and resizing add most of the cost (P1.5) |
| D10 | Panel input goes to HA as **events** (`esphome.musicspot_input`), not HA actions | Agreed | No "unknown action" errors before the integration exists; HA adds `device_id`, so no device identity in firmware. Verified 2026-10-22: events carry `device_id` |
| D11 | Panel sends **slot numbers**, never Spotify ids; the integration keeps the ids per panel page | Proposed | Keeps firmware generic and payloads small; protocol in `docs/panel-protocol.md` |
| D12 | Own minimal Spotify client (`api.py`, aiohttp, no requirements) instead of `spotifyaio` | Proposed | Only the endpoints we use, written against the Feb-2026 API; Spotify changes fixed here without waiting for a library release |
| D13 | Album art served without auth via an unguessable per-panel token in the URL (new on every restart) | Proposed | ESPHome `online_image` can't send auth headers or follow HA signed paths; only public cover art is exposed |
| D14 | Coordinator only polls while at least one panel is linked (coordinator listener) | Proposed | No panels = no Spotify quota used |
| D15 | Remember recently seen Spotify devices per account and keep them on the Devices screen | Proposed | The Web API drops idle Google Cast devices from `/me/player/devices`, so you couldn't switch back to one. Transfer to a remembered device may still fail (404); then it is forgotten and logged |
| D16 | Playlists and albums open with a **Play all** row; tracks play inside their context (playlist/album/Liked Songs) | Proposed | Since Feb 2026 Spotify only lists items of playlists you own; Play all still works for followed playlists |
| D17 | Firmware actions `show_toast` and `show_screen` | Proposed | Feedback for queueing (no 'play next') and jumping to Now Playing after starting playback |

## Findings

<!-- Versions, pinouts, measured timings, API surprises. Date each entry. -->
- 2026-10-22: Spotify Feb-2026 dev-mode changes: Premium owner, 5 users/app, search limit 10, batch/browse endpoints removed. Player + queue endpoints unaffected.
- 2026-10-22: ESPHome `online_image` supports baseline JPEG only (no progressive).
- 2026-10-22: Versions: Home Assistant 2026.10.2, ESPHome 2026.10.0.
- 2026-10-22: Test unit = `touch-control-2` from github.com/RubenKremer/artemis-esphome-config
  (`modules/hardware/guition-esp32-s3-4848s040.yaml`). Proven settings on that unit:
  - ESP32-S3, 16 MB flash, PSRAM octal @ 80 MHz, framework esp-idf
  - Display: `st7701s` platform, SPI init CLK GPIO48 / MOSI GPIO47, CS 39, DE 18, HSYNC 16, VSYNC 17, PCLK 21,
    `pclk_frequency: 12MHz`, RGB data R 11,12,13,14,0 / G 8,20,3,46,9,10 / B 4,5,6,7,15
  - Touch: GT911 on I²C SDA 19, SCL 45 (strapping-pin warning ignored)
  - Backlight: LEDC PWM on GPIO38 @ 100 Hz
  - Relays (some variants): GPIO40, GPIO2, GPIO1 — unused by MusicSpot; leave unconfigured
  - `online_image` already works on this unit with HA-served JPEGs over plain HTTP (`http_request`, RGB565, `resize`)
- 2026-10-22: P1 config validates on ESPHome 2026.10.0 (Ruben's dashboard). `pad_row`/`pad_column` belong under the `layout:` key, not on the page or widget.
- 2026-10-22: First flash OK on `musicspot-1` (ESP32-S3 rev0.2). Boot log suggests `flash_chip: boya` under
  `esp32 > framework > advanced` to save IRAM — chip vendor may differ per unit, so keep it out of the shared hardware package.
- 2026-10-22: Panel events arrive as `esphome.musicspot_input` with HA-added `device_id` (e.g. `awake` value `1` on touch after idle); all data values are strings.
- 2026-10-23: P4 on device: art, next/previous, shuffle/repeat, seek and awake-based polling work. Bugs found: device list not refreshed when playback moves elsewhere (fixed: refresh on active-device change), Google Cast speaker disappears from the device list once playback leaves it (mitigated: D15). "Add panel" button showed only a + icon — browser cache; fine after a hard refresh.
- 2026-10-23: After moving playback Google → phone, transferring back to the (remembered) Google returns 404 and the speaker is dropped — D15 keeps it visible but cannot revive it; Spotify-side limitation, documented in README. Seek jumped back for a few seconds because Spotify reports the old position briefly: panel now jumps locally and the integration ignores position-only changes for 4 s after a seek.
- 2026-10-22: Integration runs on HA 2026.10.2 (Container on Unraid, Python 3.14.6); survives restart without re-auth.
  `/me` returns `country`/`product` as null — those need the `user-read-private` scope, which MusicSpot does not request; Premium is detected via 403 instead.
- 2026-10-22: P1.5 stress test over HTTPS (48.9 KB JPEG, resized to 200×200, every 3 s): 30 ok / 0 fail,
  PSRAM free ~5917 KB and heap free ~149 KB, no display drift/flicker. Spinner stutters while each image downloads:
  `online_image` runs in the main loop (first download blocked ~1.3 s, warnings of 900+ ms). Real use refreshes art
  once per track, so a short stutter at track change is acceptable; D9 keeps it short.

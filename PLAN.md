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
   │ HA actions:  musicspot.tap / back / page / control / set_awake
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
- [ ] P0.1 Spotify Developer app created, owned by a Premium account; Client ID/Secret stored safely
- [ ] P0.2 Redirect URI `https://my.home-assistant.io/redirect/oauth` added to the Spotify app
- [ ] P0.3 Home Assistant dev instance available (version noted in Findings)
- [ ] P0.4 ESPHome version with `mipi_rgb` + `GUITION-4848S040` preset (version noted in Findings)
- [ ] P0.5 Board pinout confirmed (touch GT911 I²C pins, backlight pin) and noted in Findings
- [x] P0.6 `git init`, `.gitignore` (secrets.yaml, .esphome/, __pycache__) — verified: initial commit on `main`

**Done when:** board on the desk, HA reachable, ESPHome can compile a blank config.

## Phase 1 — Board bring-up (`esphome/`)
- [ ] P1.1 `mipi_rgb` display with `model: GUITION-4848S040`, PSRAM enabled
- [ ] P1.2 GT911 touchscreen working (tap coordinates match screen)
- [ ] P1.3 Backlight as `light` with brightness
- [ ] P1.4 LVGL hello page: label + button + brightness slider
- [ ] P1.5 Stress test: continuous `online_image` download while animating — no drift/flicker
      (tune `pclk_frequency`, `buffer_size` if needed; record result)

**Done when:** stable screen and touch during heavy Wi-Fi traffic.

## Phase 2 — Thin-client firmware (`esphome/packages/`)
- [ ] P2.1 Screen navigation: Now Playing / Browse / Devices (tab bar or swipe)
- [ ] P2.2 API action `show_now_playing(title, artist, album, art_url, state, position_ms, duration_ms, volume, shuffle, repeat)`
- [ ] P2.3 Now Playing screen: 300×300 art via `online_image` (JPEG, placeholder + `on_error`), text, controls
- [ ] P2.4 Local progress-bar interpolation between updates
- [ ] P2.5 API action `show_page(breadcrumb, page, pages, titles[], subtitles[], ids[], kinds[], thumbs[])`
- [ ] P2.6 Browse screen: 6 fixed rows (64px thumb + 2 lines), hide empty rows, Back, ◀ x/y ▶
- [ ] P2.7 API action `show_devices(names[], ids[], active_id)` + Devices screen (list/roller)
- [ ] P2.8 API action `set_busy(bool)` + spinner overlay
- [ ] P2.9 Outgoing calls: tap (slot, long_press), back, page(±1), control(cmd, value), set_awake(bool)
      — all pass the device's own identity
- [ ] P2.10 Fallback screens: no connection to HA / nothing playing / no devices
- [ ] P2.11 Test everything from HA Developer Tools with fake data (no integration yet)

**Done when:** every screen can be driven by hand from Developer Tools, and taps show up as HA action calls.

## Phase 3 — Integration skeleton (`custom_components/musicspot/`)
- [ ] P3.1 HACS layout: `custom_components/musicspot/`, `manifest.json`, `hacs.json`, `README.md`
- [ ] P3.2 `application_credentials` + OAuth2 config flow (account = config entry)
- [ ] P3.3 Spotify API client (`spotifyaio` where it covers it, raw `aiohttp` otherwise), token refresh
- [ ] P3.4 Account coordinator: playback state; fast/slow polling; 429 `QUOTA_EXCEEDED` back-off
- [ ] P3.5 Reauth flow when the token is revoked
- [ ] P3.6 Diagnostics (redacted)

**Done when:** account adds via UI, playback state visible in logs, survives HA restart.

## Phase 4 — Panel subentry + Now Playing push
- [ ] P4.1 Panel subentry: pick ESPHome device, optional default playback device
- [ ] P4.2 Register `musicspot.*` actions; resolve caller device → panel → account
- [ ] P4.3 Image view `/api/musicspot/{panel}/art/{slot}.jpg`: signed path, Pillow resize, baseline JPEG, cache
- [ ] P4.4 Push `show_now_playing` on state change (debounced) and on panel wake
- [ ] P4.5 Controls: play/pause, next, prev, seek, volume, shuffle, repeat
- [ ] P4.6 `set_awake` switches coordinator between fast and slow polling

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
- [ ] P6.1 Device list push + transfer playback
- [ ] P6.2 Queue view (read-only, `GET /me/player/queue`)
- [ ] P6.3 Search: LVGL keyboard → `musicspot.search` → results as a browse page (10/page)

## Phase 7 — Polish & release
- [ ] P7.1 Dim/screensaver after inactivity; wake on touch (optional LD2410 presence)
- [ ] P7.2 Release images when leaving Browse; check free PSRAM over 24 h
- [ ] P7.3 Translations (en, nl)
- [ ] P7.4 GitHub Actions: `hassfest` + HACS validation; ESPHome config compile check
- [ ] P7.5 README: setup (Spotify app, HACS install, flashing), limits, screenshots
- [ ] P7.6 First tagged release

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

## Findings

<!-- Versions, pinouts, measured timings, API surprises. Date each entry. -->
- 2026-10-22: Spotify Feb-2026 dev-mode changes: Premium owner, 5 users/app, search limit 10, batch/browse endpoints removed. Player + queue endpoints unaffected.
- 2026-10-22: ESPHome `online_image` supports baseline JPEG only (no progressive).

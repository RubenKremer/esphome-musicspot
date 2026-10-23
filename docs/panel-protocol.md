# Panel protocol

The contract between the MusicSpot firmware (`esphome/packages/musicspot/`) and the
Home Assistant integration. The panel is a thin client: it renders what it is told and reports touches.

## Inbound: API actions (integration → panel)

Home Assistant exposes each action as `esphome.<device_name>_<action>`, with dashes in the
device name turned into underscores. For a device named `musicspot-1`: `esphome.musicspot_1_show_page`.

Protocol v2 (design C, integration 0.4.0). Firmware and integration must be updated together.

### `show_now_playing`
| Field | Type | Notes |
|---|---|---|
| `title`, `artist` | string | |
| `context` | string | Header above the cover: `TRACK 02 / 13` for albums, else the playlist name, `LIKED SONGS` or artist (D20) |
| `device` | string | Active Spotify device, upper case; shown in the speaker chip and on the idle clock |
| `art_url` | string | Baseline JPEG, 150×150 over LAN HTTP (D9). Empty = no art. Only re-downloaded when it changes |
| `state` | string | `playing` \| `paused` \| `idle` |
| `position_ms`, `duration_ms` | int | Panel interpolates progress locally while `playing` |
| `volume` | int | 0–100, drawn as 16 segments |
| `shuffle` | bool | |
| `liked` | bool | Track is in Liked Songs (♥, D22) |

### `show_page`
| Field | Type | Notes |
|---|---|---|
| `title` | string | Folder name, shown next to BACK when `can_back` |
| `tab` | int | Active tab: 0 PLAYLISTS, 1 ALBUMS, 2 ARTISTS, 3 RECENT (D21) |
| `page`, `pages` | int | 1-based, shown as `01 / 03` in the pager column |
| `can_back` | bool | Inside a folder: BACK + title replace the source switch |
| `grid` | bool | Albums tab root: 4×2 cover grid (8 tiles) instead of 6 list rows |
| `now_index` | int | Grid tile (0-based) of the album that is playing, `-1` for none |
| `nums` | string[] | Row numbers (`01`…); empty for the Play all row. `01` is drawn in the accent colour |
| `titles`, `subtitles` | string[] | Subtitle (artist / year) is a second line; hidden when empty |
| `counts` | string[] | Right column: track count (`312`) or duration (`4:12`) |
| `thumbs` | string[] | 40×40 (list) or 84×84 (grid) baseline JPEG URLs, or empty strings |

### `show_queue`
Up next (read-only Spotify queue), sent after a `queue_view` or `queue_page` event.
| Field | Type | Notes |
|---|---|---|
| `context` | string | Shown as `SRC: <context>` (playlist name, `TRACK 02 / 13`, …) |
| `now_title`, `now_artist` | string | The current track in the NOW box |
| `page`, `pages` | int | 5 rows per page |
| `nums`, `titles`, `artists`, `durations` | string[] | Up to 5 rows; numbers continue across pages |

### `show_devices`
| Field | Type | Notes |
|---|---|---|
| `names` | string[] | Up to 5 |
| `active` | int | 0-based index of the active device, `-1` for none |

### `set_busy`
| Field | Type |
|---|---|
| `busy` | bool |

### `show_toast`
| Field | Type | Notes |
|---|---|---|
| `message` | string | Shown above the navigation bar for 2.5 s, e.g. `Queued: Out Of Me` (`text` is not allowed as an ESPHome action variable name) |

### `show_screen`
| Field | Type | Notes |
|---|---|---|
| `screen` | string | `now` \| `browse` \| `devices` (PLAYING / LIBRARY / SETUP) — also wakes the idle clock |

## Outbound: input events (panel → integration)

Every touch fires the Home Assistant event **`esphome.musicspot_input`**. All data values are strings;
Home Assistant adds the panel's `device_id`.

| `type` | `arg` | `value` | Meaning |
|---|---|---|---|
| `hello` | | `0` | Panel (re)connected — push full state |
| `awake` | | `1` / `0` | Touched after idle / idle clock shown after 2 min — switch polling rate |
| `tap` | | slot `1`–`6` (list) or `1`–`8` (grid) | Short tap on a row/tile: open folder or play item |
| `queue` | | slot `1`–`6` | Long press on a browse row: add to queue |
| `back` | | `0` | Library: up one folder |
| `tab` | | `0`–`3` | Library tab selected |
| `queue_view` | | `0` | QUEUE pressed on PLAYING: send the queue |
| `queue_page` | | `-1` / `1` | Up next previous / next page |
| `page` | | `-1` / `1` | Previous / next browse page |
| `device` | | slot `1`–`5` | Transfer playback to that device |
| `control` | `play_pause` \| `next` \| `previous` \| `shuffle` \| `like` | `0` | Transport (shuffle and like toggle; no repeat, D27) |
| `control` | `volume` | `0`–`100` | Set volume |
| `control` | `seek` | position in ms | Seek |

## Testing without the integration (P2.11)

Prerequisite: in **Settings → Devices & services → ESPHome → the panel → Configure**, enable
**Allow the device to perform Home Assistant actions**, otherwise events are dropped.

**Watch the events:** Developer Tools → Events → *Listen to events* → `esphome.musicspot_input` → Start listening,
then tap things on the panel.

**Drive the screens:** Developer Tools → Actions → YAML mode (replace `musicspot_1` with your device name):

```yaml
action: esphome.musicspot_1_show_now_playing
data:
  title: "Bohemian Rhapsody"
  artist: "Queen"
  context: "TRACK 11 / 12"
  device: "LIVING ROOM"
  art_url: "http://192.168.1.2:8123/local/musicspot/test.jpg"
  state: playing
  position_ms: 60000
  duration_ms: 354000
  volume: 40
  shuffle: true
  liked: false
```

```yaml
action: esphome.musicspot_1_show_page
data:
  title: "Playlists"
  tab: 0
  page: 1
  pages: 3
  can_back: false
  grid: false
  now_index: -1
  nums: ["01", "02", "03", "04", "05", "06"]
  titles: ["Liked Songs", "Discover Weekly", "Daily Mix 1", "Café del Mar", "Röyksopp radio", "Short list"]
  subtitles: ["", "", "", "", "", ""]
  counts: ["312", "030", "050", "120", "050", "008"]
  thumbs: ["http://192.168.1.2:8123/local/musicspot/test.jpg", "", "", "", "", ""]
```

```yaml
action: esphome.musicspot_1_show_devices
data:
  names: ["Living room", "Kitchen speaker", "Ruben's phone"]
  active: 0
```

```yaml
action: esphome.musicspot_1_set_busy
data:
  busy: true
```

Edge cases worth trying: `state: idle`, a `show_page` with 2 titles (rows 3–6 hide), empty `names: []`,
and restarting Home Assistant (the red "Not connected" banner should appear, then a `hello` event on reconnect).

# Panel protocol

The contract between the MusicSpot firmware (`esphome/packages/musicspot/`) and the
Home Assistant integration. The panel is a thin client: it renders what it is told and reports touches.

## Inbound: API actions (integration → panel)

Home Assistant exposes each action as `esphome.<device_name>_<action>`, with dashes in the
device name turned into underscores. For a device named `musicspot-1`: `esphome.musicspot_1_show_page`.

### `show_now_playing`
| Field | Type | Notes |
|---|---|---|
| `title`, `artist`, `album` | string | Empty album is fine |
| `art_url` | string | Baseline JPEG, ideally 220×220 over LAN HTTP (D9). Empty = no art. Only re-downloaded when it changes |
| `state` | string | `playing` \| `paused` \| `idle` |
| `position_ms`, `duration_ms` | int | Panel interpolates progress locally while `playing` |
| `volume` | int | 0–100 |
| `shuffle` | bool | |
| `repeat` | string | `off` \| `context` \| `track` |

### `show_page`
| Field | Type | Notes |
|---|---|---|
| `breadcrumb` | string | Header text, e.g. `Playlists` |
| `page`, `pages` | int | 1-based; pager hidden when `pages` ≤ 1 |
| `can_back` | bool | Enables the back button |
| `titles`, `subtitles`, `thumbs` | string[] | Up to 6 rows; `thumbs` are 48×48 baseline JPEG URLs or empty strings |

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
| `text` | string | Shown above the navigation bar for 2.5 s, e.g. `Queued: Out Of Me` |

### `show_screen`
| Field | Type | Notes |
|---|---|---|
| `screen` | string | `now` \| `browse` \| `devices` — e.g. jump to Now Playing after starting playback |

## Outbound: input events (panel → integration)

Every touch fires the Home Assistant event **`esphome.musicspot_input`**. All data values are strings;
Home Assistant adds the panel's `device_id`.

| `type` | `arg` | `value` | Meaning |
|---|---|---|---|
| `hello` | | `0` | Panel (re)connected — push full state |
| `awake` | | `1` / `0` | Touched after idle / idle for 60 s — switch polling rate |
| `tap` | | slot `1`–`6` | Short tap on a browse row: open folder or play item |
| `queue` | | slot `1`–`6` | Long press on a browse row: add to queue |
| `back` | | `0` | Browse back |
| `page` | | `-1` / `1` | Previous / next browse page |
| `device` | | slot `1`–`5` | Transfer playback to that device |
| `control` | `play_pause` \| `next` \| `previous` \| `shuffle` \| `repeat` | `0` | Transport (shuffle toggles, repeat cycles) |
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
  album: "A Night at the Opera"
  art_url: "http://192.168.1.2:8123/local/musicspot/test.jpg"
  state: playing
  position_ms: 60000
  duration_ms: 354000
  volume: 40
  shuffle: true
  repeat: context
```

```yaml
action: esphome.musicspot_1_show_page
data:
  breadcrumb: "Playlists"
  page: 1
  pages: 3
  can_back: true
  titles: ["Daily Mix 1", "Discover Weekly", "Liked Songs", "Café del Mar", "Röyksopp radio", "Short list"]
  subtitles: ["Made for you", "Made for you", "312 songs", "Chill", "Radio", ""]
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

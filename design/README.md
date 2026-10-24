# Design

| Folder | Contents |
|---|---|
| `brand/` | `musicspot-logo-512.png`: source of the integration icon/logo (`custom_components/musicspot/brand/`) |
| `cyber-design/exports/` | Claude Design exports of design set **C** ("cyber-design"), one ZIP per screen |
| `cyber-design/screenshots/` | Screenshots of some of those screens |
| `mockups/design-c.html` | LVGL-faithful mockup of design C as built (font scale, protocol data, agreed deviations) |
| `mockups/archive/` | Superseded mockups (`current-ui.html`: the UI before design C) |

## Design C exports

| File | Screen | Status |
|---|---|---|
| `now-playing.zip` | PLAYING | Built (D18–D22) |
| `library-v1.0.zip` | LIBRARY | Superseded by v1.1 |
| `library-v1.1.zip` | LIBRARY: dark selected source segment | Built |
| `albums.zip` | LIBRARY > Albums grid | Built |
| `up-next.zip` | Up next (queue) | Built (P6.2) |
| `output-rooms.zip` | Output | Built as single-select for Spotify (D23) |
| `search.zip` | Search with keyboard | Built (P6.3) |
| `settings.zip` | SETUP | Built, paged + sleep timer (P7.15) |
| `idle-clock.zip` | Idle clock | Built (P7.1) |
| `splash.zip` | Boot splash | Built (D33) |

Each ZIP holds the design as `*.dc.html` (values in inline styles) plus a small React runtime to view it;
serve the unpacked folder over HTTP to look at it in a browser. Decisions that deviate from the designs
are recorded in `PLAN.md` (D18–D34).

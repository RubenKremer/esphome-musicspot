"""Constants for MusicSpot."""

from __future__ import annotations

from datetime import timedelta
import logging

DOMAIN = "musicspot"
LOGGER = logging.getLogger(__package__)

OAUTH2_AUTHORIZE = "https://accounts.spotify.com/authorize"
OAUTH2_TOKEN = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"

SCOPES = [
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "user-read-recently-played",
    "user-library-read",
    "user-library-modify",  # ♥ Like (D22)
    "user-follow-read",  # Library > Artists (D22)
    "playlist-read-private",
    "playlist-read-collaborative",
]

SUBENTRY_PANEL = "panel"
CONF_DEVICE_ID = "device_id"
CONF_ART_BASE_URL = "art_base_url"
CONF_DEFAULT_DEVICE = "default_device"

# Panel protocol (docs/panel-protocol.md)
EVENT_PANEL_INPUT = "esphome.musicspot_input"
ESPHOME_DOMAIN = "esphome"
ART_SIZE_NOW = 150  # design C cover
ART_SIZE_THUMB = 40  # list rows (D26)
ART_SIZE_TILE = 84  # Albums grid tiles

# Poll fast only while a panel is awake; development-mode quota is shared per app.
UPDATE_INTERVAL_SLOW = timedelta(seconds=12)  # idle clock still feels live (Ruben, 2026-10-24)
UPDATE_INTERVAL_FAST = timedelta(seconds=3)

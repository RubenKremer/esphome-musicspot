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
    "playlist-read-private",
    "playlist-read-collaborative",
]

# Poll fast only while a panel is awake; development-mode quota is shared per app.
UPDATE_INTERVAL_SLOW = timedelta(seconds=30)
UPDATE_INTERVAL_FAST = timedelta(seconds=3)

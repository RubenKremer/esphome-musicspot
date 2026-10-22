"""Diagnostics for MusicSpot."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import MusicSpotConfigEntry

TO_REDACT = {
    "access_token",
    "refresh_token",
    "token",
    "unique_id",
    "id",
    "uri",
    "href",
    "external_urls",
    "email",
    "display_name",
    "title",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MusicSpotConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a Spotify account."""
    data = entry.runtime_data
    coordinator = data.coordinator
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "user": async_redact_data(
            {k: data.user.get(k) for k in ("id", "display_name", "country", "product")},
            TO_REDACT,
        ),
        "polling": {
            "update_interval_s": coordinator.update_interval.total_seconds()
            if coordinator.update_interval
            else None,
            "last_update_success": coordinator.last_update_success,
        },
        "playback": async_redact_data(coordinator.data or {}, TO_REDACT),
    }

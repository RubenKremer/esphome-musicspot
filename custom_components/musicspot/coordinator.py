"""Playback coordinator: one per Spotify account."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MusicSpotApi, SpotifyApiError, SpotifyAuthError, SpotifyRateLimitError
from .const import DOMAIN, LOGGER, UPDATE_INTERVAL_FAST, UPDATE_INTERVAL_SLOW

if TYPE_CHECKING:
    from .panel import MusicSpotPanel


@dataclass
class MusicSpotData:
    """Runtime data stored on the config entry."""

    api: MusicSpotApi
    coordinator: MusicSpotCoordinator
    user: dict[str, Any]
    panels: dict[str, MusicSpotPanel] = field(default_factory=dict)


MusicSpotConfigEntry = ConfigEntry[MusicSpotData]


class MusicSpotCoordinator(DataUpdateCoordinator[dict[str, Any] | None]):
    """Poll Spotify playback state; fast while any panel is awake, slow otherwise.

    `data` is the raw `/me/player` response, or None when nothing is active.
    """

    config_entry: MusicSpotConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: MusicSpotConfigEntry, api: MusicSpotApi
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=UPDATE_INTERVAL_SLOW,
        )
        self.api = api
        self._awake: set[str] = set()
        self._last_summary: str | None = None

    @property
    def normal_interval(self) -> timedelta:
        """Polling interval for the current awake state."""
        return UPDATE_INTERVAL_FAST if self._awake else UPDATE_INTERVAL_SLOW

    @callback
    def set_awake(self, panel_key: str, awake: bool) -> None:
        """Mark a panel awake/asleep and adjust the polling rate."""
        was_fast = bool(self._awake)
        if awake:
            self._awake.add(panel_key)
        else:
            self._awake.discard(panel_key)
        self.update_interval = self.normal_interval
        if awake and not was_fast:
            self.hass.async_create_task(self.async_request_refresh())

    async def _async_update_data(self) -> dict[str, Any] | None:
        """Fetch playback state."""
        try:
            data = await self.api.get_playback()
        except SpotifyAuthError as err:
            raise ConfigEntryAuthFailed("Spotify rejected the access token") from err
        except SpotifyRateLimitError as err:
            # Back off at least as long as Spotify asks; restored after the next success.
            self.update_interval = max(
                self.normal_interval, timedelta(seconds=err.retry_after)
            )
            raise UpdateFailed(
                f"Rate limited by Spotify, retrying in {err.retry_after}s"
            ) from err
        except SpotifyApiError as err:
            raise UpdateFailed(str(err)) from err

        self.update_interval = self.normal_interval
        self._log_change(data)
        return data

    def _log_change(self, data: dict[str, Any] | None) -> None:
        """Log playback changes at debug level (P3 verification aid)."""
        if not LOGGER.isEnabledFor(10):  # DEBUG
            return
        if not data or not data.get("item"):
            summary = "nothing playing"
        else:
            item = data["item"]
            artists = ", ".join(a["name"] for a in item.get("artists", []))
            device = (data.get("device") or {}).get("name", "?")
            state = "playing" if data.get("is_playing") else "paused"
            summary = f"{state}: {item.get('name')} – {artists} on {device}"
        if summary != self._last_summary:
            self._last_summary = summary
            LOGGER.debug("%s: %s", self.config_entry.title, summary)

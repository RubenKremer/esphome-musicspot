"""Sleep timer (D29): fade the volume over the last 5 minutes, pause, recover later.

Runs in the integration (not on the panel) so a panel reboot doesn't lose it.
The fade starts from the volume at the moment the fade begins. Recovery: one hour after the
timer ended the volume is set to 1/16 if it is night, otherwise to that volume capped at 3/16.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, time as dtime, timedelta
import time
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.util import dt as dt_util

from .api import SpotifyApiError
from .const import LOGGER

if TYPE_CHECKING:
    from .coordinator import MusicSpotCoordinator

FADE_S = 5 * 60
TICK = timedelta(seconds=15)
RECOVER_AFTER_S = 60 * 60
NIGHT_VOLUME = round(100 / 16)  # one volume segment
DAY_VOLUME_CAP = round(3 * 100 / 16)  # three volume segments


def is_night(now: datetime, start: str, end: str) -> bool:
    """Whether `now` (local time) lies in the night window, e.g. 22:00:00-07:00:00."""
    begin, finish = dtime.fromisoformat(start), dtime.fromisoformat(end)
    current = now.time()
    if begin <= finish:
        return begin <= current < finish
    return current >= begin or current < finish


class SleepTimer:
    """One panel's sleep timer."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: MusicSpotCoordinator,
        night: Callable[[], tuple[str, str]],
        on_change: Callable[[], Awaitable[None]],
    ) -> None:
        """Initialize; `night` returns the panel's (start, end), `on_change` pushes settings."""
        self._hass = hass
        self._coordinator = coordinator
        self._night = night
        self._on_change = on_change
        self.minutes = 0
        self._ends_at = 0.0  # time.monotonic()
        self._original_volume: int | None = None
        self._fading = False
        self._unsub_tick: CALLBACK_TYPE | None = None
        self._unsub_recover: CALLBACK_TYPE | None = None

    @property
    def remaining_s(self) -> int:
        """Seconds left, 0 when inactive."""
        if not self.minutes:
            return 0
        return max(0, int(self._ends_at - time.monotonic()))

    async def async_start(self, minutes: int) -> None:
        """Start (or restart) the timer."""
        await self.async_cancel(push=False)
        self._cancel_recovery()
        self.minutes = minutes
        self._ends_at = time.monotonic() + minutes * 60
        self._original_volume = None  # taken when the fade starts
        self._unsub_tick = async_track_time_interval(self._hass, self._async_tick, TICK)
        LOGGER.debug("Sleep timer started: %s min", minutes)
        await self._on_change()

    async def async_cancel(self, push: bool = True) -> None:
        """Stop the timer; undo a fade that already started."""
        if self._unsub_tick:
            self._unsub_tick()
            self._unsub_tick = None
        was_fading = self._fading
        self._fading = False
        self.minutes = 0
        if was_fading and self._original_volume is not None:
            await self._async_set_volume(self._original_volume)
        if push:
            await self._on_change()

    @callback
    def async_stop(self) -> None:
        """Integration unload: drop all scheduled work."""
        if self._unsub_tick:
            self._unsub_tick()
            self._unsub_tick = None
        self._cancel_recovery()

    async def _async_tick(self, _now: Any) -> None:
        remaining = self.remaining_s
        if remaining <= 0:
            await self._async_finish()
            return
        if remaining <= FADE_S:
            if not self._fading:
                # Fade from the volume at this moment (it may have changed since the start)
                self._fading = True
                device = (self._coordinator.data or {}).get("device") or {}
                self._original_volume = device.get("volume_percent")
            if self._original_volume:
                await self._async_set_volume(round(self._original_volume * remaining / FADE_S))
        await self._on_change()  # keep the panel's countdown in sync

    async def _async_finish(self) -> None:
        if self._unsub_tick:
            self._unsub_tick()
            self._unsub_tick = None
        self._fading = False
        self.minutes = 0
        try:
            await self._coordinator.api.pause()
        except SpotifyApiError as err:
            LOGGER.debug("Sleep timer could not pause: %s", err)
        LOGGER.debug("Sleep timer ended; volume recovers in %s s", RECOVER_AFTER_S)
        self._cancel_recovery()
        self._unsub_recover = async_call_later(self._hass, RECOVER_AFTER_S, self._recover)
        await self._on_change()
        await self._coordinator.async_request_refresh()

    @callback
    def _recover(self, _now: Any) -> None:
        self._unsub_recover = None
        start, end = self._night()
        if is_night(dt_util.now(), start, end):
            volume = NIGHT_VOLUME
        else:
            volume = min(self._original_volume or DAY_VOLUME_CAP, DAY_VOLUME_CAP)
        self._hass.async_create_task(self._async_set_volume(volume))

    def _cancel_recovery(self) -> None:
        if self._unsub_recover:
            self._unsub_recover()
            self._unsub_recover = None

    async def _async_set_volume(self, volume: int) -> None:
        try:
            await self._coordinator.api.set_volume(volume)
        except SpotifyApiError as err:
            # e.g. no active device after the pause; nothing to adjust then
            LOGGER.debug("Sleep timer could not set volume %s: %s", volume, err)

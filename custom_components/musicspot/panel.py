"""Panel runtime: push Spotify state to an ESPHome panel and act on its input events.

Protocol: docs/panel-protocol.md. The panel only knows slot numbers (D11); this class
keeps the matching Spotify ids.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .api import SpotifyApiError, SpotifyNotFoundError
from .art import ArtStore
from .const import (
    ART_SIZE_NOW,
    CONF_ART_BASE_URL,
    CONF_DEFAULT_DEVICE,
    CONF_DEVICE_ID,
    ESPHOME_DOMAIN,
    LOGGER,
)

if TYPE_CHECKING:
    from .coordinator import MusicSpotCoordinator

# Re-push now-playing when the panel's interpolated position is off by more than this.
_POSITION_TOLERANCE_MS = 2500
# Spotify needs a moment before a command shows up in /me/player.
_REFRESH_DELAY_S = 0.5
# After a seek, Spotify may still report the old position; don't push it back to the panel.
_SEEK_GRACE_S = 4.0
_REPEAT_CYCLE = {"off": "context", "context": "track", "track": "off"}
_MAX_DEVICES = 5


@callback
def async_resolve_action_prefix(hass: HomeAssistant, device_id: str) -> str | None:
    """Return the ESPHome action prefix (e.g. `musicspot_1`) if the device runs MusicSpot."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != ESPHOME_DOMAIN:
            continue
        name = entry.data.get("device_name")
        if not name:
            continue
        prefix = name.replace("-", "_")
        if hass.services.has_service(ESPHOME_DOMAIN, f"{prefix}_show_now_playing"):
            return prefix
    return None


class MusicSpotPanel:
    """One ESPHome panel linked to one Spotify account."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: MusicSpotCoordinator,
        subentry: ConfigSubentry,
        art_store: ArtStore,
    ) -> None:
        """Initialize the panel."""
        self.hass = hass
        self.coordinator = coordinator
        self.key = subentry.subentry_id
        self.device_id: str = subentry.data[CONF_DEVICE_ID]
        self.title = subentry.title
        self._art_base_url: str = subentry.data.get(CONF_ART_BASE_URL) or ""
        self._default_device: str = subentry.data.get(CONF_DEFAULT_DEVICE) or ""
        self._art_store = art_store
        self._token = secrets.token_urlsafe(16)
        self._unsub_coordinator: Any = None

        self._last_np: dict[str, Any] | None = None
        self._last_np_at = 0.0
        self._art_src: str | None = None
        self._art_url = ""
        self._device_ids: list[str] = []
        self._shown_active_device: str | None = None
        self._seek_grace_until = 0.0
        self._push_lock = asyncio.Lock()

    # ---- lifecycle -------------------------------------------------------

    async def async_start(self) -> None:
        """Start following playback and push the current state."""
        self._art_store.register(self._token)
        self._unsub_coordinator = self.coordinator.async_add_listener(
            self._handle_coordinator_update
        )
        await self.async_push_all()

    @callback
    def async_stop(self) -> None:
        """Stop following playback."""
        if self._unsub_coordinator:
            self._unsub_coordinator()
            self._unsub_coordinator = None
        self.coordinator.set_awake(self.key, False)
        self._art_store.unregister(self._token)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Push now-playing after every poll (only sent when something changed).

        Also refresh the device list when playback moved to another device,
        e.g. from the Spotify app on a phone.
        """
        self.hass.async_create_task(self.async_push_now_playing())
        active = ((self.coordinator.data or {}).get("device") or {}).get("id")
        if active != self._shown_active_device:
            self._shown_active_device = active
            self.hass.async_create_task(self.async_push_devices())

    # ---- outbound --------------------------------------------------------

    async def _call(self, action: str, data: dict[str, Any]) -> None:
        """Call an API action on the panel; skip quietly when it is offline."""
        prefix = async_resolve_action_prefix(self.hass, self.device_id)
        if prefix is None:
            LOGGER.debug("Panel %s is not reachable; skipping %s", self.title, action)
            return
        try:
            await self.hass.services.async_call(
                ESPHOME_DOMAIN, f"{prefix}_{action}", data, blocking=True
            )
        except HomeAssistantError as err:
            LOGGER.warning("Could not send %s to panel %s: %s", action, self.title, err)

    async def async_push_all(self) -> None:
        """Push everything (panel connected or woke up)."""
        await self.async_push_now_playing(force=True)
        await self.async_push_devices()

    async def async_push_now_playing(self, force: bool = False) -> None:
        """Send now-playing if it changed or the panel's progress drifted."""
        async with self._push_lock:
            payload = await self._build_now_playing(self.coordinator.data)
            if not force and not self._needs_push(payload):
                return
            self._last_np = payload
            self._last_np_at = time.monotonic()
            await self._call("show_now_playing", payload)

    def _needs_push(self, payload: dict[str, Any]) -> bool:
        """Compare with what the panel shows, allowing for local interpolation."""
        last = self._last_np
        if last is None:
            return True
        if {k: v for k, v in payload.items() if k != "position_ms"} != {
            k: v for k, v in last.items() if k != "position_ms"
        }:
            return True
        if time.monotonic() < self._seek_grace_until:
            return False
        expected = last["position_ms"]
        if last["state"] == "playing":
            expected += int((time.monotonic() - self._last_np_at) * 1000)
        return abs(payload["position_ms"] - expected) > _POSITION_TOLERANCE_MS

    async def _build_now_playing(self, data: dict[str, Any] | None) -> dict[str, Any]:
        """Translate Spotify playback state into the show_now_playing payload."""
        device = (data or {}).get("device") or {}
        item = (data or {}).get("item")
        payload: dict[str, Any] = {
            "title": "",
            "artist": "",
            "album": "",
            "art_url": "",
            "state": "idle",
            "position_ms": 0,
            "duration_ms": 0,
            "volume": int(device.get("volume_percent") or 0),
            "shuffle": bool((data or {}).get("shuffle_state")),
            "repeat": (data or {}).get("repeat_state") or "off",
        }
        if not data or not item:
            return payload

        if item.get("type") == "episode":
            show = item.get("show") or {}
            artist = show.get("name", "")
            album = ""
            images = item.get("images") or show.get("images") or []
        else:
            artist = ", ".join(a.get("name", "") for a in item.get("artists", []))
            album = (item.get("album") or {}).get("name", "")
            images = (item.get("album") or {}).get("images") or []

        payload.update(
            title=item.get("name", ""),
            artist=artist,
            album=album,
            art_url=await self._art_for(images),
            state="playing" if data.get("is_playing") else "paused",
            position_ms=int(data.get("progress_ms") or 0),
            duration_ms=int(item.get("duration_ms") or 0),
        )
        return payload

    async def _art_for(self, images: list[dict[str, Any]]) -> str:
        """Return the panel URL for the cover, preparing it when the track changed."""
        src = _pick_image(images, ART_SIZE_NOW)
        if src == self._art_src:
            return self._art_url
        self._art_src = src
        self._art_url = ""
        if src:
            version = await self._art_store.async_set_from_url(
                self._token, "now.jpg", src, ART_SIZE_NOW
            )
            base = self._base_url()
            if version and base:
                self._art_url = (
                    f"{base}/api/musicspot/art/{self._token}/now.jpg?v={version}"
                )
        return self._art_url

    def _base_url(self) -> str:
        """URL the panel uses to reach Home Assistant (prefer plain LAN HTTP, D9)."""
        if self._art_base_url:
            return self._art_base_url
        try:
            return get_url(
                self.hass, allow_external=False, allow_cloud=False, prefer_external=False
            )
        except NoURLAvailableError:
            LOGGER.warning(
                "No internal URL for album art; set 'Album art base URL' on panel %s",
                self.title,
            )
            return ""

    async def async_push_devices(self) -> None:
        """Send the Spotify Connect device list.

        Spotify's Web API stops listing some devices (notably Google Cast speakers)
        once they are idle, so devices seen earlier are kept and appended (D15).
        """
        try:
            listed = await self.coordinator.api.get_devices()
        except SpotifyApiError as err:
            LOGGER.warning("Could not list Spotify devices: %s", err)
            return
        listed = [d for d in listed if d.get("id")]
        known = self.coordinator.remember_devices(listed)
        active_id = next((d["id"] for d in listed if d.get("is_active")), None) or (
            ((self.coordinator.data or {}).get("device") or {}).get("id")
        )

        names = {d["id"]: d.get("name") or "?" for d in listed}
        ids = [d["id"] for d in listed]
        for device_id, name in known.items():
            if device_id not in names:
                names[device_id] = name
                ids.append(device_id)
        ids = ids[:_MAX_DEVICES]

        self._device_ids = ids
        self._shown_active_device = active_id
        await self._call(
            "show_devices",
            {
                "names": [names[i] for i in ids],
                "active": ids.index(active_id) if active_id in ids else -1,
            },
        )

    # ---- inbound ---------------------------------------------------------

    async def async_handle_input(self, type_: str, arg: str, value: int) -> None:
        """Act on a panel input event."""
        LOGGER.debug("Panel %s input: %s %s %s", self.title, type_, arg, value)
        if type_ == "hello":
            await self.async_push_all()
        elif type_ == "awake":
            self.coordinator.set_awake(self.key, value == 1)
            if value == 1:
                await self.async_push_devices()
        elif type_ == "control":
            await self._async_control(arg, value)
        elif type_ == "device":
            await self._async_transfer(value)
        else:
            LOGGER.debug("Input type %s is not handled yet", type_)

    async def _async_control(self, command: str, value: int) -> None:
        """Run a transport/volume command, then refresh."""
        api = self.coordinator.api
        data = self.coordinator.data or {}
        try:
            if command == "play_pause":
                if data.get("is_playing"):
                    await api.pause()
                else:
                    await self._async_play()
            elif command == "next":
                await api.next_track()
            elif command == "previous":
                await api.previous_track()
            elif command == "shuffle":
                await api.set_shuffle(not data.get("shuffle_state"))
            elif command == "repeat":
                await api.set_repeat(
                    _REPEAT_CYCLE.get(data.get("repeat_state") or "off", "off")
                )
            elif command == "volume":
                await api.set_volume(value)
            elif command == "seek":
                await api.seek(value)
                # The panel already jumped; treat that as what it shows.
                if self._last_np is not None:
                    self._last_np["position_ms"] = value
                    self._last_np_at = time.monotonic()
                self._seek_grace_until = time.monotonic() + _SEEK_GRACE_S
            else:
                LOGGER.debug("Unknown control command %s", command)
                return
        except SpotifyNotFoundError:
            LOGGER.info("No active Spotify device for %s; pick one on the panel", command)
            await self.async_push_devices()
        except SpotifyApiError as err:
            LOGGER.warning("Spotify rejected %s: %s", command, err)
        await self._async_refresh_soon()

    async def _async_play(self) -> None:
        """Resume; fall back to the default device when nothing is active."""
        try:
            await self.coordinator.api.play()
        except SpotifyNotFoundError:
            device_id = await self._default_device_id()
            if device_id is None:
                raise
            await self.coordinator.api.transfer_playback(device_id, play=True)

    async def _default_device_id(self) -> str | None:
        """Look up the configured default device by name."""
        if not self._default_device:
            return None
        wanted = self._default_device.casefold()
        for device in await self.coordinator.api.get_devices():
            if device.get("id") and (device.get("name") or "").casefold() == wanted:
                return device["id"]
        LOGGER.info("Default device %s is not available", self._default_device)
        return None

    async def _async_transfer(self, slot: int) -> None:
        """Move playback to the device in a slot (1-based)."""
        if not 1 <= slot <= len(self._device_ids):
            return
        device_id = self._device_ids[slot - 1]
        try:
            await self.coordinator.api.transfer_playback(device_id)
        except SpotifyNotFoundError:
            LOGGER.info(
                "Spotify no longer offers %s; start playback on it once from the "
                "Spotify app to make it available again",
                self.coordinator.known_devices.get(device_id, device_id),
            )
            self.coordinator.forget_device(device_id)
        except SpotifyApiError as err:
            LOGGER.warning("Could not transfer playback: %s", err)
        await self._async_refresh_soon()
        await self.async_push_devices()

    async def _async_refresh_soon(self) -> None:
        """Give Spotify a moment, then poll so the panel updates quickly."""
        await asyncio.sleep(_REFRESH_DELAY_S)
        await self.coordinator.async_refresh()


def _pick_image(images: list[dict[str, Any]], size: int) -> str | None:
    """Pick the smallest image at least `size` px wide (Spotify sends 640/300/64)."""
    candidates = [i for i in images if i.get("url")]
    if not candidates:
        return None
    big_enough = [i for i in candidates if (i.get("width") or 0) >= size]
    if big_enough:
        return min(big_enough, key=lambda i: i.get("width") or 0)["url"]
    return max(candidates, key=lambda i: i.get("width") or 0)["url"]

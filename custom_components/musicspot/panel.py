"""Panel runtime: push Spotify state to an ESPHome panel and act on its input events.

Protocol: docs/panel-protocol.md. The panel only knows slot numbers (D11); this class
keeps the matching Spotify ids.
"""

from __future__ import annotations

import asyncio
import math
import secrets
import time
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .api import SpotifyApiError, SpotifyNotFoundError
from .art import ArtStore
from .browse import GRID_SIZE, Browser, Row, _duration
from .const import (
    ART_SIZE_NOW,
    ART_SIZE_THUMB,
    ART_SIZE_TILE,
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
_QUEUE_PAGE = 5  # Up next rows per page (design C)
# The panel shows shuffle/like/play-pause taps at once and ignores our state for 4 s; re-send after that
_RECONCILE_S = 4.5
# First push after setup: wait up to 2 minutes for the panel's ESPHome actions.
_REACHABLE_TRIES = 24
_REACHABLE_INTERVAL_S = 5
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
        self._browser = Browser(
            coordinator.api, coordinator.config_entry.unique_id or ""
        )
        self._browse_lock = asyncio.Lock()
        self._mismatch_logged = False
        self._https_warned = False
        self._context_names: dict[str, str] = {}
        self._liked: dict[str, bool] = {}
        self._liked_current = ""
        self._queue: list[dict[str, Any]] = []
        self._queue_page = 1

    # ---- lifecycle -------------------------------------------------------

    async def async_start(self) -> None:
        """Start following playback and push the current state."""
        self._art_store.register(self._token)
        self._unsub_coordinator = self.coordinator.async_add_listener(
            self._handle_coordinator_update
        )
        # Don't hold up (or fail) integration setup on the panel; it also asks with `hello`.
        self.coordinator.config_entry.async_create_background_task(
            self.hass, self._async_push_when_reachable(), f"musicspot push {self.title}"
        )

    async def _async_push_when_reachable(self) -> None:
        """Push once the panel's actions exist (after an HA restart ESPHome connects later)."""
        for _ in range(_REACHABLE_TRIES):
            if async_resolve_action_prefix(self.hass, self.device_id) is not None:
                await self.async_push_all()
                return
            await asyncio.sleep(_REACHABLE_INTERVAL_S)
        LOGGER.info("Panel %s did not come online; waiting for its hello", self.title)

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
        except Exception as err:  # noqa: BLE001 - schema errors must never break setup
            # The action's schema comes from the panel firmware; a rejected field means
            # firmware and integration speak different protocol versions.
            if not self._mismatch_logged:
                self._mismatch_logged = True
                LOGGER.warning(
                    "Panel %s rejected %s (%s). Its firmware does not match this MusicSpot "
                    "version; flash the matching firmware from the repository",
                    self.title,
                    action,
                    err,
                )

    async def async_push_all(self) -> None:
        """Push everything (panel connected or woke up)."""
        await self.async_push_now_playing(force=True)
        await self.async_push_devices()
        await self.async_push_browse()

    async def async_push_browse(self) -> None:
        """Load the current browse page and send it with its thumbnails."""
        async with self._browse_lock:
            await self._call("set_busy", {"busy": True})
            try:
                page = await self._browser.async_load()
            except SpotifyApiError as err:
                LOGGER.warning("Could not load %s: %s", self._browser.node.title, err)
                await self._call("set_busy", {"busy": False})
                await self.async_toast("Spotify didn't answer, try again")
                return
            size = ART_SIZE_TILE if page.grid else ART_SIZE_THUMB
            thumbs = await asyncio.gather(
                *(self._thumb_url(i, row, size) for i, row in enumerate(page.rows, 1))
            )
            nums: list[str] = []
            number = page.first_number
            for row in page.rows:
                if row.play_all:
                    nums.append("")
                else:
                    nums.append(f"{number:02d}")
                    number += 1
            playing_album = (
                ((self.coordinator.data or {}).get("item") or {}).get("album") or {}
            ).get("uri")
            # Hide the spinner first: the panel's image downloads that follow show_page run
            # in its main loop and would leave a frozen spinner on screen.
            await self._call("set_busy", {"busy": False})
            await self._call(
                "show_page",
                {
                    "title": page.title,
                    "tab": page.tab,
                    "page": page.page,
                    "pages": page.pages,
                    "can_back": page.can_back,
                    "grid": page.grid,
                    "now_index": next(
                        (
                            i
                            for i, row in enumerate(page.rows)
                            if playing_album and row.album_uri == playing_album
                        ),
                        -1,
                    ),
                    "nums": nums,
                    "titles": [row.title for row in page.rows],
                    "subtitles": [row.subtitle for row in page.rows],
                    "counts": [row.count for row in page.rows],
                    "thumbs": list(thumbs),
                },
            )

    async def _thumb_url(self, slot: int, row: Row, size: int) -> str:
        """Prepare a row thumbnail and return its panel URL ('' for none)."""
        base = self._base_url()
        if not row.image or not base:
            return ""
        name = f"t{slot}_{size}.jpg"
        version = await self._art_store.async_set_from_url(
            self._token, name, row.image, size
        )
        if not version:
            return ""
        return f"{base}/api/musicspot/art/{self._token}/{name}?v={version}"

    async def async_toast(self, text: str) -> None:
        """Show a short message on the panel."""
        await self._call("show_toast", {"message": text})

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
            "context": "",
            "device": (device.get("name") or "").upper(),
            "art_url": "",
            "state": "idle",
            "position_ms": 0,
            "duration_ms": 0,
            "volume": int(device.get("volume_percent") or 0),
            "shuffle": bool((data or {}).get("shuffle_state")),
            "liked": False,
        }
        if not data or not item:
            return payload

        if item.get("type") == "episode":
            show = item.get("show") or {}
            artist = show.get("name", "")
            images = item.get("images") or show.get("images") or []
        else:
            artist = ", ".join(a.get("name", "") for a in item.get("artists", []))
            images = (item.get("album") or {}).get("images") or []

        payload.update(
            title=item.get("name", ""),
            artist=artist,
            context=await self._context_text(data),
            art_url=await self._art_for(images),
            state="playing" if data.get("is_playing") else "paused",
            position_ms=int(data.get("progress_ms") or 0),
            duration_ms=int(item.get("duration_ms") or 0),
            liked=await self._is_liked(item.get("uri") or ""),
        )
        return payload

    async def _context_text(self, data: dict[str, Any]) -> str:
        """Header above the cover (D20): TRACK nn / NN for albums, else the context name."""
        item = data.get("item") or {}
        context = data.get("context") or {}
        kind, uri = context.get("type"), context.get("uri") or ""
        album = item.get("album") or {}
        if kind == "album" or (not kind and album.get("total_tracks")):
            number, total = item.get("track_number"), album.get("total_tracks")
            if number and total:
                return f"TRACK {number:02d} / {total:02d}"
        if kind == "collection" or uri.endswith(":collection"):
            return "LIKED SONGS"
        if uri and kind in ("playlist", "artist", "show"):
            if uri not in self._context_names:
                name = ""
                try:
                    object_id = uri.rsplit(":", 1)[-1]
                    if kind == "playlist":
                        name = await self.coordinator.api.get_playlist_name(object_id)
                    elif kind == "artist":
                        name = (await self.coordinator.api.get_artist(object_id)).get("name", "")
                    else:
                        name = ((item.get("show") or {}).get("name")) or ""
                except SpotifyApiError as err:
                    LOGGER.debug("Could not name context %s: %s", uri, err)
                self._context_names[uri] = name.upper()
            return self._context_names[uri]
        return ""

    async def _is_liked(self, uri: str) -> bool:
        """Whether the track is in Liked Songs (cached per track)."""
        if not uri:
            return False
        if uri != self._liked_current:
            # New current track: ask Spotify again (it may have been liked on another device)
            self._liked_current = uri
            self._liked.pop(uri, None)
        if uri not in self._liked:
            try:
                result = await self.coordinator.api.library_contains([uri])
                self._liked[uri] = bool(result and result[0])
            except SpotifyApiError as err:
                LOGGER.debug("Could not check library for %s: %s", uri, err)
                return False
        return self._liked[uri]

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
        url = self._art_base_url
        if not url:
            try:
                url = get_url(
                    self.hass, allow_external=False, allow_cloud=False, prefer_external=False
                )
            except NoURLAvailableError:
                LOGGER.warning(
                    "No internal URL for album art; set 'Album art base URL' on panel %s",
                    self.title,
                )
                return ""
        if url.startswith("https://") and not self._https_warned:
            # A TLS handshake per image blocks the panel's main loop for about a second (P1.5)
            self._https_warned = True
            LOGGER.warning(
                "Panel %s loads album art over HTTPS (%s), which makes it freeze while images "
                "load. Reconfigure the panel with a plain-HTTP LAN address, e.g. "
                "http://<home-assistant-ip>:8123",
                self.title,
                url,
            )
        return url

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
        elif type_ == "tap":
            await self._async_tap(value)
        elif type_ == "queue":
            await self._async_queue(value)
        elif type_ == "back":
            if self._browser.back():
                await self.async_push_browse()
        elif type_ == "page":
            self._browser.turn_page(1 if value > 0 else -1)
            await self.async_push_browse()
        elif type_ == "tab":
            self._browser.select_tab(value)
            await self.async_push_browse()
        elif type_ == "queue_view":
            await self._async_load_queue()
            self._queue_page = 1
            await self.async_push_queue()
        elif type_ == "queue_page":
            self._queue_page = max(1, self._queue_page + (1 if value > 0 else -1))
            await self.async_push_queue()
        else:
            LOGGER.debug("Input type %s is not handled yet", type_)

    async def _async_load_queue(self) -> None:
        """Fetch the user queue (read-only; Spotify returns up to ~20 upcoming items)."""
        await self._call("set_busy", {"busy": True})
        try:
            data = await self.coordinator.api.get_queue()
        except SpotifyApiError as err:
            LOGGER.warning("Could not load the queue: %s", err)
            data = {}
        await self._call("set_busy", {"busy": False})
        self._queue = [item for item in data.get("queue") or [] if item and item.get("uri")]

    async def async_push_queue(self) -> None:
        """Send one page of Up next (5 rows)."""
        pages = max(1, math.ceil(len(self._queue) / _QUEUE_PAGE))
        self._queue_page = min(self._queue_page, pages)
        start = (self._queue_page - 1) * _QUEUE_PAGE
        items = self._queue[start : start + _QUEUE_PAGE]
        data = self.coordinator.data or {}
        now = data.get("item") or {}
        await self._call(
            "show_queue",
            {
                "context": await self._context_text(data) if now else "",
                "now_title": now.get("name", ""),
                "now_artist": _artists(now),
                "page": self._queue_page,
                "pages": pages,
                "nums": [f"{start + i + 1:02d}" for i in range(len(items))],
                "titles": [item.get("name", "?") for item in items],
                "artists": [_artists(item) for item in items],
                "durations": [_duration(item.get("duration_ms")) for item in items],
            },
        )

    def _row(self, slot: int) -> Row | None:
        """Row behind a 1-based slot of the page the panel shows."""
        if 1 <= slot <= min(GRID_SIZE, len(self._browser.rows)):
            return self._browser.rows[slot - 1]
        return None

    async def _async_tap(self, slot: int) -> None:
        """Open a folder, or play a row (in its context when possible)."""
        row = self._row(slot)
        if row is None:
            return
        if row.open is not None:
            self._browser.open(row.open)
            await self.async_push_browse()
            return
        try:
            if row.play_all:
                await self._async_play(context_uri=row.context_uri)
            elif row.context_uri:
                try:
                    await self._async_play(context_uri=row.context_uri, offset_uri=row.uri)
                except SpotifyNotFoundError:
                    raise
                except SpotifyApiError:
                    # e.g. the track is no longer in that context
                    await self._async_play(uris=[row.uri])
            else:
                await self._async_play(uris=[row.uri])
        except SpotifyNotFoundError:
            await self.async_toast("No active speaker - pick one in Setup")
            await self._call("show_screen", {"screen": "devices"})
            return
        except SpotifyApiError as err:
            LOGGER.warning("Could not play %s: %s", row.title, err)
            await self.async_toast("Spotify refused to play this")
            return
        await self._call("show_screen", {"screen": "now"})
        await self._async_refresh_soon()

    async def _async_queue(self, slot: int) -> None:
        """Add a track to the queue (Spotify has no 'play next')."""
        row = self._row(slot)
        if row is None:
            return
        if not row.uri:
            await self.async_toast("Only songs can be added to the queue")
            return
        try:
            await self.coordinator.api.add_to_queue(row.uri)
        except SpotifyNotFoundError:
            await self.async_toast("Start playback first, then queue songs")
            return
        except SpotifyApiError as err:
            LOGGER.warning("Could not queue %s: %s", row.title, err)
            await self.async_toast("Spotify refused to queue this")
            return
        await self.async_toast(f"Queued: {row.title}")

    async def _async_control(self, command: str, value: int) -> None:
        """Run a transport/volume command, then refresh."""
        api = self.coordinator.api
        data = self.coordinator.data or {}
        try:
            if command == "play_pause":
                self._schedule_reconcile()
                if data.get("is_playing"):
                    await api.pause()
                else:
                    await self._async_play()
            elif command == "next":
                await api.next_track()
            elif command == "previous":
                await api.previous_track()
            elif command == "shuffle":
                self._schedule_reconcile()
                await api.set_shuffle(not data.get("shuffle_state"))
            elif command == "like":
                self._schedule_reconcile()
                await self._async_toggle_like(data)
                return
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

    @callback
    def _schedule_reconcile(self) -> None:
        """Re-send the real state once the panel stops ignoring it (optimistic toggles)."""

        @callback
        def _reconcile(_now: Any) -> None:
            self.hass.async_create_task(self.async_push_now_playing(force=True))

        async_call_later(self.hass, _RECONCILE_S, _reconcile)

    async def _async_toggle_like(self, data: dict[str, Any]) -> None:
        """Save/remove the current track in Liked Songs and update the panel."""
        uri = (data.get("item") or {}).get("uri") or ""
        if not uri:
            return
        liked = await self._is_liked(uri)
        try:
            if liked:
                await self.coordinator.api.library_remove([uri])
            else:
                await self.coordinator.api.library_save([uri])
        except SpotifyApiError as err:
            LOGGER.warning("Could not update Liked Songs: %s", err)
            await self.async_toast("Spotify refused to change Liked Songs")
            return
        self._liked[uri] = not liked
        self._browser.invalidate_liked()
        # No toast: the ♥ on the panel already shows the new state (D34)
        await self.async_push_now_playing(force=True)

    async def _async_play(self, **kwargs: Any) -> None:
        """Play/resume; when nothing is active, use the default device if configured."""
        try:
            await self.coordinator.api.play(**kwargs)
        except SpotifyNotFoundError:
            device_id = await self._default_device_id()
            if device_id is None:
                raise
            if kwargs:
                await self.coordinator.api.play(device_id=device_id, **kwargs)
            else:
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


def _artists(item: dict[str, Any]) -> str:
    """Artist names of a track, or the show name of an episode."""
    if item.get("type") == "episode":
        return (item.get("show") or {}).get("name", "")
    return ", ".join(a.get("name", "") for a in item.get("artists", []))

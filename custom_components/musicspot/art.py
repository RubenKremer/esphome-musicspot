"""Album art for panels: fetch from Spotify, resize to the exact widget size, serve over HTTP.

Panels cannot send auth headers, so each panel gets an unguessable token in the URL
(regenerated on every restart). Only album covers are served, which are public anyway (D13).
"""

from __future__ import annotations

from collections import OrderedDict
import hashlib
import io

from aiohttp import ClientError, web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import LOGGER

_RESIZE_CACHE_SIZE = 48


class ArtStore:
    """Per-panel image slots plus a small resize cache shared by all panels."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the store."""
        self._hass = hass
        self._slots: dict[str, dict[str, bytes]] = {}
        self._resized: OrderedDict[tuple[str, int], bytes] = OrderedDict()

    def register(self, token: str) -> None:
        """Create image slots for a panel."""
        self._slots[token] = {}

    def unregister(self, token: str) -> None:
        """Drop a panel's image slots."""
        self._slots.pop(token, None)

    def get(self, token: str, name: str) -> bytes | None:
        """Return the image in a slot."""
        return self._slots.get(token, {}).get(name)

    async def async_set_from_url(
        self, token: str, name: str, url: str, size: int
    ) -> str | None:
        """Fetch, resize and store an image; return a short version hash or None on error."""
        if token not in self._slots:
            return None
        key = (url, size)
        data = self._resized.get(key)
        if data is None:
            try:
                session = async_get_clientsession(self._hass)
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    raw = await resp.read()
                data = await self._hass.async_add_executor_job(_resize_jpeg, raw, size)
            except (ClientError, OSError, ValueError) as err:
                LOGGER.warning("Could not prepare album art %s: %s", url, err)
                return None
            self._resized[key] = data
            while len(self._resized) > _RESIZE_CACHE_SIZE:
                self._resized.popitem(last=False)
        else:
            self._resized.move_to_end(key)
        self._slots[token][name] = data
        return hashlib.sha1(url.encode()).hexdigest()[:10]


def _resize_jpeg(raw: bytes, size: int) -> bytes:
    """Crop/resize to size×size and encode as baseline JPEG (ESPHome can't decode progressive)."""
    from PIL import Image, ImageOps  # noqa: PLC0415

    with Image.open(io.BytesIO(raw)) as img:
        fitted = ImageOps.fit(img.convert("RGB"), (size, size), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    fitted.save(out, "JPEG", quality=85, optimize=True, progressive=False)
    return out.getvalue()


class MusicSpotArtView(HomeAssistantView):
    """Serve panel album art without authentication (token in the path)."""

    url = "/api/musicspot/art/{token}/{name}"
    name = "api:musicspot:art"
    requires_auth = False

    def __init__(self, store: ArtStore) -> None:
        """Initialize the view."""
        self._store = store

    async def get(self, request: web.Request, token: str, name: str) -> web.Response:
        """Return the image or 404."""
        data = self._store.get(token, name)
        if data is None:
            return web.Response(status=404)
        return web.Response(
            body=data, content_type="image/jpeg", headers={"Cache-Control": "no-cache"}
        )

"""Minimal Spotify Web API client for MusicSpot.

Only the endpoints MusicSpot uses, written against the February 2026 Web API
(development mode). Kept dependency-free so Spotify API changes can be handled here
without waiting for a library release.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from aiohttp import ClientError, ClientSession

from homeassistant.helpers import config_entry_oauth2_flow

from .const import API_BASE


class SpotifyApiError(Exception):
    """Spotify returned an error or could not be reached."""


class SpotifyAuthError(SpotifyApiError):
    """The token was rejected (401)."""


class SpotifyForbiddenError(SpotifyApiError):
    """The request was forbidden (403), e.g. no Premium or user not added to the app."""


class SpotifyNotFoundError(SpotifyApiError):
    """Resource or active device not found (404)."""


class SpotifyRateLimitError(SpotifyApiError):
    """Rate limited or quota exceeded (429)."""

    def __init__(self, retry_after: int, message: str) -> None:
        """Store how long Spotify asked us to wait."""
        super().__init__(message)
        self.retry_after = retry_after


class TokenProvider(Protocol):
    """Something that can hand out a valid access token."""

    async def async_get_access_token(self) -> str:
        """Return a valid access token."""


class OAuthTokenProvider:
    """Token provider backed by Home Assistant's OAuth2 session (auto refresh)."""

    def __init__(self, session: config_entry_oauth2_flow.OAuth2Session) -> None:
        """Wrap the OAuth2 session."""
        self._session = session

    async def async_get_access_token(self) -> str:
        """Refresh if needed and return the access token."""
        await self._session.async_ensure_token_valid()
        return self._session.token["access_token"]


class StaticTokenProvider:
    """Token provider for a token that is known to be fresh (config flow)."""

    def __init__(self, token: str) -> None:
        """Store the token."""
        self._token = token

    async def async_get_access_token(self) -> str:
        """Return the token."""
        return self._token


class MusicSpotApi:
    """Spotify Web API calls used by MusicSpot."""

    def __init__(self, websession: ClientSession, tokens: TokenProvider) -> None:
        """Initialize the client."""
        self._websession = websession
        self._tokens = tokens

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Make a request and return the decoded JSON body, or None for empty bodies."""
        token = await self._tokens.async_get_access_token()
        try:
            async with self._websession.request(
                method,
                f"{API_BASE}{path}",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
                json=body,
            ) as resp:
                text = await resp.text()
                if resp.status == 401:
                    raise SpotifyAuthError(text)
                if resp.status == 403:
                    raise SpotifyForbiddenError(text)
                if resp.status == 404:
                    raise SpotifyNotFoundError(text)
                if resp.status == 429:
                    raise SpotifyRateLimitError(
                        int(resp.headers.get("Retry-After", "30")), text
                    )
                if resp.status >= 400:
                    raise SpotifyApiError(f"HTTP {resp.status}: {text}")
        except ClientError as err:
            raise SpotifyApiError(f"Error talking to Spotify: {err}") from err
        if not text:
            return None
        return json.loads(text)

    # ---- user -------------------------------------------------------------

    async def get_me(self) -> dict[str, Any]:
        """Return the current user profile."""
        return await self._request("GET", "/me")

    # ---- player state -----------------------------------------------------

    async def get_playback(self) -> dict[str, Any] | None:
        """Return playback state, or None when nothing is active (204)."""
        return await self._request(
            "GET", "/me/player", params={"additional_types": "episode"}
        )

    async def get_devices(self) -> list[dict[str, Any]]:
        """Return the available Spotify Connect devices."""
        data = await self._request("GET", "/me/player/devices")
        return (data or {}).get("devices", [])

    async def get_queue(self) -> dict[str, Any]:
        """Return the currently playing item and the user queue (read-only)."""
        return await self._request("GET", "/me/player/queue") or {}

    # ---- player control ---------------------------------------------------

    async def play(
        self,
        *,
        device_id: str | None = None,
        context_uri: str | None = None,
        uris: list[str] | None = None,
        offset_uri: str | None = None,
    ) -> None:
        """Start or resume playback, optionally of a context or list of tracks."""
        body: dict[str, Any] = {}
        if context_uri:
            body["context_uri"] = context_uri
        if uris:
            body["uris"] = uris
        if offset_uri:
            body["offset"] = {"uri": offset_uri}
        await self._request(
            "PUT",
            "/me/player/play",
            params={"device_id": device_id} if device_id else None,
            body=body or None,
        )

    async def pause(self) -> None:
        """Pause playback."""
        await self._request("PUT", "/me/player/pause")

    async def next_track(self) -> None:
        """Skip to the next track."""
        await self._request("POST", "/me/player/next")

    async def previous_track(self) -> None:
        """Skip to the previous track."""
        await self._request("POST", "/me/player/previous")

    async def seek(self, position_ms: int) -> None:
        """Seek within the current track."""
        await self._request(
            "PUT", "/me/player/seek", params={"position_ms": max(0, int(position_ms))}
        )

    async def set_volume(self, volume_percent: int) -> None:
        """Set the volume of the active device (0-100)."""
        await self._request(
            "PUT",
            "/me/player/volume",
            params={"volume_percent": min(100, max(0, int(volume_percent)))},
        )

    async def set_shuffle(self, state: bool) -> None:
        """Turn shuffle on or off."""
        await self._request(
            "PUT", "/me/player/shuffle", params={"state": "true" if state else "false"}
        )

    async def set_repeat(self, state: str) -> None:
        """Set repeat mode: off, context or track."""
        await self._request("PUT", "/me/player/repeat", params={"state": state})

    async def transfer_playback(self, device_id: str, play: bool = True) -> None:
        """Move playback to another device."""
        await self._request(
            "PUT", "/me/player", body={"device_ids": [device_id], "play": play}
        )

    async def add_to_queue(self, uri: str) -> None:
        """Append a track or episode to the user queue (no 'play next' in the API)."""
        await self._request("POST", "/me/player/queue", params={"uri": uri})

    # ---- library (paged) --------------------------------------------------

    async def get_playlists(self, limit: int, offset: int) -> dict[str, Any]:
        """Return a page of the user's playlists."""
        return await self._request(
            "GET", "/me/playlists", params={"limit": limit, "offset": offset}
        )

    async def get_playlist_items(
        self, playlist_id: str, limit: int, offset: int
    ) -> dict[str, Any]:
        """Return a page of items of a playlist the user owns or collaborates on."""
        return await self._request(
            "GET",
            f"/playlists/{playlist_id}/items",
            params={"limit": limit, "offset": offset, "additional_types": "episode"},
        )

    async def get_saved_tracks(self, limit: int, offset: int) -> dict[str, Any]:
        """Return a page of Liked Songs."""
        return await self._request(
            "GET", "/me/tracks", params={"limit": limit, "offset": offset}
        )

    async def get_saved_albums(self, limit: int, offset: int) -> dict[str, Any]:
        """Return a page of saved albums."""
        return await self._request(
            "GET", "/me/albums", params={"limit": limit, "offset": offset}
        )

    async def get_album_tracks(
        self, album_id: str, limit: int, offset: int
    ) -> dict[str, Any]:
        """Return a page of tracks of an album."""
        return await self._request(
            "GET",
            f"/albums/{album_id}/tracks",
            params={"limit": limit, "offset": offset},
        )

    async def get_recently_played(self, limit: int) -> dict[str, Any]:
        """Return recently played tracks (cursor based, newest first)."""
        return await self._request(
            "GET", "/me/player/recently-played", params={"limit": limit}
        )

    async def search(
        self, query: str, types: list[str], limit: int, offset: int
    ) -> dict[str, Any]:
        """Search the catalog (development mode: limit max 10)."""
        return await self._request(
            "GET",
            "/search",
            params={
                "q": query,
                "type": ",".join(types),
                "limit": min(limit, 10),
                "offset": offset,
            },
        )

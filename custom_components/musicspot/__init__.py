"""MusicSpot: Spotify control for ESPHome touch panels."""

from __future__ import annotations

from aiohttp import ClientError, ClientResponseError

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MusicSpotApi, OAuthTokenProvider, SpotifyApiError, SpotifyAuthError
from .const import SCOPES
from .coordinator import MusicSpotConfigEntry, MusicSpotCoordinator, MusicSpotData


async def async_setup_entry(hass: HomeAssistant, entry: MusicSpotConfigEntry) -> bool:
    """Set up a Spotify account."""
    implementation = (
        await config_entry_oauth2_flow.async_get_config_entry_implementation(
            hass, entry
        )
    )
    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)

    try:
        await session.async_ensure_token_valid()
    except ClientResponseError as err:
        if 400 <= err.status < 500:
            raise ConfigEntryAuthFailed("Spotify refresh token is no longer valid") from err
        raise ConfigEntryNotReady from err
    except ClientError as err:
        raise ConfigEntryNotReady from err

    granted = set(session.token.get("scope", "").split())
    if not set(SCOPES) <= granted:
        raise ConfigEntryAuthFailed("Spotify token is missing required scopes")

    api = MusicSpotApi(async_get_clientsession(hass), OAuthTokenProvider(session))
    try:
        user = await api.get_me()
    except SpotifyAuthError as err:
        raise ConfigEntryAuthFailed from err
    except SpotifyApiError as err:
        raise ConfigEntryNotReady from err

    coordinator = MusicSpotCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = MusicSpotData(api=api, coordinator=coordinator, user=user)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MusicSpotConfigEntry) -> bool:
    """Unload a Spotify account."""
    return True

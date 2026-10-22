"""MusicSpot: Spotify control for ESPHome touch panels."""

from __future__ import annotations

from aiohttp import ClientError, ClientResponseError

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_entry_oauth2_flow, config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import MusicSpotApi, OAuthTokenProvider, SpotifyApiError, SpotifyAuthError
from .art import ArtStore, MusicSpotArtView
from .const import DOMAIN, EVENT_PANEL_INPUT, LOGGER, SCOPES, SUBENTRY_PANEL
from .coordinator import MusicSpotConfigEntry, MusicSpotCoordinator, MusicSpotData
from .panel import MusicSpotPanel

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the album art view once for all accounts and panels."""
    store = ArtStore(hass)
    hass.data[DOMAIN] = store
    hass.http.register_view(MusicSpotArtView(store))
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MusicSpotConfigEntry) -> bool:
    """Set up a Spotify account and its panels."""
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

    panels = {
        panel.device_id: panel
        for panel in (
            MusicSpotPanel(hass, coordinator, subentry, hass.data[DOMAIN])
            for subentry in entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_PANEL
        )
    }
    entry.runtime_data = MusicSpotData(
        api=api, coordinator=coordinator, user=user, panels=panels
    )

    @callback
    def _handle_panel_input(event: Event) -> None:
        panel = panels.get(event.data.get("device_id"))
        if panel is None:
            return
        try:
            value = int(event.data.get("value") or 0)
        except ValueError:
            value = 0
        entry.async_create_background_task(
            hass,
            panel.async_handle_input(
                str(event.data.get("type") or ""), str(event.data.get("arg") or ""), value
            ),
            f"{DOMAIN} panel input",
        )

    entry.async_on_unload(hass.bus.async_listen(EVENT_PANEL_INPUT, _handle_panel_input))
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    for panel in panels.values():
        await panel.async_start()
        entry.async_on_unload(panel.async_stop)
    LOGGER.debug("%s: %d panel(s) linked", entry.title, len(panels))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: MusicSpotConfigEntry) -> None:
    """Reload when panels are added or removed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: MusicSpotConfigEntry) -> bool:
    """Unload a Spotify account."""
    return True

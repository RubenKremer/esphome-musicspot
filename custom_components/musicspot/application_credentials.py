"""Application credentials for MusicSpot (each user brings their own Spotify app)."""

from __future__ import annotations

from homeassistant.components.application_credentials import AuthorizationServer
from homeassistant.core import HomeAssistant

from .const import OAUTH2_AUTHORIZE, OAUTH2_TOKEN


async def async_get_authorization_server(hass: HomeAssistant) -> AuthorizationServer:
    """Return the Spotify authorization server."""
    return AuthorizationServer(authorize_url=OAUTH2_AUTHORIZE, token_url=OAUTH2_TOKEN)


async def async_get_description_placeholders(hass: HomeAssistant) -> dict[str, str]:
    """Return placeholders for the credentials dialog."""
    return {
        "developer_dashboard_url": "https://developer.spotify.com/dashboard",
        "redirect_url": "https://my.home-assistant.io/redirect/oauth",
    }

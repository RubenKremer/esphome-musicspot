"""Config flow for MusicSpot: one config entry per Spotify account."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlowResult,
    ConfigSubentryFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MusicSpotApi, SpotifyApiError, SpotifyForbiddenError, StaticTokenProvider
from .const import DOMAIN, SCOPES, SUBENTRY_PANEL
from .panel_flow import PanelSubentryFlowHandler


class MusicSpotFlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Handle the Spotify OAuth flow."""

    DOMAIN = DOMAIN
    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Panels are added as subentries of a Spotify account."""
        return {SUBENTRY_PANEL: PanelSubentryFlowHandler}

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return logging.getLogger(__name__)

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        """Request the scopes MusicSpot needs and always show the consent dialog."""
        return {"scope": " ".join(SCOPES), "show_dialog": "true"}

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Create (or update on reauth) the entry for the signed-in Spotify account."""
        api = MusicSpotApi(
            async_get_clientsession(self.hass),
            StaticTokenProvider(data["token"]["access_token"]),
        )
        try:
            me = await api.get_me()
        except SpotifyForbiddenError:
            return self.async_abort(reason="user_not_premium")
        except SpotifyApiError:
            self.logger.exception("Error fetching the Spotify user")
            return self.async_abort(reason="connection_error")

        await self.async_set_unique_id(me["id"])

        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data_updates=data
            )

        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=me.get("display_name") or me["id"], data=data)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauthentication when Spotify rejects the token."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm reauthentication."""
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                description_placeholders={"account": self._get_reauth_entry().title},
            )
        return await self.async_step_pick_implementation(
            user_input={
                "implementation": self._get_reauth_entry().data["auth_implementation"]
            }
        )

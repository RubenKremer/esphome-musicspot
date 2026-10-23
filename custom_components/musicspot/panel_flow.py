"""Subentry flow: link an ESPHome panel to a Spotify account."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigSubentryFlow, SubentryFlowResult
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.selector import (
    DeviceSelector,
    DeviceSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_ART_BASE_URL,
    CONF_DEFAULT_DEVICE,
    CONF_DEVICE_ID,
    DOMAIN,
    ESPHOME_DOMAIN,
    SUBENTRY_PANEL,
)
from .panel import async_resolve_action_prefix


class PanelSubentryFlowHandler(ConfigSubentryFlow):
    """Add a MusicSpot panel to a Spotify account."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Pick the ESPHome device and optional settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID]
            if self._device_in_use(device_id):
                return self.async_abort(reason="already_configured")
            if async_resolve_action_prefix(self.hass, device_id) is None:
                errors[CONF_DEVICE_ID] = "not_musicspot"
            else:
                device = dr.async_get(self.hass).async_get(device_id)
                title = (device.name_by_user or device.name) if device else device_id
                return self.async_create_entry(
                    title=title or device_id,
                    data={
                        CONF_DEVICE_ID: device_id,
                        CONF_ART_BASE_URL: (user_input.get(CONF_ART_BASE_URL) or "").rstrip("/"),
                        CONF_DEFAULT_DEVICE: user_input.get(CONF_DEFAULT_DEVICE) or "",
                    },
                    unique_id=device_id,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): DeviceSelector(
                    DeviceSelectorConfig(integration=ESPHOME_DOMAIN)
                ),
                vol.Optional(CONF_ART_BASE_URL): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.URL)
                ),
                vol.Optional(CONF_DEFAULT_DEVICE): TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change the album art URL or default playback device of a panel."""
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                data_updates={
                    CONF_ART_BASE_URL: (user_input.get(CONF_ART_BASE_URL) or "").rstrip("/"),
                    CONF_DEFAULT_DEVICE: user_input.get(CONF_DEFAULT_DEVICE) or "",
                },
            )

        schema = vol.Schema(
            {
                vol.Optional(CONF_ART_BASE_URL): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.URL)
                ),
                vol.Optional(CONF_DEFAULT_DEVICE): TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(schema, subentry.data),
            description_placeholders={"panel": subentry.title},
        )

    def _device_in_use(self, device_id: str) -> bool:
        """Return True if any MusicSpot account already has this panel."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            for subentry in entry.subentries.values():
                if (
                    subentry.subentry_type == SUBENTRY_PANEL
                    and subentry.data.get(CONF_DEVICE_ID) == device_id
                ):
                    return True
        return False

"""Config flow for the DSC IT-100 integration.

Three steps:
  1. user      — pick serial port + baud rate
  2. link      — (optional) pick an AlarmDecoder alarm_control_panel entity to
                 attach our DSC IT-100 entities to. The picked entity's device
                 becomes the parent device for all our binary_sensors and
                 sensors, so they show up in the same device card as the
                 panel itself.
  3. users     — (optional, deferred to options flow) friendly names for
                 user codes

The options flow lets the user change the linked entity and rename users
without removing and re-adding the integration.
"""

from __future__ import annotations

import logging
from typing import Any

import serialx
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import Platform
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BAUDRATE,
    CONF_LINKED_ENTITY,
    CONF_PARTITION_NAMES,
    CONF_PORT,
    CONF_USER_NAMES,
    CONF_ZONE_MODELS,
    DEFAULT_BAUDRATE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

BAUD_RATES = ["1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"]


class DSCIT100ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Initial UI setup wizard."""

    VERSION = 1

    def __init__(self) -> None:
        self._port: str = ""
        self._baudrate: int = DEFAULT_BAUDRATE
        self._linked_entity_id: str | None = None

    # ── Step 1: serial port ──────────────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1 — pick the serial port and verify it opens."""
        errors: dict[str, str] = {}

        if user_input is not None:
            port = user_input[CONF_PORT]
            baudrate = int(user_input.get(CONF_BAUDRATE, DEFAULT_BAUDRATE))

            try:
                _reader, writer = await serialx.open_serial_connection(
                    port, baudrate=baudrate, byte_size=8, parity="N", stopbits=1
                )
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:  # noqa: BLE001
                    pass
            except FileNotFoundError:
                errors["base"] = "port_not_found"
            except OSError:
                errors["base"] = "cannot_connect"

            if not errors:
                self._port = port
                self._baudrate = baudrate
                return await self.async_step_link()

        schema = vol.Schema(
            {
                vol.Required(CONF_PORT): selector.SerialPortSelector(),
                vol.Required(CONF_BAUDRATE, default=str(DEFAULT_BAUDRATE)): (
                    selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=BAUD_RATES,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    # ── Step 2: link to AlarmDecoder entity ──────────────────────────────────

    async def async_step_link(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2 — optionally pick an existing alarm_control_panel entity.

        We don't restrict by integration; user picks whichever
        alarm_control_panel they want to attach DSC trouble/user data to. If
        they skip, our entities live on their own dsc_it100 device.
        """
        if user_input is not None:
            self._linked_entity_id = user_input.get(CONF_LINKED_ENTITY) or None
            return self._create_entry()

        schema = vol.Schema(
            {
                vol.Optional(CONF_LINKED_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=Platform.ALARM_CONTROL_PANEL
                    )
                ),
            }
        )
        return self.async_show_form(step_id="link", data_schema=schema)

    # ── Finalise ─────────────────────────────────────────────────────────────

    def _create_entry(self) -> config_entries.ConfigFlowResult:
        return self.async_create_entry(
            title=f"DSC IT-100 ({self._port})",
            data={
                CONF_PORT: self._port,
                CONF_BAUDRATE: self._baudrate,
                CONF_LINKED_ENTITY: self._linked_entity_id,
            },
            options={
                CONF_USER_NAMES: {},
                CONF_PARTITION_NAMES: {},
                CONF_ZONE_MODELS: {},
            },
        )

    # ── Options flow hook ────────────────────────────────────────────────────

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> DSCIT100OptionsFlow:
        return DSCIT100OptionsFlow(config_entry)


class DSCIT100OptionsFlow(config_entries.OptionsFlow):
    """Edit linked entity + user-code names after initial setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Single-page options form."""
        current_opts = dict(self._config_entry.options)
        current_data = dict(self._config_entry.data)

        if user_input is not None:
            # Parse comma-separated 'code:name' pairs from each textbox
            new_user_names = _parse_pairs(user_input.get("user_names_raw", ""))
            new_part_names = _parse_pairs(user_input.get("partition_names_raw", ""))
            new_zone_models = _parse_pairs(user_input.get("zone_models_raw", ""))

            # Linked entity lives in config_entry.data so it survives options
            # flow correctly; update via async_update_entry.
            new_data = {
                **current_data,
                CONF_LINKED_ENTITY: user_input.get(CONF_LINKED_ENTITY) or None,
            }
            self.hass.config_entries.async_update_entry(
                self._config_entry, data=new_data
            )
            return self.async_create_entry(
                title="",
                data={
                    CONF_USER_NAMES: new_user_names,
                    CONF_PARTITION_NAMES: new_part_names,
                    CONF_ZONE_MODELS: new_zone_models,
                },
            )

        existing_users = current_opts.get(CONF_USER_NAMES, {})
        existing_parts = current_opts.get(CONF_PARTITION_NAMES, {})
        existing_zones = current_opts.get(CONF_ZONE_MODELS, {})

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_LINKED_ENTITY,
                    default=current_data.get(CONF_LINKED_ENTITY) or vol.UNDEFINED,
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=Platform.ALARM_CONTROL_PANEL
                    )
                ),
                vol.Optional(
                    "user_names_raw",
                    default=_format_pairs(existing_users),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(
                        multiline=True, type=selector.TextSelectorType.TEXT
                    )
                ),
                vol.Optional(
                    "partition_names_raw",
                    default=_format_pairs(existing_parts),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(
                        multiline=True, type=selector.TextSelectorType.TEXT
                    )
                ),
                # zone_models maps DSC zone number -> wireless-sensor model id
                # (e.g. "1: WS4945"). The model ends up on the per-zone child
                # device created for each zone's battery sensor, letting
                # battery_notes library-match per-model and assign the right
                # battery type. Zones without an entry get model="Wireless
                # Zone" and won't auto-match.
                vol.Optional(
                    "zone_models_raw",
                    default=_format_pairs(existing_zones),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(
                        multiline=True, type=selector.TextSelectorType.TEXT
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


def _parse_pairs(text: str) -> dict[str, str]:
    """Parse `code:name` pairs (one per line or comma-separated) into a dict.

    Empty input gives an empty dict. Whitespace is trimmed. Lines without a
    colon are skipped.
    """
    out: dict[str, str] = {}
    if not text:
        return out
    # Allow either newline-separated or comma-separated entries
    raw_entries = []
    for line in text.splitlines():
        raw_entries.extend(line.split(","))
    for entry in raw_entries:
        if ":" not in entry:
            continue
        code, _, name = entry.partition(":")
        code = code.strip()
        name = name.strip()
        if code and name:
            out[code] = name
    return out


def _format_pairs(pairs: dict[str, str]) -> str:
    """Render dict as one `code: name` pair per line for the options textbox."""
    return "\n".join(f"{k}: {v}" for k, v in pairs.items())

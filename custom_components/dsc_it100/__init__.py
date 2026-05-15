"""DSC IT-100 Home Assistant integration.

Top-level entry that:
  - opens the serial connection
  - creates the coordinator
  - forwards to sensor + binary_sensor platforms
  - registers the `dsc_it100.set_clock` and `dsc_it100.send_command` services
  - resolves the optional linked AlarmDecoder entity into a device_id so
    our entities can attach to the same device card
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BAUDRATE,
    CONF_LINKED_ENTITY,
    CONF_PARTITION_NAMES,
    CONF_PORT,
    CONF_USER_NAMES,
    DATA_CONNECTION,
    DATA_COORDINATOR,
    DATA_LINKED_DEVICE_ID,
    DEFAULT_BAUDRATE,
    DOMAIN,
)
from .coordinator import DSCIT100Coordinator
from .dsc import DSCIT100Connection

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor", "sensor"]

SERVICE_SET_CLOCK = "set_clock"
SERVICE_SEND_COMMAND = "send_command"
SERVICE_CLEAR_DURESS = "clear_duress"

SEND_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required("code"): vol.All(str, vol.Length(min=3, max=3)),
        vol.Optional("data", default=""): str,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up DSC IT-100 from a config entry."""
    port = entry.data[CONF_PORT]
    baudrate = int(entry.data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE))
    linked_entity_id = entry.data.get(CONF_LINKED_ENTITY)

    user_names = entry.options.get(CONF_USER_NAMES, {})
    partition_names = entry.options.get(CONF_PARTITION_NAMES, {})

    # Raw RX/TX framing is logged via _LOGGER.debug — enable it by setting
    # the `custom_components.dsc_it100` logger to DEBUG (see README).
    connection = DSCIT100Connection(port, baudrate)
    try:
        await connection.connect()
    except FileNotFoundError as exc:
        raise ConfigEntryNotReady(f"Serial port {port} not found: {exc}") from exc
    except OSError as exc:
        raise ConfigEntryNotReady(f"Cannot open {port}: {exc}") from exc

    coordinator = DSCIT100Coordinator(
        hass=hass,
        entry_id=entry.entry_id,
        connection=connection,
        user_names=user_names,
        partition_names=partition_names,
    )

    # Resolve linked AlarmDecoder entity -> DeviceInfo we can hand to child
    # platforms. We re-use the linked device's `identifiers`/`connections`,
    # which causes HA to merge our entities into that existing device (this
    # is how battery_notes attaches itself to source-entity devices).
    #
    # If the user didn't link anything, fall back to our own device card so
    # the entities still show up somewhere coherent.
    device_info = _resolve_device_info(hass, entry, linked_entity_id)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CONNECTION: connection,
        DATA_COORDINATOR: coordinator,
        DATA_LINKED_DEVICE_ID: device_info,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id, {})
        conn: DSCIT100Connection | None = data.get(DATA_CONNECTION)
        if conn:
            await conn.disconnect()

        # If this was the last entry, drop the services too
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_SET_CLOCK)
            hass.services.async_remove(DOMAIN, SERVICE_SEND_COMMAND)
            hass.services.async_remove(DOMAIN, SERVICE_CLEAR_DURESS)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload on options change — handles linked-entity changes and rename
    maps in one shot."""
    await hass.config_entries.async_reload(entry.entry_id)


def _resolve_device_info(
    hass: HomeAssistant,
    entry: ConfigEntry,
    linked_entity_id: str | None,
) -> DeviceInfo:
    """Build the DeviceInfo our entities should advertise.

    If `linked_entity_id` resolves to an existing device, re-use that
    device's identifiers so HA merges our entities into the same device.
    Otherwise build a standalone DSC IT-100 device.
    """
    if linked_entity_id:
        ent_reg = er.async_get(hass)
        dev_reg = dr.async_get(hass)
        ent_entry = ent_reg.async_get(linked_entity_id)
        if ent_entry and ent_entry.device_id:
            dev_entry = dev_reg.async_get(ent_entry.device_id)
            if dev_entry and dev_entry.identifiers:
                # Re-use identifiers only; HA preserves the existing device's
                # name/manufacturer/model when we don't set them here.
                return DeviceInfo(identifiers=set(dev_entry.identifiers))
        _LOGGER.warning(
            "Linked entity %s has no resolvable device; DSC IT-100 entities "
            "will be created on a standalone device instead",
            linked_entity_id,
        )

    # Standalone fallback — one device per config entry
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="DSC IT-100",
        manufacturer="DSC",
        model="PC5401",
    )


# ── Services ─────────────────────────────────────────────────────────────────


def _register_services(hass: HomeAssistant) -> None:
    """Register the integration services exactly once."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_CLOCK):
        return

    async def _set_clock(_call: ServiceCall) -> None:
        """Sync every configured panel's clock to the current HA local time."""
        now = dt_util.now()
        hour = now.hour
        minute = now.minute
        month = now.month
        day = now.day
        year_2d = now.year % 100
        for entry_data in hass.data[DOMAIN].values():
            conn: DSCIT100Connection = entry_data[DATA_CONNECTION]
            try:
                await conn.set_clock(hour, minute, month, day, year_2d)
                _LOGGER.info(
                    "Synced DSC panel clock to %02d:%02d %02d/%02d/%02d",
                    hour, minute, month, day, year_2d,
                )
            except OSError as exc:
                _LOGGER.error("DSC set_clock failed: %s", exc)

    async def _send_command(call: ServiceCall) -> None:
        """Send a raw DSC API command to every configured panel."""
        code = call.data["code"]
        data = call.data.get("data", "")
        for entry_data in hass.data[DOMAIN].values():
            conn: DSCIT100Connection = entry_data[DATA_CONNECTION]
            try:
                await conn.send(code, data)
            except OSError as exc:
                _LOGGER.error("DSC send_command failed: %s", exc)

    async def _clear_duress(_call: ServiceCall) -> None:
        """Manually clear the latched duress flag."""
        for entry_data in hass.data[DOMAIN].values():
            coordinator: DSCIT100Coordinator = entry_data[DATA_COORDINATOR]
            coordinator.reset_duress()

    hass.services.async_register(DOMAIN, SERVICE_SET_CLOCK, _set_clock)
    hass.services.async_register(
        DOMAIN, SERVICE_SEND_COMMAND, _send_command, schema=SEND_COMMAND_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_CLEAR_DURESS, _clear_duress)

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
    CONF_ZONE_MODELS,
    DATA_CONNECTION,
    DATA_COORDINATOR,
    DATA_LINKED_DEVICE_ID,
    DATA_OWN_DEVICE_INFO,
    DATA_ZONES,
    DATA_ZONE_MODELS,
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
    zone_models = entry.options.get(CONF_ZONE_MODELS, {})

    # Raw RX/TX framing is logged via _LOGGER.debug — enable it by setting
    # the `custom_components.dsc_it100` logger to DEBUG (see README).
    connection = DSCIT100Connection(port, baudrate)
    try:
        await connection.connect()
    except FileNotFoundError as exc:
        raise ConfigEntryNotReady(f"Serial port {port} not found: {exc}") from exc
    except OSError as exc:
        raise ConfigEntryNotReady(f"Cannot open {port}: {exc}") from exc

    # Discover zones from the linked AlarmDecoder device (if any). We use
    # these to create one battery binary_sensor per zone — the DSC IT-100
    # protocol reports per-zone low-battery via code 821 but doesn't list
    # which zones exist, so we lean on AlarmDecoder (which knows because
    # it's already exposing zone open/close binary_sensors).
    zones = _discover_alarmdecoder_zones(hass, linked_entity_id)
    if linked_entity_id and not zones:
        _LOGGER.info(
            "No AlarmDecoder zones discovered for %s; per-zone battery "
            "sensors will be created dynamically on first 821 event",
            linked_entity_id,
        )

    coordinator = DSCIT100Coordinator(
        hass=hass,
        entry_id=entry.entry_id,
        connection=connection,
        user_names=user_names,
        partition_names=partition_names,
        zones=zones,
    )

    # Build two DeviceInfos:
    #   - own_device_info: always points to *our* dsc_it100 device. Used
    #     by entities that report on the integration / panel hardware
    #     itself (troubles, diagnostics, recent event log).
    #   - linked_device_info: points to the linked AlarmDecoder device
    #     when one is configured, falling back to own_device_info if not.
    #     Used by entities that conceptually belong with the alarm system
    #     itself (user attribution, duress, per-zone batteries) so they
    #     appear on the AlarmDecoder card alongside the zones.
    own_device_info = _own_device_info(entry)
    linked_device_info = _resolve_linked_device_info(
        hass, linked_entity_id
    ) or own_device_info

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CONNECTION: connection,
        DATA_COORDINATOR: coordinator,
        DATA_LINKED_DEVICE_ID: linked_device_info,
        DATA_OWN_DEVICE_INFO: own_device_info,
        DATA_ZONES: zones,
        DATA_ZONE_MODELS: zone_models,
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


def _discover_alarmdecoder_zones(
    hass: HomeAssistant,
    linked_entity_id: str | None,
) -> list[tuple[int, str]]:
    """Return [(zone_number, zone_name), ...] discovered from AlarmDecoder.

    AlarmDecoder creates one binary_sensor per zone, all attached to the
    panel's device, with a unique_id of the form
    `{serial_number}-zone-{N}`. We walk the linked entity's device, pick
    out anything matching that pattern, and parse the zone number from the
    suffix.

    Returns an empty list when nothing is linked, the linked entity has no
    device, or no entities match the pattern. The caller is expected to
    handle the empty case (per-zone sensors simply won't be created).
    """
    if not linked_entity_id:
        return []

    ent_reg = er.async_get(hass)
    linked_entry = ent_reg.async_get(linked_entity_id)
    if not linked_entry or not linked_entry.device_id:
        return []

    zones: list[tuple[int, str]] = []
    # Default include_disabled_entities=False is what we want: zones the
    # user has disabled in AlarmDecoder are assumed unused, so we don't
    # create battery sensors for them either.
    for entity in er.async_entries_for_device(ent_reg, linked_entry.device_id):
        if entity.domain != "binary_sensor" or not entity.unique_id:
            continue
        marker = "-zone-"
        idx = entity.unique_id.rfind(marker)
        if idx < 0:
            continue
        suffix = entity.unique_id[idx + len(marker):]
        try:
            zone_num = int(suffix)
        except ValueError:
            continue
        # Prefer the user-overridden registry name, then the integration's
        # original name; fall back to "Zone N" if both are blank.
        name = entity.name or entity.original_name or f"Zone {zone_num}"
        zones.append((zone_num, name))

    zones.sort(key=lambda z: z[0])
    return zones


def _own_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Build the DeviceInfo for the dsc_it100 device itself.

    Always returns a fresh DeviceInfo keyed by config entry id, so each
    configured panel ends up with its own dsc_it100 device card.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="DSC IT-100",
        manufacturer="DSC",
        model="PC5401",
    )


def _resolve_linked_device_info(
    hass: HomeAssistant,
    linked_entity_id: str | None,
) -> DeviceInfo | None:
    """Return DeviceInfo pointing at the linked AlarmDecoder device.

    Returns None if no entity was linked or the link can't be resolved —
    callers should fall back to the own dsc_it100 device in that case.
    Re-uses the linked device's identifiers only; HA preserves the
    existing device's name/manufacturer/model when we don't set them.
    """
    if not linked_entity_id:
        return None

    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    ent_entry = ent_reg.async_get(linked_entity_id)
    if not (ent_entry and ent_entry.device_id):
        _LOGGER.warning(
            "Linked entity %s not found in the registry; panel-side "
            "entities will fall back to the dsc_it100 device",
            linked_entity_id,
        )
        return None
    dev_entry = dev_reg.async_get(ent_entry.device_id)
    if not (dev_entry and dev_entry.identifiers):
        _LOGGER.warning(
            "Linked entity %s has no resolvable device; panel-side "
            "entities will fall back to the dsc_it100 device",
            linked_entity_id,
        )
        return None
    return DeviceInfo(identifiers=set(dev_entry.identifiers))


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

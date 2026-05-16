"""DSC IT-100 binary_sensor platform.

Creates:
  - one binary_sensor per trouble category (panel battery, AC, bell, TLM,
    FTC, keybus, tamper, fire trouble, etc.)
  - a latching Duress Alarm sensor
  - one per-zone wireless-battery sensor for every zone discovered from
    the linked AlarmDecoder device, driven by DSC codes 821 / 822 — uses
    the BATTERY device class so battery_notes picks them up automatically

All entities attach to the linked AlarmDecoder device (if configured) so
they appear on the same device card.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATA_COORDINATOR,
    DATA_LINKED_DEVICE_ID,
    DATA_ZONES,
    DOMAIN,
    TROUBLE_LABELS,
)
from .coordinator import DSCIT100Coordinator, signal_update

# Troubles that should be hidden in the entity registry by default. Users
# without dual phone lines, wireless keys, or handheld keypads will never see
# these go active, so we don't clutter the device card with them. Re-enable in
# the UI per-entity if the hardware is actually present.
_DEFAULT_DISABLED: set[str] = {
    "tlm_line_1",
    "tlm_line_2",
    "wireless_key_low_battery",
    "handheld_keypad_low_battery",
}

# Device-class assignments — the panel/AC/battery/bell troubles are best
# represented as PROBLEM; fire trouble is a dedicated FIRE class so the UI
# uses the right icon.
_DEVICE_CLASSES: dict[str, BinarySensorDeviceClass] = {
    "panel_battery": BinarySensorDeviceClass.BATTERY,
    "panel_ac": BinarySensorDeviceClass.POWER,
    "bell": BinarySensorDeviceClass.PROBLEM,
    "tlm_line_1": BinarySensorDeviceClass.PROBLEM,
    "tlm_line_2": BinarySensorDeviceClass.PROBLEM,
    "ftc": BinarySensorDeviceClass.PROBLEM,
    "buffer_near_full": BinarySensorDeviceClass.PROBLEM,
    "device_low_battery": BinarySensorDeviceClass.BATTERY,
    "wireless_key_low_battery": BinarySensorDeviceClass.BATTERY,
    "handheld_keypad_low_battery": BinarySensorDeviceClass.BATTERY,
    "general_tamper": BinarySensorDeviceClass.TAMPER,
    "home_automation": BinarySensorDeviceClass.PROBLEM,
    "trouble_status": BinarySensorDeviceClass.PROBLEM,
    "fire_trouble": BinarySensorDeviceClass.PROBLEM,
    "keybus_fault": BinarySensorDeviceClass.PROBLEM,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a trouble binary_sensor for each known DSC trouble key, plus
    one per-zone battery binary_sensor for every zone discovered from the
    linked AlarmDecoder device."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DSCIT100Coordinator = data[DATA_COORDINATOR]
    device_info: DeviceInfo = data[DATA_LINKED_DEVICE_ID]
    zones: list[tuple[int, str]] = data.get(DATA_ZONES, [])

    entities: list = [
        DSCTroubleBinarySensor(coordinator, entry.entry_id, key, label, device_info)
        for key, label in TROUBLE_LABELS.items()
    ]
    entities.append(DSCDuressBinarySensor(coordinator, entry.entry_id, device_info))
    entities.extend(
        DSCZoneBatterySensor(
            coordinator, entry.entry_id, zone_num, zone_name, device_info
        )
        for zone_num, zone_name in zones
    )
    async_add_entities(entities)


class DSCTroubleBinarySensor(BinarySensorEntity):
    """One binary sensor per DSC trouble category."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: DSCIT100Coordinator,
        entry_id: str,
        key: str,
        label: str,
        device_info: DeviceInfo,
    ) -> None:
        self._coordinator = coordinator
        self._key = key
        self._attr_name = label
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = device_info
        self._attr_device_class = _DEVICE_CLASSES.get(key)
        if key in _DEFAULT_DISABLED:
            self._attr_entity_registry_enabled_default = False

    @property
    def is_on(self) -> bool:
        return self._coordinator.state.troubles.get(self._key, False)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_update(self._coordinator.entry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class DSCDuressBinarySensor(BinarySensorEntity):
    """Latching duress-alarm sensor (DSC code 620).

    Stays ON after a duress code is entered until cleared by the
    `dsc_it100.clear_duress` service. We deliberately don't auto-restore —
    a silently-cleared duress would defeat the point of the alarm.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Duress Alarm"
    _attr_device_class = BinarySensorDeviceClass.SAFETY

    def __init__(
        self,
        coordinator,
        entry_id: str,
        device_info: DeviceInfo,
    ) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry_id}_duress"
        self._attr_device_info = device_info

    @property
    def is_on(self) -> bool:
        return self._coordinator.state.duress_active

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        st = self._coordinator.state
        return {
            "user_id": st.duress_user_id,
            "user": st.duress_user_name,
            "time": st.duress_time.isoformat() if st.duress_time else None,
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_update(self._coordinator.entry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class DSCZoneBatterySensor(BinarySensorEntity):
    """Per-zone wireless low-battery sensor (DSC codes 821 / 822).

    One instance per zone discovered from the linked AlarmDecoder device.
    `is_on` is True when the panel has reported a low battery for this
    zone and not yet restored it. Uses the BATTERY device class so HA
    renders it as a battery tile and battery_notes can pick it up
    automatically.

    Wired zones won't ever fire 821, so their entity will sit at `off`
    forever — disable those manually in the entity registry if the
    clutter bothers you.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.BATTERY

    def __init__(
        self,
        coordinator: DSCIT100Coordinator,
        entry_id: str,
        zone_num: int,
        zone_name: str,
        device_info: DeviceInfo,
    ) -> None:
        self._coordinator = coordinator
        self._zone_num = zone_num
        self._attr_name = f"{zone_name} Battery"
        self._attr_unique_id = f"{entry_id}_zone_{zone_num}_battery"
        self._attr_device_info = device_info

    @property
    def is_on(self) -> bool:
        return self._coordinator.state.zone_low_battery.get(self._zone_num, False)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_update(self._coordinator.entry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

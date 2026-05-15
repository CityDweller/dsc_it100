"""DSC 5401 sensor platform.

Creates user-attribution and last-event sensors that attach to the linked
AlarmDecoder device (if configured).

Entities:
  - Last User           (name)
  - Last User Code      (4-digit user code)
  - Last User Action    (armed / disarmed / special_armed / partial_armed /
                         special_disarmed)
  - Last Arm Mode       (away / stay / zero_entry_away / zero_entry_stay)
  - Last Event          (timestamp of most recent DSC frame)
  - Last Event Code     (3-digit DSC code, e.g. "700")
  - Last Error          (most recent 501/502 error text, if any)
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DATA_LINKED_DEVICE_ID, DOMAIN
from .coordinator import DSC5401Coordinator, signal_update


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DSC5401Coordinator = data[DATA_COORDINATOR]
    device_info: DeviceInfo = data[DATA_LINKED_DEVICE_ID]

    async_add_entities(
        [
            DSCLastUserSensor(coordinator, entry.entry_id, device_info),
            DSCLastUserCodeSensor(coordinator, entry.entry_id, device_info),
            DSCLastActionSensor(coordinator, entry.entry_id, device_info),
            DSCLastArmModeSensor(coordinator, entry.entry_id, device_info),
            DSCLastEventSensor(coordinator, entry.entry_id, device_info),
            DSCLastEventCodeSensor(coordinator, entry.entry_id, device_info),
            DSCLastErrorSensor(coordinator, entry.entry_id, device_info),
        ]
    )


class _DSCBaseSensor(SensorEntity):
    """Common boilerplate for every DSC sensor."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DSC5401Coordinator,
        entry_id: str,
        device_info: DeviceInfo,
        key: str,
        name: str,
    ) -> None:
        self._coordinator = coordinator
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = device_info

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


class DSCLastUserSensor(_DSCBaseSensor):
    def __init__(self, coordinator, entry_id, device_info):
        super().__init__(coordinator, entry_id, device_info, "last_user", "Last User")

    @property
    def native_value(self) -> str | None:
        return self._coordinator.state.last_user_name

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        st = self._coordinator.state
        return {
            "user_id": st.last_user_id,
            "partition": st.last_user_partition,
            "action": st.last_user_action,
        }


class DSCLastUserCodeSensor(_DSCBaseSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry_id, device_info):
        super().__init__(
            coordinator, entry_id, device_info, "last_user_code", "Last User Code"
        )

    @property
    def native_value(self) -> str | None:
        return self._coordinator.state.last_user_id


class DSCLastActionSensor(_DSCBaseSensor):
    def __init__(self, coordinator, entry_id, device_info):
        super().__init__(
            coordinator, entry_id, device_info, "last_action", "Last Action"
        )

    @property
    def native_value(self) -> str | None:
        return self._coordinator.state.last_user_action


class DSCLastArmModeSensor(_DSCBaseSensor):
    def __init__(self, coordinator, entry_id, device_info):
        super().__init__(
            coordinator, entry_id, device_info, "last_arm_mode", "Last Arm Mode"
        )

    @property
    def native_value(self) -> str | None:
        return self._coordinator.state.last_arm_mode


class DSCLastEventSensor(_DSCBaseSensor):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry_id, device_info):
        super().__init__(
            coordinator, entry_id, device_info, "last_event", "Last Event"
        )

    @property
    def native_value(self) -> datetime | None:
        return self._coordinator.state.last_event_time


class DSCLastEventCodeSensor(_DSCBaseSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry_id, device_info):
        super().__init__(
            coordinator, entry_id, device_info, "last_event_code", "Last Event Code"
        )

    @property
    def native_value(self) -> str | None:
        return self._coordinator.state.last_event_code


class DSCLastErrorSensor(_DSCBaseSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry_id, device_info):
        super().__init__(
            coordinator, entry_id, device_info, "last_error", "Last Error"
        )

    @property
    def native_value(self) -> str | None:
        return self._coordinator.state.last_error_text

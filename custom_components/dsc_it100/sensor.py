"""DSC IT-100 sensor platform.

Creates user-attribution and diagnostic sensors that attach to the linked
AlarmDecoder device (if configured).

Entities:
  - Last User           (name; raw 4-digit code is on the `user_id` attribute)
  - Last User Action    (armed / disarmed / special_armed / partial_armed /
                         special_disarmed / duress)
  - Last Arm Mode       (away / stay / zero_entry_away / zero_entry_stay)
  - Last Event          (timestamp of most recent DSC frame)
  - Last Event Code     (3-digit DSC code, e.g. "700")
  - Last Error          (most recent 501/502 error text, if any)
  - Recent Events       (one-line summary of the newest event as state;
                         ring buffer of last 50 as `events` attribute and
                         buffer occupancy as `count`)
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATA_COORDINATOR,
    DATA_LINKED_DEVICE_ID,
    DATA_OWN_DEVICE_INFO,
    DOMAIN,
)
from .coordinator import DSCIT100Coordinator, signal_update


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DSCIT100Coordinator = data[DATA_COORDINATOR]
    # User-attribution sensors describe panel activity — they go on the
    # linked AlarmDecoder device card alongside the panel state.
    # Diagnostic sensors describe the IT-100 serial stream itself — they
    # go on the dsc_it100 device card.
    linked_device: DeviceInfo = data[DATA_LINKED_DEVICE_ID]
    own_device: DeviceInfo = data[DATA_OWN_DEVICE_INFO]

    async_add_entities(
        [
            DSCLastUserSensor(coordinator, entry.entry_id, linked_device),
            DSCLastActionSensor(coordinator, entry.entry_id, linked_device),
            DSCLastArmModeSensor(coordinator, entry.entry_id, linked_device),
            DSCLastEventSensor(coordinator, entry.entry_id, own_device),
            DSCLastEventCodeSensor(coordinator, entry.entry_id, own_device),
            DSCLastErrorSensor(coordinator, entry.entry_id, own_device),
            DSCRecentEventsSensor(coordinator, entry.entry_id, own_device),
        ]
    )


class _DSCBaseSensor(SensorEntity):
    """Common boilerplate for every DSC sensor."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DSCIT100Coordinator,
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


class DSCRecentEventsSensor(_DSCBaseSensor):
    """Ring buffer of recent panel events.

    Native value is a one-line summary of the newest buffered event (e.g.
    "Gaetan armed House"), so the entity is glanceable. The full log lives
    in the `events` extra-state attribute and the buffer occupancy in
    `count`. Designed for the Lovelace `markdown` / `auto-entities` cards
    to surface a panel-event history without needing a separate database.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry_id, device_info):
        super().__init__(
            coordinator, entry_id, device_info, "recent_events", "Recent Events"
        )

    @property
    def native_value(self) -> str | None:
        buf = self._coordinator.state.recent_events
        if not buf:
            return None
        latest = buf[0]
        return latest.get("summary") or latest.get("name")

    @property
    def extra_state_attributes(self) -> dict:
        buf = self._coordinator.state.recent_events
        return {
            "count": len(buf),
            "events": list(buf),
        }

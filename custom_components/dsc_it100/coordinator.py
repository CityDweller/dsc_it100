"""
DSC IT-100 coordinator.

Owns the serial connection, parses inbound events into structured state, and
signals platform entities when something they care about changes.

This is the only module in the integration that knows the DSC event-code
semantics; entities just consume the resulting state dict.

State tracked
─────────────
- `troubles[key]`            one bool per trouble category (see TROUBLE_EVENTS)
- `last_user_name`           friendly name of the user who last acted
- `last_user_id`             4-digit user code
- `last_user_action`         "armed" | "disarmed" | "special_armed" |
                             "special_disarmed" | "partial_armed" | "duress"
- `last_user_partition`      partition number (string, e.g. "1")
- `last_arm_mode`            "away" | "stay" | "zero_entry_away" |
                             "zero_entry_stay" | "armed"
- `last_event_time`          datetime of the most recent inbound frame
- `last_event_code`          most recent inbound DSC code
- `last_error_text`          most recent 501/502 error text
- `last_op_event`            most recent operational/diagnostic event
                             (failed-to-arm, invalid code, keypad lockout, …)
- `duress_active`            True after a 620 (latched until manually reset
                             via the `dsc_it100.send_command` service or HA
                             restart — duress is too important to auto-clear)
- `recent_events`            ring buffer of the last RECENT_EVENTS_MAX events
                             with timestamp, code, name, partition, user
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import (
    ANON_USER_ID,
    ANON_USER_NAME,
    ARM_MODES,
    DOMAIN,
    ERROR_CODES,
    EVENT_NAMES,
    EVT_CMD_ACK,
    EVT_CMD_ERROR,
    EVT_DURESS_ALARM,
    EVT_FAILED_TO_ARM,
    EVT_FUNCTION_UNAVAILABLE,
    EVT_INVALID_CODE,
    EVT_KEYPAD_LOCKOUT,
    EVT_PARTIAL_CLOSING,
    EVT_PARTITION_ARMED,
    EVT_PARTITION_BUSY,
    EVT_PARTITION_DISARMED,
    EVT_SPECIAL_CLOSING,
    EVT_SPECIAL_OPENING,
    EVT_SYSTEM_ERROR,
    EVT_USER_CLOSING,
    EVT_USER_OPENING,
    RECENT_EVENTS_MAX,
    TROUBLE_EVENTS,
)
from .dsc import DSCIT100Connection

_LOGGER = logging.getLogger(__name__)


def signal_update(entry_id: str) -> str:
    """Return the dispatcher signal name for state updates of this entry."""
    return f"{DOMAIN}_{entry_id}_update"


# Codes treated as operational/diagnostic events. These don't latch like
# troubles do — they're transient notifications useful for troubleshooting
# (especially arming failures).
OP_EVENT_CODES = {
    EVT_KEYPAD_LOCKOUT,
    EVT_INVALID_CODE,
    EVT_FUNCTION_UNAVAILABLE,
    EVT_FAILED_TO_ARM,
    EVT_PARTITION_BUSY,
}

# Anonymous/system close-open mapping
ANON_ACTIONS = {
    EVT_SPECIAL_CLOSING: "special_armed",
    EVT_PARTIAL_CLOSING: "partial_armed",
    EVT_SPECIAL_OPENING: "special_disarmed",
}


@dataclass
class DSCState:
    """Shared state read by all DSC IT-100 entities."""

    troubles: dict[str, bool] = field(default_factory=dict)

    last_user_name: str | None = None
    last_user_id: str | None = None
    last_user_action: str | None = None
    last_user_partition: str | None = None
    last_arm_mode: str | None = None

    last_event_time: datetime | None = None
    last_event_code: str | None = None
    last_error_text: str | None = None
    last_op_event: str | None = None

    duress_active: bool = False
    duress_user_id: str | None = None
    duress_user_name: str | None = None
    duress_time: datetime | None = None

    recent_events: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=RECENT_EVENTS_MAX)
    )


class DSCIT100Coordinator:
    """Translate raw frames into DSCState changes; notify entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        connection: DSCIT100Connection,
        user_names: dict[str, str],
        partition_names: dict[str, str],
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.connection = connection
        self.user_names = user_names
        self.partition_names = partition_names

        self.state = DSCState()

        # Initialise every known trouble key to False so the binary sensors
        # come up with a definite state on first start.
        for code, (key, _is_restore) in TROUBLE_EVENTS.items():
            self.state.troubles.setdefault(key, False)

        connection._on_frame = self.handle_frame  # noqa: SLF001

    # ── Public helpers ───────────────────────────────────────────────────────

    def reset_duress(self) -> None:
        """Clear the latched duress flag (called from a service)."""
        self.state.duress_active = False
        async_dispatcher_send(self.hass, signal_update(self.entry_id))

    def _resolve_user(self, user_id: str) -> str:
        return self.user_names.get(user_id, f"User {user_id}")

    def _resolve_partition(self, part_id: str) -> str:
        return self.partition_names.get(part_id, part_id)

    # ── Frame dispatch ───────────────────────────────────────────────────────

    async def handle_frame(self, code: str, data: str) -> None:
        """Top-level dispatcher for inbound frames."""
        now = dt_util.now()
        self.state.last_event_time = now
        self.state.last_event_code = code

        # Always log to the recent-events ring buffer, regardless of whether
        # we handle the code specifically — gives a complete diagnostic trail.
        self._log_event(now, code, data)

        if code in TROUBLE_EVENTS:
            self._handle_trouble(code, data)
        elif code == EVT_DURESS_ALARM:
            self._handle_duress(code, data, now)
        elif code in (EVT_USER_CLOSING, EVT_USER_OPENING):
            self._handle_user_event(code, data)
        elif code in (
            EVT_SPECIAL_CLOSING,
            EVT_PARTIAL_CLOSING,
            EVT_SPECIAL_OPENING,
        ):
            self._handle_anon_event(code, data)
        elif code == EVT_PARTITION_ARMED:
            self._handle_partition_armed(data)
        elif code == EVT_PARTITION_DISARMED:
            self._handle_partition_disarmed(data)
        elif code in OP_EVENT_CODES:
            self._handle_op_event(code, data)
        elif code == EVT_CMD_ACK:
            _LOGGER.debug("DSC ack for command %s", data)
        elif code in (EVT_CMD_ERROR, EVT_SYSTEM_ERROR):
            text = ERROR_CODES.get(data, f"Unknown error {data}")
            self.state.last_error_text = text
            _LOGGER.warning("DSC %s: %s", code, text)
        else:
            # Zone events (6xx) and broadcasts (550/56x/570/580/660) are
            # intentionally ignored for state — AlarmDecoder handles zones
            # and we don't surface time/temp/ring/labels. But they're still
            # captured in the recent-events log above.
            _LOGGER.debug("DSC ignoring code %s data=%r", code, data)

        async_dispatcher_send(self.hass, signal_update(self.entry_id))

    # ── Event log ────────────────────────────────────────────────────────────

    def _log_event(self, when: datetime, code: str, data: str) -> None:
        """Append an event to the recent-events ring buffer.

        Each entry is a small dict suitable for direct exposure as an entity
        attribute. We pull user/partition out of the data where the code
        carries them.
        """
        entry: dict[str, Any] = {
            "time": when.isoformat(timespec="seconds"),
            "code": code,
            "name": EVENT_NAMES.get(code, f"Unknown {code}"),
        }

        # User-bearing codes: 620/700/750 have <part1><user4>
        if code in (EVT_DURESS_ALARM, EVT_USER_CLOSING, EVT_USER_OPENING) and len(data) >= 5:
            entry["partition"] = self._resolve_partition(data[0])
            entry["user_id"] = data[1:5]
            entry["user"] = self._resolve_user(data[1:5])
        # Partition-only codes: many 6xx and 7xx and 8xx with <part1> data
        elif data and data[0].isdigit() and len(data) <= 2:
            entry["partition"] = self._resolve_partition(data[:1])
            if len(data) == 2 and code == EVT_PARTITION_ARMED:
                entry["mode"] = ARM_MODES.get(data[1], "armed")

        entry["summary"] = self._summarize(entry)
        self.state.recent_events.appendleft(entry)

    @staticmethod
    def _summarize(entry: dict[str, Any]) -> str:
        """Render a one-line human summary of a buffered event."""
        code = entry["code"]
        name = entry["name"]
        if code == EVT_DURESS_ALARM:
            return f"DURESS by {entry['user']} on {entry['partition']}"
        if code == EVT_USER_CLOSING:
            return f"{entry['user']} armed {entry['partition']}"
        if code == EVT_USER_OPENING:
            return f"{entry['user']} disarmed {entry['partition']}"
        if code == EVT_PARTITION_ARMED and "mode" in entry:
            return f"{name} ({entry['mode']}) on {entry['partition']}"
        if "partition" in entry:
            return f"{name} on {entry['partition']}"
        return name

    # ── Individual event handlers ────────────────────────────────────────────

    def _handle_trouble(self, code: str, _data: str) -> None:
        key, is_restore = TROUBLE_EVENTS[code]
        self.state.troubles[key] = not is_restore
        _LOGGER.info(
            "DSC trouble %s -> %s (%s)",
            key,
            "RESTORED" if is_restore else "ACTIVE",
            code,
        )

    def _handle_duress(self, code: str, data: str, when: datetime) -> None:
        """620 — duress code was entered. Latches `duress_active=True`.

        Duress doesn't auto-restore in the DSC protocol; the panel just
        reports it once. We latch the flag so it stays visible in HA until
        cleared explicitly (binary_sensor remains ON).
        """
        if len(data) < 5:
            _LOGGER.warning("DSC duress short data: %r", data)
            return
        part_id = data[0]
        user_id = data[1:5]
        self.state.duress_active = True
        self.state.duress_user_id = user_id
        self.state.duress_user_name = self._resolve_user(user_id)
        self.state.duress_time = when

        # Also reflect on the "last user" pipeline so automations that
        # trigger on user changes see the duress event.
        self.state.last_user_partition = part_id
        self.state.last_user_id = user_id
        self.state.last_user_name = self._resolve_user(user_id)
        self.state.last_user_action = "duress"

        _LOGGER.warning(
            "DSC DURESS by user %s (%s) on partition %s",
            self.state.duress_user_name, user_id, part_id,
        )

    def _handle_user_event(self, code: str, data: str) -> None:
        """700 (close/arm) or 750 (open/disarm) with `<part1><user4>` data."""
        if len(data) < 5:
            _LOGGER.warning("DSC %s short data: %r", code, data)
            return
        part_id = data[0]
        user_id = data[1:5]
        self.state.last_user_partition = part_id
        self.state.last_user_id = user_id
        self.state.last_user_name = self._resolve_user(user_id)
        self.state.last_user_action = (
            "armed" if code == EVT_USER_CLOSING else "disarmed"
        )
        _LOGGER.info(
            "DSC user %s (%s) %s partition %s",
            self.state.last_user_name,
            user_id,
            self.state.last_user_action,
            part_id,
        )

    def _handle_anon_event(self, code: str, data: str) -> None:
        """701/702/751 — system/anonymous close/open with `<part1>` data."""
        self.state.last_user_partition = data[:1] if data else None
        self.state.last_user_id = ANON_USER_ID
        self.state.last_user_name = ANON_USER_NAME
        self.state.last_user_action = ANON_ACTIONS.get(code, "system")

    def _handle_partition_armed(self, data: str) -> None:
        """652 — partition armed; second character is the arm mode."""
        mode_byte = data[1] if len(data) >= 2 else "4"
        self.state.last_arm_mode = ARM_MODES.get(mode_byte, "armed")
        if not self.state.last_user_partition:
            self.state.last_user_partition = data[:1]

    def _handle_partition_disarmed(self, _data: str) -> None:
        self.state.last_arm_mode = None

    def _handle_op_event(self, code: str, data: str) -> None:
        """Operational/diagnostic events (failed-to-arm, lockout, etc.).

        These don't have a latched on/off state — they fire once. We just
        record the most recent one for the Last Op Event sensor and rely
        on the recent-events log for history.
        """
        name = EVENT_NAMES.get(code, f"Op event {code}")
        part = self._resolve_partition(data[:1]) if data else None
        self.state.last_op_event = (
            f"{name} (partition {part})" if part else name
        )
        _LOGGER.info("DSC op event: %s", self.state.last_op_event)

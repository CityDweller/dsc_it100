"""
DSC 5401 coordinator.

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
                             "special_disarmed" | "partial_armed"
- `last_user_partition`      partition number (string, e.g. "1")
- `last_arm_mode`            "away" | "stay" | "zero_entry_away" |
                             "zero_entry_stay" | "armed"
- `last_event_time`          datetime of the most recent inbound frame
- `last_event_code`          most recent inbound DSC code
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import (
    ANON_USER_ID,
    ANON_USER_NAME,
    ARM_MODES,
    DOMAIN,
    ERROR_CODES,
    EVT_CMD_ACK,
    EVT_CMD_ERROR,
    EVT_PARTITION_ARMED,
    EVT_PARTITION_DISARMED,
    EVT_PARTIAL_CLOSING,
    EVT_SPECIAL_CLOSING,
    EVT_SPECIAL_OPENING,
    EVT_SYSTEM_ERROR,
    EVT_USER_CLOSING,
    EVT_USER_OPENING,
    TROUBLE_EVENTS,
)
from .dsc import DSC5401Connection

_LOGGER = logging.getLogger(__name__)


def signal_update(entry_id: str) -> str:
    """Return the dispatcher signal name for state updates of this entry."""
    return f"{DOMAIN}_{entry_id}_update"


@dataclass
class DSCState:
    """Shared state read by all DSC 5401 entities."""

    troubles: dict[str, bool] = field(default_factory=dict)

    last_user_name: str | None = None
    last_user_id: str | None = None
    last_user_action: str | None = None
    last_user_partition: str | None = None
    last_arm_mode: str | None = None

    last_event_time: datetime | None = None
    last_event_code: str | None = None
    last_error_text: str | None = None


class DSC5401Coordinator:
    """Translate raw frames into DSCState changes; notify entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        connection: DSC5401Connection,
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
        # come up with a definite state on first start (rather than unknown).
        for code, (key, _is_restore) in TROUBLE_EVENTS.items():
            self.state.troubles.setdefault(key, False)

        # Wire the connection's frame callback to our handler
        connection._on_frame = self.handle_frame  # noqa: SLF001

    # ── Frame dispatch ───────────────────────────────────────────────────────

    async def handle_frame(self, code: str, data: str) -> None:
        """Top-level dispatcher for inbound frames."""
        self.state.last_event_time = dt_util.now()
        self.state.last_event_code = code

        if code in TROUBLE_EVENTS:
            self._handle_trouble(code, data)
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
        elif code == EVT_CMD_ACK:
            _LOGGER.debug("DSC ack for command %s", data)
        elif code in (EVT_CMD_ERROR, EVT_SYSTEM_ERROR):
            text = ERROR_CODES.get(data, f"Unknown error {data}")
            self.state.last_error_text = text
            _LOGGER.warning("DSC %s: %s", code, text)
        else:
            # Zone events (6xx) and broadcasts (550/56x) are intentionally
            # ignored — the AlarmDecoder integration handles zones, and we
            # don't surface time/temperature/ring.
            _LOGGER.debug("DSC ignoring code %s data=%r", code, data)

        async_dispatcher_send(self.hass, signal_update(self.entry_id))

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

    def _handle_user_event(self, code: str, data: str) -> None:
        """700 (close/arm) or 750 (open/disarm) with `<part1><user4>` data."""
        if len(data) < 5:
            _LOGGER.warning("DSC %s short data: %r", code, data)
            return
        part_id = data[0]
        user_id = data[1:5]
        self.state.last_user_partition = part_id
        self.state.last_user_id = user_id
        self.state.last_user_name = self.user_names.get(user_id, f"User {user_id}")
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
        action_map = {
            EVT_SPECIAL_CLOSING: "special_armed",
            EVT_PARTIAL_CLOSING: "partial_armed",
            EVT_SPECIAL_OPENING: "special_disarmed",
        }
        self.state.last_user_partition = data[:1] if data else None
        self.state.last_user_id = ANON_USER_ID
        self.state.last_user_name = ANON_USER_NAME
        self.state.last_user_action = action_map.get(code, "system")

    def _handle_partition_armed(self, data: str) -> None:
        """652 — partition armed; second character is the arm mode."""
        # data = <part1><mode> where mode 0=away 1=stay 2=zea 3=zes; if data
        # is only one byte long the panel didn't include a mode, so call it
        # generically "armed".
        mode_byte = data[1] if len(data) >= 2 else "4"
        self.state.last_arm_mode = ARM_MODES.get(mode_byte, "armed")
        if not self.state.last_user_partition:
            self.state.last_user_partition = data[:1]

    def _handle_partition_disarmed(self, _data: str) -> None:
        self.state.last_arm_mode = None

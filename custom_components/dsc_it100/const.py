"""Constants for the DSC IT-100 integration."""

from __future__ import annotations

DOMAIN = "dsc_it100"

# Config entry data keys
CONF_PORT = "port"
CONF_BAUDRATE = "baudrate"
CONF_LINKED_ENTITY = "linked_entity_id"
CONF_USER_NAMES = "user_names"    # {"0040": "Gaetan", "0001": "Master", ...}
CONF_PARTITION_NAMES = "partition_names"  # {"1": "House", ...}

# hass.data keys
DATA_CONNECTION = "connection"
DATA_COORDINATOR = "coordinator"
DATA_LINKED_DEVICE_ID = "linked_device_id"
DATA_ZONES = "zones"

DEFAULT_BAUDRATE = 9600

# ── DSC API codes ────────────────────────────────────────────────────────────

# Outbound commands (sent to panel)
CMD_POLL = "000"
CMD_STATUS_REPORT = "001"
CMD_SET_DATETIME = "010"
CMD_PARTITION_ARM = "030"
CMD_PARTITION_ARM_STAY = "031"
CMD_PARTITION_ARM_ZERO_ENTRY = "032"
CMD_PARTITION_ARM_WITH_CODE = "033"
CMD_PARTITION_DISARM = "040"
CMD_VERBOSE_ARMING = "050"
CMD_TIME_BROADCAST = "056"
CMD_TEMP_BROADCAST = "057"
CMD_TRIGGER_PANIC = "060"
CMD_CODE_SEND = "200"

# Inbound: ack/error
EVT_CMD_ACK = "500"
EVT_CMD_ERROR = "501"
EVT_SYSTEM_ERROR = "502"

# Inbound: arm/disarm / user attribution
EVT_PARTITION_ARMED = "652"
EVT_PARTITION_DISARMED = "655"
EVT_USER_CLOSING = "700"          # data = <part1><user4>
EVT_SPECIAL_CLOSING = "701"       # data = <part1>
EVT_PARTIAL_CLOSING = "702"       # data = <part1>
EVT_USER_OPENING = "750"          # data = <part1><user4>
EVT_SPECIAL_OPENING = "751"       # data = <part1>

# Special alarms (IT-100, also present on PC5401)
EVT_DURESS_ALARM = "620"          # data = <part1><user4> — duress code entered
EVT_FIRE_KEY_ALARM = "621"
EVT_FIRE_KEY_RESTORED = "622"
EVT_AUX_KEY_ALARM = "623"
EVT_AUX_KEY_RESTORED = "624"
EVT_PANIC_KEY_ALARM = "625"
EVT_PANIC_KEY_RESTORED = "626"

# Operational / diagnostic events — not "troubles" but useful for
# troubleshooting arming failures and security events. IT-100 extends the
# 5401 set with 659/660/672/673; we include them all.
EVT_KEYPAD_LOCKOUT = "658"        # data = <part1>
EVT_KEYPAD_BLANKING = "659"
EVT_COMMAND_OUTPUT = "660"
EVT_INVALID_CODE = "670"          # data = <part1>
EVT_FUNCTION_UNAVAILABLE = "671"  # data = <part1>
EVT_FAILED_TO_ARM = "672"         # data = <part1>  (IT-100 only)
EVT_PARTITION_BUSY = "673"        # data = <part1>  (IT-100 only)
EVT_CODE_REQUIRED = "900"         # panel is prompting for a user code

# Arm mode codes (cmd 652 second byte)
ARM_MODES = {
    "0": "away",
    "1": "stay",
    "2": "zero_entry_away",
    "3": "zero_entry_stay",
    "4": "armed",  # fallback when length == 1
}

# Inbound: trouble events. Mapping: code -> (key, is_restore_of)
# is_restore_of points at the "trouble" code; restore codes set the binary
# sensor OFF, trouble codes set it ON.
TROUBLE_EVENTS: dict[str, tuple[str, bool]] = {
    "800": ("panel_battery", False),
    "801": ("panel_battery", True),
    "802": ("panel_ac", False),
    "803": ("panel_ac", True),
    "806": ("bell", False),
    "807": ("bell", True),
    "810": ("tlm_line_1", False),
    "811": ("tlm_line_1", True),
    "812": ("tlm_line_2", False),
    "813": ("tlm_line_2", True),
    "814": ("ftc", False),               # FTC has no restore code in the API
    "816": ("buffer_near_full", False),  # no restore
    # 821/822 are intentionally absent — they're handled by the dedicated
    # per-zone battery code path in coordinator._handle_zone_low_battery,
    # which also derives the `device_low_battery` rollup so the aggregate
    # binary_sensor below stays correct (the trouble-event collapse was
    # wrong anyway: a 822 for zone N would clear the aggregate even if
    # zone M was still low).
    "825": ("wireless_key_low_battery", False),
    "826": ("wireless_key_low_battery", True),
    "827": ("handheld_keypad_low_battery", False),
    "828": ("handheld_keypad_low_battery", True),
    "829": ("general_tamper", False),
    "830": ("general_tamper", True),
    "831": ("home_automation", False),
    "832": ("home_automation", True),
    "840": ("trouble_status", False),
    "841": ("trouble_status", True),
    "842": ("fire_trouble", False),
    "843": ("fire_trouble", True),
    # IT-100 additions (event-code map from kostko/dsc-it100 — facts, not
    # creative content; no AGPL contamination).
    "896": ("keybus_fault", False),
    "897": ("keybus_fault", True),
}

# Friendly labels for each trouble key (used by binary_sensor names)
TROUBLE_LABELS: dict[str, str] = {
    "panel_battery": "Panel Battery Trouble",
    "panel_ac": "Panel AC Trouble",
    "bell": "Bell Circuit Trouble",
    "tlm_line_1": "Phone Line 1 Trouble",
    "tlm_line_2": "Phone Line 2 Trouble",
    "ftc": "Failure to Communicate",
    "buffer_near_full": "Event Buffer Near Full",
    "device_low_battery": "Device Low Battery",
    "wireless_key_low_battery": "Wireless Key Low Battery",
    "handheld_keypad_low_battery": "Handheld Keypad Low Battery",
    "general_tamper": "General System Tamper",
    "home_automation": "Home Automation Trouble",
    "trouble_status": "System Trouble Status",
    "fire_trouble": "Fire Trouble Alarm",
    "keybus_fault": "Keybus Fault",
}

# Full event-name lookup, used to populate the recent-events log with human
# readable descriptions. Sourced from the PC5401 spec (Misterhouse
# DSC5401.pm) and extended with IT-100 codes per kostko/dsc-it100.
EVENT_NAMES: dict[str, str] = {
    "500": "Command Acknowledge",
    "501": "Command Error",
    "502": "System Error",
    "550": "Time/Date Broadcast",
    "560": "Ring Detected",
    "561": "Indoor Temperature Broadcast",
    "562": "Outdoor Temperature Broadcast",
    "570": "Broadcast Labels",
    "580": "Baud Rate Set",
    "601": "Zone Alarm",
    "602": "Zone Alarm Restore",
    "603": "Zone Tamper",
    "604": "Zone Tamper Restore",
    "605": "Zone Fault",
    "606": "Zone Fault Restore",
    "609": "Zone Open",
    "610": "Zone Restored",
    "620": "Duress Alarm",
    "621": "Fire Key Alarm",
    "622": "Fire Key Restored",
    "623": "Auxiliary Key Alarm",
    "624": "Auxiliary Key Restored",
    "625": "Panic Key Alarm",
    "626": "Panic Key Restored",
    "631": "Auxiliary Input Alarm",
    "632": "Auxiliary Input Restored",
    "650": "Partition Ready",
    "651": "Partition Not Ready",
    "652": "Partition Armed",
    "653": "Partition Ready To Force Arm",
    "654": "Partition In Alarm",
    "655": "Partition Disarmed",
    "656": "Exit Delay In Progress",
    "657": "Entry Delay In Progress",
    "658": "Keypad Lock-Out",
    "659": "Keypad Blanking",
    "660": "Command Output",
    "670": "Invalid Code Access",
    "671": "Function Not Available",
    "672": "Failed To Arm",
    "673": "Partition Busy",
    "700": "User Closing (armed)",
    "701": "Special Closing (system-armed)",
    "702": "Partial Closing",
    "750": "User Opening (disarmed)",
    "751": "Special Opening (system-disarmed)",
    "800": "Panel Battery Trouble",
    "801": "Panel Battery Restored",
    "802": "Panel AC Trouble",
    "803": "Panel AC Restored",
    "806": "Bell Circuit Trouble",
    "807": "Bell Circuit Restored",
    "810": "Phone Line 1 Trouble",
    "811": "Phone Line 1 Restored",
    "812": "Phone Line 2 Trouble",
    "813": "Phone Line 2 Restored",
    "814": "Failure To Communicate",
    "816": "Event Buffer Near Full",
    "821": "Device Low Battery",
    "822": "Device Low Battery Restored",
    "825": "Wireless Key Low Battery",
    "826": "Wireless Key Low Battery Restored",
    "827": "Handheld Keypad Low Battery",
    "828": "Handheld Keypad Low Battery Restored",
    "829": "General System Tamper",
    "830": "General System Tamper Restored",
    "831": "Home Automation Trouble",
    "832": "Home Automation Trouble Restored",
    "840": "System Trouble Status",
    "841": "System Trouble Status Restored",
    "842": "Fire Trouble Alarm",
    "843": "Fire Trouble Restored",
    "896": "Keybus Fault",
    "897": "Keybus Fault Restored",
    "900": "Code Required",
    "904": "Beep Status",
    "908": "Version Info",
}

# How many recent events to retain on the Recent Events sensor attribute
RECENT_EVENTS_MAX = 50

# Error codes returned by 501 (Command Error)
ERROR_CODES: dict[str, str] = {
    "000": "No Error",
    "001": "RS-232 Receive Buffer Overrun",
    "002": "RS-232 Receive Buffer Overflow",
    "003": "Keybus Transmit Buffer Overrun",
    "010": "Keybus Transmit Buffer Overrun",
    "011": "Keybus Transmit Time Timeout",
    "012": "Keybus Transmit Mode Timeout",
    "013": "Keybus Transmit Keystring Timeout",
    "014": "Keybus Not Functioning",
    "015": "Keybus Busy (attempting arm or disarm)",
    "016": "Keybus Busy - Lockout (too many disarms)",
    "017": "Keybus Busy - Installers Mode",
    "020": "API Command Syntax Error",
    "021": "API Command Partition Error (partition out of bound)",
    "022": "API Command Not Supported",
    "023": "API System Not Armed",
    "024": "API System Not Ready To Arm",
    "025": "API Command Invalid Length",
    "026": "API User Code not Required",
    "027": "API Invalid Characters in Command",
}

# Default user-friendly name used when a special/anonymous close happens
ANON_USER_NAME = "System"
ANON_USER_ID = "0000"

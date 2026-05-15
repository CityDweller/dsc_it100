"""Constants for the DSC 5401 integration."""

from __future__ import annotations

DOMAIN = "dsc5401"

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
    "821": ("device_low_battery", False),
    "822": ("device_low_battery", True),
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
}

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

# DSC 5401 Home Assistant Integration

A custom Home Assistant integration for the DSC PC5401 (and IT-100) serial
interface boards used with DSC PowerSeries alarm panels. Designed to
**complement** the existing
[AlarmDecoder](https://www.home-assistant.io/integrations/alarmdecoder/)
integration rather than replace it.

AlarmDecoder already exposes the zones, partitions, and arm/disarm state.
This integration adds the things AlarmDecoder doesn't:

- **Who** armed or disarmed the panel (user name + 4-digit code)
- **Duress alarm** with the offending user code (latched, DSC code 620)
- **Trouble conditions** the panel reports as binary sensors: panel AC,
  panel battery, bell circuit, phone lines 1/2, FTC, **keybus fault**,
  device low battery, wireless key / handheld keypad low battery, general
  tamper, home automation, system trouble status, fire trouble
- **Operational events** for troubleshooting arming failures: invalid
  code, function unavailable, failed to arm, partition busy, keypad
  lockout
- A **recent-events log** (last 50 panel events as an entity attribute)
  for diagnostics without needing the HA history database
- A **`set_clock`** service to sync the DSC panel's internal clock to HA time
- A **`clear_duress`** service to manually clear a latched duress alarm

## Requirements

- Home Assistant **2026.5** or newer (uses the `serialx` async serial library)
- A DSC PC5401 (or compatible) serial interface board connected to a serial
  port reachable from HA — local USB, `rfc2217://`, or `esphome://`

## Installation

1. Copy `custom_components/dsc5401` into your HA `custom_components/` folder
2. Restart Home Assistant
3. Add the integration via **Settings → Devices & Services → Add Integration → DSC 5401**

## Configuration

The config flow has two steps:

1. **Serial port** — pick the port and baud rate (9600 default)
2. **Link to AlarmDecoder** *(optional)* — select an existing AlarmDecoder
   `alarm_control_panel` entity. When linked, all DSC 5401 entities are
   attached to the same device card as the AlarmDecoder panel.

You can map DSC user codes to friendly names via the options flow
(e.g. `0040` → "Gaetan").

## Services

### `dsc5401.set_clock`

Sets the DSC panel's internal clock to the current HA time. Recommend running
this daily (e.g. at 3 AM) via an automation to keep the panel synchronised and
to handle DST.

```yaml
automation:
  - alias: "DSC panel clock sync"
    trigger:
      platform: time
      at: "03:00:00"
    action:
      service: dsc5401.set_clock
```

### `dsc5401.send_command`

Advanced: send any raw DSC API command to the panel. See the
[DSC IT-100 Developer's Manual](https://cms.dsc.com/download.php?t=1&id=16238)
for command codes.

## Debug logging

To log every raw frame received from the panel:

```yaml
logger:
  default: warning
  logs:
    custom_components.dsc5401: debug
```

### `dsc5401.clear_duress`

Clears the latched Duress Alarm binary sensor. The DSC panel reports a
duress alarm once (code 620) and does not emit a restore code, so this
integration latches the alarm ON until you explicitly clear it via this
service.

## License

[MIT](LICENSE) — Copyright (c) 2026 Timothy Spaulding.

## Credits

Protocol framing/checksum/event-handling logic was ported from
[`DSC5401.pm`](https://github.com/hollie/misterhouse/blob/master/lib/DSC5401.pm)
in Misterhouse (by Jocelyn Brouillard and Gaetan Lord), with extensions
drawn from a related DSC IT-100 Misterhouse module the original author of
this integration wrote some years ago.

The IT-100 event-code extensions (keybus 896/897, partition busy 673,
failed-to-arm 672, etc.) were cross-referenced against the numeric
event-code table in [kostko/dsc-it100](https://github.com/kostko/dsc-it100)
(AGPL-3.0). Only the factual code → name mapping was used; no
copyrightable code was incorporated from that project.

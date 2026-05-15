# DSC 5401 Home Assistant Integration

A custom Home Assistant integration for the DSC PC5401 serial interface board
(used with DSC PowerSeries alarm panels). Designed to **complement** the
existing [AlarmDecoder](https://www.home-assistant.io/integrations/alarmdecoder/)
integration rather than replace it.

AlarmDecoder already exposes the zones, partitions, and arm/disarm state.
This integration adds the things AlarmDecoder doesn't:

- **Who** armed or disarmed the panel (user name and user code)
- **Trouble conditions** the panel reports (AC fail, low battery, bell trouble,
  TLM, FTC, tamper, fire trouble, etc.) as binary sensors
- A **`set_clock`** service to sync the DSC panel's internal clock to HA time

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

## Credits

Protocol logic adapted from Jocelyn Brouillard and Gaetan Lord's
`DSC5401.pm` Misterhouse module.

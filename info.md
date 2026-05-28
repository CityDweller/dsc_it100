# DSC IT-100

Home Assistant integration for the **DSC IT-100** (and equivalent
**PC5401**) serial interface module used with DSC PowerSeries alarm
panels.

Designed to **complement** the
[AlarmDecoder integration](https://www.home-assistant.io/integrations/alarmdecoder/)
rather than replace it: AlarmDecoder already handles zones, partitions,
and arm/disarm. This integration adds what AlarmDecoder doesn't expose:

- **Who** armed or disarmed the panel (user name + 4-digit code)
- **Duress alarm** — latched binary sensor, fires on DSC code 620
- **15 trouble binary sensors** for the conditions the panel reports:
  AC, panel battery, bell circuit, phone lines, FTC, keybus fault,
  device low battery, wireless key / handheld keypad low battery,
  general tamper, home automation, system trouble, fire trouble
- **Per-zone wireless battery sensors** (when linked to AlarmDecoder)
- **Last 50 panel events** as an entity attribute (for diagnostics
  without needing the HA history database)
- **`set_clock`** service — daily clock sync so panel timestamps stay
  accurate through DST
- **`clear_duress`** service — manually clear a latched duress alarm

## Requirements

- Home Assistant **2026.5** or newer
- DSC IT-100 / PC5401 reachable over USB serial, `rfc2217://`, or
  `esphome://` proxy
- *(Optional)* AlarmDecoder integration configured first, to enable
  device linking and per-zone wireless battery sensors

## Configuration

Add via **Settings → Devices & Services → Add Integration → DSC IT-100**.

The config flow has two steps:

1. **Serial port** — path or URL + baud rate (default 9600)
2. **Link to AlarmDecoder** *(optional)* — pick an existing
   `alarm_control_panel` entity to attach user-attribution entities to
   that device card

User-code-to-name mapping and partition / zone-model labels are set
later via the options flow.

## Local push, no polling

`iot_class: local_push` — the IT-100 emits events as they happen and the
integration parses them. Outbound traffic only happens when you call a
service.

See the [full README](https://github.com/CityDweller/dsc_it100#readme)
for the complete entity inventory, automation examples, FAQ, and
troubleshooting.

# DSC IT-100 Home Assistant Integration

A Home Assistant custom integration for the **DSC IT-100** serial
interface module (and the equivalent **PC5401**) used with DSC PowerSeries
alarm panels. Designed to **complement** — not replace — the existing
[AlarmDecoder](https://www.home-assistant.io/integrations/alarmdecoder/)
integration.

> **Why both?** AlarmDecoder already does the heavy lifting: zones,
> partitions, arm/disarm state, and the `alarm_control_panel` entity that
> drives automations and voice assistants. What it doesn't expose is
> *who* armed the panel, *what* the panel is troubleshooting, or *which*
> events the panel just emitted. The DSC IT-100 module reports all of
> that natively — this integration surfaces it as first-class HA
> entities.

[![Open in HACS][hacs-shield]][hacs-link]
[![License: MIT][license-shield]](LICENSE)
[![HA 2026.5+][ha-shield]][ha-link]

[hacs-shield]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[hacs-link]: https://hacs.xyz/
[license-shield]: https://img.shields.io/badge/license-MIT-blue.svg
[ha-shield]: https://img.shields.io/badge/Home%20Assistant-2026.5%2B-blue.svg
[ha-link]: https://www.home-assistant.io/

---

## What you get

### Trouble & diagnostic binary sensors (15)

All attach to a single "DSC IT-100" device card. Each maps to a specific
trouble code the panel raises and clears, so they reflect the panel's
own self-diagnostics rather than a polling heuristic:

| Entity | DSC codes | Notes |
|---|---|---|
| Panel AC Trouble | 802 / 803 | Mains power lost to the panel |
| Panel Battery Trouble | 800 / 801 | Standby battery weak |
| Bell Circuit Trouble | 806 / 807 | Siren circuit fault |
| Phone Line 1 Trouble | 810 / 811 | TLM line 1 (older panels) |
| Phone Line 2 Trouble | 812 / 813 | TLM line 2 (older panels) |
| Failure to Communicate | 814 | Cannot reach monitoring station |
| Event Buffer Near Full | 816 | Panel event log filling up |
| Device Low Battery | rolled-up | Aggregate of all per-zone 821/822 |
| Wireless Key Low Battery | 825 / 826 | Wireless keyfob battery |
| Handheld Keypad Low Battery | 827 / 828 | Portable keypad battery |
| General System Tamper | 829 / 830 | Cabinet / siren tamper |
| Home Automation Trouble | 831 / 832 | PGM / X-10 fault |
| System Trouble Status | 840 / 841 | Catch-all panel trouble flag |
| Fire Trouble Alarm | 842 / 843 | Fire-zone fault |
| **Keybus Fault** | 896 / 897 | IT-100 extension — wiring/comm fault on the keybus |

### Per-zone wireless battery sensors *(optional)*

When linked to an AlarmDecoder integration that has wireless zones, the
integration creates one **Battery** binary_sensor per zone, attached to
the AlarmDecoder zone's device. Driven by DSC codes 821 / 822, scoped to
the specific zone. You can label each zone's wireless model (e.g.
`WS4945`, `WS4904`) in the options flow so the
[Battery Notes](https://github.com/andrew-codechimp/HA-Battery-Notes)
integration can match the right battery type from its library.

### User-attribution sensors (4)

Attach to the linked AlarmDecoder device card. These tell you *who*
acted on the panel and *what* they did:

| Entity | Reports |
|---|---|
| Last User | Friendly name from your code map (e.g. "Angela"); raw 4-digit code on `user_id` attribute |
| Last Action | `armed` / `disarmed` / `special_armed` / `partial_armed` / `special_disarmed` / `duress` |
| Last Arm Mode | `away` / `stay` / `zero_entry_away` / `zero_entry_stay` |
| Duress Alarm (binary_sensor) | Latches ON when DSC code 620 fires; user code carried as attribute |

The **Duress Alarm** is intentionally latching — the DSC panel emits a
duress code *once* and doesn't send a restore. Use the
[`dsc_it100.clear_duress`](#dsc_it100clear_duress) service to clear it
once you've responded.

### Diagnostic sensors (4)

| Entity | Reports |
|---|---|
| Last Event | Timestamp of the most recent frame received |
| Last Event Code | Three-digit DSC code (e.g. `700`, `650`) |
| Last Error | Most recent 501/502 error text (if any) |
| Recent Events | Newest event as state; **last 50 events** as ring buffer in the `events` attribute |

The Recent Events sensor is particularly useful for debugging arming
failures without needing to enable the HA history database — just look
at the entity's attributes in Developer Tools.

---

## Requirements

- **Home Assistant 2026.5** or newer
- A **DSC IT-100** or **PC5401** serial interface board, with one of:
  - A local USB serial adapter wired to the IT-100
  - An `rfc2217://` network serial proxy (e.g. ser2net on a Pi)
  - An `esphome://` serial proxy on an ESPHome device wired to the IT-100
- *(Optional but recommended)* The
  [AlarmDecoder integration](https://www.home-assistant.io/integrations/alarmdecoder/)
  configured first, so you can link this integration to it during setup

The only external dependency is [`serialx`](https://pypi.org/project/serialx/) ≥ 0.1.0
(async-native serial library), installed automatically by HA.

---

## Installation

### Via HACS (recommended)

1. In HACS, go to **Integrations** → **⋮** → **Custom repositories**
2. Add `https://github.com/CityDweller/dsc_it100` as an **Integration**
3. Install **DSC IT-100** from the integrations list
4. Restart Home Assistant
5. Add the integration via **Settings → Devices & Services → Add Integration → DSC IT-100**

### Manual

1. Copy `custom_components/dsc_it100/` into your HA config's
   `custom_components/` folder
2. Restart Home Assistant
3. Add via **Settings → Devices & Services → Add Integration → DSC IT-100**

---

## Configuration

### Initial setup (two steps)

**Step 1 — Serial port**

| Field | Description |
|---|---|
| Serial port | Path or URL to the IT-100 — e.g. `/dev/ttyUSB0`, `rfc2217://10.0.0.5:4001`, `esphome://nodename:6638` |
| Baud rate | Default `9600`. Most installs leave this alone; only change if you've reprogrammed the panel's serial baud. |

**Step 2 — Link to AlarmDecoder *(optional)***

Select an existing `alarm_control_panel` entity — typically the one
AlarmDecoder created. When linked:

- The 4 user-attribution / duress entities attach to the AlarmDecoder
  device card, alongside its zones and arm state
- Per-zone wireless battery sensors are created using AlarmDecoder's
  zone list

Leave blank for a standalone install — everything attaches to the
DSC IT-100 device, no per-zone battery sensors.

### Options flow

Available later via **Settings → Devices & Services → DSC IT-100 → Configure**:

```
0040: Gaetan
0001: Master
1234: Service tech
```

Each line is `code: name`. The four-digit code matches the user code on
your panel; the name shows up as the value of the `sensor.last_user`
entity when that code is used.

You can also rename partitions (e.g. `1: House`, `2: Garage`) and assign
wireless zone models (e.g. `1: WS4945`) in the same options screen.

---

## Services

### `dsc_it100.set_clock`

Sync the DSC panel's internal clock to HA's current local time. Recommended
as a daily automation so the panel's event timestamps stay in sync and DST
transitions get handled automatically:

```yaml
automation:
  - alias: "DSC panel clock sync"
    trigger:
      - platform: time
        at: "03:00:00"
    action:
      - service: dsc_it100.set_clock
```

### `dsc_it100.send_command`

Send a raw DSC API command to the panel. The integration appends the
checksum and CR/LF framing automatically — you only provide the
three-digit command code and optional data string.

```yaml
service: dsc_it100.send_command
data:
  code: "010"
  data: "0830052625"   # arbitrary command-specific payload
```

See the
[DSC IT-100 Developer's Manual](https://cms.dsc.com/download.php?t=1&id=16238)
for valid command codes and their payload format. **Advanced use only**;
incorrect commands won't damage the panel but can confuse it.

### `dsc_it100.clear_duress`

Clear the latched `binary_sensor.duress_alarm`. Use this after you've
responded to a duress event:

```yaml
service: dsc_it100.clear_duress
```

The panel emits the duress code (620) exactly once and never sends a
restore, so this integration latches the binary_sensor ON until you
explicitly clear it. Don't auto-clear it in an automation unless you're
sure that's what you want — a duress alarm typically warrants manual
acknowledgement.

---

## Suggested automations

### Notify on any new trouble

```yaml
automation:
  - alias: "DSC trouble alert"
    trigger:
      - platform: state
        entity_id:
          - binary_sensor.dsc_it_100_panel_ac_trouble
          - binary_sensor.dsc_it_100_panel_battery_trouble
          - binary_sensor.dsc_it_100_bell_circuit_trouble
          - binary_sensor.dsc_it_100_keybus_fault
          - binary_sensor.dsc_it_100_system_trouble_status
        to: "on"
    action:
      - service: notify.mobile_app
        data:
          title: "DSC panel trouble"
          message: >-
            {{ trigger.to_state.attributes.friendly_name }} just went on
```

### Daily panel clock sync (see `set_clock` above)

### Log who disarmed the panel at night

```yaml
automation:
  - alias: "Late-night disarm log"
    trigger:
      - platform: state
        entity_id: sensor.dsc_it_100_last_action
        to: "disarmed"
    condition:
      - condition: time
        after: "22:00:00"
        before: "06:00:00"
    action:
      - service: logbook.log
        data:
          name: "Alarm"
          message: >-
            Disarmed late by {{ states('sensor.dsc_it_100_last_user') }}
```

---

## Debug logging

To log every raw frame read from / written to the panel:

```yaml
logger:
  default: warning
  logs:
    custom_components.dsc_it100: debug
```

Each line is prefixed with the source (`RX:` / `TX:`) and shows the raw
DSC API frame including checksum.

---

## Frequently asked questions

**Will this work without AlarmDecoder?**
Yes. AlarmDecoder linking is optional. Without it you get all the trouble
sensors and diagnostic entities; you just lose the per-zone battery
sensors (which need AlarmDecoder's zone list) and the user-attribution
co-location with the alarm panel.

**Does this support multiple DSC panels in one HA install?**
No. The integration is `single_config_entry: true` — one IT-100 per HA
install. If you have multiple panels and want this changed, file an issue.

**Why is the duress alarm latching?**
The DSC protocol reports duress as a one-shot event (code 620) with no
restore. If the integration auto-cleared it after the next event the
user code would scroll past and you'd miss it. Latching makes the alarm
unmissable — see [`clear_duress`](#dsc_it100clear_duress) to reset it.

**What if my panel is a PC1864 / PC1832 / PC5020?**
Those panels all use the same IT-100 / PC5401 serial protocol. The
integration speaks the protocol, not the panel — anything that talks to
an IT-100 will work.

**Does this poll the panel?**
No. The IT-100 pushes events as they happen (it's `iot_class:
local_push`). The integration only sends outbound when you call a
service.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Integration won't start, "cannot connect" | Wrong serial port path, wrong baud rate, or another process owns the serial device |
| Entities created but never update | Panel section programming has IT-100 module disabled, or wrong protocol mode set |
| Last User always shows raw code instead of name | The code isn't in the options-flow user-name map yet |
| "Failure to Communicate" stuck ON | Panel really can't reach the monitoring station — check phone/cell module — or you've never had a successful comm and the trouble was set as initial state |
| Trouble entities don't restore | Some trouble codes (FTC 814, buffer-full 816) genuinely have no restore in the DSC protocol. Clear them by triggering then resolving the underlying condition, or use the panel's keypad to acknowledge. |

If you find a bug, please open an issue at
[github.com/CityDweller/dsc_it100/issues](https://github.com/CityDweller/dsc_it100/issues)
with debug logs (see above).

---

## License

[MIT](LICENSE) — Copyright (c) 2026 Timothy Spaulding.

## Credits

Protocol framing, checksum, and event-handling logic was ported from
[`DSC5401.pm`](https://github.com/hollie/misterhouse/blob/master/lib/DSC5401.pm)
in [Misterhouse](https://github.com/hollie/misterhouse) (by Jocelyn
Brouillard and Gaetan Lord), with additional extensions drawn from a
related DSC IT-100 Misterhouse module the original author of this
integration wrote some years ago.

The IT-100 event-code extensions (keybus 896/897, partition busy 673,
failed-to-arm 672, etc.) were cross-referenced against the numeric
event-code table in
[kostko/dsc-it100](https://github.com/kostko/dsc-it100) (AGPL-3.0).
**Only the factual code → name mapping was consulted; no copyrightable
code was incorporated from that project.**

<p align="center">
  <img src="custom_components/chained_blinds/brand/icon@2x.png" alt="Chained Blinds Controller icon" width="96" height="96">
</p>

# Chained Blinds Controller

[![CI](https://github.com/snapicek/home-assistant-blinds/actions/workflows/validate.yml/badge.svg)](https://github.com/snapicek/home-assistant-blinds/actions/workflows/validate.yml)
[![GitHub Release](https://img.shields.io/github/v/release/snapicek/home-assistant-blinds?style=flat-square)](https://github.com/snapicek/home-assistant-blinds/releases)
[![License: MIT](https://img.shields.io/github/license/snapicek/home-assistant-blinds?style=flat-square)](LICENSE)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=flat-square)](https://hacs.xyz)

A Home Assistant custom integration for **chain-driven motorized blinds** where both 0 % and 100 % are fully dark and the position of maximum light differs per physical cover and must be calibrated individually.

The integration automatically moves your covers through four semantic states based on a lux sensor and configurable thresholds — every threshold can be retuned at any time via the integration's **Configure** dialog, with no restart needed.

---

## Features

- **Four semantic states** — `open`, `medium`, `shade`, `closed` — mapped to per-cover calibrated raw positions.
- **Automatic lux-based control** — moves covers darker as light increases, lighter when light drops, using separate thresholds for each direction (hysteresis).
- **Dwell lock** — prevents rapid down→up→down cycling that can damage chain-drive mechanisms.
- **Night window** — configurable time range during which the integration holds the blind closed regardless of lux.
- **Workday-aware mornings** — uses `binary_sensor.workday_sensor` to choose between normal and non-workday morning opening times.
- **Manual override** — dedicated switch holds the current position for a configurable number of minutes, then auto-clears; no external `timer` helper needed.
- **Optional gradual ramping** — when enabled, blinds move toward the target in configurable step sizes at configurable intervals.
- **Fully UI-configured** — Config Flow setup, with every threshold and calibration value re-adjustable later via **Configure** (no YAML editing).
- **Two-cover rooms** — left and right covers move together with a 1 s stagger so they don't strain the same circuit simultaneously.

---

## Requirements

| Requirement | Notes |
|---|---|
| Home Assistant | ≥ 2026.5 |
| A lux sensor entity | e.g. `sensor.living_room_illuminance` |
| One or two `cover` entities | Chain-driven roller blind(s) |
| Optional `binary_sensor.workday_sensor` | `on` = workday open time, `off` = non-workday open time |

---

## Installation

### Via HACS (recommended)

1. Open HACS in Home Assistant.
2. Go to **Integrations** → click the three-dot menu → **Custom repositories**.
3. Paste `https://github.com/snapicek/home-assistant-blinds` and set category to **Integration**, then click **Add**.
4. Search for **Chained Blinds Controller** and click **Download**.
5. Restart Home Assistant.

### Manual

1. Download or clone this repository.
2. Copy the `custom_components/chained_blinds/` folder into your Home Assistant config directory:
   ```
   <config>/custom_components/chained_blinds/
   ```
3. Restart Home Assistant.

---

## Configuration

Setup takes just **two pages**:

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **Chained Blinds Controller** and select it.
3. **Page 1 — Room & devices:**
    - **Room name** *(optional)* — used for the device and every entity created for it, e.g. "Bedroom".
    - **Left cover** *(required)* — a `cover` entity.
    - **Right cover** *(optional)* — second `cover` entity; moves 1 s after the left one.
    - **Light sensor** — a `sensor` entity reporting illuminance in lux.
4. **Page 2 — Calibration:** the raw position (0–100 %) each blind should take for the four states.

That's it — all thresholds, delays, and scheduling start with sensible defaults.

### Changing settings later

Open the integration's **Configure** button to get a **settings menu** with focused pages:

| Menu section | What's on it |
|---|---|
| 🏠 Room & devices | Room name, covers, light sensor |
| ☀️ Light thresholds | Close/reopen brightness levels with hysteresis |
| ⏱️ Delay times | Darkening/reopening delays, pause duration |
| 🌅 Opening schedule | Workday & weekend opening times, sunrise/sunset offsets |
| 🍂 Seasonal sensitivity | Summer/winter threshold factors |
| 🐢 Gradual movement | Step-by-step motion instead of direct jumps |
| 🎯 Position calibration | Per-blind raw positions for each state |

Each page shows an explanation and the default under every field, **saves the moment you submit it**, and returns you to the menu — adjust one setting or all of them in a single visit, then choose *Finish*. Changes apply immediately; no restart needed.

### Entities

Everything the integration creates lives under one device per room:

| Entity | Purpose |
|---|---|
| `select.<room>_blind_position_mode` | Current/manual semantic state — pick `Open`, `Medium shade`, `Full shade`, or `Closed` to move the blinds there directly. Selecting a state does **not** pause the automatic resolver; use "Pause automation" for that. |
| `switch.<room>_automation_enabled` | Turn the automatic lux/schedule-based control on or off |
| `switch.<room>_pause_automation` | Temporarily hold the current position while keeping automation enabled; auto-clears after the configured pause duration |

All lux thresholds, delays, scheduling, seasonal factors, ramp settings, and per-cover calibration are tuned via **Configure**, not via separate entities.

If `binary_sensor.workday_sensor` does not exist, the integration falls back to the normal workday opening time every day.

---

## How it works

<details>
<summary>Show details</summary>

Covers are moved only via `cover.set_cover_position` with an explicit calibrated percentage — never `open_cover`/`close_cover`. This guarantees physical accuracy regardless of the cover's internal state tracking.

The coordinator re-evaluates on every 5-minute poll **and** whenever the lux sensor or `binary_sensor.workday_sensor` changes. Effective morning open time is selected first: the configured "Workday opening time" on workdays, "Non-workday opening time" on non-workdays.

Resolver/move priority then works like this:

1. **Manual override** — if `switch.<room>_pause_automation` is on, current state is held.
2. **Night window** — before effective morning open time, or after sunset boundary, target state is `closed`.
3. **Lux thresholds** — compares lux against primary thresholds to darken immediately.
4. **Reopen hysteresis** — lightening only happens after the lower `*_reopen` thresholds are crossed.
5. **Dwell lock** — actual movement is delayed by `dwell_minutes` for darkening and `reopen_dwell_minutes` for lightening.

| State | Rank | Description |
|---|---|---|
| `open` | 0 | Maximum light (~75 %, calibrated per cover) |
| `medium` | 1 | Partially closed |
| `shade` | 2 | Sun-blocking position |
| `closed` | 3 | Fully dark, 0 % |

Darkening (rank ↑) is immediate. Lightening (rank ↓) requires crossing the `lux_reopen` threshold **and** waiting out the dwell period.

</details>

---

## Development

```bash
pip install pytest pytest-asyncio homeassistant
pytest
```

The test suite in `tests/` uses lightweight hand-rolled fakes (`tests/fakes.py`) rather than the full `pytest-homeassistant-custom-component` harness. The resolver unit tests serve as the executable specification for the decision logic.

CI runs HACS validation and hassfest on every push — see `.github/workflows/validate.yml`.

---

## Contributing

Pull requests and issues are welcome. Please open an issue first for larger changes.

[Open an issue](https://github.com/snapicek/home-assistant-blinds/issues)

---

## License

[MIT](LICENSE) © 2026 Snapicek

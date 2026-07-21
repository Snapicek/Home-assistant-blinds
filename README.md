# Chained Blinds Controller

A Home Assistant **custom integration** (installable via HACS as a custom
repository, category *Integration*) for chain-driven motorized blinds where
0% and 100% are both fully dark and the position of maximum light differs
per physical cover and must be calibrated.

This project used to be a markdown prompt template for generating a
YAML automation blueprint. It is now being rebuilt as a real Python
integration so it can be installed and configured from the HA UI instead of
hand-editing YAML. The original rules/design doc is preserved at
[`docs/BLUEPRINT_PROMPT.md`](docs/BLUEPRINT_PROMPT.md).

## Status

🚧 Under construction. Implemented so far:

- [x] `const.py` — domain, semantic states (`open`/`medium`/`shade`/`closed`),
      rank table, default thresholds/dwell values.
- [x] `resolver.py` — the pure decision logic (night window, lux tiers,
      sun-at-window gating, hysteresis on lightening moves, dwell lock),
      covered by unit tests in `tests/test_resolver.py`.
- [x] `manifest.json` / `hacs.json` — HACS Integration-category metadata.
- [ ] Config Flow (set up covers, lux sensor, optional sun sensor per room).
- [ ] `number`/`select`/`switch`/`time` entities for live dashboard tuning
      of thresholds, dwell minutes, per-cover calibration, and manual
      override.
- [ ] `coordinator.py` + `cover_control.py` wiring it all together and
      calling `cover.set_cover_position`.
- [ ] CI (hassfest + HACS validation).

## Design summary

Each cover is controlled only via `cover.set_cover_position` with an
explicit calibrated percentage — never `open_cover`/`close_cover`. Covers
move between four semantic states, not raw percentages:

| State | Rank | Meaning |
| --- | --- | --- |
| `open` | 0 | Straight/max light, ~75% (calibrated per cover). |
| `medium` | 1 | Partially closed. |
| `shade` | 2 | Sun-blocking position. |
| `closed` | 3 | Fully dark, 0%. |

Darkening (moving to a higher rank) happens immediately. Lightening (moving
to a lower rank) requires the smoothed lux to cross a separate, lower
"reopen" threshold and a longer dwell period — this hysteresis plus the
dwell lock is what prevents chain-load-damaging `down → up → down` cycling.
See `custom_components/chained_blinds/resolver.py` and its tests for the
exact rules, and `docs/BLUEPRINT_PROMPT.md` for the original prose spec this
was ported from.

## Installing (once complete)

1. HACS → Custom repositories → add this repo's URL, category *Integration*.
2. Install, restart Home Assistant.
3. Settings → Devices & Services → Add Integration → "Chained Blinds
   Controller", and follow the config flow.

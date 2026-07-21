# Chained Blinds Controller

A Home Assistant **custom integration** (installable via HACS as a custom
repository, category *Integration*) for chain-driven motorized blinds where
0% and 100% are both fully dark and the position of maximum light differs
per physical cover and must be calibrated.

This project used to be a markdown prompt template for generating a YAML
automation blueprint. It's now a real Python integration, configured from
the HA UI instead of hand-edited YAML.

## Status

Implemented:

- `const.py` — domain, semantic states (`open`/`medium`/`shade`/`closed`),
  rank table, default thresholds/dwell values, entity specs.
- `resolver.py` — the pure decision logic (night window, lux tiers,
  sun-at-window gating, hysteresis on lightening moves, dwell lock).
- `models.py` — per-room runtime data + restart-safe persistence
  (`current_state`/`last_move_time`) via `homeassistant.helpers.storage.Store`.
- `config_flow.py` — Config Flow + Options Flow (left/right cover, lux
  sensor, optional sun-at-window sensor).
- `number.py` / `select.py` / `switch.py` / `time.py` — the live-tunable
  dashboard entities: lux thresholds (+ reopen hysteresis), dwell minutes,
  sunset offset, per-cover-per-state calibration, enable switch, manual
  override switch (self-contained — no external `timer` helper needed),
  open time, and the tracked-state select.
- `cover_control.py` — looks up calibrated positions and calls
  `cover.set_cover_position` only, with a 1s stagger for the second cover.
- `coordinator.py` — 5-minute + event-driven re-evaluation wiring the
  resolver to `cover_control`.
- `__init__.py` — entry setup/teardown, listener wiring, reload-on-options.
- `manifest.json` / `hacs.json` — HACS Integration-category metadata.
- `.github/workflows/validate.yml` — hassfest + HACS validation + pytest.
- Test suite (`tests/`): resolver unit tests are the executable spec;
  cover_control/coordinator/config_flow/entity tests run against lightweight
  hand-rolled fakes rather than the full `pytest-homeassistant-custom-component`
  harness (that package's transitive dependencies didn't build cleanly in
  the sandbox this was developed in — see `tests/fakes.py`'s docstring).
  Run with `pytest`.

Not yet done / needs a real Home Assistant instance to verify:

- End-to-end HACS custom-repository install flow and the config flow UI.
- Real chain-driven cover behavior at calibrated raw percentages.
- HA restart persistence of `current_state`/`last_move_time` (unit-tested
  against a fake store; not yet checked against a real restart).
- Real `sun.sun`/sunset+offset timing across timezones/DST.
- Two simultaneous config entries (two rooms) not colliding.
- Full entity-lifecycle tests (`RestoreEntity` restore-on-add, config-flow
  FlowManager steps end-to-end) via `pytest-homeassistant-custom-component`.

The `hacs` CI job checks readiness for the *official HACS default store*
listing, not for adding this as your own custom repository (which works
regardless of this job's result). It currently fails on things only you can
set: repo description and topics (GitHub repo "About" section) and brand
assets (a submission to the separate `home-assistant/brands` repo) — none of
these block personal use, only official-store listing, so they're left as
manual/optional follow-up.

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
exact rules.

A manual override is its own switch (`switch.<room>_override`): turning it
on holds the current position and auto-clears after
`number.<room>_override_duration_minutes`, without needing a pre-created
`timer.` helper. Manually picking a state on `select.<room>_state` routes
through the same move path the automatic resolver uses, so it never
bypasses calibration or dwell bookkeeping — but it doesn't disable the
resolver, which can still move things again on its next cycle unless you
also turn off `switch.<room>_enabled` or engage override.

## Installing

1. HACS → Custom repositories → add this repo's URL, category *Integration*.
2. Install, restart Home Assistant.
3. Settings → Devices & Services → Add Integration → "Chained Blinds
   Controller" → pick the left cover (required), right cover (optional),
   lux sensor, and optional sun-at-window binary sensor.
4. Calibrate: on the room's device page, set each `number.*_pos` entity to
   the raw position that gives that physical cover the right amount of
   light for that semantic state, then tune the lux thresholds/dwell values
   to taste — all live, no reload needed.

## Development

```
pip install pytest pytest-asyncio homeassistant
pytest
```

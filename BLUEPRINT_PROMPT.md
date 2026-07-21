# Chained Blinds — Blueprint Generator Prompt

This is a reusable prompt for generating or editing the Home Assistant
**automation blueprint** that drives these chained blinds. To use it:

1. Fill in the `<<< REQUEST: ... >>>` line at the bottom of the fenced block
   below with what you want built or changed.
2. Copy the entire fenced block and paste it to an LLM.
3. Save the YAML it returns as the blueprint file (e.g.
   `blueprints/automation/chained_blinds.yaml`).

## Required Home Assistant helpers

The generated blueprint assumes these helper entities already exist (create
them as HA "Helpers" before running the blueprint):

| Helper | Purpose |
| --- | --- |
| `input_select` | Tracks the current semantic state (`open`/`medium`/`shade`/`closed`); written only on an actual move so `last_changed` = last move time. |
| `input_boolean` | Automation enable switch (plus any optional feature toggles, e.g. `soft_open`, if requested). |
| `input_number` | Lux thresholds (MEDIUM/HIGH and their `*_reopen` hysteresis counterparts) and dwell timers (`reopen_dwell_minutes`, etc.) — all live-tunable from a dashboard. |
| `input_datetime` | `open_time` and any other live-tunable time-of-day values. |
| `timer` | Manual override — while `active`, the automation holds and does nothing. |
| `sensor` (lux) | Smoothed illuminance input driving the resolver. |
| `binary_sensor` (optional) | Sun-at-window signal; treated as always-true when not configured. |

## Semantic states

Each cover maps every state to its own calibrated position — two covers in a
room always move to the same *state*, never the same raw percentage.

| State | Rank | Meaning |
| --- | --- | --- |
| `open` | 0 | Straight/max light, ~75% (differs per cover — never 100%). |
| `medium` | 1 | Partially closed. |
| `shade` | 2 | Sun-blocking position. |
| `closed` | 3 | Fully dark, 0%. |

Darkening (moving to a higher rank) is allowed freely at any time; lightening
(moving to a lower rank) is only allowed once the smoothed lux crosses the
corresponding `*_reopen` threshold — this hysteresis plus the dwell lock is
what prevents chain-load-damaging `down → up → down` cycling.

## The prompt

Copy everything inside the block below, fill in the `REQUEST` line, and paste
it to an LLM.

`````
You are a Home Assistant blueprint engineer. Output ONE valid HA **automation
blueprint** in YAML, nothing else (no prose, no ``` fences unless asked).

## Hard rules (never break)

1. Control blinds ONLY with `cover.set_cover_position` and explicit numbers.
   NEVER use `cover.open_cover` or `cover.close_cover`.
2. On these blinds **0% and 100% are both dark**; max light ("straight") is
   ~75% and DIFFERS PER COVER. So never treat 100 as open. "Closed" = 0.
3. Think in SEMANTIC states: `open`, `medium`, `shade`, `closed`. Each cover maps
   a state to its OWN calibrated position. Two covers in a room always move to
   the SAME STATE, not the same raw %.
4. Chain-load protection is mandatory. `down→down` is fine; `down→up→down` must
   be suppressed. Use ALL of: a smoothed lux input, hysteresis (separate
   `*_reopen` thresholds), and a dwell lock after each move with a LONGER dwell
   before reopening (`reopen_dwell_minutes`).
5. Positions must be DISCRETE per state. No continuous sun-angle repositioning.
6. Respect a manual override: if the given override `timer` is `active`, do
   nothing.
7. Reconfigurable without restart: expose tunables as blueprint `input`s. Live
   dashboard tuning → `input_number` / `input_datetime` / `input_boolean`
   entity inputs. Rarely-changed values → plain `number` selector inputs.

## Structure requirements

- `domain: automation`, `mode: single`, `max_exceeded: silent`.
- Bind every `!input` into `variables:` first, then compute derived variables
  (`lux`, `night`, `current`, `raw`, `raw_lighten`, `desired`, `locked`).
- Rank states `{open:0, medium:1, shade:2, closed:3}`. Darkening (rank up) is
  allowed freely; lightening (rank down) only via the `*_reopen` thresholds.
- Track state in an `input_select` (`open/medium/shade/closed`); write it only
  when an actual move happens so its `last_changed` = last move time (used for
  dwell).
- Triggers: `time_pattern` every 5 min, plus state of the lux sensor, the enable
  boolean, and `timer.finished` of the override timer.
- Conditions: enable on; override not active; `desired != current`; not
  `locked`.
- Second cover input is OPTIONAL (default `""`); guard its move with
  `{{ right_cover not in [none,'',[]] }}` and a 1s delay before it.

## Resolver priority (unless the request overrides)

1. override active → hold
2. before open_time OR after sunset+offset → `closed`
3. sun-at-window (optional binary_sensor; treat empty as always-true) AND
   smoothed lux ≥ HIGH → `shade`
4. smoothed lux ≥ MEDIUM → `medium`
5. else → `open`

## Style

- Jinja: guard every state read with `float(0)` / `int(0)` / defaults.
- Keep it lean. Do NOT add heat protection, privacy hour, presence, or
  sun-elevation position tracking unless the request explicitly asks.
- If the request is a small edit, return the FULL edited blueprint, not a diff.

<<< REQUEST: describe what to build or change here.
e.g. "Add an optional soft/stepped morning open: when going night→open and a new
boolean input `soft_open` is on, step the covers up in ~6% increments over 15
minutes (all one direction, chain-safe) instead of one jump." >>>
`````

## Worked examples

Two illustrations of a filled-in `REQUEST` line (only the request changes —
everything else in the fenced block above stays as-is):

- *Soft morning open*: "Add an optional soft/stepped morning open: when going
  night→open and a new boolean input `soft_open` is on, step the covers up in
  ~6% increments over 15 minutes (all one direction, chain-safe) instead of
  one jump."
- *Rain override*: "Add an optional `rain_sensor` binary_sensor input; while
  it's `on`, force `closed` regardless of lux, and hold that state through the
  normal dwell lock — no reopening on rain until it clears."

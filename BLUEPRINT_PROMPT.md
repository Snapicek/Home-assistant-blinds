# Blueprint prompt

Paste this to an LLM to generate or edit a Home Assistant **automation
blueprint** for these chained blinds. Fill the `<<< >>>` request line at the
bottom.

---

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

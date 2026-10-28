# Engine scenarios

The engine scenarios let an integrator replay the three fixed care
scenarios — a normal morning dropoff, a forgotten passenger with a
rising cabin temperature, and a pet dropoff — through the public API
and observe the exact session states a real signal source would produce.

## Sub-features

- `scenario-dropoff` replays `dropoff_normal` to COMPLETED.
- `scenario-forgotten` replays `forgotten_rising_temp` to EXCEPTION with
  the passenger still present and the cabin at 35.5℃.
- `scenario-pet` replays `pet_dropoff` to COMPLETED.
- `scenario-unknown` rejects an unknown scenario name with `ValueError`
  and leaves the session untouched.
- `scenario-determinism` gives identical transitions on repeated replays.

## How to get to it (user POV)

- Run the verification helper's `drive` command with a scenario name.
- Import `replay_scenario` from `engine.adapters.simulator` in Python and
  apply it to a new `CareSession`.
- Look up snapshot sequences by name with `scenario_snapshots`.

## Driving it with verify_carbom.py

Preconditions:

- `verify_carbom.py doctor` exits 0 from the project root.
- Each drive uses a fresh `CareSession()`.

- **Normal dropoff.** Run `python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py drive --scenario dropoff_normal --out .cursor/skills/verify-carbom/artifacts/check`. Exit code 0, final state COMPLETED, 6 transitions ending ALIGHTING -> COMPLETED (`alighting_confirmed`) at 300.0, report summary `하차 확인 완료 · 예외 없음`.
- **Forgotten passenger.** Run the same command with `--scenario forgotten_rising_temp`. Exit code 0, final state EXCEPTION, `passenger_present: True`, last transition ARRIVED -> EXCEPTION (`ignition_off_locked_passenger_present`), guidance URGENT with `35.5도` and `즉시` in the text, report summary `예외 발생 · 하차 미확인`.
- **Pet dropoff.** Run the same command with `--scenario pet_dropoff`. Exit code 0, final state COMPLETED with 6 transitions.
- **Unknown name.** In Python, call `replay_scenario(CareSession(), "nope")`. It raises `ValueError`; the session stays IDLE with an empty history.
- **Determinism.** Drive `dropoff_normal` twice into two fresh sessions. The (from_state, to_state, reason, timestamp) sequences are identical.
- **Proof.** Open `artifacts/check/drive-<scenario>.json`. It records the scenario, expected and actual final state, every transition, the guidance, and the report for each driven scenario.

## Gotchas

- Scenario names are exact: case changes, surrounding spaces, or
  separator changes all raise `ValueError` — do not "fix" input.
- `SessionState` values are lowercase strings; compare by enum or by
  `.name`, never against an uppercase `.value`.
- The forgotten scenario's exception is entered from ARRIVED, not from
  DRIVING; a drive that expects a direct DRIVING -> EXCEPTION transition
  is wrong, not the engine.
- Reusing one session across scenarios leaks history and temperatures
  into the next report. Always start fresh (or call `reset()` and prove
  the reset state first).

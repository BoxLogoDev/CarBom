---
name: verify-carbom
description: "Verify CarBom (가족 동승 케어 코어 엔진 + 정적 웹 데모) the way a user/integrator does: replay the fixed care scenarios through the public Python engine API, check guidance and care reports, and drive the static demo page state. Use whenever CarBom engine, guidance, report, adapter, or demo behavior changes, or before claiming a CarBom cycle is complete."
---

# Verify CarBom

Project-local verification skill for CarBom, generated with the pstack
`create-verification-skill` procedure on 2026-10-28. CarBom has two
user-facing surfaces:

- **Core engine (primary):** a Python library in `engine/`. Its "user" is
  an integrator (demo, future AAOS app) calling the public API:
  `CareSession`, the simulator adapter, `guidance_for_session`,
  `report_for_session`, profiles, and the Vehicle SDK adapter layer.
- **Demo (secondary):** a static web page in `demo/` (`index.html`,
  `styles.css`, `demo.js`) with no build step and no external resources,
  showing the vehicle screen and the driver phone screen side by side.

There is no server, database, account, or seed data. Do not invent one.

## Launch

- Engine: no process to start. Work from the project root
  (`~/workspace/projects/carbom`) so `import engine` resolves, and drive
  the public API in a fresh Python process per run.
- Demo: open `demo/index.html` directly as a file. Do **not** start
  `python3 -m http.server` or any other server; the page is fully static.
  For scripted checks, load `demo/demo.js` in Node with a minimal DOM
  stub (the pattern used by the supervisor checks) or open the file in a
  real browser when one is available. Query parameters
  `?scenario=<key>&step=<1-based step>` pin a scenario and step on load.
- Ready means: the doctor check below passes and one scenario drive
  reaches its expected final state — not merely that imports succeed.

## Doctor

Run the read-only health check first, and again whenever anything looks
off:

```bash
cd ~/workspace/projects/carbom
python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py doctor
```

It prints the resolved project root, the Python version (requires
>= 3.10), the presence of every required engine/demo file, and the
result of `node --check demo/demo.js`. Exit code 0 means this checkout
is worth driving. It writes nothing.

Baseline regression check (run alongside, not instead of, driving):

```bash
python3 -m unittest discover -s tests
node --check demo/demo.js
```

## Drive

Use the helper for the engine surface:

```bash
python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py drive \
  --scenario dropoff_normal \
  --out .cursor/skills/verify-carbom/artifacts/<run-name>
```

- `--scenario` is one of `dropoff_normal` (expected final state
  COMPLETED), `forgotten_rising_temp` (EXCEPTION, passenger still
  present, guidance URGENT), `pet_dropoff` (COMPLETED).
- The helper drives only the public path: `replay_scenario` from
  `engine.adapters.simulator`, then `guidance_for_session` with the
  DROPOFF context, then `report_for_session`. It fails (exit 1) if the
  final state differs from the scenario's expected outcome or the
  report disagrees with the session.
- Feature recipes live in `features/` — read the index
  (`features/README.md`) first, then the matching feature file, and
  follow it literally.

For the demo surface, drive the real controls, by their stable ids:
scenario select `#scenario-select`, `#next-step`, `#reset`, step readout
`#step-indicator`, vehicle screen `#vehicle-state`, `#guidance-level`,
`#guidance-text`, signal readouts `#sig-door`, `#sig-belt`,
`#sig-ignition`, `#sig-lock`, `#sig-hvac`, `#sig-temp`, and phone screen
`#phone-card`, `#phone-level`, `#phone-state`, `#phone-text`. Prefer
these ids over coordinates or tab order. Cross-check every demo step
against the engine: replaying the same scenario through the engine must
produce the same state, guidance level/text, and signal values.

## Evidence

- Proof artifacts go under
  `.cursor/skills/verify-carbom/artifacts/<run-name>/` and survive
  cleanup. The helper writes `drive-<scenario>.json` (transitions,
  guidance, report, snapshots) and `drive-<scenario>.txt` (human
  transcript) there.
- Exercise the real user path (public API / real demo controls), not
  internal setters or private helpers.
- Capture the action **and** the resulting state: the full transition
  list with reasons and timestamps, not only the final state.
- Verify side effects alongside what is visible: report fields must
  agree with the session (`final_state`, `transition_count` ==
  `len(history)`, exception counts, max cabin temperature), and demo
  displays must agree with the engine replay.
- Record the feature ID and entry point used with every artifact. If a
  path cannot be driven, report the attempted command and the unmet
  precondition — never report a skipped path as verified.
- No mocks beyond the boundaries the project itself defines: the
  simulator adapter and fake Vehicle SDK clients in tests are those
  boundaries; the real SDK connection does not exist yet and must never
  be claimed (an unconnected `VehicleSdkAdapter` raises
  `NotImplementedError` from `poll()` and reports
  `is_connected=False`).

## Cleanup

- The helper and the engine create no processes, ports, or persistent
  state; each drive is a fresh in-process session, so there is nothing
  to tear down. If you started a browser or Node process for demo
  checks, close only the process you started — never kill by process
  name.
- Remove scratch output you created outside `artifacts/` (for example
  `/tmp` drive directories). Never delete evidence under `artifacts/`.
- Confirm after cleanup that the evidence files for the run still exist
  at the path above.

## Helpers

- `scripts/verify_carbom.py doctor` — read-only health check (see
  Doctor). Invocation:
  `python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py doctor`
- `scripts/verify_carbom.py drive --scenario <name> --out <dir>` —
  replay one fixed scenario through the public API and write JSON+text
  evidence to `<dir>`; exit 1 on any mismatch. Invocation:
  `python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py drive --scenario forgotten_rising_temp --out .cursor/skills/verify-carbom/artifacts/<run-name>`
- The helper is standard-library only and resolves the project root
  from its own file location, so it can be run from any directory.

## Maintenance

Keep this map honest with the pstack `maintain-verification-skill`
procedure whenever engine surfaces, demo controls, or scenario
expectations change.

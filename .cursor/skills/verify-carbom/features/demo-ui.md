# Demo UI

The demo lets a viewer watch a care scenario play out on the two screens
a driver would see: the vehicle screen with the session state, guidance,
and six signal readouts, and the phone screen with the matching alert
card — stepping through a scenario manually, switching scenarios, or
opening a pinned step directly from a link.

## Sub-features

- `demo-select` switches between the three scenarios (등원 정상 흐름,
  하차 깜빡 + 온도 상승, 반려동물 등원).
- `demo-step` advances one step at a time with the step indicator
  (`n/N`) and disables the next button on the last step.
- `demo-reset` returns to step 1 of the current scenario.
- `demo-query` pins scenario and step from `?scenario=<key>&step=<n>`,
  clamping out-of-range steps and falling back on unknown scenarios.
- `demo-exception` highlights the phone card in the warning style at
  EXCEPTION / URGENT (35.5℃ step of the forgotten scenario).

## How to get to it (user POV)

- Open `demo/index.html` in a browser as a file (no server, no build).
- Choose a scenario in the `#scenario-select` dropdown.
- Press `#next-step` (다음 단계) or `#reset` (처음부터).
- Open the file with `?scenario=forgotten_rising_temp&step=8`-style
  query parameters to land on a pinned step.

## Driving it with the DOM harness

Preconditions:

- `verify_carbom.py doctor` exits 0 (includes `node --check demo/demo.js`).
- Scripted drives load `demo/demo.js` in Node with a minimal DOM stub
  implementing the ids below, or use a real browser on the file.

- **Initial state.** Load the page. `#step-indicator` reads `1/6`, `#vehicle-state` reads BOARDING, `#guidance-level` reads INFO, and the phone card mirrors the same level and state.
- **Step through.** Press `#next-step` repeatedly for the dropoff scenario. The states follow BOARDING -> ONBOARD -> DRIVING -> ARRIVED -> ALIGHTING -> COMPLETED, the indicator ends at `6/6`, and `#next-step` becomes disabled.
- **Cross-check.** Replay `dropoff_normal` through the engine (see engine-scenarios). Every step's state, guidance level/text, and the six signal readouts (`#sig-door`, `#sig-belt`, `#sig-ignition`, `#sig-lock`, `#sig-hvac`, `#sig-temp`) match the engine exactly.
- **Exception highlight.** Select the forgotten scenario and step to its last step (8/8). `#vehicle-state` reads EXCEPTION, `#guidance-level` reads URGENT, `#sig-temp` reads 35.5℃, and `#phone-card` carries the warning style.
- **Reset.** Press `#reset`. The indicator returns to `1/N` for the current scenario and the first step is displayed again.
- **Query pinning.** Load with `?scenario=pet_dropoff&step=6`. The pet scenario is selected at `6/6` COMPLETED; `step=99` clamps to the last step, a non-numeric step falls back to 1, and an unknown scenario falls back to the default scenario.
- **Proof.** Record, per driven step, the state, guidance level/text, indicator, and signal readouts, alongside the matching engine replay output. A screenshot is valid proof only in a real browser; in this VM headless Chromium hangs (see Gotchas), so DOM-stub transcripts are the accepted evidence here.

## Gotchas

- This VM's headless Chromium (`/opt/meta-chromium/chrome`) hangs on any
  page, including `about:blank` — do not treat a missing screenshot as a
  demo failure, and do not claim a screenshot you did not capture.
- The demo's step data is a hand-maintained mirror of the engine
  scenarios; a demo/engine mismatch is a demo defect to fix in
  `demo/demo.js`, never by editing the engine to match the demo.
- Query step numbers are 1-based; step 0 and negative values clamp to
  the first step.
- Changing the scenario select resets the step to 1 — assert the
  indicator after every switch.

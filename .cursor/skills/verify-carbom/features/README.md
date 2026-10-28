# CarBom verification map

This directory is the maintained source for verifying the user-facing
behavior of CarBom. Read this index before driving the app, then use the
matching feature file as the recipe. The parent skill
(`../SKILL.md`) covers launch, doctor, evidence, and cleanup.

## Baseline preconditions

- Work from the project root `~/workspace/projects/carbom`.
- Run `python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py doctor`
  and require exit code 0 before driving anything.
- Python >= 3.10 and Node (for `node --check demo/demo.js`) are available.
- No server, account, seed data, or network access is needed or allowed.
- Engine drives always start from a fresh `CareSession()`; never reuse a
  session across features unless the recipe says so.

## Driving conventions

- Start every recipe from the baseline state unless its preconditions
  say otherwise.
- Drive the public API only (`engine` package exports and
  `engine.adapters` exports). Never call private (`_`-prefixed) members
  to set up or assert state.
- For the demo, prefer the stable element ids listed in `../SKILL.md`
  over CSS position, coordinates, or tab order.
- Treat every command as literal. Keep scenario names and flags unchanged.
- Cross-check surfaces against each other: demo steps against engine
  replays, reports against session history.

## Proof and skip reporting

- Capture the user action and the resulting state, not only the final
  screen or final state.
- Engine proof includes the full transition list (from/to state, reason,
  timestamp), the guidance (level, text, reason), and the report summary.
- Demo proof includes the displayed state, guidance level/text, step
  indicator, and signal readouts for each driven step.
- Record the feature ID and entry point used with every artifact.
- Report an unreachable path with the attempted command and the unmet
  precondition. Do not report a skipped entry point as verified through
  a different path.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph describing
the user-visible behavior. It then uses exactly four H2 sections in this
order.

1. `Sub-features` lists short IDs with one line for each behavior.
2. `How to get to it (user POV)` lists every user entry point.
3. `Driving it with <harness>` starts with `Preconditions:` and uses
   labeled bullets that pair each user action with an exact command and
   observable result.
4. `Gotchas` lists traps that can waste or invalidate a verification run.

Keep implementation details out of the map. Name only user paths, stable
handles, required state, commands, and observable proof.

## Features

- [Engine scenarios](./engine-scenarios.md) covers replaying the three
  fixed scenarios (dropoff normal, forgotten + rising temperature,
  pet variant) through the public API.
- [Guidance and report](./guidance-and-report.md) covers destination
  context guidance, urgency escalation with cabin temperature, and the
  care report plus its log aggregates.
- [Demo UI](./demo-ui.md) covers scenario selection, step navigation,
  reset, and query-parameter pinning in the static demo page.
- [SDK adapter](./sdk-adapter.md) covers raw/snapshot conversion,
  bulk conversion, raw application, and the explicit not-connected
  failure of the Vehicle SDK adapter layer.

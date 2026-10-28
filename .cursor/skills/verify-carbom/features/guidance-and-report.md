# Guidance and report

Guidance turns a session state into the message a driver actually sees —
calm information during boarding and driving, a reminder on arrival, and
an urgent warning when a passenger is left in a locked, heating car —
and the care report turns the session into the one-line summary and
statistics a driver reviews afterwards.

## Sub-features

- `guidance-context` varies BOARDING and ARRIVED wording by destination
  context (general / dropoff / pickup) and leaves other states unchanged.
- `guidance-escalation` adds the cabin temperature at 32℃ and escalates
  to immediate-danger wording at 35℃ in EXCEPTION.
- `guidance-no-passenger` returns level NONE with empty text when no
  passenger is present (except boarding/alighting/completed info states).
- `report-summary` produces the Korean one-line summary for completed,
  completed-after-exception, unresolved-exception, and in-progress cases.
- `report-log` accumulates reports and aggregates completion, exception,
  temperature, and duration statistics.

## How to get to it (user POV)

- Call `guidance_for_session(session, context=...)` from `engine.guidance`
  after driving a session, with a `DestinationContext`, a string such as
  `"dropoff"`, or `None`.
- Call `report_for_session(session)` from `engine.report`, and accumulate
  sessions with `CareReportLog` (`add_session`, `add_sessions`).
- Read the guidance and report sections of any helper `drive` evidence file.

## Driving it with verify_carbom.py

Preconditions:

- `verify_carbom.py doctor` exits 0 from the project root.
- Sessions are driven only through scenario replay or snapshot application.

- **Dropoff context.** Drive `dropoff_normal` with the helper (DROPOFF context). The completed guidance is INFO with reason `completed`; mid-journey, an ARRIVED session under DROPOFF shows REMIND with the dropoff-specific rear-seat wording, while the same session under PICKUP shows the pickup wording and under GENERAL the general wording.
- **Escalation.** Drive `forgotten_rising_temp` with the helper. Guidance is URGENT, reason ends with `dangerous_cabin_temp`, and the text contains `35.5도` and `즉시`. At exactly 32.0℃ the wording includes the temperature without `즉시`; below 32℃ no temperature appears.
- **No passenger.** Build an IDLE session with no snapshots and call `guidance_for_session`. Level is NONE and text is empty; an EXCEPTION state queried directly without a passenger is also NONE (`no_passenger`).
- **Report summary.** Read the `report` block of the helper evidence: `dropoff_normal` gives `하차 확인 완료 · 예외 없음`, `forgotten_rising_temp` gives `예외 발생 · 하차 미확인` with `exception_count` 1 and `max_cabin_temp_c` 35.5.
- **Report log.** In Python, `add_sessions` the three scenario sessions into one `CareReportLog`. It reports length 3, `completed_count` 2, `sessions_with_exception` 1, `total_exception_count` 1, `max_cabin_temp_c` 35.5, `average_duration_seconds` 280.0.
- **Proof.** The helper JSON evidence pairs each guidance with the report of the same session; assert `report.final_state` equals the session state and `report.transition_count` equals the number of recorded transitions.

## Gotchas

- Temperatures are formatted with `:g`, so 32.0℃ prints as `32도`, never
  `32.0도`. Assert the rendered text.
- Context strings are normalized (case/space-insensitive); unknown
  strings and `None` fall back to GENERAL instead of raising.
- Guidance reads the session without changing it; a drive that mutates
  the session to "prepare" guidance has left the user path.
- Report duration is `None` unless both the first and last transitions
  carry timestamps — a single-transition report has duration 0.0, not None.

"""QA scenarios for ignition input alone after a session is COMPLETED.

COMPLETED is the terminal state, so turning the ignition on (or back
off) after completion must not revive the session into a new drive.
The only effect an ignition-only step may have is updating the
ignition flag on the current snapshot: the session never leaves
COMPLETED, the transition history never grows, and the completed
guidance and report verdicts stay exactly as they were.

Unlike the wider terminal-state QA (which applies a combined
belt + lock + dangerous-temperature snapshot at once) and the
simultaneous-input scenarios, each ignition step here is derived
from the current snapshot with dataclasses.replace, changing only
the ignition flag (and, where stated, the cabin temperature or the
rear door) and the timestamp. The setup is all six dropoff_normal
snapshots (0.0 to 300.0), which leave COMPLETED with no passenger
present and six transitions. The scenarios cover ignition toggling
and idempotence, a high cabin temperature riding along without the
escalation it would cause while ARRIVED, the event path, guidance
in every destination context, a rear door opening after ignition
(which also must not revive the session), and bulk application
with report-log aggregation. This file closes the ignition-only
series: IDLE, BOARDING, ONBOARD, DRIVING, ARRIVED, ALIGHTING and
EXCEPTION already have one.
"""

import dataclasses
import unittest

from engine import (
    CareSession,
    DestinationContext,
    DoorState,
    GuidanceLevel,
    IgnitionState,
    SessionState,
    SignalEvent,
    SignalEventType,
    guidance_for_session,
    report_for_session,
)
from engine.adapters.simulator import dropoff_normal_snapshots
from engine.report import CareReportLog

COMPLETED_TEXT = "하차 확인이 완료되었습니다."


def completed_session():
    session = CareSession()
    for snapshot in dropoff_normal_snapshots():
        session.apply_snapshot(snapshot)
    return session


def with_ignition(session, on, timestamp, **extra):
    return dataclasses.replace(
        session.current_snapshot,
        ignition=IgnitionState.ON if on else IgnitionState.OFF,
        timestamp=timestamp,
        **extra,
    )


def history_of(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


COMPLETED_HISTORY = [
    (SessionState.IDLE, SessionState.BOARDING, "rear_door_opened", 0.0),
    (
        SessionState.BOARDING,
        SessionState.ONBOARD,
        "passenger_onboard",
        60.0,
    ),
    (SessionState.ONBOARD, SessionState.DRIVING, "ignition_on", 120.0),
    (SessionState.DRIVING, SessionState.ARRIVED, "ignition_off", 180.0),
    (
        SessionState.ARRIVED,
        SessionState.ALIGHTING,
        "alighting_started",
        240.0,
    ),
    (
        SessionState.ALIGHTING,
        SessionState.COMPLETED,
        "alighting_confirmed",
        300.0,
    ),
]


def assert_completed_report(test_case, session, max_temp=None):
    report = report_for_session(session)
    test_case.assertEqual(report.final_state, SessionState.COMPLETED)
    test_case.assertTrue(report.completed)
    test_case.assertFalse(report.exception_occurred)
    test_case.assertEqual(report.exception_count, 0)
    test_case.assertEqual(report.transition_count, 6)
    test_case.assertEqual(report.started_at, 0.0)
    test_case.assertEqual(report.ended_at, 300.0)
    test_case.assertEqual(report.duration_seconds, 300.0)
    if max_temp is None:
        test_case.assertIsNone(report.max_cabin_temp_c)
    else:
        test_case.assertEqual(report.max_cabin_temp_c, max_temp)
    test_case.assertFalse(report.passenger_present)
    test_case.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")
    return report


class CompletedIgnitionQATest(unittest.TestCase):
    def test_ignition_on_alone_in_completed_keeps_terminal_state(self):
        session = completed_session()

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertEqual(
            session.current_snapshot.ignition, IgnitionState.OFF
        )
        self.assertFalse(session.current_snapshot.ignition_on)
        self.assertEqual(session.current_snapshot.timestamp, 300.0)

        session.apply_snapshot(with_ignition(session, True, 360.0))

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertEqual(
            session.current_snapshot.ignition, IgnitionState.ON
        )
        self.assertTrue(session.current_snapshot.ignition_on)
        self.assertEqual(session.current_snapshot.timestamp, 360.0)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        self.assertEqual(guidance.text, COMPLETED_TEXT)
        assert_completed_report(self, session)

    def test_ignition_repeated_is_idempotent_and_toggles_off(self):
        session = completed_session()

        for timestamp in (360.0, 420.0):
            session.apply_snapshot(with_ignition(session, True, timestamp))
            self.assertEqual(session.state, SessionState.COMPLETED)
            self.assertEqual(history_of(session), COMPLETED_HISTORY)
            self.assertTrue(session.current_snapshot.ignition_on)

        session.apply_snapshot(with_ignition(session, False, 480.0))

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertEqual(
            session.current_snapshot.ignition, IgnitionState.OFF
        )
        self.assertEqual(session.current_snapshot.timestamp, 480.0)
        assert_completed_report(self, session)

    def test_ignition_on_high_temp_no_escalation(self):
        session = completed_session()

        session.apply_snapshot(
            with_ignition(session, True, 360.0, cabin_temp_c=35.5)
        )

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertNotEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertNotEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(guidance.reason, "completed")
        self.assertEqual(guidance.text, COMPLETED_TEXT)
        self.assertNotIn("35.5도", guidance.text)
        self.assertNotIn("즉시", guidance.text)

        assert_completed_report(self, session, max_temp=35.5)

    def test_ignition_events_match_snapshot_path_in_completed(self):
        via_events = completed_session()
        via_events.apply_event(
            SignalEvent(type=SignalEventType.IGNITION_ON, timestamp=360.0)
        )
        via_events.apply_event(
            SignalEvent(type=SignalEventType.IGNITION_OFF, timestamp=420.0)
        )

        via_snapshots = completed_session()
        via_snapshots.apply_snapshot(with_ignition(via_snapshots, True, 360.0))
        via_snapshots.apply_snapshot(
            with_ignition(via_snapshots, False, 420.0)
        )

        self.assertEqual(via_events.state, SessionState.COMPLETED)
        self.assertEqual(via_events.state, via_snapshots.state)
        self.assertEqual(history_of(via_events), history_of(via_snapshots))
        self.assertEqual(history_of(via_events), COMPLETED_HISTORY)
        self.assertEqual(
            via_events.current_snapshot.ignition,
            via_snapshots.current_snapshot.ignition,
        )
        self.assertEqual(
            via_events.current_snapshot.ignition, IgnitionState.OFF
        )
        self.assertEqual(
            via_events.current_snapshot.timestamp,
            via_snapshots.current_snapshot.timestamp,
        )
        self.assertFalse(via_events.passenger_present)
        assert_completed_report(self, via_events)

    def test_ignition_on_guidance_completed_in_every_context(self):
        session = completed_session()

        session.apply_snapshot(with_ignition(session, True, 360.0))

        for context in (
            DestinationContext.GENERAL,
            DestinationContext.DROPOFF,
            DestinationContext.PICKUP,
        ):
            guidance = guidance_for_session(session, context=context)
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.state, SessionState.COMPLETED)
            self.assertEqual(guidance.reason, "completed")
            self.assertEqual(guidance.text, COMPLETED_TEXT)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        assert_completed_report(self, session)

    def test_door_open_after_ignition_on_still_terminal(self):
        session = completed_session()

        session.apply_snapshot(with_ignition(session, True, 360.0))
        self.assertTrue(session.current_snapshot.ignition_on)

        session.apply_snapshot(
            dataclasses.replace(
                session.current_snapshot,
                rear_door=DoorState.OPEN,
                timestamp=420.0,
            )
        )

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertEqual(session.current_snapshot.rear_door, DoorState.OPEN)
        self.assertTrue(session.current_snapshot.ignition_on)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        self.assertEqual(guidance.text, COMPLETED_TEXT)
        assert_completed_report(self, session)

    def test_ignition_bulk_and_report_log(self):
        session = completed_session()

        state = session.apply_snapshots(
            [
                with_ignition(session, True, 360.0),
                dataclasses.replace(
                    session.current_snapshot,
                    ignition=IgnitionState.OFF,
                    timestamp=420.0,
                ),
            ]
        )

        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertFalse(session.current_snapshot.ignition_on)
        assert_completed_report(self, session)

        untouched = completed_session()
        restarted = completed_session()
        restarted.apply_snapshot(
            with_ignition(restarted, True, 360.0, cabin_temp_c=35.5)
        )

        log = CareReportLog()
        log.add_sessions([untouched, restarted])

        self.assertEqual(len(log), 2)
        self.assertEqual(len(log.reports), 2)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 0)
        self.assertEqual(log.total_exception_count, 0)
        self.assertEqual(log.total_transition_count, 12)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.average_duration_seconds, 300.0)


if __name__ == "__main__":
    unittest.main()

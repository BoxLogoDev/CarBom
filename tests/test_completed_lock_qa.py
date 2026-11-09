"""QA scenarios for changing only the lock while COMPLETED.

COMPLETED is the terminal state: alighting has been confirmed, the
rear door is closed, and no passenger is latched present. Locking or
unlocking on its own after completion drives nothing — the session
never leaves COMPLETED, the transition history never grows, and the
completed guidance and report verdicts stay exactly as they were.
The lock flag itself still lands on the current snapshot, and that
is the only effect a lock-only step may have.

Unlike the simultaneous-input scenarios (and the wider terminal QA,
which applies a belt + lock + dangerous-temperature snapshot at
once), each lock step here is derived from the current snapshot with
dataclasses.replace, changing only lock and timestamp. The setup is
all six dropoff_normal snapshots (0.0 to 300.0), which leave
COMPLETED with no passenger present and six transitions. The
scenarios cover the snapshot path and the event path, plus the
guidance in every destination context and the completed report.
This file closes the lock-only series: IDLE, BOARDING, ONBOARD,
DRIVING, ARRIVED, ALIGHTING and EXCEPTION already have one.
"""

import dataclasses
import unittest

from engine import (
    CareSession,
    DestinationContext,
    GuidanceLevel,
    LockState,
    SessionState,
    SignalEvent,
    SignalEventType,
    guidance_for_session,
    report_for_session,
)
from engine.adapters.simulator import dropoff_normal_snapshots

COMPLETED_TEXT = "하차 확인이 완료되었습니다."


def completed_session():
    session = CareSession()
    for snapshot in dropoff_normal_snapshots():
        session.apply_snapshot(snapshot)
    return session


def with_lock(session, locked, timestamp):
    return dataclasses.replace(
        session.current_snapshot,
        lock=LockState.LOCKED if locked else LockState.UNLOCKED,
        timestamp=timestamp,
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


def assert_completed_report(test_case, session):
    report = report_for_session(session)
    test_case.assertEqual(report.final_state, SessionState.COMPLETED)
    test_case.assertTrue(report.completed)
    test_case.assertFalse(report.exception_occurred)
    test_case.assertEqual(report.exception_count, 0)
    test_case.assertEqual(report.transition_count, 6)
    test_case.assertEqual(report.started_at, 0.0)
    test_case.assertEqual(report.ended_at, 300.0)
    test_case.assertEqual(report.duration_seconds, 300.0)
    test_case.assertIsNone(report.max_cabin_temp_c)
    test_case.assertFalse(report.passenger_present)
    test_case.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")
    return report


class CompletedLockQATest(unittest.TestCase):
    def test_lock_alone_in_completed_keeps_terminal_state(self):
        session = completed_session()

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertEqual(session.current_snapshot.lock, LockState.UNLOCKED)
        self.assertEqual(session.current_snapshot.timestamp, 300.0)

        session.apply_snapshot(with_lock(session, True, 360.0))

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertEqual(session.current_snapshot.lock, LockState.LOCKED)
        self.assertTrue(session.current_snapshot.locked)
        self.assertEqual(session.current_snapshot.timestamp, 360.0)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        self.assertEqual(guidance.text, COMPLETED_TEXT)
        assert_completed_report(self, session)

    def test_lock_repeated_in_completed_is_idempotent(self):
        session = completed_session()

        session.apply_snapshot(with_lock(session, True, 360.0))
        session.apply_snapshot(with_lock(session, True, 370.0))

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertEqual(session.current_snapshot.lock, LockState.LOCKED)
        self.assertEqual(session.current_snapshot.timestamp, 370.0)
        assert_completed_report(self, session)

    def test_unlock_alone_in_completed_keeps_terminal_state(self):
        session = completed_session()

        session.apply_snapshot(with_lock(session, True, 360.0))
        self.assertEqual(session.current_snapshot.lock, LockState.LOCKED)

        session.apply_snapshot(with_lock(session, False, 370.0))

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertEqual(session.current_snapshot.lock, LockState.UNLOCKED)
        self.assertFalse(session.current_snapshot.locked)
        self.assertEqual(session.current_snapshot.timestamp, 370.0)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        self.assertEqual(guidance.text, COMPLETED_TEXT)
        assert_completed_report(self, session)

    def test_lock_toggle_in_completed_only_updates_snapshot(self):
        session = completed_session()

        for locked, timestamp in ((True, 360.0), (False, 370.0), (True, 380.0)):
            session.apply_snapshot(with_lock(session, locked, timestamp))

            self.assertEqual(session.state, SessionState.COMPLETED)
            self.assertFalse(session.passenger_present)
            self.assertEqual(history_of(session), COMPLETED_HISTORY)
            self.assertEqual(
                session.current_snapshot.lock,
                LockState.LOCKED if locked else LockState.UNLOCKED,
            )
            self.assertEqual(session.current_snapshot.timestamp, timestamp)

        assert_completed_report(self, session)

    def test_lock_events_match_snapshot_path_in_completed(self):
        via_events = completed_session()
        via_events.apply_event(
            SignalEvent(type=SignalEventType.LOCKED, timestamp=360.0)
        )
        via_events.apply_event(
            SignalEvent(type=SignalEventType.UNLOCKED, timestamp=370.0)
        )

        via_snapshots = completed_session()
        via_snapshots.apply_snapshot(with_lock(via_snapshots, True, 360.0))
        via_snapshots.apply_snapshot(with_lock(via_snapshots, False, 370.0))

        self.assertEqual(via_events.state, SessionState.COMPLETED)
        self.assertEqual(via_events.state, via_snapshots.state)
        self.assertEqual(history_of(via_events), history_of(via_snapshots))
        self.assertEqual(history_of(via_events), COMPLETED_HISTORY)
        self.assertEqual(
            via_events.current_snapshot.lock,
            via_snapshots.current_snapshot.lock,
        )
        self.assertEqual(via_events.current_snapshot.lock, LockState.UNLOCKED)
        self.assertEqual(
            via_events.current_snapshot.timestamp,
            via_snapshots.current_snapshot.timestamp,
        )
        self.assertEqual(
            via_events.passenger_present, via_snapshots.passenger_present
        )
        self.assertFalse(via_events.passenger_present)

    def test_lock_alone_guidance_completed_in_every_context(self):
        session = completed_session()

        session.apply_snapshot(with_lock(session, True, 360.0))

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


if __name__ == "__main__":
    unittest.main()

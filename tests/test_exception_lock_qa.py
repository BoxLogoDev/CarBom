"""QA scenarios for changing only the lock while in EXCEPTION.

The exception state is entered precisely because the car was locked
with a passenger still inside (ignition off, locked, rear door
closed, passenger present). Once in EXCEPTION, the lock flag on its
own no longer drives anything: re-locking changes nothing, and
unlocking on its own also changes nothing, because the EXCEPTION
exit rules need more than an unlocked car — the rear door opening,
or ignition on while unlocked, or the passenger actually leaving.
Guidance is state-based, so even after an unlock the session still
reports the locked-passenger urgent guidance until a real exit
transition happens.

Unlike the simultaneous-input scenarios, each lock step here is
derived from the current snapshot with dataclasses.replace,
changing only lock and timestamp. The setup is the full
forgotten_rising_temp scenario, which leaves EXCEPTION with a
passenger present, five transitions, and a 35.5 degree cabin. The
scenarios cover the snapshot path and the event path, plus the two
lock-gated recovery routes out of EXCEPTION.
"""

import dataclasses
import unittest

from engine import (
    CareSession,
    DestinationContext,
    DoorState,
    GuidanceLevel,
    IgnitionState,
    LockState,
    SessionState,
    SignalEvent,
    SignalEventType,
    guidance_for_session,
    report_for_session,
)
from engine.adapters.simulator import forgotten_rising_temp_snapshots

EXCEPTION_TEXT = (
    "위험합니다. 잠긴 차량의 뒷좌석에 동승자가 남아 있을 수 있고 "
    "실내 온도 35.5도입니다. 즉시 뒷좌석을 확인해 주세요."
)


def exception_session():
    session = CareSession()
    for snapshot in forgotten_rising_temp_snapshots():
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


EXCEPTION_HISTORY = [
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
        SessionState.EXCEPTION,
        "ignition_off_locked_passenger_present",
        240.0,
    ),
]


class ExceptionLockQATest(unittest.TestCase):
    def test_relock_alone_in_exception_keeps_state(self):
        session = exception_session()

        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), EXCEPTION_HISTORY)

        session.apply_snapshot(with_lock(session, True, 480.0))

        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), EXCEPTION_HISTORY)
        self.assertEqual(session.current_snapshot.lock, LockState.LOCKED)
        self.assertEqual(session.current_snapshot.timestamp, 480.0)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason, "passenger_left_locked_dangerous_cabin_temp"
        )
        self.assertEqual(guidance.text, EXCEPTION_TEXT)
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)
        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_unlock_alone_in_exception_keeps_state_and_guidance(self):
        session = exception_session()

        session.apply_snapshot(with_lock(session, False, 480.0))

        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), EXCEPTION_HISTORY)
        self.assertEqual(session.current_snapshot.lock, LockState.UNLOCKED)
        self.assertFalse(session.current_snapshot.locked)
        # Guidance follows the state, not the live lock flag: the
        # session is still in EXCEPTION, so the urgent locked-passenger
        # wording (including the dangerous-temperature escalation)
        # is reported unchanged even though the car is now unlocked.
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason, "passenger_left_locked_dangerous_cabin_temp"
        )
        self.assertEqual(guidance.text, EXCEPTION_TEXT)
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)
        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_lock_toggle_in_exception_is_idempotent(self):
        session = exception_session()

        for locked, timestamp in ((False, 480.0), (True, 490.0), (False, 500.0)):
            session.apply_snapshot(with_lock(session, locked, timestamp))

            self.assertEqual(session.state, SessionState.EXCEPTION)
            self.assertTrue(session.passenger_present)
            self.assertEqual(history_of(session), EXCEPTION_HISTORY)
            self.assertEqual(
                session.current_snapshot.lock,
                LockState.LOCKED if locked else LockState.UNLOCKED,
            )
            self.assertEqual(session.current_snapshot.timestamp, timestamp)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 5)

    def test_lock_events_match_snapshot_path_in_exception(self):
        via_events = exception_session()
        via_events.apply_event(
            SignalEvent(type=SignalEventType.UNLOCKED, timestamp=480.0)
        )
        via_events.apply_event(
            SignalEvent(type=SignalEventType.LOCKED, timestamp=490.0)
        )

        via_snapshots = exception_session()
        via_snapshots.apply_snapshot(with_lock(via_snapshots, False, 480.0))
        via_snapshots.apply_snapshot(with_lock(via_snapshots, True, 490.0))

        self.assertEqual(via_events.state, SessionState.EXCEPTION)
        self.assertEqual(via_events.state, via_snapshots.state)
        self.assertEqual(history_of(via_events), history_of(via_snapshots))
        self.assertEqual(history_of(via_events), EXCEPTION_HISTORY)
        self.assertEqual(
            via_events.current_snapshot.lock,
            via_snapshots.current_snapshot.lock,
        )
        self.assertEqual(via_events.current_snapshot.lock, LockState.LOCKED)
        self.assertEqual(
            via_events.passenger_present, via_snapshots.passenger_present
        )

    def test_unlock_then_ignition_on_recovers_through_onboard(self):
        session = exception_session()

        session.apply_snapshot(with_lock(session, False, 480.0))
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(history_of(session), EXCEPTION_HISTORY)

        session.apply_snapshot(
            dataclasses.replace(
                session.current_snapshot,
                ignition=IgnitionState.ON,
                timestamp=540.0,
            )
        )

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(
            history_of(session),
            EXCEPTION_HISTORY
            + [
                (
                    SessionState.EXCEPTION,
                    SessionState.ONBOARD,
                    "unlocked_and_ignition_on_after_exception",
                    540.0,
                ),
                (
                    SessionState.ONBOARD,
                    SessionState.DRIVING,
                    "ignition_on",
                    540.0,
                ),
            ],
        )

    def test_unlock_then_door_open_recovers_to_completed(self):
        session = exception_session()

        session.apply_snapshot(with_lock(session, False, 480.0))
        self.assertEqual(session.state, SessionState.EXCEPTION)

        session.apply_snapshot(
            dataclasses.replace(
                session.current_snapshot,
                rear_door=DoorState.OPEN,
                timestamp=540.0,
            )
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertEqual(
            history_of(session)[-1],
            (
                SessionState.EXCEPTION,
                SessionState.ALIGHTING,
                "rear_door_opened_after_exception",
                540.0,
            ),
        )

        session.apply_snapshot(
            dataclasses.replace(
                session.current_snapshot,
                rear_seat_belt_buckled=False,
                timestamp=600.0,
            )
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)

        session.apply_snapshot(
            dataclasses.replace(
                session.current_snapshot,
                rear_door=DoorState.CLOSED,
                timestamp=660.0,
            )
        )
        self.assertEqual(session.state, SessionState.COMPLETED)
        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 7)
        self.assertEqual(report.duration_seconds, 660.0)
        self.assertEqual(report.summary, "예외 발생 후 하차 확인 완료")


if __name__ == "__main__":
    unittest.main()

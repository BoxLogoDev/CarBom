"""QA scenarios for changing only the lock while DRIVING.

Driving is underway: the ignition is on, the rear door is closed
and the passenger is latched present. The exception rule needs
four conditions at once (ignition off, locked, rear door closed,
passenger present), so locking on its own while the ignition is
still on completes nothing: the session stays in DRIVING, the
passenger stays latched, and the transition history does not grow,
because DRIVING only advances once the ignition goes off. The
lock flag held at ignition-off time is what then decides the
transition: with the lock still held, ignition off moves DRIVING
straight to EXCEPTION in a single transition, without passing
through ARRIVED, while an unlocked ignition off walks DRIVING to
ARRIVED as usual.

Unlike the simultaneous-input scenarios, each lock step here is
derived from the current snapshot with dataclasses.replace,
changing only lock and timestamp. The setup is the first three
dropoff_normal snapshots (0.0, rear door open, 60.0, belt buckled
with the door closed, and 120.0, ignition on), which leave
DRIVING with a passenger present and three transitions. The
scenarios cover the snapshot path and the event path, plus the
guidance and report views of the held driving state.
"""

import dataclasses
import unittest

from engine import (
    CareSession,
    DestinationContext,
    GuidanceLevel,
    IgnitionState,
    LockState,
    SessionState,
    SignalEvent,
    SignalEventType,
    guidance_for_session,
    report_for_session,
)
from engine.adapters.simulator import dropoff_normal_snapshots

DRIVING_TEXT = "안전 운전 중입니다. 운전 중에는 화면을 조작하지 마세요."
EXCEPTION_TEXT = (
    "잠긴 차량의 뒷좌석에 동승자가 남아 있을 수 있습니다. "
    "뒷좌석을 확인해 주세요."
)
ARRIVED_TEXT = "도착했습니다. 등원 하차 전 뒷좌석을 확인해 주세요."


def driving_session():
    session = CareSession()
    for snapshot in dropoff_normal_snapshots()[:3]:
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


DRIVING_HISTORY = [
    (SessionState.IDLE, SessionState.BOARDING, "rear_door_opened", 0.0),
    (
        SessionState.BOARDING,
        SessionState.ONBOARD,
        "passenger_onboard",
        60.0,
    ),
    (SessionState.ONBOARD, SessionState.DRIVING, "ignition_on", 120.0),
]


class DrivingLockQATest(unittest.TestCase):
    def test_lock_alone_in_driving_keeps_state_while_ignition_on(self):
        session = driving_session()

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), DRIVING_HISTORY)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")
        self.assertEqual(guidance.text, DRIVING_TEXT)
        report = report_for_session(session)
        self.assertEqual(report.transition_count, 3)
        self.assertEqual(report.started_at, 0.0)
        self.assertEqual(report.ended_at, 120.0)
        self.assertEqual(report.duration_seconds, 120.0)
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

        session.apply_snapshot(with_lock(session, True, 180.0))

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), DRIVING_HISTORY)
        self.assertEqual(session.current_snapshot.lock, LockState.LOCKED)
        self.assertTrue(session.current_snapshot.locked)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")
        self.assertEqual(guidance.text, DRIVING_TEXT)
        report = report_for_session(session)
        self.assertEqual(report.transition_count, 3)
        self.assertEqual(report.duration_seconds, 120.0)
        self.assertEqual(report.ended_at, 120.0)
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_lock_repeated_in_driving_is_idempotent(self):
        session = driving_session()

        session.apply_snapshot(with_lock(session, True, 180.0))
        session.apply_snapshot(with_lock(session, True, 190.0))

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), DRIVING_HISTORY)
        self.assertEqual(len(session.history), 3)
        self.assertEqual(session.current_snapshot.lock, LockState.LOCKED)
        self.assertEqual(session.current_snapshot.timestamp, 190.0)

    def test_lock_toggles_in_driving_flip_snapshot_flag_only(self):
        session = driving_session()

        for timestamp, locked in (
            (200.0, True),
            (210.0, False),
            (220.0, True),
        ):
            session.apply_snapshot(with_lock(session, locked, timestamp))

            self.assertEqual(session.state, SessionState.DRIVING)
            self.assertTrue(session.passenger_present)
            self.assertEqual(
                session.current_snapshot.lock,
                LockState.LOCKED if locked else LockState.UNLOCKED,
            )
            self.assertEqual(session.current_snapshot.locked, locked)
            self.assertEqual(history_of(session), DRIVING_HISTORY)
            self.assertEqual(len(session.history), 3)
            guidance = guidance_for_session(
                session, context=DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "driving")
            self.assertEqual(guidance.text, DRIVING_TEXT)
            report = report_for_session(session)
            self.assertEqual(report.transition_count, 3)
            self.assertEqual(report.exception_count, 0)

    def test_lock_flag_at_ignition_off_in_driving_decides_transition(self):
        locked = driving_session()
        locked.apply_snapshot(with_lock(locked, True, 180.0))
        locked.apply_snapshot(
            dataclasses.replace(
                locked.current_snapshot,
                ignition=IgnitionState.OFF,
                timestamp=240.0,
            )
        )

        self.assertEqual(locked.state, SessionState.EXCEPTION)
        self.assertTrue(locked.passenger_present)
        self.assertEqual(
            history_of(locked),
            DRIVING_HISTORY
            + [
                (
                    SessionState.DRIVING,
                    SessionState.EXCEPTION,
                    "ignition_off_locked_passenger_present",
                    240.0,
                )
            ],
        )
        self.assertEqual(len(locked.history), 4)
        guidance = guidance_for_session(
            locked, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.reason, "passenger_left_locked")
        self.assertEqual(guidance.text, EXCEPTION_TEXT)
        report = report_for_session(locked)
        self.assertEqual(report.transition_count, 4)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

        unlocked = driving_session()
        unlocked.apply_snapshot(
            dataclasses.replace(
                unlocked.current_snapshot,
                ignition=IgnitionState.OFF,
                timestamp=240.0,
            )
        )

        self.assertEqual(unlocked.state, SessionState.ARRIVED)
        self.assertTrue(unlocked.passenger_present)
        self.assertEqual(
            history_of(unlocked),
            DRIVING_HISTORY
            + [
                (
                    SessionState.DRIVING,
                    SessionState.ARRIVED,
                    "ignition_off",
                    240.0,
                )
            ],
        )
        self.assertEqual(len(unlocked.history), 4)
        guidance = guidance_for_session(
            unlocked, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(
            guidance.reason, "arrived_dropoff_check_rear_seat"
        )
        self.assertEqual(guidance.text, ARRIVED_TEXT)
        report = report_for_session(unlocked)
        self.assertEqual(report.transition_count, 4)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_event_path_lock_in_driving_matches_snapshot_path(self):
        snapshot_session = driving_session()
        snapshot_session.apply_snapshot(
            with_lock(snapshot_session, True, 180.0)
        )
        snapshot_session.apply_snapshot(
            dataclasses.replace(
                snapshot_session.current_snapshot,
                ignition=IgnitionState.OFF,
                timestamp=240.0,
            )
        )
        self.assertEqual(snapshot_session.state, SessionState.EXCEPTION)

        event_session = driving_session()
        state = event_session.apply_event(
            SignalEvent(SignalEventType.LOCKED, timestamp=180.0)
        )

        self.assertEqual(state, SessionState.DRIVING)
        self.assertEqual(event_session.state, SessionState.DRIVING)
        self.assertTrue(event_session.passenger_present)
        self.assertEqual(
            event_session.current_snapshot.lock, LockState.LOCKED
        )
        self.assertEqual(history_of(event_session), DRIVING_HISTORY)
        self.assertEqual(len(event_session.history), 3)

        state = event_session.apply_event(
            SignalEvent(SignalEventType.IGNITION_OFF, timestamp=240.0)
        )

        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertEqual(event_session.state, SessionState.EXCEPTION)
        self.assertTrue(event_session.passenger_present)
        self.assertEqual(len(event_session.history), 4)
        self.assertEqual(
            history_of(event_session), history_of(snapshot_session)
        )

    def test_lock_with_high_temperature_in_driving_keeps_driving_guidance(
        self,
    ):
        session = driving_session()

        session.apply_snapshot(
            dataclasses.replace(
                session.current_snapshot,
                lock=LockState.LOCKED,
                cabin_temp_c=35.5,
                timestamp=180.0,
            )
        )

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(session.current_snapshot.lock, LockState.LOCKED)
        self.assertEqual(history_of(session), DRIVING_HISTORY)
        self.assertEqual(len(session.history), 3)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertNotEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertNotEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(guidance.reason, "driving")
        self.assertEqual(guidance.text, DRIVING_TEXT)
        self.assertNotIn("35.5도", guidance.text)
        self.assertNotIn("즉시", guidance.text)
        report = report_for_session(session)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 3)


if __name__ == "__main__":
    unittest.main()

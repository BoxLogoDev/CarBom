"""QA scenarios for locking the vehicle while ONBOARD.

Onboard means boarding is finished: the rear door is closed, the
passenger is belted, and the ignition is still off while the driver
prepares to depart. Locking in this window is the pre-departure
forgotten-passenger case: the door is already closed, so a single
locked snapshot must enter EXCEPTION directly from ONBOARD.

This angle is not covered elsewhere. Boarding lock keeps BOARDING
while the door is open and only enters the exception when the door
closes (straight from BOARDING, skipping ONBOARD). Alighting lock
keeps ALIGHTING while the door is open. Locking with the ignition
on while driving never enters the exception. None of those isolate
ONBOARD, with the door closed, entering EXCEPTION on lock alone.
The scenarios cover both the snapshot path and the LOCKED event,
repeated locking, unlock alone, a hot cabin, and both recovery
paths (unlock plus ignition, and rear door opening).
"""

import unittest

from engine import (
    CareSession,
    DoorState,
    IgnitionState,
    LockState,
    SessionState,
    SignalEvent,
    SignalEventType,
    SignalSnapshot,
)
from engine.guidance import DestinationContext, GuidanceLevel, guidance_for_session
from engine.report import report_for_session


def snapshot(timestamp, *, door_open=False, belt=False, ignition=False,
             locked=False, hvac_on=False, cabin_temp_c=None):
    return SignalSnapshot(
        rear_door=DoorState.OPEN if door_open else DoorState.CLOSED,
        rear_seat_belt_buckled=belt,
        ignition=IgnitionState.ON if ignition else IgnitionState.OFF,
        lock=LockState.LOCKED if locked else LockState.UNLOCKED,
        hvac_on=hvac_on,
        cabin_temp_c=cabin_temp_c,
        timestamp=timestamp,
    )


def onboard_session():
    """ONBOARD reached by opening the rear door, belting, closing it."""
    session = CareSession()
    session.apply_snapshot(snapshot(0.0, door_open=True))
    session.apply_snapshot(snapshot(60.0, belt=True))
    return session


def exception_from_onboard_session():
    """EXCEPTION reached directly from ONBOARD by locking."""
    session = onboard_session()
    session.apply_snapshot(
        snapshot(90.0, belt=True, locked=True, cabin_temp_c=24.0)
    )
    return session


def history_signature(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


class OnboardLockQATest(unittest.TestCase):
    def test_lock_in_onboard_enters_exception_directly(self):
        session = onboard_session()
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 2)
        guidance = guidance_for_session(session, DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "passenger_onboard")

        state = session.apply_snapshot(
            snapshot(90.0, belt=True, locked=True, cabin_temp_c=24.0)
        )

        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 3)
        self.assertEqual(session.history[-1].from_state, SessionState.ONBOARD)
        self.assertEqual(session.history[-1].to_state, SessionState.EXCEPTION)
        self.assertEqual(
            session.history[-1].reason,
            "ignition_off_locked_passenger_present",
        )
        self.assertEqual(session.history[-1].timestamp, 90.0)
        self.assertTrue(session.passenger_present)
        guidance = guidance_for_session(session, DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.reason, "passenger_left_locked")
        report = report_for_session(session)
        self.assertFalse(report.completed)
        self.assertTrue(report.exception_occurred)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 3)
        self.assertEqual(report.duration_seconds, 90.0)
        self.assertEqual(report.max_cabin_temp_c, 24.0)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_locked_event_in_onboard_enters_exception(self):
        session = onboard_session()

        state = session.apply_event(
            SignalEvent(type=SignalEventType.LOCKED, timestamp=90.0)
        )

        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertEqual(session.current_snapshot.lock, LockState.LOCKED)
        snapshot_session = exception_from_onboard_session()
        self.assertEqual(
            history_signature(session),
            [
                (
                    SessionState.IDLE,
                    SessionState.BOARDING,
                    "rear_door_opened",
                    0.0,
                ),
                (
                    SessionState.BOARDING,
                    SessionState.ONBOARD,
                    "passenger_onboard",
                    60.0,
                ),
                (
                    SessionState.ONBOARD,
                    SessionState.EXCEPTION,
                    "ignition_off_locked_passenger_present",
                    90.0,
                ),
            ],
        )
        self.assertEqual(
            history_signature(session)[:2],
            history_signature(snapshot_session)[:2],
        )
        self.assertEqual(
            history_signature(session)[-1][:3],
            history_signature(snapshot_session)[-1][:3],
        )

    def test_repeated_lock_and_unlock_alone_keep_exception(self):
        session = exception_from_onboard_session()
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 3)

        state = session.apply_snapshot(
            snapshot(120.0, belt=True, locked=True, cabin_temp_c=26.0)
        )
        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 3)

        state = session.apply_snapshot(
            snapshot(150.0, belt=True, locked=True, cabin_temp_c=26.0)
        )
        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 3)

        # Unlocking alone does not recover: ignition is still off
        # and the passenger is still inside with the door closed.
        state = session.apply_snapshot(snapshot(180.0, belt=True, locked=False))
        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 3)
        self.assertTrue(session.passenger_present)
        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 3)

    def test_hot_cabin_lock_in_onboard_is_urgent_with_temperature(self):
        session = onboard_session()

        state = session.apply_snapshot(
            snapshot(90.0, belt=True, locked=True, cabin_temp_c=35.5)
        )

        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 3)
        guidance = guidance_for_session(session, DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason, "passenger_left_locked_dangerous_cabin_temp"
        )
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)
        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_exception_from_onboard_lock_recovers_via_unlock_and_ignition(self):
        session = exception_from_onboard_session()
        self.assertEqual(len(session.history), 3)

        state = session.apply_snapshot(
            snapshot(120.0, belt=True, ignition=True, locked=False)
        )

        self.assertEqual(state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 5)
        self.assertEqual(
            history_signature(session)[-2:],
            [
                (
                    SessionState.EXCEPTION,
                    SessionState.ONBOARD,
                    "unlocked_and_ignition_on_after_exception",
                    120.0,
                ),
                (
                    SessionState.ONBOARD,
                    SessionState.DRIVING,
                    "ignition_on",
                    120.0,
                ),
            ],
        )
        self.assertTrue(session.passenger_present)

    def test_exception_from_onboard_lock_recovers_via_door_open(self):
        session = exception_from_onboard_session()
        self.assertEqual(len(session.history), 3)

        state = session.apply_snapshot(
            snapshot(120.0, door_open=True, belt=True, locked=True)
        )
        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertEqual(
            session.history[-1].reason, "rear_door_opened_after_exception"
        )

        state = session.apply_snapshot(
            snapshot(150.0, door_open=True, belt=False, locked=False)
        )
        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)

        state = session.apply_snapshot(snapshot(180.0))

        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 5)
        self.assertEqual(session.history[-1].reason, "alighting_confirmed")
        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.duration_seconds, 180.0)
        self.assertEqual(report.summary, "예외 발생 후 하차 확인 완료")


if __name__ == "__main__":
    unittest.main()

"""QA scenarios for locking the vehicle while BOARDING.

Boarding has started: the rear door is open and the session is
waiting for the passenger to settle and the door to close.
Locking in this window must not be mistaken for a
forgotten-passenger exception. While the rear door is open the
session holds in BOARDING, with or without a passenger present,
and the transition history does not grow. The exception only
takes hold once the door actually closes with a belted passenger
still inside, and it then goes straight from BOARDING to
EXCEPTION without passing through ONBOARD. Without a passenger,
closing the locked door returns the session to IDLE instead.
The scenarios cover both the snapshot path and the LOCKED event,
plus the guidance and report views of the held boarding state.
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


def boarding_session():
    """BOARDING reached by opening the rear door; no passenger yet."""
    session = CareSession()
    session.apply_snapshot(snapshot(0.0, door_open=True))
    return session


def exception_from_boarding_session():
    """EXCEPTION reached directly from BOARDING by closing the locked door."""
    session = boarding_session()
    session.apply_snapshot(
        snapshot(30.0, door_open=True, belt=True, locked=True)
    )
    session.apply_snapshot(
        snapshot(60.0, belt=True, locked=True, cabin_temp_c=24.0)
    )
    return session


class BoardingLockQATest(unittest.TestCase):
    def test_lock_with_door_open_keeps_boarding(self):
        session = boarding_session()
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)

        state = session.apply_snapshot(
            snapshot(30.0, door_open=True, locked=True, cabin_temp_c=24.0)
        )

        self.assertEqual(state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)
        self.assertEqual(session.current_snapshot.lock, LockState.LOCKED)
        self.assertFalse(session.passenger_present)
        guidance = guidance_for_session(session, DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "boarding_dropoff")
        report = report_for_session(session)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 1)
        self.assertEqual(report.duration_seconds, 0.0)
        self.assertEqual(report.max_cabin_temp_c, 24.0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

        event_session = boarding_session()
        event_state = event_session.apply_event(
            SignalEvent(type=SignalEventType.LOCKED, timestamp=30.0)
        )
        self.assertEqual(event_state, SessionState.BOARDING)
        self.assertEqual(len(event_session.history), 1)
        self.assertEqual(event_session.current_snapshot.lock, LockState.LOCKED)

    def test_repeated_lock_is_idempotent_in_boarding(self):
        session = boarding_session()
        session.apply_snapshot(snapshot(30.0, door_open=True, locked=True))
        session.apply_snapshot(snapshot(60.0, door_open=True, locked=True))

        state = session.apply_snapshot(snapshot(90.0, door_open=True, locked=True))

        self.assertEqual(state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)
        self.assertEqual(session.current_snapshot.lock, LockState.LOCKED)

    def test_closing_door_while_locked_enters_exception_directly(self):
        session = boarding_session()

        state = session.apply_snapshot(
            snapshot(30.0, door_open=True, belt=True, locked=True)
        )
        self.assertEqual(state, SessionState.BOARDING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 1)

        state = session.apply_snapshot(
            snapshot(60.0, belt=True, locked=True, cabin_temp_c=24.0)
        )

        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 2)
        self.assertEqual(session.history[-1].from_state, SessionState.BOARDING)
        self.assertEqual(session.history[-1].to_state, SessionState.EXCEPTION)
        self.assertNotIn(
            SessionState.ONBOARD,
            [transition.to_state for transition in session.history],
        )
        self.assertEqual(
            session.history[-1].reason, "ignition_off_locked_passenger_present"
        )
        guidance = guidance_for_session(session, DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.reason, "passenger_left_locked")
        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)

    def test_exception_from_boarding_lock_recovers_via_door_open(self):
        session = exception_from_boarding_session()
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 2)

        state = session.apply_snapshot(
            snapshot(90.0, door_open=True, belt=True, locked=True)
        )
        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertEqual(
            session.history[-1].reason, "rear_door_opened_after_exception"
        )

        state = session.apply_snapshot(
            snapshot(120.0, door_open=True, belt=False, locked=False)
        )
        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)

        state = session.apply_snapshot(snapshot(150.0))

        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 4)
        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.duration_seconds, 150.0)
        self.assertEqual(report.summary, "예외 발생 후 하차 확인 완료")

    def test_lock_without_passenger_returns_to_idle_not_exception(self):
        session = boarding_session()
        self.assertFalse(session.passenger_present)

        state = session.apply_snapshot(snapshot(30.0, door_open=True, locked=True))
        self.assertEqual(state, SessionState.BOARDING)

        state = session.apply_snapshot(snapshot(60.0, locked=True))

        self.assertEqual(state, SessionState.IDLE)
        self.assertEqual(len(session.history), 2)
        self.assertEqual(session.history[-1].reason, "boarding_without_passenger")
        guidance = guidance_for_session(session, DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.NONE)
        self.assertEqual(guidance.text, "")

    def test_hot_cabin_lock_with_door_open_keeps_boarding(self):
        session = boarding_session()

        state = session.apply_snapshot(
            snapshot(30.0, door_open=True, belt=True, locked=True,
                     cabin_temp_c=35.5)
        )

        self.assertEqual(state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)
        self.assertTrue(session.passenger_present)
        guidance = guidance_for_session(session, DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "boarding_dropoff")
        self.assertEqual(
            guidance.text,
            "등원 준비 중입니다. 뒷좌석 승차와 안전벨트를 확인해 주세요.",
        )
        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)


if __name__ == "__main__":
    unittest.main()

"""QA scenarios for locking the vehicle while ALIGHTING.

Alighting has started at the destination: the rear door is open and
the session is waiting for the door to close so it can confirm
completion. Locking in this window must not be mistaken for a
forgotten-passenger exception: while the rear door is open the
session holds in ALIGHTING, with or without a passenger still
present, and the transition history does not grow — the exception
condition also requires the door closed (the door-open guard added
to the exception check). The exception only takes hold once the
door actually closes with a belted passenger still inside. The
scenarios cover both the snapshot path and the LOCKED event, plus
the guidance and report views of the held alighting state.
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
from engine.adapters.simulator import scenario_snapshots
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


def alighting_session_passenger_gone():
    """ALIGHTING reached via the normal dropoff flow; passenger is out."""
    session = CareSession()
    for snap in scenario_snapshots("dropoff_normal")[:5]:
        session.apply_snapshot(snap)
    return session


def alighting_session_passenger_present():
    """ALIGHTING with the passenger still belted (door opened only)."""
    session = CareSession()
    for snap in scenario_snapshots("dropoff_normal")[:4]:
        session.apply_snapshot(snap)
    session.apply_snapshot(snapshot(240, door_open=True, belt=True))
    return session


class AlightingLockQATest(unittest.TestCase):
    def test_lock_in_alighting_passenger_gone_keeps_state(self):
        session = alighting_session_passenger_gone()
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 5)

        state = session.apply_snapshot(snapshot(300, door_open=True, locked=True))

        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertEqual(len(session.history), 5)
        self.assertEqual(session.current_snapshot.lock, LockState.LOCKED)
        guidance = guidance_for_session(session, DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "alighting")
        self.assertEqual(
            guidance.text, "하차 중입니다. 뒷좌석이 비었는지 확인해 주세요."
        )
        report = report_for_session(session)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

        # The LOCKED event alone holds ALIGHTING the same way.
        event_session = alighting_session_passenger_gone()
        event_state = event_session.apply_event(
            SignalEvent(type=SignalEventType.LOCKED, timestamp=300)
        )
        self.assertEqual(event_state, SessionState.ALIGHTING)
        self.assertEqual(len(event_session.history), 5)
        self.assertEqual(event_session.current_snapshot.lock, LockState.LOCKED)

    def test_lock_repeated_is_idempotent(self):
        session = alighting_session_passenger_gone()

        session.apply_snapshot(snapshot(300, door_open=True, locked=True))
        state = session.apply_snapshot(snapshot(360, door_open=True, locked=True))

        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertEqual(session.current_snapshot.lock, LockState.LOCKED)
        self.assertEqual(len(session.history), 5)

    def test_lock_episode_then_door_close_completes(self):
        session = alighting_session_passenger_gone()
        session.apply_snapshot(snapshot(300, door_open=True, locked=True))

        state = session.apply_snapshot(snapshot(420))

        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        self.assertEqual(session.history[-1].reason, "alighting_confirmed")
        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.duration_seconds, 420.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_lock_in_alighting_passenger_present_does_not_raise_exception(self):
        session = alighting_session_passenger_present()
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 5)

        state = session.apply_snapshot(
            snapshot(300, door_open=True, belt=True, locked=True,
                     cabin_temp_c=35.5)
        )

        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 5)
        guidance = guidance_for_session(session, DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "alighting")
        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertFalse(report.exception_occurred)

    def test_door_close_while_locked_without_passenger_completes(self):
        session = alighting_session_passenger_gone()

        state = session.apply_snapshot(snapshot(300, locked=True))

        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        self.assertEqual(session.history[-1].reason, "alighting_confirmed")
        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)

    def test_door_close_while_locked_with_passenger_raises_exception(self):
        session = alighting_session_passenger_present()

        state = session.apply_snapshot(snapshot(300, belt=True, locked=True))

        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 6)
        self.assertEqual(
            session.history[-1].reason, "ignition_off_locked_passenger_present"
        )
        report = report_for_session(session)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 1)
        self.assertTrue(report.exception_occurred)


if __name__ == "__main__":
    unittest.main()

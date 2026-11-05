"""QA scenarios for switching the ignition on while ALIGHTING.

Alighting has started at the destination: the rear door is open and
the care session is waiting for the door to close so it can confirm
completion. Turning the ignition on in this window must not be
mistaken for a new departure: the session holds in ALIGHTING, with or
without a passenger still present, and the transition history does
not grow. Completion still requires the ignition off and the door
closed with no passenger left; closing the door while a belted
passenger is still present does not complete the session. The
scenarios cover both the snapshot path and the event path, plus the
guidance and report views of the held alighting state.
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


def history_tuples(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


class AlightingIgnitionQATest(unittest.TestCase):
    def test_ignition_on_in_alighting_passenger_gone_keeps_state(self):
        session = alighting_session_passenger_gone()
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 5)

        state = session.apply_snapshot(snapshot(300, door_open=True, ignition=True))

        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 5)
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

    def test_ignition_on_repeated_is_idempotent(self):
        session = alighting_session_passenger_gone()

        session.apply_snapshot(snapshot(300, door_open=True, ignition=True))
        state = session.apply_snapshot(snapshot(360, door_open=True, ignition=True))

        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertTrue(session.current_snapshot.ignition_on)
        self.assertEqual(len(session.history), 5)

    def test_ignition_on_in_alighting_passenger_present_keeps_state(self):
        session = alighting_session_passenger_present()
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 5)

        state = session.apply_snapshot(
            snapshot(300, door_open=True, belt=True, ignition=True)
        )

        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 5)
        guidance = guidance_for_session(session, DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "alighting")

    def test_completion_after_ignition_episode_in_alighting(self):
        session = alighting_session_passenger_gone()
        session.apply_snapshot(snapshot(300, door_open=True, ignition=True))

        state = session.apply_snapshot(snapshot(420))

        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        last = session.history[-1]
        self.assertEqual(last.from_state, SessionState.ALIGHTING)
        self.assertEqual(last.to_state, SessionState.COMPLETED)
        self.assertEqual(last.reason, "alighting_confirmed")
        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 420.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_door_closed_with_passenger_still_present_does_not_complete(self):
        session = alighting_session_passenger_present()
        session.apply_snapshot(
            snapshot(300, door_open=True, belt=True, ignition=True)
        )

        state = session.apply_snapshot(snapshot(420, belt=True))

        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 5)
        report = report_for_session(session)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 5)

    def test_event_path_ignition_in_alighting_matches_snapshot_path(self):
        snapshot_session = alighting_session_passenger_gone()
        snapshot_session.apply_snapshot(snapshot(300, door_open=True, ignition=True))
        snapshot_session.apply_snapshot(snapshot(420))

        event_session = alighting_session_passenger_gone()
        state = event_session.apply_event(
            SignalEvent(SignalEventType.IGNITION_ON, timestamp=300)
        )
        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertEqual(len(event_session.history), 5)
        self.assertTrue(event_session.current_snapshot.ignition_on)

        state = event_session.apply_event(
            SignalEvent(SignalEventType.IGNITION_OFF, timestamp=360)
        )
        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertEqual(len(event_session.history), 5)
        self.assertFalse(event_session.current_snapshot.ignition_on)

        state = event_session.apply_event(
            SignalEvent(SignalEventType.REAR_DOOR_CLOSED, timestamp=420)
        )
        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(
            history_tuples(event_session), history_tuples(snapshot_session)
        )


if __name__ == "__main__":
    unittest.main()

"""QA scenarios for opening the rear door while ONBOARD.

Boarding is complete but the vehicle has not departed yet. In this
ONBOARD window the rear door opening again must not be mistaken for
alighting while the passenger is still belted: the session holds in
ONBOARD and the passenger latch stays set. Releasing the belt while
the door is closed also does not clear the latch on its own; the
latch only clears once the door actually opens, and that combination
is the pre-departure alighting path ONBOARD -> ALIGHTING. The
scenarios cover both the snapshot path and the event path, plus the
guidance and report views of the held onboard state.
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
    """A session that reached ONBOARD with the door closed."""
    session = CareSession()
    session.apply_snapshot(snapshot(0, door_open=True))
    session.apply_snapshot(snapshot(60, door_open=True, belt=True))
    session.apply_snapshot(snapshot(120, belt=True))
    return session


def history_tuples(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


class OnboardDoorOpenQATest(unittest.TestCase):
    def test_door_open_while_belted_holds_onboard(self):
        session = onboard_session()
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertEqual(len(session.history), 2)

        state = session.apply_snapshot(snapshot(180, door_open=True, belt=True))

        self.assertEqual(state, SessionState.ONBOARD)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 2)
        guidance = guidance_for_session(session, DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "passenger_onboard")
        self.assertEqual(
            guidance.text,
            "뒷좌석 승차가 확인되었습니다. 출발 전 안전벨트를 확인해 주세요.",
        )

    def test_door_open_close_repeat_is_idempotent(self):
        session = onboard_session()

        session.apply_snapshot(snapshot(180, door_open=True, belt=True))
        session.apply_snapshot(snapshot(240, door_open=True, belt=True))
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertTrue(session.current_snapshot.rear_door_open)
        self.assertEqual(len(session.history), 2)

        session.apply_snapshot(snapshot(300, belt=True))
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertFalse(session.current_snapshot.rear_door_open)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 2)

    def test_departure_after_door_episode_completes_normally(self):
        session = onboard_session()
        session.apply_snapshot(snapshot(180, door_open=True, belt=True))
        session.apply_snapshot(snapshot(300, belt=True))
        session.apply_snapshot(snapshot(360, belt=True, ignition=True))
        session.apply_snapshot(snapshot(420, belt=True))
        session.apply_snapshot(snapshot(480, door_open=True))
        state = session.apply_snapshot(snapshot(540))

        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(
            [(f, t, r) for f, t, r, _ in history_tuples(session)],
            [
                (SessionState.IDLE, SessionState.BOARDING, "rear_door_opened"),
                (SessionState.BOARDING, SessionState.ONBOARD, "passenger_onboard"),
                (SessionState.ONBOARD, SessionState.DRIVING, "ignition_on"),
                (SessionState.DRIVING, SessionState.ARRIVED, "ignition_off"),
                (SessionState.ARRIVED, SessionState.ALIGHTING, "alighting_started"),
                (SessionState.ALIGHTING, SessionState.COMPLETED, "alighting_confirmed"),
            ],
        )
        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 540.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_event_path_matches_snapshot_path(self):
        snapshot_session = onboard_session()
        snapshot_session.apply_snapshot(snapshot(180, door_open=True, belt=True))
        snapshot_session.apply_snapshot(snapshot(300, belt=True))
        snapshot_session.apply_snapshot(snapshot(360, belt=True, ignition=True))

        event_session = CareSession()
        for event in [
            SignalEvent(SignalEventType.REAR_DOOR_OPENED, timestamp=0),
            SignalEvent(SignalEventType.REAR_BELT_BUCKLED, timestamp=60),
            SignalEvent(SignalEventType.REAR_DOOR_CLOSED, timestamp=120),
            SignalEvent(SignalEventType.REAR_DOOR_OPENED, timestamp=180),
            SignalEvent(SignalEventType.REAR_DOOR_CLOSED, timestamp=300),
            SignalEvent(SignalEventType.IGNITION_ON, timestamp=360),
        ]:
            event_session.apply_event(event)

        self.assertEqual(event_session.state, SessionState.DRIVING)
        self.assertTrue(event_session.passenger_present)
        self.assertEqual(
            history_tuples(event_session), history_tuples(snapshot_session)
        )

    def test_unbuckle_with_door_closed_keeps_latch(self):
        session = onboard_session()

        state = session.apply_snapshot(snapshot(180, belt=False))

        self.assertEqual(state, SessionState.ONBOARD)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 2)

    def test_unbuckle_then_door_open_is_predeparture_alighting(self):
        session = onboard_session()
        session.apply_snapshot(snapshot(180, belt=False))

        state = session.apply_snapshot(snapshot(240, door_open=True))

        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        last = session.history[-1]
        self.assertEqual(last.from_state, SessionState.ONBOARD)
        self.assertEqual(last.to_state, SessionState.ALIGHTING)
        self.assertEqual(last.reason, "passenger_alighting")
        guidance = guidance_for_session(session, DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "alighting")

        state = session.apply_snapshot(snapshot(300))
        self.assertEqual(state, SessionState.COMPLETED)
        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 4)
        self.assertEqual(report.duration_seconds, 300.0)


if __name__ == "__main__":
    unittest.main()

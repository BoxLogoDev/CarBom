"""QA scenarios for opening the rear door while driving.

Opening the rear door does not leave DRIVING on its own. With the
belt buckled the passenger stays detected. Repeated door open and
close snapshots while driving add no transitions, and a drive with
such a door episode still completes through the normal arrival and
alighting path. The passenger latch has no DRIVING exception. A
door opening together with an unbuckled belt clears the passenger
while still driving, and that cleared drive then walks to COMPLETED
in one ignition off snapshot without an exception when the car
locks afterward. The scenarios cover both the snapshot path and
the event path.
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
             locked=False, hvac_on=True, cabin_temp_c=None):
    return SignalSnapshot(
        rear_door=DoorState.OPEN if door_open else DoorState.CLOSED,
        rear_seat_belt_buckled=belt,
        ignition=IgnitionState.ON if ignition else IgnitionState.OFF,
        lock=LockState.LOCKED if locked else LockState.UNLOCKED,
        hvac_on=hvac_on,
        cabin_temp_c=cabin_temp_c,
        timestamp=timestamp,
    )


def driving_session():
    session = CareSession()
    session.apply_snapshot(snapshot(0.0, door_open=True))
    session.apply_snapshot(snapshot(60.0, belt=True))
    session.apply_snapshot(snapshot(120.0, belt=True, ignition=True))
    return session


class DrivingDoorOpenQATest(unittest.TestCase):
    def test_door_open_while_driving_keeps_driving_and_passenger(self):
        session = driving_session()
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)
        self.assertTrue(session.passenger_present)

        state = session.apply_snapshot(
            snapshot(
                180.0,
                door_open=True,
                belt=True,
                ignition=True,
                cabin_temp_c=22.0,
            )
        )

        self.assertEqual(state, SessionState.DRIVING)
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 3)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")

    def test_door_open_close_while_driving_is_idempotent(self):
        session = driving_session()

        for timestamp in (180.0, 240.0):
            state = session.apply_snapshot(
                snapshot(
                    timestamp, door_open=True, belt=True, ignition=True
                )
            )
            self.assertEqual(state, SessionState.DRIVING)
            self.assertEqual(len(session.history), 3)

        state = session.apply_snapshot(
            snapshot(300.0, belt=True, ignition=True)
        )
        self.assertEqual(state, SessionState.DRIVING)
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 3)

    def test_drive_with_door_episode_completes_normally(self):
        session = driving_session()
        session.apply_snapshot(
            snapshot(180.0, door_open=True, belt=True, ignition=True)
        )
        state = session.apply_snapshot(
            snapshot(240.0, belt=True, ignition=True)
        )
        self.assertEqual(state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)

        state = session.apply_snapshot(snapshot(300.0, belt=True))
        self.assertEqual(state, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)

        state = session.apply_snapshot(
            snapshot(360.0, door_open=True, belt=True)
        )
        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 5)

        state = session.apply_snapshot(
            snapshot(420.0, door_open=True, belt=False)
        )
        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 5)

        state = session.apply_snapshot(snapshot(480.0))
        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 480.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_event_path_door_open_while_driving(self):
        session = driving_session()

        state = session.apply_event(
            SignalEvent(SignalEventType.REAR_DOOR_OPENED, timestamp=180.0)
        )
        self.assertEqual(state, SessionState.DRIVING)
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 3)
        self.assertEqual(session.current_snapshot.rear_door, DoorState.OPEN)

        state = session.apply_event(
            SignalEvent(SignalEventType.REAR_DOOR_CLOSED, timestamp=240.0)
        )
        self.assertEqual(state, SessionState.DRIVING)
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)
        self.assertEqual(
            session.current_snapshot.rear_door, DoorState.CLOSED
        )

    def test_door_open_with_unbuckle_while_driving_clears_passenger_latch(self):
        session = driving_session()

        state = session.apply_snapshot(
            snapshot(180.0, door_open=True, belt=False, ignition=True)
        )

        self.assertEqual(state, SessionState.DRIVING)
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 3)
        guidance = guidance_for_session(session)
        self.assertEqual(guidance.level, GuidanceLevel.NONE)
        self.assertEqual(guidance.reason, "no_passenger")
        self.assertEqual(guidance.text, "")

    def test_cleared_passenger_drive_completes_without_exception_on_lock(self):
        session = driving_session()
        session.apply_snapshot(
            snapshot(180.0, door_open=True, belt=False, ignition=True)
        )
        self.assertFalse(session.passenger_present)

        state = session.apply_snapshot(
            snapshot(240.0, belt=False, ignition=True)
        )
        self.assertEqual(state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)

        state = session.apply_snapshot(snapshot(300.0, belt=False))
        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)

        state = session.apply_snapshot(
            snapshot(360.0, belt=False, locked=True)
        )
        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")


if __name__ == "__main__":
    unittest.main()

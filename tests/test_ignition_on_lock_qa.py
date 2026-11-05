"""QA scenarios for locking while the ignition stays on.

The exception needs four conditions together. The ignition must be
off. The vehicle must be locked. The rear door must be closed. A
passenger must still be present. This file fixes the ignition
condition. Locking while the ignition is on is a normal driving or
idling situation and must never enter the exception state. The same
lock must enter the exception only when the ignition turns off. The
scenarios cover both the snapshot path and the event path.
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


class IgnitionOnLockQATest(unittest.TestCase):
    def test_locked_while_driving_with_ignition_on_never_raises_exception(self):
        session = driving_session()
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 3)
        self.assertEqual(
            [
                (t.from_state, t.to_state, t.reason, t.timestamp)
                for t in session.history
            ],
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
                    SessionState.DRIVING,
                    "ignition_on",
                    120.0,
                ),
            ],
        )

        state = session.apply_snapshot(
            snapshot(180.0, belt=True, ignition=True, locked=True)
        )
        self.assertEqual(state, SessionState.DRIVING)
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)

        state = session.apply_snapshot(
            snapshot(240.0, belt=True, ignition=True, locked=True)
        )
        self.assertEqual(state, SessionState.DRIVING)
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)
        self.assertTrue(session.passenger_present)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")

        report = report_for_session(session)
        self.assertEqual(report.final_state, SessionState.DRIVING)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 3)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_same_locked_snapshot_with_ignition_off_enters_exception_from_driving(self):
        session = driving_session()
        session.apply_snapshot(
            snapshot(180.0, belt=True, ignition=True, locked=True)
        )
        session.apply_snapshot(
            snapshot(240.0, belt=True, ignition=True, locked=True)
        )
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)

        state = session.apply_snapshot(
            snapshot(300.0, belt=True, locked=True)
        )
        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 4)
        last = session.history[-1]
        self.assertEqual(last.from_state, SessionState.DRIVING)
        self.assertEqual(last.to_state, SessionState.EXCEPTION)
        self.assertEqual(
            last.reason, "ignition_off_locked_passenger_present"
        )
        self.assertEqual(last.timestamp, 300.0)
        self.assertNotIn(
            SessionState.ARRIVED,
            [t.to_state for t in session.history],
        )

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)

    def test_locked_while_idling_after_arrival_stays_arrived_until_ignition_off(self):
        session = driving_session()

        state = session.apply_snapshot(snapshot(180.0, belt=True))
        self.assertEqual(state, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)
        last = session.history[-1]
        self.assertEqual(last.from_state, SessionState.DRIVING)
        self.assertEqual(last.to_state, SessionState.ARRIVED)
        self.assertEqual(last.reason, "ignition_off")
        self.assertEqual(last.timestamp, 180.0)

        state = session.apply_snapshot(
            snapshot(240.0, belt=True, ignition=True)
        )
        self.assertEqual(state, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)

        state = session.apply_snapshot(
            snapshot(300.0, belt=True, ignition=True, locked=True)
        )
        self.assertEqual(state, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertFalse(report.completed)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(
            guidance.reason, "arrived_dropoff_check_rear_seat"
        )

        state = session.apply_snapshot(
            snapshot(360.0, belt=True, locked=True)
        )
        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)
        last = session.history[-1]
        self.assertEqual(last.from_state, SessionState.ARRIVED)
        self.assertEqual(last.to_state, SessionState.EXCEPTION)
        self.assertEqual(
            last.reason, "ignition_off_locked_passenger_present"
        )
        self.assertEqual(last.timestamp, 360.0)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)

    def test_departure_with_doors_already_locked_reaches_driving(self):
        session = CareSession()
        session.apply_snapshot(snapshot(0.0, door_open=True))
        session.apply_snapshot(snapshot(60.0, belt=True))
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertEqual(len(session.history), 2)

        state = session.apply_snapshot(
            snapshot(120.0, belt=True, ignition=True, locked=True)
        )
        self.assertEqual(state, SessionState.DRIVING)
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)
        last = session.history[-1]
        self.assertEqual(last.from_state, SessionState.ONBOARD)
        self.assertEqual(last.to_state, SessionState.DRIVING)
        self.assertEqual(last.reason, "ignition_on")
        self.assertEqual(last.timestamp, 120.0)

    def test_locked_snapshot_with_rear_door_open_stays_boarding_until_door_closes(self):
        session = CareSession()
        session.apply_snapshot(snapshot(0.0, door_open=True))
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)

        state = session.apply_snapshot(
            snapshot(60.0, door_open=True, belt=True, locked=True)
        )
        self.assertEqual(state, SessionState.BOARDING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 1)

        state = session.apply_snapshot(
            snapshot(120.0, belt=True, locked=True)
        )
        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 2)
        last = session.history[-1]
        self.assertEqual(last.from_state, SessionState.BOARDING)
        self.assertEqual(last.to_state, SessionState.EXCEPTION)
        self.assertEqual(
            last.reason, "ignition_off_locked_passenger_present"
        )
        self.assertEqual(last.timestamp, 120.0)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)

    def test_event_path_locked_while_ignition_on_matches_snapshot_path(self):
        """The event path matches the snapshot path for this lock.

        A locked event while the ignition is on keeps driving. An
        ignition off event after that lock enters the exception. The
        result is the same as the snapshot path covered by the first
        two tests in this class.
        """
        session = CareSession()
        session.apply_event(
            SignalEvent(SignalEventType.REAR_DOOR_OPENED, timestamp=0.0)
        )
        session.apply_event(
            SignalEvent(SignalEventType.REAR_BELT_BUCKLED, timestamp=60.0)
        )
        session.apply_event(
            SignalEvent(SignalEventType.REAR_DOOR_CLOSED, timestamp=60.0)
        )
        session.apply_event(
            SignalEvent(SignalEventType.IGNITION_ON, timestamp=120.0)
        )
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)

        state = session.apply_event(
            SignalEvent(SignalEventType.LOCKED, timestamp=180.0)
        )
        self.assertEqual(state, SessionState.DRIVING)
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)

        state = session.apply_event(
            SignalEvent(SignalEventType.IGNITION_OFF, timestamp=240.0)
        )
        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 4)
        last = session.history[-1]
        self.assertEqual(last.from_state, SessionState.DRIVING)
        self.assertEqual(last.to_state, SessionState.EXCEPTION)
        self.assertEqual(
            last.reason, "ignition_off_locked_passenger_present"
        )
        self.assertEqual(last.timestamp, 240.0)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)


if __name__ == "__main__":
    unittest.main()

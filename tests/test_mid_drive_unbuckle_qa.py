"""QA scenarios for unbuckling mid-drive and cabin heat while driving.

Passenger presence is latched by the belt and cleared only when the
belt is unbuckled *and* the rear door opens together. A child who
unbuckles mid-drive (door still closed) must therefore stay detected,
so the forgotten-passenger exception still fires after arrival and
locking. Cabin temperature escalation in guidance is an ARRIVED /
EXCEPTION behaviour: while DRIVING the guidance stays a plain driving
notice even at dangerous temperatures, although the report still
records the peak temperature seen.
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


class MidDriveUnbuckleQATest(unittest.TestCase):
    def test_unbuckle_mid_drive_keeps_passenger_and_state(self):
        session = driving_session()
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)

        state = session.apply_snapshot(
            snapshot(180.0, belt=False, ignition=True, cabin_temp_c=26.0)
        )

        self.assertEqual(state, SessionState.DRIVING)
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 3)
        guidance = guidance_for_session(session, context=DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")

    def test_unbuckled_passenger_still_triggers_exception_after_lock(self):
        session = driving_session()
        session.apply_snapshot(snapshot(180.0, belt=False, ignition=True))

        state = session.apply_snapshot(snapshot(240.0, belt=False))
        self.assertEqual(state, SessionState.ARRIVED)
        self.assertTrue(session.passenger_present)

        state = session.apply_snapshot(snapshot(300.0, belt=False, locked=True))
        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        guidance = guidance_for_session(session, context=DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.reason, "passenger_left_locked")

    def test_recovery_after_mid_drive_unbuckle_completes(self):
        session = driving_session()
        session.apply_snapshot(snapshot(180.0, belt=False, ignition=True))
        session.apply_snapshot(snapshot(240.0, belt=False))
        session.apply_snapshot(snapshot(300.0, belt=False, locked=True))
        self.assertEqual(session.state, SessionState.EXCEPTION)

        state = session.apply_snapshot(snapshot(360.0, door_open=True, belt=False))
        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)

        state = session.apply_snapshot(snapshot(420.0, belt=False))
        self.assertEqual(state, SessionState.COMPLETED)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 7)
        self.assertEqual(report.duration_seconds, 420.0)
        self.assertEqual(report.summary, "예외 발생 후 하차 확인 완료")

    def test_driving_temperature_rise_keeps_driving_guidance(self):
        session = CareSession()
        session.apply_snapshot(snapshot(0.0, door_open=True))
        session.apply_snapshot(snapshot(60.0, belt=True))
        session.apply_snapshot(
            snapshot(120.0, belt=True, ignition=True, cabin_temp_c=24.0)
        )
        self.assertEqual(len(session.history), 3)

        for cabin_temp_c, timestamp in ((32.0, 180.0), (35.5, 240.0)):
            state = session.apply_snapshot(
                snapshot(
                    timestamp,
                    belt=True,
                    ignition=True,
                    hvac_on=False,
                    cabin_temp_c=cabin_temp_c,
                )
            )
            self.assertEqual(state, SessionState.DRIVING)
            self.assertEqual(len(session.history), 3)
            guidance = guidance_for_session(session)
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "driving")
            self.assertNotIn("도", guidance.text)

        report = report_for_session(session)
        self.assertEqual(report.final_state, SessionState.DRIVING)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_event_path_unbuckle_mid_drive_matches_snapshot_path(self):
        session = CareSession()
        events = [
            SignalEvent(SignalEventType.REAR_DOOR_OPENED, timestamp=0.0),
            SignalEvent(SignalEventType.REAR_BELT_BUCKLED, timestamp=60.0),
            SignalEvent(SignalEventType.REAR_DOOR_CLOSED, timestamp=60.0),
            SignalEvent(SignalEventType.IGNITION_ON, timestamp=120.0),
            SignalEvent(SignalEventType.REAR_BELT_UNBUCKLED, timestamp=180.0),
        ]
        for event in events:
            session.apply_event(event)

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 3)

    def test_unbuckle_alone_onboard_keeps_passenger(self):
        session = CareSession()
        session.apply_snapshot(snapshot(0.0, door_open=True))
        session.apply_snapshot(snapshot(60.0, belt=True))
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertEqual(len(session.history), 2)

        state = session.apply_snapshot(snapshot(120.0, belt=False))
        self.assertEqual(state, SessionState.ONBOARD)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 2)

        state = session.apply_snapshot(snapshot(180.0, belt=False, ignition=True))
        self.assertEqual(state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)


if __name__ == "__main__":
    unittest.main()

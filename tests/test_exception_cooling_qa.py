"""QA scenarios for cooling down while a session stays in EXCEPTION.

Entering EXCEPTION is covered elsewhere (temperature rising). This file
covers the opposite direction: the cabin cools down (for example remote
HVAC start) while the passenger is still locked inside. Cooling must
never clear the exception, the guidance must soften with the *current*
temperature, and recovery through the rear door must stay possible.
"""

import unittest

from engine import (
    CareSession,
    DoorState,
    LockState,
    SessionState,
    SignalEvent,
    SignalEventType,
    SignalSnapshot,
)
from engine.adapters.simulator import replay_scenario
from engine.guidance import DestinationContext, guidance_for_session
from engine.report import report_for_session


def exception_session():
    session = CareSession()
    replay_scenario(session, "forgotten_rising_temp")
    return session


def locked_snapshot(cabin_temp_c, timestamp):
    return SignalSnapshot(
        rear_seat_belt_buckled=True,
        lock=LockState.LOCKED,
        hvac_on=True,
        cabin_temp_c=cabin_temp_c,
        timestamp=timestamp,
    )


class ExceptionCoolingQATest(unittest.TestCase):
    def test_sequential_cooling_keeps_exception_and_history(self):
        session = exception_session()
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)

        for cabin_temp_c, timestamp in (
            (32.0, 480.0),
            (28.0, 540.0),
            (24.0, 600.0),
        ):
            result = session.apply_snapshot(
                locked_snapshot(cabin_temp_c, timestamp)
            )
            self.assertEqual(result, SessionState.EXCEPTION)
            self.assertEqual(session.state, SessionState.EXCEPTION)
            self.assertTrue(session.passenger_present)
            self.assertEqual(len(session.history), 5)
            self.assertEqual(
                session.current_snapshot.cabin_temp_c, cabin_temp_c
            )

    def test_guidance_deescalates_with_current_temperature(self):
        session = exception_session()

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level.name, "URGENT")
        self.assertEqual(
            guidance.reason,
            "passenger_left_locked_dangerous_cabin_temp",
        )
        self.assertIn("위험합니다", guidance.text)
        self.assertIn("즉시", guidance.text)
        self.assertIn("35.5도", guidance.text)

        session.apply_snapshot(locked_snapshot(32.0, 480.0))
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level.name, "URGENT")
        self.assertEqual(
            guidance.reason, "passenger_left_locked_hot_cabin"
        )
        self.assertIn("32도", guidance.text)
        self.assertNotIn("즉시", guidance.text)
        self.assertNotIn("위험합니다", guidance.text)

        session.apply_snapshot(locked_snapshot(24.0, 540.0))
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level.name, "URGENT")
        self.assertEqual(guidance.reason, "passenger_left_locked")
        self.assertNotIn("실내 온도", guidance.text)

    def test_cooling_boundary_descent(self):
        cases = (
            (35.0, "passenger_left_locked_dangerous_cabin_temp"),
            (34.9, "passenger_left_locked_hot_cabin"),
            (32.0, "passenger_left_locked_hot_cabin"),
            (31.9, "passenger_left_locked"),
        )
        for cabin_temp_c, expected_reason in cases:
            with self.subTest(cabin_temp_c=cabin_temp_c):
                session = exception_session()
                session.apply_snapshot(
                    locked_snapshot(cabin_temp_c, 480.0)
                )
                self.assertEqual(session.state, SessionState.EXCEPTION)
                guidance = guidance_for_session(session)
                self.assertEqual(guidance.reason, expected_reason)

    def test_event_path_cooling_matches_snapshot_path(self):
        via_snapshot = exception_session()
        via_snapshot.apply_snapshot(locked_snapshot(24.0, 480.0))

        via_events = exception_session()
        via_events.apply_event(SignalEvent(SignalEventType.HVAC_ON))
        via_events.apply_event(
            SignalEvent(
                SignalEventType.CABIN_TEMP_CHANGED, cabin_temp_c=24.0
            )
        )

        self.assertEqual(via_events.state, via_snapshot.state)
        self.assertEqual(
            via_events.passenger_present, via_snapshot.passenger_present
        )
        self.assertEqual(
            len(via_events.history), len(via_snapshot.history)
        )
        self.assertEqual(
            via_events.current_snapshot.cabin_temp_c,
            via_snapshot.current_snapshot.cabin_temp_c,
        )
        self.assertTrue(via_events.current_snapshot.hvac_on)
        event_guidance = guidance_for_session(via_events)
        snapshot_guidance = guidance_for_session(via_snapshot)
        self.assertEqual(event_guidance.level, snapshot_guidance.level)
        self.assertEqual(event_guidance.text, snapshot_guidance.text)
        self.assertEqual(event_guidance.reason, snapshot_guidance.reason)

    def test_recovery_after_cooling_still_completes(self):
        session = exception_session()
        session.apply_snapshot(locked_snapshot(24.0, 480.0))
        self.assertEqual(session.state, SessionState.EXCEPTION)

        result = session.apply_snapshot(
            SignalSnapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                cabin_temp_c=24.0,
                timestamp=540.0,
            )
        )
        self.assertEqual(result, SessionState.ALIGHTING)
        self.assertEqual(
            session.history[-1].reason,
            "rear_door_opened_after_exception",
        )

        result = session.apply_snapshot(
            SignalSnapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=False,
                cabin_temp_c=24.0,
                timestamp=600.0,
            )
        )
        self.assertEqual(result, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)

        result = session.apply_snapshot(
            SignalSnapshot(timestamp=660.0)
        )
        self.assertEqual(result, SessionState.COMPLETED)

        report = report_for_session(session)
        self.assertEqual(report.summary, "예외 발생 후 하차 확인 완료")
        self.assertEqual(report.exception_count, 1)

    def test_report_during_cooled_exception(self):
        session = exception_session()
        session.apply_snapshot(locked_snapshot(32.0, 480.0))

        report = report_for_session(session)
        self.assertEqual(report.final_state, SessionState.EXCEPTION)
        self.assertFalse(report.completed)
        self.assertTrue(report.exception_occurred)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")
        # CareReport defines max_cabin_temp_c over the transition
        # snapshots plus the current snapshot only, so once a cooler
        # snapshot replaces the 35.5-degree one without a transition,
        # the reported maximum follows the current snapshot.
        self.assertEqual(report.max_cabin_temp_c, 32.0)


if __name__ == "__main__":
    unittest.main()

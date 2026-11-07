"""QA scenarios for HVAC input alone while EXCEPTION.

The cooling QA (test_exception_cooling_qa.py) covers the cabin
temperature falling while a passenger stays locked inside. This file
covers the orthogonal angle: toggling HVAC on and off by itself, with
the cabin temperature held at 35.5 degrees, must never change the
session state, the passenger presence, or the transition history --
only the current snapshot's hvac_on flag may move. Recovery through
the rear door must still work after an HVAC episode.
"""

import unittest

from engine import (
    CareSession,
    DestinationContext,
    DoorState,
    GuidanceLevel,
    IgnitionState,
    LockState,
    SessionState,
    SignalEvent,
    SignalEventType,
    SignalSnapshot,
    guidance_for_session,
    report_for_session,
)
from engine.adapters.simulator import replay_scenario


def exception_session():
    session = CareSession()
    replay_scenario(session, "forgotten_rising_temp")
    return session


def locked_hvac_snapshot(hvac_on, timestamp):
    return SignalSnapshot(
        rear_seat_belt_buckled=True,
        ignition=IgnitionState.OFF,
        hvac_on=hvac_on,
        cabin_temp_c=35.5,
        lock=LockState.LOCKED,
        timestamp=timestamp,
    )


def history_tuples(session):
    return [
        (
            transition.from_state,
            transition.to_state,
            transition.reason,
            transition.timestamp,
        )
        for transition in session.history
    ]


BASELINE_HISTORY = [
    (SessionState.IDLE, SessionState.BOARDING, "rear_door_opened", 0.0),
    (
        SessionState.BOARDING,
        SessionState.ONBOARD,
        "passenger_onboard",
        60.0,
    ),
    (SessionState.ONBOARD, SessionState.DRIVING, "ignition_on", 120.0),
    (SessionState.DRIVING, SessionState.ARRIVED, "ignition_off", 180.0),
    (
        SessionState.ARRIVED,
        SessionState.EXCEPTION,
        "ignition_off_locked_passenger_present",
        240.0,
    ),
]


class ExceptionHvacQATest(unittest.TestCase):
    def test_exception_hvac_on_alone_stays_exception(self):
        session = exception_session()

        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(history_tuples(session), BASELINE_HISTORY)
        self.assertTrue(session.passenger_present)
        self.assertFalse(session.current_snapshot.hvac_on)

        result = session.apply_snapshot(
            locked_hvac_snapshot(True, 480.0)
        )

        self.assertEqual(result, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(history_tuples(session), BASELINE_HISTORY)
        self.assertTrue(session.passenger_present)
        self.assertTrue(session.current_snapshot.hvac_on)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)
        self.assertTrue(session.current_snapshot.locked)

    def test_exception_hvac_repeated_is_idempotent_and_toggles_off(self):
        session = exception_session()

        for timestamp in (480.0, 490.0):
            session.apply_snapshot(
                locked_hvac_snapshot(True, timestamp)
            )
            self.assertEqual(session.state, SessionState.EXCEPTION)
            self.assertEqual(len(session.history), 5)
            self.assertTrue(session.passenger_present)
            self.assertTrue(session.current_snapshot.hvac_on)

        session.apply_snapshot(locked_hvac_snapshot(False, 500.0))
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(history_tuples(session), BASELINE_HISTORY)
        self.assertTrue(session.passenger_present)
        self.assertFalse(session.current_snapshot.hvac_on)

    def test_exception_hvac_toggle_preserves_guidance_and_report(self):
        session = exception_session()

        def guidance_and_report(a_session):
            guidance = guidance_for_session(
                a_session, context=DestinationContext.DROPOFF
            )
            report = report_for_session(a_session)
            return guidance, report

        before_guidance, before_report = guidance_and_report(session)
        self.assertEqual(before_guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            before_guidance.reason,
            "passenger_left_locked_dangerous_cabin_temp",
        )
        self.assertIn("위험합니다", before_guidance.text)
        self.assertIn("35.5도", before_guidance.text)
        self.assertIn("즉시", before_guidance.text)
        self.assertEqual(before_report.final_state, SessionState.EXCEPTION)
        self.assertFalse(before_report.completed)
        self.assertTrue(before_report.exception_occurred)
        self.assertEqual(before_report.exception_count, 1)
        self.assertEqual(before_report.transition_count, 5)
        self.assertEqual(before_report.duration_seconds, 240.0)
        self.assertEqual(before_report.max_cabin_temp_c, 35.5)
        self.assertEqual(before_report.summary, "예외 발생 · 하차 미확인")

        for hvac_on, timestamp in ((True, 480.0), (False, 490.0)):
            session.apply_snapshot(
                locked_hvac_snapshot(hvac_on, timestamp)
            )
            guidance, report = guidance_and_report(session)
            self.assertEqual(guidance.level, before_guidance.level)
            self.assertEqual(guidance.state, before_guidance.state)
            self.assertEqual(guidance.text, before_guidance.text)
            self.assertEqual(guidance.reason, before_guidance.reason)
            self.assertEqual(report.final_state, before_report.final_state)
            self.assertEqual(report.completed, before_report.completed)
            self.assertEqual(
                report.exception_count, before_report.exception_count
            )
            self.assertEqual(
                report.transition_count, before_report.transition_count
            )
            self.assertEqual(
                report.duration_seconds, before_report.duration_seconds
            )
            self.assertEqual(
                report.max_cabin_temp_c, before_report.max_cabin_temp_c
            )
            self.assertEqual(report.summary, before_report.summary)

    def test_exception_hvac_event_path_matches_snapshot_path(self):
        snapshot_session = exception_session()
        snapshot_session.apply_snapshot(
            locked_hvac_snapshot(True, 480.0)
        )
        self.assertTrue(snapshot_session.current_snapshot.hvac_on)
        snapshot_session.apply_snapshot(
            locked_hvac_snapshot(False, 490.0)
        )

        event_session = exception_session()
        event_session.apply_event(
            SignalEvent(type=SignalEventType.HVAC_ON, timestamp=480.0)
        )
        self.assertEqual(event_session.state, SessionState.EXCEPTION)
        self.assertTrue(event_session.current_snapshot.hvac_on)
        # The event path preserves the locked, belted, hot snapshot.
        self.assertTrue(event_session.current_snapshot.locked)
        self.assertTrue(
            event_session.current_snapshot.rear_seat_belt_buckled
        )
        self.assertEqual(
            event_session.current_snapshot.cabin_temp_c, 35.5
        )
        event_session.apply_event(
            SignalEvent(type=SignalEventType.HVAC_OFF, timestamp=490.0)
        )

        self.assertEqual(snapshot_session.state, SessionState.EXCEPTION)
        self.assertEqual(event_session.state, SessionState.EXCEPTION)
        self.assertTrue(snapshot_session.passenger_present)
        self.assertTrue(event_session.passenger_present)
        self.assertEqual(
            history_tuples(event_session),
            history_tuples(snapshot_session),
        )
        self.assertEqual(history_tuples(event_session), BASELINE_HISTORY)
        self.assertFalse(snapshot_session.current_snapshot.hvac_on)
        self.assertFalse(event_session.current_snapshot.hvac_on)
        self.assertEqual(
            event_session.current_snapshot.cabin_temp_c,
            snapshot_session.current_snapshot.cabin_temp_c,
        )

    def test_exception_hvac_episode_then_recovery_completes(self):
        session = exception_session()

        session.apply_snapshot(locked_hvac_snapshot(True, 480.0))
        session.apply_snapshot(locked_hvac_snapshot(False, 490.0))
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)

        result = session.apply_snapshot(
            SignalSnapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                cabin_temp_c=35.5,
                timestamp=540.0,
            )
        )
        self.assertEqual(result, SessionState.ALIGHTING)
        self.assertEqual(len(session.history), 6)
        self.assertEqual(
            session.history[-1].reason,
            "rear_door_opened_after_exception",
        )

        result = session.apply_snapshot(
            SignalSnapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=False,
                cabin_temp_c=35.5,
                timestamp=600.0,
            )
        )
        self.assertEqual(result, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)

        result = session.apply_snapshot(
            SignalSnapshot(timestamp=660.0)
        )
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 7)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 7)
        self.assertEqual(report.duration_seconds, 660.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.summary, "예외 발생 후 하차 확인 완료")

    def test_exception_hvac_on_rear_door_open_starts_alighting(self):
        session = exception_session()

        result = session.apply_snapshot(
            SignalSnapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                hvac_on=True,
                cabin_temp_c=35.5,
                timestamp=480.0,
            )
        )

        self.assertEqual(result, SessionState.ALIGHTING)
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertEqual(len(session.history), 6)
        self.assertTrue(session.current_snapshot.hvac_on)
        self.assertEqual(
            session.history[-1].from_state, SessionState.EXCEPTION
        )
        self.assertEqual(
            session.history[-1].to_state, SessionState.ALIGHTING
        )
        self.assertEqual(
            session.history[-1].reason,
            "rear_door_opened_after_exception",
        )
        self.assertEqual(session.history[-1].timestamp, 480.0)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "alighting")

        report = report_for_session(session)
        self.assertEqual(report.final_state, SessionState.ALIGHTING)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 480.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)


if __name__ == "__main__":
    unittest.main()

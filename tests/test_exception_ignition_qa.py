"""QA scenarios for ignition input alone while EXCEPTION.

The partial-release QA (test_exception_partial_release_qa.py) checks
with a single test that switching the ignition on while the car stays
locked does not release the exception. This file is the dedicated
ignition episode series for EXCEPTION, in the same spirit as the
per-signal files for the other states: toggling the ignition on and
off by itself -- derived from the current snapshot with
dataclasses.replace, changing only ignition and timestamp -- must
never change the session state, the passenger presence, or the
transition history while the car stays locked at 35.5 degrees; only
the current snapshot's ignition flag may move. The exception exit
that needs ignition (unlock while ignition is on) still works when
the unlock arrives in a later step, and the rear-door recovery still
completes after an ignition episode. The scenarios cover both the
snapshot path and the event path, plus the guidance views in every
destination context and the care report.
"""

import dataclasses
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
    guidance_for_session,
    report_for_session,
)
from engine.adapters.simulator import replay_scenario


def exception_session():
    session = CareSession()
    replay_scenario(session, "forgotten_rising_temp")
    return session


def with_ignition(session, ignition_on, timestamp):
    return dataclasses.replace(
        session.current_snapshot,
        ignition=IgnitionState.ON if ignition_on else IgnitionState.OFF,
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


class ExceptionIgnitionQATest(unittest.TestCase):
    def test_exception_ignition_on_alone_keeps_state(self):
        session = exception_session()

        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(history_tuples(session), BASELINE_HISTORY)
        self.assertTrue(session.passenger_present)
        self.assertFalse(session.current_snapshot.ignition_on)

        result = session.apply_snapshot(with_ignition(session, True, 480.0))

        self.assertEqual(result, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(history_tuples(session), BASELINE_HISTORY)
        self.assertTrue(session.passenger_present)
        self.assertTrue(session.current_snapshot.ignition_on)
        self.assertEqual(session.current_snapshot.lock, LockState.LOCKED)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason,
            "passenger_left_locked_dangerous_cabin_temp",
        )
        self.assertIn("위험합니다", guidance.text)
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)

        report = report_for_session(session)
        self.assertEqual(report.final_state, SessionState.EXCEPTION)
        self.assertFalse(report.completed)
        self.assertTrue(report.exception_occurred)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_exception_ignition_repeated_is_idempotent_and_toggles_off(self):
        session = exception_session()

        for timestamp in (480.0, 540.0):
            result = session.apply_snapshot(
                with_ignition(session, True, timestamp)
            )
            self.assertEqual(result, SessionState.EXCEPTION)
            self.assertEqual(history_tuples(session), BASELINE_HISTORY)
            self.assertTrue(session.passenger_present)
            self.assertTrue(session.current_snapshot.ignition_on)

        result = session.apply_snapshot(with_ignition(session, False, 600.0))

        self.assertEqual(result, SessionState.EXCEPTION)
        self.assertEqual(history_tuples(session), BASELINE_HISTORY)
        self.assertTrue(session.passenger_present)
        self.assertFalse(session.current_snapshot.ignition_on)

    def test_exception_ignition_preserves_guidance_and_report_all_contexts(
        self,
    ):
        session = exception_session()
        contexts = (
            DestinationContext.GENERAL,
            DestinationContext.DROPOFF,
            DestinationContext.PICKUP,
        )
        before = [
            guidance_for_session(session, context=context)
            for context in contexts
        ]
        before_report = report_for_session(session)
        for guidance in before:
            self.assertEqual(guidance.level, GuidanceLevel.URGENT)
            self.assertEqual(
                guidance.reason,
                "passenger_left_locked_dangerous_cabin_temp",
            )

        session.apply_snapshot(with_ignition(session, True, 480.0))

        after = [
            guidance_for_session(session, context=context)
            for context in contexts
        ]
        self.assertEqual(
            [(g.level, g.state, g.text, g.reason) for g in after],
            [(g.level, g.state, g.text, g.reason) for g in before],
        )
        report = report_for_session(session)
        self.assertEqual(report.final_state, before_report.final_state)
        self.assertEqual(report.completed, before_report.completed)
        self.assertEqual(report.exception_count, before_report.exception_count)
        self.assertEqual(
            report.transition_count, before_report.transition_count
        )
        self.assertEqual(
            report.duration_seconds, before_report.duration_seconds
        )
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(
            report.max_cabin_temp_c, before_report.max_cabin_temp_c
        )
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.summary, before_report.summary)

    def test_exception_ignition_event_path_matches_snapshot_path(self):
        snapshot_session = exception_session()
        snapshot_session.apply_snapshot(
            with_ignition(snapshot_session, True, 480.0)
        )
        self.assertTrue(snapshot_session.current_snapshot.ignition_on)
        snapshot_session.apply_snapshot(
            with_ignition(snapshot_session, False, 540.0)
        )

        event_session = exception_session()
        event_session.apply_event(
            SignalEvent(type=SignalEventType.IGNITION_ON, timestamp=480.0)
        )
        self.assertEqual(event_session.state, SessionState.EXCEPTION)
        self.assertTrue(event_session.current_snapshot.ignition_on)
        # The event path preserves the locked, belted, hot snapshot.
        self.assertEqual(event_session.current_snapshot.lock, LockState.LOCKED)
        self.assertTrue(
            event_session.current_snapshot.rear_seat_belt_buckled
        )
        self.assertEqual(event_session.current_snapshot.cabin_temp_c, 35.5)
        event_session.apply_event(
            SignalEvent(type=SignalEventType.IGNITION_OFF, timestamp=540.0)
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
        self.assertFalse(snapshot_session.current_snapshot.ignition_on)
        self.assertFalse(event_session.current_snapshot.ignition_on)

    def test_unlock_after_ignition_episode_recovers_to_driving(self):
        session = exception_session()

        session.apply_snapshot(with_ignition(session, True, 480.0))
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(history_tuples(session), BASELINE_HISTORY)

        unlocked = dataclasses.replace(
            session.current_snapshot,
            lock=LockState.UNLOCKED,
            timestamp=540.0,
        )
        result = session.apply_snapshot(unlocked)

        self.assertEqual(result, SessionState.DRIVING)
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 7)
        self.assertEqual(
            history_tuples(session)[-2:],
            [
                (
                    SessionState.EXCEPTION,
                    SessionState.ONBOARD,
                    "unlocked_and_ignition_on_after_exception",
                    540.0,
                ),
                (
                    SessionState.ONBOARD,
                    SessionState.DRIVING,
                    "ignition_on",
                    540.0,
                ),
            ],
        )

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")

        report = report_for_session(session)
        self.assertEqual(report.final_state, SessionState.DRIVING)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 7)
        self.assertEqual(report.duration_seconds, 540.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_exception_ignition_episode_then_door_recovery_completes(self):
        session = exception_session()

        session.apply_snapshot(with_ignition(session, True, 480.0))
        session.apply_snapshot(with_ignition(session, False, 540.0))
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(history_tuples(session), BASELINE_HISTORY)

        opened = dataclasses.replace(
            session.current_snapshot,
            rear_door=DoorState.OPEN,
            timestamp=600.0,
        )
        result = session.apply_snapshot(opened)
        self.assertEqual(result, SessionState.ALIGHTING)
        self.assertEqual(len(session.history), 6)
        self.assertEqual(
            session.history[-1].reason,
            "rear_door_opened_after_exception",
        )
        self.assertEqual(session.history[-1].timestamp, 600.0)

        unbuckled = dataclasses.replace(
            session.current_snapshot,
            rear_seat_belt_buckled=False,
            timestamp=660.0,
        )
        result = session.apply_snapshot(unbuckled)
        self.assertEqual(result, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 6)

        closed = dataclasses.replace(
            session.current_snapshot,
            rear_door=DoorState.CLOSED,
            timestamp=720.0,
        )
        result = session.apply_snapshot(closed)
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 7)
        self.assertEqual(session.history[-1].reason, "alighting_confirmed")

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 7)
        self.assertEqual(report.duration_seconds, 720.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.summary, "예외 발생 후 하차 확인 완료")


if __name__ == "__main__":
    unittest.main()

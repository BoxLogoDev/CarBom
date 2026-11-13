"""QA scenarios for cabin temperature input alone while EXCEPTION.

본 파일은 전체 신호를 명시한 스냅샷 기준이다.
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


def snapshot(**overrides):
    values = {
        "rear_door": DoorState.CLOSED,
        "rear_seat_belt_buckled": True,
        "ignition": IgnitionState.OFF,
        "hvac_on": False,
        "cabin_temp_c": None,
        "lock": LockState.LOCKED,
        "timestamp": None,
    }
    values.update(overrides)
    return SignalSnapshot(**values)


def exception_session():
    session = CareSession()
    replay_scenario(session, "forgotten_rising_temp")
    return session


class ExceptionTempQATest(unittest.TestCase):
    def test_exception_temp_alone_stays_exception(self):
        session = exception_session()

        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)
        self.assertTrue(session.passenger_present)
        self.assertEqual(
            session.history[-1].from_state, SessionState.ARRIVED
        )
        self.assertEqual(
            session.history[-1].to_state, SessionState.EXCEPTION
        )
        self.assertEqual(
            session.history[-1].reason,
            "ignition_off_locked_passenger_present",
        )
        self.assertEqual(session.history[-1].timestamp, 240.0)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)

        session.apply_snapshot(
            snapshot(cabin_temp_c=24.0, timestamp=480.0)
        )

        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)
        self.assertTrue(session.passenger_present)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 24.0)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.reason, "passenger_left_locked")
        self.assertEqual(
            guidance.text,
            "잠긴 차량의 뒷좌석에 동승자가 남아 있을 수 있습니다. "
            "뒷좌석을 확인해 주세요.",
        )
        self.assertNotIn("24", guidance.text)

        report = report_for_session(session)
        self.assertEqual(report.final_state, SessionState.EXCEPTION)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.max_cabin_temp_c, 24.0)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_exception_temp_sequence_updates_guidance_and_max(self):
        session = exception_session()

        for cabin_temp_c, timestamp, expected_reason in (
            (24.0, 480.0, "passenger_left_locked"),
            (32.0, 540.0, "passenger_left_locked_hot_cabin"),
            (
                35.5,
                600.0,
                "passenger_left_locked_dangerous_cabin_temp",
            ),
            (28.0, 660.0, "passenger_left_locked"),
        ):
            session.apply_snapshot(
                snapshot(cabin_temp_c=cabin_temp_c, timestamp=timestamp)
            )
            self.assertEqual(session.state, SessionState.EXCEPTION)
            self.assertEqual(len(session.history), 5)
            self.assertTrue(session.passenger_present)
            self.assertEqual(
                session.current_snapshot.cabin_temp_c, cabin_temp_c
            )

            guidance = guidance_for_session(
                session, context=DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.URGENT)
            self.assertEqual(guidance.reason, expected_reason)

            report = report_for_session(session)
            self.assertEqual(report.max_cabin_temp_c, cabin_temp_c)
            self.assertEqual(report.duration_seconds, 240.0)

    def test_exception_temp_escalation_boundaries_all_contexts(self):
        session = exception_session()

        session.apply_snapshot(
            snapshot(cabin_temp_c=31.9, timestamp=480.0)
        )
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.reason, "passenger_left_locked")
        self.assertNotIn("31.9", guidance.text)

        session.apply_snapshot(
            snapshot(cabin_temp_c=32.0, timestamp=540.0)
        )
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason, "passenger_left_locked_hot_cabin"
        )
        self.assertIn("32도", guidance.text)
        self.assertNotIn("즉시", guidance.text)
        self.assertNotIn("위험합니다", guidance.text)

        session.apply_snapshot(
            snapshot(cabin_temp_c=34.9, timestamp=600.0)
        )
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason, "passenger_left_locked_hot_cabin"
        )

        session.apply_snapshot(
            snapshot(cabin_temp_c=35.0, timestamp=660.0)
        )
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason,
            "passenger_left_locked_dangerous_cabin_temp",
        )
        self.assertIn("35도", guidance.text)
        self.assertNotIn("35.0도", guidance.text)
        self.assertIn("위험합니다", guidance.text)
        self.assertIn("즉시", guidance.text)

        for cabin_temp_c, expected_reason in (
            (35.5, "passenger_left_locked_dangerous_cabin_temp"),
            (32.0, "passenger_left_locked_hot_cabin"),
        ):
            context_session = exception_session()
            context_session.apply_snapshot(
                snapshot(cabin_temp_c=cabin_temp_c, timestamp=480.0)
            )
            guidances = [
                guidance_for_session(context_session, context=context)
                for context in (
                    DestinationContext.GENERAL,
                    DestinationContext.DROPOFF,
                    DestinationContext.PICKUP,
                )
            ]
            self.assertEqual(guidances[0].level, GuidanceLevel.URGENT)
            self.assertEqual(guidances[0].reason, expected_reason)
            for context_guidance in guidances[1:]:
                self.assertEqual(
                    context_guidance.level, guidances[0].level
                )
                self.assertEqual(
                    context_guidance.text, guidances[0].text
                )
                self.assertEqual(
                    context_guidance.reason, guidances[0].reason
                )

    def test_exception_temp_event_path_matches_snapshot_path(self):
        snapshot_session = exception_session()
        snapshot_session.apply_snapshot(
            snapshot(cabin_temp_c=32.0, timestamp=480.0)
        )
        snapshot_session.apply_snapshot(
            snapshot(cabin_temp_c=24.0, timestamp=540.0)
        )

        event_session = exception_session()
        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=480.0,
                cabin_temp_c=32.0,
            )
        )
        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=540.0,
                cabin_temp_c=24.0,
            )
        )

        self.assertEqual(event_session.state, snapshot_session.state)
        self.assertEqual(event_session.state, SessionState.EXCEPTION)
        self.assertEqual(
            len(event_session.history), len(snapshot_session.history)
        )
        self.assertEqual(len(event_session.history), 5)
        self.assertEqual(
            [
                (
                    transition.from_state,
                    transition.to_state,
                    transition.reason,
                )
                for transition in event_session.history
            ],
            [
                (
                    transition.from_state,
                    transition.to_state,
                    transition.reason,
                )
                for transition in snapshot_session.history
            ],
        )
        self.assertEqual(
            event_session.current_snapshot,
            snapshot_session.current_snapshot,
        )
        self.assertEqual(event_session.current_snapshot.cabin_temp_c, 24.0)
        self.assertEqual(
            event_session.current_snapshot.rear_door, DoorState.CLOSED
        )
        self.assertTrue(
            event_session.current_snapshot.rear_seat_belt_buckled
        )

        guidance = guidance_for_session(
            event_session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.reason, "passenger_left_locked")

        empty_session = exception_session()
        empty_session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=480.0,
            )
        )
        self.assertEqual(empty_session.state, SessionState.EXCEPTION)
        self.assertEqual(len(empty_session.history), 5)
        self.assertIsNone(empty_session.current_snapshot.cabin_temp_c)
        self.assertIsNone(
            report_for_session(empty_session).max_cabin_temp_c
        )

        empty_guidance = guidance_for_session(
            empty_session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(empty_guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(empty_guidance.reason, "passenger_left_locked")

    def test_exception_temp_episode_then_recovery_completion(self):
        session = exception_session()

        session.apply_snapshot(
            snapshot(cabin_temp_c=24.0, timestamp=480.0)
        )
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                cabin_temp_c=24.0,
                timestamp=540.0,
            )
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertEqual(len(session.history), 6)
        self.assertEqual(
            session.history[-1].reason,
            "rear_door_opened_after_exception",
        )
        self.assertTrue(session.passenger_present)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=False,
                cabin_temp_c=24.0,
                timestamp=600.0,
            )
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertEqual(len(session.history), 6)
        self.assertFalse(session.passenger_present)

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=False,
                cabin_temp_c=24.0,
                lock=LockState.UNLOCKED,
                timestamp=660.0,
            )
        )
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 7)
        self.assertEqual(
            session.history[-1].reason, "alighting_confirmed"
        )

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 7)
        self.assertEqual(report.duration_seconds, 660.0)
        self.assertEqual(report.max_cabin_temp_c, 24.0)
        self.assertEqual(
            report.summary, "예외 발생 후 하차 확인 완료"
        )

    def test_exception_temp_with_belt_ignition_and_lock_signals(self):
        belt_session = exception_session()
        belt_session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=False,
                cabin_temp_c=35.5,
                timestamp=480.0,
            )
        )

        self.assertEqual(belt_session.state, SessionState.EXCEPTION)
        self.assertEqual(len(belt_session.history), 5)
        self.assertTrue(belt_session.passenger_present)

        ignition_session = exception_session()
        ignition_session.apply_snapshot(
            snapshot(
                ignition=IgnitionState.ON,
                cabin_temp_c=35.5,
                timestamp=480.0,
            )
        )

        self.assertEqual(ignition_session.state, SessionState.EXCEPTION)
        self.assertEqual(len(ignition_session.history), 5)
        self.assertTrue(ignition_session.passenger_present)

        unlock_session = exception_session()
        unlock_session.apply_snapshot(
            snapshot(
                cabin_temp_c=35.5,
                lock=LockState.UNLOCKED,
                timestamp=480.0,
            )
        )

        self.assertEqual(unlock_session.state, SessionState.EXCEPTION)
        self.assertEqual(len(unlock_session.history), 5)
        self.assertTrue(unlock_session.passenger_present)

        driving_session = exception_session()
        driving_session.apply_snapshot(
            snapshot(
                ignition=IgnitionState.ON,
                cabin_temp_c=35.5,
                lock=LockState.UNLOCKED,
                timestamp=480.0,
            )
        )

        self.assertEqual(driving_session.state, SessionState.DRIVING)
        self.assertEqual(len(driving_session.history), 7)
        self.assertEqual(
            driving_session.history[-2].from_state,
            SessionState.EXCEPTION,
        )
        self.assertEqual(
            driving_session.history[-2].to_state, SessionState.ONBOARD
        )
        self.assertEqual(
            driving_session.history[-2].reason,
            "unlocked_and_ignition_on_after_exception",
        )
        self.assertEqual(
            driving_session.history[-1].from_state, SessionState.ONBOARD
        )
        self.assertEqual(
            driving_session.history[-1].to_state, SessionState.DRIVING
        )
        self.assertEqual(
            driving_session.history[-1].reason, "ignition_on"
        )

        door_session = exception_session()
        door_session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                cabin_temp_c=35.5,
                timestamp=480.0,
            )
        )

        self.assertEqual(door_session.state, SessionState.ALIGHTING)
        self.assertEqual(len(door_session.history), 6)
        self.assertEqual(
            door_session.history[-1].from_state, SessionState.EXCEPTION
        )
        self.assertEqual(
            door_session.history[-1].to_state, SessionState.ALIGHTING
        )
        self.assertEqual(
            door_session.history[-1].reason,
            "rear_door_opened_after_exception",
        )


if __name__ == "__main__":
    unittest.main()

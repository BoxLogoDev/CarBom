"""QA scenarios for cabin temperature input alone while DRIVING."""

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
    SignalSnapshot,
    guidance_for_session,
    report_for_session,
)
from engine.adapters.simulator import dropoff_normal_snapshots


def snapshot(**overrides):
    values = {
        "rear_door": DoorState.CLOSED,
        "rear_seat_belt_buckled": True,
        "ignition": IgnitionState.ON,
        "hvac_on": False,
        "cabin_temp_c": None,
        "lock": LockState.UNLOCKED,
        "timestamp": None,
    }
    values.update(overrides)
    return SignalSnapshot(**values)


def driving_session():
    session = CareSession()
    for item in dropoff_normal_snapshots()[:3]:
        session.apply_snapshot(item)
    return session


class DrivingTempQATest(unittest.TestCase):
    def test_driving_temp_alone_stays_driving(self):
        session = driving_session()

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)
        self.assertTrue(session.passenger_present)
        self.assertEqual(
            session.history[-1].from_state, SessionState.ONBOARD
        )
        self.assertEqual(
            session.history[-1].to_state, SessionState.DRIVING
        )
        self.assertEqual(session.history[-1].reason, "ignition_on")
        self.assertEqual(session.history[-1].timestamp, 120.0)

        session.apply_snapshot(
            snapshot(cabin_temp_c=24.0, timestamp=150.0)
        )

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)
        self.assertTrue(session.passenger_present)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 24.0)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")
        self.assertEqual(
            guidance.text,
            "안전 운전 중입니다. 운전 중에는 화면을 조작하지 마세요.",
        )

        report = report_for_session(session)
        self.assertEqual(report.final_state, SessionState.DRIVING)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 3)
        self.assertEqual(report.duration_seconds, 120.0)
        self.assertEqual(report.max_cabin_temp_c, 24.0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_driving_temp_sequence_updates_current_and_max(self):
        session = driving_session()

        for cabin_temp_c, timestamp in (
            (24.0, 150.0),
            (32.0, 180.0),
            (35.5, 210.0),
            (28.0, 240.0),
        ):
            session.apply_snapshot(
                snapshot(cabin_temp_c=cabin_temp_c, timestamp=timestamp)
            )
            self.assertEqual(session.state, SessionState.DRIVING)
            self.assertEqual(len(session.history), 3)
            self.assertTrue(session.passenger_present)
            self.assertEqual(
                session.current_snapshot.cabin_temp_c, cabin_temp_c
            )
            self.assertEqual(
                report_for_session(session).max_cabin_temp_c,
                cabin_temp_c,
            )

            guidance = guidance_for_session(
                session, context=DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "driving")

    def test_driving_high_temp_locked_ignition_on_no_exception_all_contexts(
        self,
    ):
        session = driving_session()

        session.apply_snapshot(
            snapshot(cabin_temp_c=35.5, timestamp=150.0)
        )

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertNotEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 3)
        self.assertTrue(session.passenger_present)

        for context in (
            DestinationContext.GENERAL,
            DestinationContext.DROPOFF,
            DestinationContext.PICKUP,
        ):
            context_guidance = guidance_for_session(
                session, context=context
            )
            self.assertEqual(context_guidance.level, GuidanceLevel.INFO)
            self.assertNotEqual(
                context_guidance.level, GuidanceLevel.URGENT
            )
            self.assertEqual(context_guidance.reason, "driving")
            self.assertEqual(
                context_guidance.text,
                "안전 운전 중입니다. 운전 중에는 화면을 조작하지 마세요.",
            )
            self.assertNotIn("35.5", context_guidance.text)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

        locked_session = driving_session()
        locked_session.apply_snapshot(
            snapshot(
                cabin_temp_c=35.5,
                lock=LockState.LOCKED,
                timestamp=150.0,
            )
        )

        self.assertEqual(locked_session.state, SessionState.DRIVING)
        self.assertEqual(len(locked_session.history), 3)
        self.assertTrue(locked_session.passenger_present)
        self.assertEqual(
            report_for_session(locked_session).exception_count, 0
        )

    def test_driving_temp_event_path_matches_snapshot_path(self):
        snapshot_session = driving_session()
        snapshot_session.apply_snapshot(
            snapshot(cabin_temp_c=32.0, timestamp=150.0)
        )
        snapshot_session.apply_snapshot(
            snapshot(cabin_temp_c=35.5, timestamp=180.0)
        )

        event_session = driving_session()
        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=150.0,
                cabin_temp_c=32.0,
            )
        )
        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=180.0,
                cabin_temp_c=35.5,
            )
        )

        self.assertEqual(event_session.state, snapshot_session.state)
        self.assertEqual(
            len(event_session.history), len(snapshot_session.history)
        )
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
            event_session.current_snapshot.cabin_temp_c,
            snapshot_session.current_snapshot.cabin_temp_c,
        )
        self.assertEqual(event_session.current_snapshot.cabin_temp_c, 35.5)
        self.assertTrue(
            event_session.current_snapshot.rear_seat_belt_buckled
        )
        self.assertEqual(
            event_session.current_snapshot.rear_door, DoorState.CLOSED
        )

        empty_session = driving_session()
        empty_session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=150.0,
            )
        )
        self.assertEqual(empty_session.state, SessionState.DRIVING)
        self.assertEqual(len(empty_session.history), 3)
        self.assertIsNone(empty_session.current_snapshot.cabin_temp_c)
        self.assertIsNone(
            report_for_session(empty_session).max_cabin_temp_c
        )

    def test_driving_temp_episode_then_normal_dropoff_completes(self):
        session = CareSession()
        snapshots = dropoff_normal_snapshots()

        for item in snapshots[:2]:
            session.apply_snapshot(item)

        session.apply_snapshot(
            dataclasses.replace(snapshots[2], cabin_temp_c=24.0)
        )
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)
        self.assertEqual(
            report_for_session(session).max_cabin_temp_c, 24.0
        )

        for item in snapshots[3:]:
            session.apply_snapshot(item)

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.max_cabin_temp_c, 24.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_driving_temp_with_ignition_off_arrives_and_locked_exceptions(
        self,
    ):
        session = driving_session()

        session.apply_snapshot(
            snapshot(
                ignition=IgnitionState.OFF,
                cabin_temp_c=24.0,
                timestamp=150.0,
            )
        )

        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)
        self.assertEqual(
            session.history[-1].from_state, SessionState.DRIVING
        )
        self.assertEqual(
            session.history[-1].to_state, SessionState.ARRIVED
        )
        self.assertEqual(session.history[-1].reason, "ignition_off")
        self.assertEqual(session.history[-1].timestamp, 150.0)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(
            guidance.reason, "arrived_dropoff_check_rear_seat"
        )

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 4)
        self.assertEqual(report.duration_seconds, 150.0)
        self.assertEqual(report.max_cabin_temp_c, 24.0)

        locked_session = driving_session()
        locked_session.apply_snapshot(
            snapshot(
                ignition=IgnitionState.OFF,
                cabin_temp_c=35.5,
                lock=LockState.LOCKED,
                timestamp=150.0,
            )
        )

        self.assertEqual(locked_session.state, SessionState.EXCEPTION)
        self.assertEqual(len(locked_session.history), 4)
        self.assertEqual(
            locked_session.history[-1].from_state, SessionState.DRIVING
        )
        self.assertEqual(
            locked_session.history[-1].to_state, SessionState.EXCEPTION
        )
        self.assertEqual(
            locked_session.history[-1].reason,
            "ignition_off_locked_passenger_present",
        )
        self.assertEqual(locked_session.history[-1].timestamp, 150.0)

        locked_guidance = guidance_for_session(
            locked_session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(locked_guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            locked_guidance.reason,
            "passenger_left_locked_dangerous_cabin_temp",
        )
        self.assertIn("35.5도", locked_guidance.text)
        self.assertIn("즉시", locked_guidance.text)

        locked_report = report_for_session(locked_session)
        self.assertEqual(locked_report.exception_count, 1)
        self.assertEqual(locked_report.max_cabin_temp_c, 35.5)
        self.assertEqual(locked_report.summary, "예외 발생 · 하차 미확인")

        belt_session = driving_session()
        belt_session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=False,
                cabin_temp_c=35.5,
                timestamp=150.0,
            )
        )

        self.assertEqual(belt_session.state, SessionState.DRIVING)
        self.assertEqual(len(belt_session.history), 3)
        self.assertTrue(belt_session.passenger_present)


if __name__ == "__main__":
    unittest.main()

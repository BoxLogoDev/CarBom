"""QA scenarios for cabin temperature input alone while ALIGHTING.

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
from engine.adapters.simulator import dropoff_normal_snapshots


def snapshot(**overrides):
    values = {
        "rear_door": DoorState.OPEN,
        "rear_seat_belt_buckled": True,
        "ignition": IgnitionState.OFF,
        "hvac_on": False,
        "cabin_temp_c": None,
        "lock": LockState.UNLOCKED,
        "timestamp": None,
    }
    values.update(overrides)
    return SignalSnapshot(**values)


def alighting_session():
    session = CareSession()
    for item in dropoff_normal_snapshots()[:4]:
        session.apply_snapshot(item)
    session.apply_snapshot(snapshot(timestamp=240.0))
    return session


class AlightingTempQATest(unittest.TestCase):
    def test_alighting_temp_alone_stays_alighting(self):
        session = alighting_session()

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertEqual(len(session.history), 5)
        self.assertTrue(session.passenger_present)
        self.assertNotEqual(
            session.history[-1].from_state, SessionState.DRIVING
        )
        self.assertEqual(
            session.history[-1].from_state, SessionState.ARRIVED
        )
        self.assertEqual(
            session.history[-1].to_state, SessionState.ALIGHTING
        )
        self.assertEqual(
            session.history[-1].reason, "alighting_started"
        )
        self.assertEqual(session.history[-1].timestamp, 240.0)

        session.apply_snapshot(
            snapshot(cabin_temp_c=24.0, timestamp=270.0)
        )

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertEqual(len(session.history), 5)
        self.assertTrue(session.passenger_present)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 24.0)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "alighting")
        self.assertEqual(
            guidance.text,
            "하차 중입니다. 뒷좌석이 비었는지 확인해 주세요.",
        )

        report = report_for_session(session)
        self.assertEqual(report.final_state, SessionState.ALIGHTING)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.max_cabin_temp_c, 24.0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_alighting_temp_sequence_updates_current_and_max(self):
        session = alighting_session()

        for cabin_temp_c, timestamp in (
            (24.0, 270.0),
            (32.0, 300.0),
            (35.5, 330.0),
            (28.0, 360.0),
        ):
            session.apply_snapshot(
                snapshot(cabin_temp_c=cabin_temp_c, timestamp=timestamp)
            )
            self.assertEqual(session.state, SessionState.ALIGHTING)
            self.assertEqual(len(session.history), 5)
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
            self.assertEqual(guidance.reason, "alighting")

    def test_alighting_high_temp_no_exception_all_contexts(self):
        session = alighting_session()

        session.apply_snapshot(
            snapshot(cabin_temp_c=35.5, timestamp=270.0)
        )

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertNotEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)

        for context in (
            DestinationContext.GENERAL,
            DestinationContext.DROPOFF,
            DestinationContext.PICKUP,
        ):
            context_guidance = guidance_for_session(
                session, context=context
            )
            self.assertEqual(context_guidance.level, GuidanceLevel.INFO)
            self.assertEqual(context_guidance.reason, "alighting")
            self.assertEqual(
                context_guidance.text,
                "하차 중입니다. 뒷좌석이 비었는지 확인해 주세요.",
            )
            self.assertNotIn("35.5", context_guidance.text)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

        locked_session = alighting_session()
        locked_session.apply_snapshot(
            snapshot(
                cabin_temp_c=35.5,
                lock=LockState.LOCKED,
                timestamp=270.0,
            )
        )

        self.assertEqual(locked_session.state, SessionState.ALIGHTING)
        self.assertEqual(len(locked_session.history), 5)
        self.assertEqual(
            report_for_session(locked_session).exception_count, 0
        )

    def test_alighting_temp_event_path_matches_snapshot_path(self):
        snapshot_session = alighting_session()
        snapshot_session.apply_snapshot(
            snapshot(cabin_temp_c=32.0, timestamp=270.0)
        )
        snapshot_session.apply_snapshot(
            snapshot(cabin_temp_c=35.5, timestamp=300.0)
        )

        event_session = alighting_session()
        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=270.0,
                cabin_temp_c=32.0,
            )
        )
        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=300.0,
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
        self.assertEqual(
            event_session.current_snapshot.rear_door, DoorState.OPEN
        )
        self.assertTrue(
            event_session.current_snapshot.rear_seat_belt_buckled
        )

        empty_session = alighting_session()
        empty_session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=270.0,
            )
        )
        self.assertEqual(empty_session.state, SessionState.ALIGHTING)
        self.assertEqual(len(empty_session.history), 5)
        self.assertIsNone(empty_session.current_snapshot.cabin_temp_c)
        self.assertIsNone(
            report_for_session(empty_session).max_cabin_temp_c
        )

    def test_alighting_temp_episode_then_normal_completion(self):
        session = CareSession()
        for item in dropoff_normal_snapshots()[:4]:
            session.apply_snapshot(item)

        session.apply_snapshot(
            snapshot(cabin_temp_c=24.0, timestamp=240.0)
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertEqual(len(session.history), 5)
        self.assertEqual(
            report_for_session(session).max_cabin_temp_c, 24.0
        )

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=False,
                cabin_temp_c=24.0,
                timestamp=270.0,
            )
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.CLOSED,
                rear_seat_belt_buckled=False,
                cabin_temp_c=24.0,
                timestamp=300.0,
            )
        )
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        self.assertEqual(
            session.history[-1].reason, "alighting_confirmed"
        )

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.max_cabin_temp_c, 24.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_alighting_temp_with_belt_ignition_and_lock_signals(self):
        belt_session = alighting_session()
        belt_session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=False,
                cabin_temp_c=35.5,
                timestamp=270.0,
            )
        )

        self.assertEqual(belt_session.state, SessionState.ALIGHTING)
        self.assertEqual(len(belt_session.history), 5)
        self.assertFalse(belt_session.passenger_present)

        belt_session.apply_snapshot(
            snapshot(
                rear_door=DoorState.CLOSED,
                rear_seat_belt_buckled=False,
                cabin_temp_c=35.5,
                timestamp=300.0,
            )
        )

        self.assertEqual(belt_session.state, SessionState.COMPLETED)
        self.assertEqual(len(belt_session.history), 6)
        self.assertEqual(
            belt_session.history[-1].reason, "alighting_confirmed"
        )

        belt_report = report_for_session(belt_session)
        self.assertEqual(belt_report.max_cabin_temp_c, 35.5)
        self.assertEqual(belt_report.duration_seconds, 300.0)

        ignition_session = alighting_session()
        ignition_session.apply_snapshot(
            snapshot(
                ignition=IgnitionState.ON,
                cabin_temp_c=35.5,
                timestamp=270.0,
            )
        )

        self.assertEqual(ignition_session.state, SessionState.ALIGHTING)
        self.assertEqual(len(ignition_session.history), 5)
        self.assertTrue(ignition_session.passenger_present)
        self.assertEqual(
            report_for_session(ignition_session).exception_count, 0
        )

        lock_session = alighting_session()
        lock_session.apply_snapshot(
            snapshot(
                rear_door=DoorState.CLOSED,
                lock=LockState.LOCKED,
                cabin_temp_c=35.5,
                timestamp=270.0,
            )
        )

        self.assertEqual(lock_session.state, SessionState.EXCEPTION)
        self.assertEqual(len(lock_session.history), 6)
        self.assertEqual(
            lock_session.history[-1].from_state, SessionState.ALIGHTING
        )
        self.assertEqual(
            lock_session.history[-1].to_state, SessionState.EXCEPTION
        )
        self.assertEqual(
            lock_session.history[-1].reason,
            "ignition_off_locked_passenger_present",
        )

        lock_guidance = guidance_for_session(
            lock_session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(lock_guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            lock_guidance.reason,
            "passenger_left_locked_dangerous_cabin_temp",
        )

        lock_report = report_for_session(lock_session)
        self.assertEqual(lock_report.exception_count, 1)
        self.assertEqual(lock_report.max_cabin_temp_c, 35.5)


if __name__ == "__main__":
    unittest.main()

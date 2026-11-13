"""QA scenarios for cabin temperature input alone while ARRIVED.

본 파일은 전체 신호를 명시한 스냅샷 기준이며, dwell 파일은 부분 스냅샷 기준이다.
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
    SignalSnapshot,
    guidance_for_session,
    report_for_session,
)
from engine.adapters.simulator import dropoff_normal_snapshots


def snapshot(**overrides):
    values = {
        "rear_door": DoorState.CLOSED,
        "rear_seat_belt_buckled": True,
        "ignition": IgnitionState.OFF,
        "hvac_on": False,
        "cabin_temp_c": None,
        "lock": LockState.UNLOCKED,
        "timestamp": None,
    }
    values.update(overrides)
    return SignalSnapshot(**values)


def arrived_session():
    session = CareSession()
    for item in dropoff_normal_snapshots()[:4]:
        session.apply_snapshot(item)
    return session


class ArrivedTempQATest(unittest.TestCase):
    def test_arrived_temp_alone_stays_arrived(self):
        session = arrived_session()

        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)
        self.assertTrue(session.passenger_present)
        self.assertEqual(
            session.history[-1].from_state, SessionState.DRIVING
        )
        self.assertEqual(
            session.history[-1].to_state, SessionState.ARRIVED
        )
        self.assertEqual(session.history[-1].reason, "ignition_off")
        self.assertEqual(session.history[-1].timestamp, 180.0)

        session.apply_snapshot(
            snapshot(cabin_temp_c=24.0, timestamp=210.0)
        )

        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)
        self.assertTrue(session.passenger_present)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 24.0)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(
            guidance.reason, "arrived_dropoff_check_rear_seat"
        )
        self.assertEqual(
            guidance.text,
            "도착했습니다. 등원 하차 전 뒷좌석을 확인해 주세요.",
        )

        report = report_for_session(session)
        self.assertEqual(report.final_state, SessionState.ARRIVED)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 4)
        self.assertEqual(report.duration_seconds, 180.0)
        self.assertEqual(report.max_cabin_temp_c, 24.0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_arrived_temp_sequence_updates_current_and_reasons(self):
        session = arrived_session()

        for cabin_temp_c, timestamp, reason in (
            (24.0, 210.0, "arrived_dropoff_check_rear_seat"),
            (
                32.0,
                240.0,
                "arrived_dropoff_check_rear_seat_hot_cabin",
            ),
            (
                35.5,
                270.0,
                "arrived_dropoff_check_rear_seat_dangerous_cabin_temp",
            ),
            (28.0, 300.0, "arrived_dropoff_check_rear_seat"),
        ):
            session.apply_snapshot(
                snapshot(cabin_temp_c=cabin_temp_c, timestamp=timestamp)
            )
            self.assertEqual(session.state, SessionState.ARRIVED)
            self.assertEqual(len(session.history), 4)
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
            self.assertEqual(guidance.level, GuidanceLevel.REMIND)
            self.assertEqual(guidance.reason, reason)
            if cabin_temp_c == 32.0:
                self.assertIn("실내 온도 32도입니다.", guidance.text)
            if cabin_temp_c == 35.5:
                self.assertIn(
                    "실내 온도 35.5도로 높습니다.", guidance.text
                )
                self.assertIn("즉시", guidance.text)

    def test_arrived_high_temp_unlocked_no_exception_all_contexts(
        self,
    ):
        session = arrived_session()

        session.apply_snapshot(
            snapshot(cabin_temp_c=35.5, timestamp=210.0)
        )

        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertNotEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 4)
        self.assertTrue(session.passenger_present)

        for context, reason, text in (
            (
                DestinationContext.GENERAL,
                "arrived_check_rear_seat_dangerous_cabin_temp",
                "도착했습니다. 하차 전 뒷좌석을 확인해 주세요. "
                "실내 온도 35.5도로 높습니다. "
                "즉시 뒷좌석을 확인해 주세요.",
            ),
            (
                DestinationContext.DROPOFF,
                "arrived_dropoff_check_rear_seat_dangerous_cabin_temp",
                "도착했습니다. 등원 하차 전 뒷좌석을 확인해 주세요. "
                "실내 온도 35.5도로 높습니다. "
                "즉시 뒷좌석을 확인해 주세요.",
            ),
            (
                DestinationContext.PICKUP,
                "arrived_pickup_check_rear_seat_dangerous_cabin_temp",
                "도착했습니다. 하원 하차 전 뒷좌석을 확인해 주세요. "
                "실내 온도 35.5도로 높습니다. "
                "즉시 뒷좌석을 확인해 주세요.",
            ),
        ):
            context_guidance = guidance_for_session(
                session, context=context
            )
            self.assertEqual(context_guidance.level, GuidanceLevel.REMIND)
            self.assertNotEqual(
                context_guidance.level, GuidanceLevel.URGENT
            )
            self.assertEqual(context_guidance.reason, reason)
            self.assertEqual(context_guidance.text, text)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

        locked_session = arrived_session()
        locked_session.apply_snapshot(
            snapshot(
                cabin_temp_c=35.5,
                lock=LockState.LOCKED,
                timestamp=210.0,
            )
        )

        self.assertEqual(locked_session.state, SessionState.EXCEPTION)
        self.assertEqual(len(locked_session.history), 5)
        self.assertEqual(
            locked_session.history[-1].from_state, SessionState.ARRIVED
        )
        self.assertEqual(
            locked_session.history[-1].to_state, SessionState.EXCEPTION
        )
        self.assertEqual(
            locked_session.history[-1].reason,
            "ignition_off_locked_passenger_present",
        )
        self.assertEqual(locked_session.history[-1].timestamp, 210.0)

        locked_guidance = guidance_for_session(
            locked_session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(locked_guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            locked_guidance.reason,
            "passenger_left_locked_dangerous_cabin_temp",
        )
        self.assertEqual(
            report_for_session(locked_session).exception_count, 1
        )

    def test_arrived_temp_event_path_matches_snapshot_path(self):
        snapshot_session = arrived_session()
        snapshot_session.apply_snapshot(
            snapshot(cabin_temp_c=32.0, timestamp=210.0)
        )
        snapshot_session.apply_snapshot(
            snapshot(cabin_temp_c=35.5, timestamp=240.0)
        )

        event_session = arrived_session()
        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=210.0,
                cabin_temp_c=32.0,
            )
        )
        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=240.0,
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

        empty_session = arrived_session()
        empty_session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=210.0,
            )
        )
        self.assertEqual(empty_session.state, SessionState.ARRIVED)
        self.assertEqual(len(empty_session.history), 4)
        self.assertIsNone(empty_session.current_snapshot.cabin_temp_c)
        self.assertIsNone(
            report_for_session(empty_session).max_cabin_temp_c
        )

    def test_arrived_temp_episode_then_normal_dropoff_completes(self):
        session = CareSession()
        snapshots = dropoff_normal_snapshots()

        for item in snapshots[:3]:
            session.apply_snapshot(item)

        session.apply_snapshot(
            dataclasses.replace(snapshots[3], cabin_temp_c=24.0)
        )
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)
        self.assertEqual(
            report_for_session(session).max_cabin_temp_c, 24.0
        )

        for item in snapshots[4:]:
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

    def test_arrived_temp_with_ignition_belt_and_door_signals(self):
        ignition_session = arrived_session()
        ignition_session.apply_snapshot(
            snapshot(
                ignition=IgnitionState.ON,
                cabin_temp_c=35.5,
                timestamp=210.0,
            )
        )

        self.assertEqual(ignition_session.state, SessionState.ARRIVED)
        self.assertEqual(len(ignition_session.history), 4)
        self.assertTrue(ignition_session.passenger_present)

        ignition_guidance = guidance_for_session(
            ignition_session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(ignition_guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(
            ignition_guidance.reason,
            "arrived_dropoff_check_rear_seat_dangerous_cabin_temp",
        )

        ignition_report = report_for_session(ignition_session)
        self.assertEqual(ignition_report.exception_count, 0)
        self.assertEqual(ignition_report.max_cabin_temp_c, 35.5)

        belt_session = arrived_session()
        belt_session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=False,
                cabin_temp_c=35.5,
                timestamp=210.0,
            )
        )

        self.assertEqual(belt_session.state, SessionState.ARRIVED)
        self.assertEqual(len(belt_session.history), 4)
        self.assertTrue(belt_session.passenger_present)

        door_session = arrived_session()
        door_session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                cabin_temp_c=24.0,
                timestamp=210.0,
            )
        )

        self.assertEqual(door_session.state, SessionState.ALIGHTING)
        self.assertEqual(len(door_session.history), 5)
        self.assertEqual(
            door_session.history[-1].from_state, SessionState.ARRIVED
        )
        self.assertEqual(
            door_session.history[-1].to_state, SessionState.ALIGHTING
        )
        self.assertEqual(
            door_session.history[-1].reason, "alighting_started"
        )
        self.assertTrue(door_session.passenger_present)

        door_guidance = guidance_for_session(
            door_session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(door_guidance.level, GuidanceLevel.INFO)
        self.assertEqual(door_guidance.reason, "alighting")

        door_session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=False,
                cabin_temp_c=24.0,
                timestamp=240.0,
            )
        )
        self.assertEqual(door_session.state, SessionState.ALIGHTING)
        self.assertEqual(len(door_session.history), 5)
        self.assertFalse(door_session.passenger_present)

        door_session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=False,
                cabin_temp_c=24.0,
                timestamp=270.0,
            )
        )
        self.assertEqual(door_session.state, SessionState.COMPLETED)
        self.assertEqual(len(door_session.history), 6)
        self.assertEqual(
            door_session.history[-1].reason, "alighting_confirmed"
        )

        door_report = report_for_session(door_session)
        self.assertTrue(door_report.completed)
        self.assertEqual(door_report.exception_count, 0)
        self.assertEqual(door_report.transition_count, 6)
        self.assertEqual(door_report.duration_seconds, 270.0)
        self.assertEqual(door_report.max_cabin_temp_c, 24.0)
        self.assertEqual(
            door_report.summary, "하차 확인 완료 · 예외 없음"
        )


if __name__ == "__main__":
    unittest.main()

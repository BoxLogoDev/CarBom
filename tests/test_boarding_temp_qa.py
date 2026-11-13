"""QA scenarios for cabin temperature input alone while BOARDING."""

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
        "rear_seat_belt_buckled": False,
        "ignition": IgnitionState.OFF,
        "hvac_on": False,
        "cabin_temp_c": None,
        "lock": LockState.UNLOCKED,
        "timestamp": None,
    }
    values.update(overrides)
    return SignalSnapshot(**values)


class BoardingTempQATest(unittest.TestCase):
    def test_boarding_temp_alone_stays_boarding(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)
        self.assertEqual(session.history[0].reason, "rear_door_opened")
        self.assertFalse(session.passenger_present)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                cabin_temp_c=24.0,
                timestamp=60.0,
            )
        )

        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)
        self.assertFalse(session.passenger_present)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 24.0)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "boarding_dropoff")
        self.assertEqual(
            guidance.text,
            "등원 준비 중입니다. 뒷좌석 승차와 안전벨트를 확인해 주세요.",
        )

        report = report_for_session(session)
        self.assertEqual(report.final_state, SessionState.BOARDING)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 1)
        self.assertEqual(report.duration_seconds, 0.0)
        self.assertEqual(report.max_cabin_temp_c, 24.0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_boarding_temp_sequence_updates_current_and_max(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)

        for cabin_temp_c, timestamp in (
            (24.0, 60.0),
            (32.0, 120.0),
            (35.5, 180.0),
            (28.0, 240.0),
        ):
            session.apply_snapshot(
                snapshot(
                    rear_door=DoorState.OPEN,
                    cabin_temp_c=cabin_temp_c,
                    timestamp=timestamp,
                )
            )
            self.assertEqual(session.state, SessionState.BOARDING)
            self.assertEqual(len(session.history), 1)
            self.assertEqual(
                session.current_snapshot.cabin_temp_c, cabin_temp_c
            )
            self.assertEqual(
                report_for_session(session).max_cabin_temp_c,
                cabin_temp_c,
            )

    def test_boarding_high_temp_without_passenger_no_exception(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                cabin_temp_c=35.5,
                timestamp=60.0,
            )
        )

        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertNotEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 1)
        self.assertFalse(session.passenger_present)

        for context, reason in (
            (DestinationContext.GENERAL, "boarding"),
            (DestinationContext.DROPOFF, "boarding_dropoff"),
            (DestinationContext.PICKUP, "boarding_pickup"),
        ):
            context_guidance = guidance_for_session(
                session, context=context
            )
            self.assertEqual(context_guidance.level, GuidanceLevel.INFO)
            self.assertNotEqual(
                context_guidance.level, GuidanceLevel.URGENT
            )
            self.assertEqual(context_guidance.reason, reason)
            self.assertNotIn("35.5", context_guidance.text)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

        locked_session = CareSession()
        locked_session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )
        locked_session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                cabin_temp_c=35.5,
                lock=LockState.LOCKED,
                timestamp=60.0,
            )
        )

        self.assertEqual(locked_session.state, SessionState.BOARDING)
        self.assertEqual(
            report_for_session(locked_session).exception_count, 0
        )

    def test_boarding_temp_event_path_matches_snapshot_path(self):
        snapshot_session = CareSession()
        snapshot_session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )
        snapshot_session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                cabin_temp_c=32.0,
                timestamp=60.0,
            )
        )
        snapshot_session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                cabin_temp_c=35.5,
                timestamp=120.0,
            )
        )

        event_session = CareSession()
        event_session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )
        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=60.0,
                cabin_temp_c=32.0,
            )
        )
        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=120.0,
                cabin_temp_c=35.5,
            )
        )

        self.assertEqual(event_session.state, snapshot_session.state)
        self.assertEqual(
            len(event_session.history), len(snapshot_session.history)
        )
        self.assertEqual(
            event_session.current_snapshot.cabin_temp_c,
            snapshot_session.current_snapshot.cabin_temp_c,
        )
        self.assertEqual(
            event_session.current_snapshot.rear_door, DoorState.OPEN
        )

        empty_session = CareSession()
        empty_session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )
        empty_session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=60.0,
            )
        )
        self.assertIsNone(empty_session.current_snapshot.cabin_temp_c)
        self.assertIsNone(
            report_for_session(empty_session).max_cabin_temp_c
        )

    def test_boarding_temp_episode_then_normal_dropoff_completes(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                cabin_temp_c=24.0,
                timestamp=0.0,
            )
        )
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)

        for item in dropoff_normal_snapshots(start=60.0):
            session.apply_snapshot(item)

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 360.0)
        self.assertEqual(report.max_cabin_temp_c, 24.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_boarding_temp_with_belt_stays_then_door_close_onboard_and_close_without_passenger_returns_idle(
        self,
    ):
        session = CareSession()

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                cabin_temp_c=24.0,
                timestamp=60.0,
            )
        )

        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)
        self.assertTrue(session.passenger_present)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.CLOSED,
                rear_seat_belt_buckled=True,
                cabin_temp_c=24.0,
                timestamp=120.0,
            )
        )

        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertEqual(len(session.history), 2)
        self.assertEqual(
            session.history[-1].reason, "passenger_onboard"
        )

        idle_session = CareSession()
        idle_session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )
        idle_session.apply_snapshot(
            snapshot(
                rear_door=DoorState.CLOSED,
                cabin_temp_c=35.5,
                timestamp=60.0,
            )
        )

        self.assertEqual(idle_session.state, SessionState.IDLE)
        self.assertEqual(len(idle_session.history), 2)
        self.assertEqual(
            idle_session.history[-1].reason,
            "boarding_without_passenger",
        )

        guidance = guidance_for_session(idle_session)
        self.assertEqual(guidance.level, GuidanceLevel.NONE)
        self.assertEqual(guidance.reason, "idle")


if __name__ == "__main__":
    unittest.main()

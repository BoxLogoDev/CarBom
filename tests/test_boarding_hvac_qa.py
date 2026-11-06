"""QA scenarios for HVAC input alone while BOARDING."""

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


class BoardingHvacQATest(unittest.TestCase):
    def test_boarding_hvac_on_alone_stays_boarding(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                hvac_on=True,
                cabin_temp_c=24.0,
                timestamp=10.0,
            )
        )

        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)
        self.assertFalse(session.passenger_present)
        self.assertTrue(session.current_snapshot.hvac_on)

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

        event_session = CareSession()
        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.REAR_DOOR_OPENED, timestamp=0.0
            )
        )
        event_session.apply_event(
            SignalEvent(type=SignalEventType.HVAC_ON, timestamp=10.0)
        )
        self.assertEqual(event_session.state, SessionState.BOARDING)
        self.assertEqual(len(event_session.history), 1)
        self.assertTrue(event_session.current_snapshot.hvac_on)

    def test_boarding_hvac_repeated_is_idempotent_and_toggles_off(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )

        for timestamp in (10.0, 20.0):
            session.apply_snapshot(
                snapshot(
                    rear_door=DoorState.OPEN,
                    hvac_on=True,
                    timestamp=timestamp,
                )
            )
            self.assertEqual(session.state, SessionState.BOARDING)
            self.assertEqual(len(session.history), 1)
            self.assertTrue(session.current_snapshot.hvac_on)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                hvac_on=False,
                timestamp=30.0,
            )
        )
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)
        self.assertFalse(session.current_snapshot.hvac_on)

        event_session = CareSession()
        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.REAR_DOOR_OPENED, timestamp=0.0
            )
        )
        event_session.apply_event(
            SignalEvent(type=SignalEventType.HVAC_ON, timestamp=10.0)
        )
        self.assertTrue(event_session.current_snapshot.hvac_on)

        event_session.apply_event(
            SignalEvent(type=SignalEventType.HVAC_OFF, timestamp=20.0)
        )
        self.assertEqual(event_session.state, SessionState.BOARDING)
        self.assertEqual(len(event_session.history), 1)
        self.assertFalse(event_session.current_snapshot.hvac_on)

    def test_boarding_hvac_on_high_temp_locked_without_passenger_no_exception(
        self,
    ):
        session = CareSession()

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                hvac_on=True,
                cabin_temp_c=35.5,
                lock=LockState.LOCKED,
                timestamp=10.0,
            )
        )

        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)
        self.assertFalse(session.passenger_present)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertNotEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.reason, "boarding_dropoff")

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_boarding_hvac_episode_then_normal_dropoff_completes(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                hvac_on=True,
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
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_boarding_hvac_on_belt_buckled_stays_boarding_then_door_close_onboard(
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
                hvac_on=True,
                cabin_temp_c=24.0,
                timestamp=10.0,
            )
        )

        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)
        self.assertTrue(session.passenger_present)

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                hvac_on=True,
                timestamp=20.0,
            )
        )

        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertEqual(len(session.history), 2)
        self.assertEqual(
            session.history[-1].reason, "passenger_onboard"
        )

    def test_boarding_hvac_event_path_matches_snapshot_path(self):
        snapshot_session = CareSession()
        snapshot_session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )
        snapshot_session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                hvac_on=True,
                timestamp=10.0,
            )
        )

        event_session = CareSession()
        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.REAR_DOOR_OPENED, timestamp=0.0
            )
        )
        event_session.apply_event(
            SignalEvent(type=SignalEventType.HVAC_ON, timestamp=10.0)
        )

        self.assertEqual(snapshot_session.state, SessionState.BOARDING)
        self.assertEqual(event_session.state, SessionState.BOARDING)
        self.assertEqual(
            [
                (
                    transition.from_state,
                    transition.to_state,
                    transition.reason,
                    transition.timestamp,
                )
                for transition in snapshot_session.history
            ],
            [
                (
                    transition.from_state,
                    transition.to_state,
                    transition.reason,
                    transition.timestamp,
                )
                for transition in event_session.history
            ],
        )
        self.assertTrue(snapshot_session.current_snapshot.hvac_on)
        self.assertTrue(event_session.current_snapshot.hvac_on)


if __name__ == "__main__":
    unittest.main()

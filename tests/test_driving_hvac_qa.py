"""QA scenarios for HVAC input alone while DRIVING."""

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


def driving_session():
    session = CareSession()
    for item in dropoff_normal_snapshots()[:3]:
        session.apply_snapshot(item)
    return session


class DrivingHvacQATest(unittest.TestCase):
    def test_driving_hvac_on_alone_stays_driving(self):
        session = driving_session()

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)
        self.assertTrue(session.passenger_present)
        self.assertEqual(
            [
                (
                    transition.from_state,
                    transition.to_state,
                    transition.reason,
                    transition.timestamp,
                )
                for transition in session.history
            ],
            [
                (
                    SessionState.IDLE,
                    SessionState.BOARDING,
                    "rear_door_opened",
                    0.0,
                ),
                (
                    SessionState.BOARDING,
                    SessionState.ONBOARD,
                    "passenger_onboard",
                    60.0,
                ),
                (
                    SessionState.ONBOARD,
                    SessionState.DRIVING,
                    "ignition_on",
                    120.0,
                ),
            ],
        )

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                hvac_on=True,
                cabin_temp_c=24.0,
                timestamp=180.0,
            )
        )

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)
        self.assertTrue(session.passenger_present)
        self.assertTrue(session.current_snapshot.hvac_on)

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

    def test_driving_hvac_repeated_is_idempotent_and_toggles_off(self):
        session = driving_session()

        for timestamp in (180.0, 190.0):
            session.apply_snapshot(
                snapshot(
                    rear_seat_belt_buckled=True,
                    ignition=IgnitionState.ON,
                    hvac_on=True,
                    timestamp=timestamp,
                )
            )
            self.assertEqual(session.state, SessionState.DRIVING)
            self.assertEqual(len(session.history), 3)
            self.assertTrue(session.current_snapshot.hvac_on)

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                hvac_on=False,
                timestamp=200.0,
            )
        )
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)
        self.assertFalse(session.current_snapshot.hvac_on)

    def test_driving_hvac_on_high_temp_no_exception(self):
        session = driving_session()

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                hvac_on=True,
                cabin_temp_c=35.5,
                lock=LockState.UNLOCKED,
                timestamp=180.0,
            )
        )

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)
        self.assertTrue(session.passenger_present)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertNotEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.reason, "driving")

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_driving_hvac_episode_then_normal_dropoff_completes(self):
        session = driving_session()

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                hvac_on=True,
                cabin_temp_c=24.0,
                timestamp=150.0,
            )
        )
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)

        for item in dropoff_normal_snapshots()[3:]:
            session.apply_snapshot(item)

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_driving_hvac_event_path_matches_snapshot_path(self):
        snapshot_session = driving_session()
        snapshot_session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                hvac_on=True,
                timestamp=180.0,
            )
        )
        self.assertTrue(snapshot_session.current_snapshot.hvac_on)
        snapshot_session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                hvac_on=False,
                timestamp=190.0,
            )
        )

        event_session = CareSession()
        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.REAR_DOOR_OPENED, timestamp=0.0
            )
        )
        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.REAR_BELT_BUCKLED, timestamp=10.0
            )
        )
        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.REAR_DOOR_CLOSED, timestamp=20.0
            )
        )
        event_session.apply_event(
            SignalEvent(type=SignalEventType.IGNITION_ON, timestamp=30.0)
        )
        self.assertEqual(event_session.state, SessionState.DRIVING)
        self.assertEqual(len(event_session.history), 3)

        event_session.apply_event(
            SignalEvent(type=SignalEventType.HVAC_ON, timestamp=40.0)
        )
        self.assertTrue(event_session.current_snapshot.hvac_on)

        event_session.apply_event(
            SignalEvent(type=SignalEventType.HVAC_OFF, timestamp=50.0)
        )

        self.assertEqual(snapshot_session.state, SessionState.DRIVING)
        self.assertEqual(event_session.state, SessionState.DRIVING)
        self.assertEqual(len(snapshot_session.history), 3)
        self.assertEqual(len(event_session.history), 3)
        self.assertEqual(
            [
                (
                    transition.from_state,
                    transition.to_state,
                    transition.reason,
                )
                for transition in snapshot_session.history
            ],
            [
                (
                    transition.from_state,
                    transition.to_state,
                    transition.reason,
                )
                for transition in event_session.history
            ],
        )
        self.assertFalse(snapshot_session.current_snapshot.hvac_on)
        self.assertFalse(event_session.current_snapshot.hvac_on)

    def test_driving_hvac_on_then_ignition_off_arrives(self):
        session = driving_session()

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                hvac_on=True,
                cabin_temp_c=24.0,
                timestamp=150.0,
            )
        )
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)
        self.assertTrue(session.current_snapshot.hvac_on)

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.OFF,
                hvac_on=True,
                cabin_temp_c=24.0,
                timestamp=180.0,
            )
        )

        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)
        self.assertTrue(session.current_snapshot.hvac_on)
        self.assertEqual(session.history[-1].reason, "ignition_off")
        self.assertEqual(
            session.history[-1].from_state, SessionState.DRIVING
        )
        self.assertEqual(
            session.history[-1].to_state, SessionState.ARRIVED
        )

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(
            guidance.reason, "arrived_dropoff_check_rear_seat"
        )

        report = report_for_session(session)
        self.assertEqual(report.final_state, SessionState.ARRIVED)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 4)
        self.assertEqual(report.duration_seconds, 180.0)
        self.assertEqual(report.max_cabin_temp_c, 24.0)


if __name__ == "__main__":
    unittest.main()

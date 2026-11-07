"""QA scenarios for HVAC input alone while ONBOARD."""

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


def onboard_session():
    session = CareSession()
    for item in dropoff_normal_snapshots()[:2]:
        session.apply_snapshot(item)
    return session


class OnboardHvacQATest(unittest.TestCase):
    def test_onboard_hvac_on_alone_stays_onboard(self):
        session = onboard_session()

        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertEqual(len(session.history), 2)
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
            ],
        )

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                hvac_on=True,
                cabin_temp_c=24.0,
                timestamp=90.0,
            )
        )

        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertEqual(len(session.history), 2)
        self.assertTrue(session.passenger_present)
        self.assertTrue(session.current_snapshot.hvac_on)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "passenger_onboard")
        self.assertEqual(
            guidance.text,
            "뒷좌석 승차가 확인되었습니다. 출발 전 안전벨트를 확인해 주세요.",
        )

        report = report_for_session(session)
        self.assertEqual(report.final_state, SessionState.ONBOARD)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 2)
        self.assertEqual(report.duration_seconds, 60.0)
        self.assertEqual(report.max_cabin_temp_c, 24.0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_onboard_hvac_repeated_is_idempotent_and_toggles_off(self):
        session = onboard_session()

        for timestamp in (90.0, 100.0):
            session.apply_snapshot(
                snapshot(
                    rear_seat_belt_buckled=True,
                    hvac_on=True,
                    timestamp=timestamp,
                )
            )
            self.assertEqual(session.state, SessionState.ONBOARD)
            self.assertEqual(len(session.history), 2)
            self.assertTrue(session.current_snapshot.hvac_on)

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                hvac_on=False,
                timestamp=110.0,
            )
        )
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertEqual(len(session.history), 2)
        self.assertFalse(session.current_snapshot.hvac_on)

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
        self.assertEqual(event_session.state, SessionState.ONBOARD)
        self.assertEqual(len(event_session.history), 2)

        event_session.apply_event(
            SignalEvent(type=SignalEventType.HVAC_ON, timestamp=30.0)
        )
        self.assertTrue(event_session.current_snapshot.hvac_on)

        event_session.apply_event(
            SignalEvent(type=SignalEventType.HVAC_OFF, timestamp=40.0)
        )
        self.assertEqual(event_session.state, SessionState.ONBOARD)
        self.assertEqual(len(event_session.history), 2)
        self.assertFalse(event_session.current_snapshot.hvac_on)

    def test_onboard_hvac_on_high_temp_unlocked_no_exception(self):
        session = onboard_session()

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                hvac_on=True,
                cabin_temp_c=35.5,
                lock=LockState.UNLOCKED,
                timestamp=90.0,
            )
        )

        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertEqual(len(session.history), 2)
        self.assertTrue(session.passenger_present)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertNotEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.reason, "passenger_onboard")

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_onboard_hvac_episode_then_normal_dropoff_completes(self):
        session = onboard_session()

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                hvac_on=True,
                cabin_temp_c=24.0,
                timestamp=90.0,
            )
        )
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertEqual(len(session.history), 2)

        for item in dropoff_normal_snapshots()[2:]:
            session.apply_snapshot(item)

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_onboard_hvac_on_with_ignition_on_still_departs(self):
        session = onboard_session()

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                hvac_on=True,
                ignition=IgnitionState.ON,
                timestamp=90.0,
            )
        )

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)
        self.assertTrue(session.current_snapshot.hvac_on)
        self.assertEqual(session.history[-1].reason, "ignition_on")
        self.assertEqual(
            session.history[-1].from_state, SessionState.ONBOARD
        )
        self.assertEqual(
            session.history[-1].to_state, SessionState.DRIVING
        )

    def test_onboard_hvac_event_path_matches_snapshot_path(self):
        snapshot_session = onboard_session()
        snapshot_session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                hvac_on=True,
                timestamp=90.0,
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
            SignalEvent(type=SignalEventType.HVAC_ON, timestamp=30.0)
        )

        self.assertEqual(snapshot_session.state, SessionState.ONBOARD)
        self.assertEqual(event_session.state, SessionState.ONBOARD)
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
        self.assertTrue(snapshot_session.current_snapshot.hvac_on)
        self.assertTrue(event_session.current_snapshot.hvac_on)


if __name__ == "__main__":
    unittest.main()

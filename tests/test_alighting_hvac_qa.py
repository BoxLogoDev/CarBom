"""QA scenarios for HVAC input alone while ALIGHTING."""

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


def alighting_session_gone():
    session = CareSession()
    for item in dropoff_normal_snapshots()[:5]:
        session.apply_snapshot(item)
    return session


def alighting_session_present():
    session = CareSession()
    for item in dropoff_normal_snapshots()[:4]:
        session.apply_snapshot(item)
    session.apply_snapshot(
        SignalSnapshot(
            rear_door=DoorState.OPEN,
            rear_seat_belt_buckled=True,
            timestamp=240.0,
        )
    )
    return session


class AlightingHvacQATest(unittest.TestCase):
    def test_alighting_hvac_on_alone_stays_alighting(self):
        session = alighting_session_gone()

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 5)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=False,
                hvac_on=True,
                cabin_temp_c=24.0,
                timestamp=300.0,
            )
        )

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertEqual(len(session.history), 5)
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
                (
                    SessionState.DRIVING,
                    SessionState.ARRIVED,
                    "ignition_off",
                    180.0,
                ),
                (
                    SessionState.ARRIVED,
                    SessionState.ALIGHTING,
                    "alighting_started",
                    240.0,
                ),
            ],
        )
        self.assertFalse(session.passenger_present)
        self.assertTrue(session.current_snapshot.hvac_on)

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

    def test_alighting_hvac_repeated_is_idempotent_and_toggles_off(self):
        session = alighting_session_gone()

        for timestamp in (300.0, 310.0):
            session.apply_snapshot(
                snapshot(
                    rear_door=DoorState.OPEN,
                    hvac_on=True,
                    timestamp=timestamp,
                )
            )
            self.assertEqual(session.state, SessionState.ALIGHTING)
            self.assertEqual(len(session.history), 5)
            self.assertTrue(session.current_snapshot.hvac_on)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                hvac_on=False,
                timestamp=320.0,
            )
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertEqual(len(session.history), 5)
        self.assertFalse(session.current_snapshot.hvac_on)

    def test_alighting_hvac_on_high_temp_no_escalation_no_exception(self):
        session = alighting_session_present()

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 5)
        self.assertEqual(session.history[-1].reason, "alighting_started")

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                hvac_on=True,
                cabin_temp_c=35.5,
                lock=LockState.UNLOCKED,
                timestamp=300.0,
            )
        )

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertEqual(len(session.history), 5)
        self.assertTrue(session.passenger_present)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertNotEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertNotEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(guidance.reason, "alighting")
        self.assertNotIn("35.5도", guidance.text)
        self.assertNotIn("즉시", guidance.text)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_alighting_hvac_episode_then_normal_dropoff_completes(self):
        session = alighting_session_gone()

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                hvac_on=True,
                cabin_temp_c=24.0,
                timestamp=270.0,
            )
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertEqual(len(session.history), 5)

        for item in dropoff_normal_snapshots()[5:]:
            session.apply_snapshot(item)

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_alighting_hvac_event_path_matches_snapshot_path(self):
        snapshot_session = alighting_session_present()
        snapshot_session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                hvac_on=True,
                timestamp=300.0,
            )
        )
        self.assertTrue(snapshot_session.current_snapshot.hvac_on)
        snapshot_session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                hvac_on=False,
                timestamp=310.0,
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
            SignalEvent(type=SignalEventType.IGNITION_OFF, timestamp=40.0)
        )
        self.assertEqual(event_session.state, SessionState.ARRIVED)
        self.assertEqual(len(event_session.history), 4)

        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.REAR_DOOR_OPENED, timestamp=50.0
            )
        )
        self.assertEqual(event_session.state, SessionState.ALIGHTING)
        self.assertEqual(len(event_session.history), 5)

        event_session.apply_event(
            SignalEvent(type=SignalEventType.HVAC_ON, timestamp=60.0)
        )
        self.assertTrue(event_session.current_snapshot.hvac_on)

        event_session.apply_event(
            SignalEvent(type=SignalEventType.HVAC_OFF, timestamp=70.0)
        )

        self.assertEqual(snapshot_session.state, SessionState.ALIGHTING)
        self.assertEqual(event_session.state, SessionState.ALIGHTING)
        self.assertEqual(len(snapshot_session.history), 5)
        self.assertEqual(len(event_session.history), 5)
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

    def test_alighting_hvac_on_then_door_close_completes_with_hvac_on(self):
        session = alighting_session_gone()

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                hvac_on=True,
                cabin_temp_c=24.0,
                timestamp=300.0,
            )
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertEqual(len(session.history), 5)
        self.assertTrue(session.current_snapshot.hvac_on)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.CLOSED,
                rear_seat_belt_buckled=False,
                hvac_on=True,
                timestamp=360.0,
            )
        )

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        self.assertEqual(
            session.history[-1].from_state, SessionState.ALIGHTING
        )
        self.assertEqual(
            session.history[-1].to_state, SessionState.COMPLETED
        )
        self.assertEqual(session.history[-1].reason, "alighting_confirmed")
        self.assertTrue(session.current_snapshot.hvac_on)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 360.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")


if __name__ == "__main__":
    unittest.main()

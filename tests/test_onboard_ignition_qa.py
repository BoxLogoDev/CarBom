"""QA scenarios for ignition input alone while ONBOARD."""

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


def onboard_event_session():
    session = CareSession()
    session.apply_event(
        SignalEvent(type=SignalEventType.REAR_DOOR_OPENED, timestamp=0.0)
    )
    session.apply_event(
        SignalEvent(type=SignalEventType.REAR_BELT_BUCKLED, timestamp=10.0)
    )
    session.apply_event(
        SignalEvent(type=SignalEventType.REAR_DOOR_CLOSED, timestamp=20.0)
    )
    return session


class OnboardIgnitionQATest(unittest.TestCase):
    def test_onboard_ignition_on_alone_departs_to_driving(self):
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
                ignition=IgnitionState.ON,
                cabin_temp_c=24.0,
                timestamp=90.0,
            )
        )

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)
        self.assertTrue(session.passenger_present)
        self.assertTrue(session.current_snapshot.ignition_on)
        last = session.history[-1]
        self.assertEqual(
            (last.from_state, last.to_state, last.reason, last.timestamp),
            (
                SessionState.ONBOARD,
                SessionState.DRIVING,
                "ignition_on",
                90.0,
            ),
        )

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
        self.assertEqual(report.duration_seconds, 90.0)
        self.assertEqual(report.max_cabin_temp_c, 24.0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

        event_session = onboard_event_session()
        self.assertEqual(event_session.state, SessionState.ONBOARD)
        self.assertEqual(len(event_session.history), 2)

        event_session.apply_event(
            SignalEvent(type=SignalEventType.IGNITION_ON, timestamp=30.0)
        )
        self.assertEqual(event_session.state, SessionState.DRIVING)
        self.assertEqual(len(event_session.history), 3)
        self.assertTrue(event_session.current_snapshot.ignition_on)

    def test_onboard_ignition_off_alone_stays_onboard(self):
        session = onboard_session()

        for timestamp in (90.0, 100.0):
            session.apply_snapshot(
                snapshot(
                    rear_seat_belt_buckled=True,
                    ignition=IgnitionState.OFF,
                    cabin_temp_c=24.0,
                    timestamp=timestamp,
                )
            )
            self.assertEqual(session.state, SessionState.ONBOARD)
            self.assertEqual(len(session.history), 2)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "passenger_onboard")

        report = report_for_session(session)
        self.assertEqual(report.transition_count, 2)
        self.assertEqual(report.duration_seconds, 60.0)
        self.assertEqual(report.max_cabin_temp_c, 24.0)

        event_session = onboard_event_session()
        event_session.apply_event(
            SignalEvent(type=SignalEventType.IGNITION_OFF, timestamp=30.0)
        )
        self.assertEqual(event_session.state, SessionState.ONBOARD)
        self.assertEqual(len(event_session.history), 2)

    def test_onboard_ignition_on_high_temp_locked_still_drives_no_exception(
        self,
    ):
        session = onboard_session()

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                cabin_temp_c=35.5,
                lock=LockState.LOCKED,
                timestamp=90.0,
            )
        )

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertNotEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.reason, "driving")
        self.assertNotIn("35.5", guidance.text)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_onboard_ignition_on_repeated_idempotent_then_off_arrives(self):
        session = onboard_session()

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                timestamp=90.0,
            )
        )
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                timestamp=100.0,
            )
        )
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.OFF,
                timestamp=110.0,
            )
        )
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)
        self.assertEqual(session.history[-1].reason, "ignition_off")

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(
            guidance.reason, "arrived_dropoff_check_rear_seat"
        )

        report = report_for_session(session)
        self.assertEqual(report.transition_count, 4)
        self.assertEqual(report.duration_seconds, 110.0)

    def test_onboard_ignition_episode_then_normal_dropoff_completes(self):
        session = onboard_session()

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                cabin_temp_c=24.0,
                timestamp=90.0,
            )
        )
        self.assertEqual(session.state, SessionState.DRIVING)

        for item in dropoff_normal_snapshots()[3:]:
            session.apply_snapshot(item)

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        self.assertEqual(
            [transition.reason for transition in session.history],
            [
                "rear_door_opened",
                "passenger_onboard",
                "ignition_on",
                "ignition_off",
                "alighting_started",
                "alighting_confirmed",
            ],
        )

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.max_cabin_temp_c, 24.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_onboard_ignition_on_with_belt_unbuckled_keeps_passenger_latch(
        self,
    ):
        session = onboard_session()

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=False,
                ignition=IgnitionState.ON,
                timestamp=90.0,
            )
        )

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)
        self.assertEqual(session.history[-1].reason, "ignition_on")
        self.assertTrue(session.passenger_present)
        self.assertFalse(session.current_snapshot.rear_seat_belt_buckled)
        self.assertTrue(session.current_snapshot.ignition_on)


if __name__ == "__main__":
    unittest.main()

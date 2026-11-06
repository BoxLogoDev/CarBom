"""QA scenarios for ignition-on input while BOARDING."""

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


class BoardingIgnitionQATest(unittest.TestCase):
    def test_boarding_ignition_on_alone_stays_boarding(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                ignition=IgnitionState.ON,
                cabin_temp_c=24.0,
                timestamp=60.0,
            )
        )

        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)
        self.assertFalse(session.passenger_present)
        self.assertTrue(session.current_snapshot.ignition_on)

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
            SignalEvent(type=SignalEventType.IGNITION_ON, timestamp=60.0)
        )
        self.assertEqual(event_session.state, SessionState.BOARDING)
        self.assertEqual(len(event_session.history), 1)
        self.assertTrue(event_session.current_snapshot.ignition_on)

    def test_boarding_ignition_repeated_is_idempotent_and_toggles_off(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )

        for timestamp in (60.0, 120.0):
            session.apply_snapshot(
                snapshot(
                    rear_door=DoorState.OPEN,
                    ignition=IgnitionState.ON,
                    timestamp=timestamp,
                )
            )
            self.assertEqual(session.state, SessionState.BOARDING)
            self.assertEqual(len(session.history), 1)
            self.assertTrue(session.current_snapshot.ignition_on)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                ignition=IgnitionState.OFF,
                timestamp=180.0,
            )
        )
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)
        self.assertFalse(session.current_snapshot.ignition_on)

        event_session = CareSession()
        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.REAR_DOOR_OPENED, timestamp=0.0
            )
        )
        event_session.apply_event(
            SignalEvent(type=SignalEventType.IGNITION_ON, timestamp=60.0)
        )
        self.assertTrue(event_session.current_snapshot.ignition_on)

        event_session.apply_event(
            SignalEvent(type=SignalEventType.IGNITION_OFF, timestamp=180.0)
        )
        self.assertEqual(event_session.state, SessionState.BOARDING)
        self.assertEqual(len(event_session.history), 1)
        self.assertFalse(event_session.current_snapshot.ignition_on)

    def test_boarding_ignition_on_high_temp_locked_no_exception(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                ignition=IgnitionState.ON,
                cabin_temp_c=35.5,
                lock=LockState.LOCKED,
                timestamp=60.0,
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
        self.assertNotIn("온도", guidance.text)
        self.assertNotIn("35.5", guidance.text)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_boarding_ignition_with_belt_stays_then_door_close_drives(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                timestamp=60.0,
            )
        )
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)
        self.assertTrue(session.passenger_present)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                timestamp=120.0,
            )
        )
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)
        self.assertTrue(session.passenger_present)
        self.assertTrue(session.current_snapshot.ignition_on)

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                timestamp=180.0,
            )
        )

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)
        self.assertEqual(
            [transition.reason for transition in session.history],
            ["rear_door_opened", "passenger_onboard", "ignition_on"],
        )
        self.assertEqual(session.history[-2].timestamp, 180.0)
        self.assertEqual(session.history[-1].timestamp, 180.0)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")

    def test_boarding_ignition_door_closed_without_passenger_returns_idle(
        self,
    ):
        session = CareSession()

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )
        self.assertEqual(session.state, SessionState.BOARDING)

        session.apply_snapshot(
            snapshot(
                ignition=IgnitionState.ON,
                timestamp=60.0,
            )
        )

        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(len(session.history), 2)
        self.assertEqual(
            session.history[-1].reason, "boarding_without_passenger"
        )
        self.assertFalse(session.passenger_present)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.NONE)
        self.assertEqual(guidance.reason, "idle")
        self.assertEqual(guidance.text, "")

        report = report_for_session(session)
        self.assertEqual(report.transition_count, 2)
        self.assertEqual(report.duration_seconds, 60.0)
        self.assertEqual(report.exception_count, 0)

    def test_boarding_ignition_episode_then_full_journey_completes(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )
        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                timestamp=60.0,
            )
        )
        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                timestamp=120.0,
            )
        )
        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                timestamp=180.0,
            )
        )
        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.OFF,
                timestamp=240.0,
            )
        )
        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=False,
                timestamp=300.0,
            )
        )
        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=False,
                timestamp=360.0,
            )
        )

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
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 360.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")


if __name__ == "__main__":
    unittest.main()

"""QA scenarios for ignition-on input while IDLE without a passenger."""

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


class IdleIgnitionQATest(unittest.TestCase):
    def test_idle_ignition_on_without_passenger_stays_idle(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(
                ignition=IgnitionState.ON,
                cabin_temp_c=24.0,
                timestamp=10.0,
            )
        )

        self.assertEqual(session.state, SessionState.IDLE)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 0)
        self.assertEqual(
            session.current_snapshot.ignition, IgnitionState.ON
        )

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.NONE)
        self.assertEqual(guidance.reason, "idle")
        self.assertEqual(guidance.text, "")

        report = report_for_session(session)
        self.assertEqual(report.final_state, SessionState.IDLE)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 0)
        self.assertIsNone(report.duration_seconds)
        self.assertEqual(report.max_cabin_temp_c, 24.0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

        event_session = CareSession()
        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.IGNITION_ON, timestamp=10.0
            )
        )
        self.assertEqual(event_session.state, SessionState.IDLE)
        self.assertEqual(len(event_session.history), 0)
        self.assertEqual(
            event_session.current_snapshot.ignition, IgnitionState.ON
        )

    def test_idle_ignition_on_repeated_is_idempotent(self):
        session = CareSession()

        for timestamp in (10.0, 20.0):
            session.apply_snapshot(
                snapshot(
                    ignition=IgnitionState.ON, timestamp=timestamp
                )
            )
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(len(session.history), 0)

    def test_idle_ignition_on_high_temp_without_passenger_no_exception(
        self,
    ):
        session = CareSession()

        session.apply_snapshot(
            snapshot(
                ignition=IgnitionState.ON,
                cabin_temp_c=35.5,
                timestamp=10.0,
            )
        )

        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(len(session.history), 0)
        self.assertFalse(session.passenger_present)

        guidance = guidance_for_session(session)
        self.assertEqual(guidance.level, GuidanceLevel.NONE)
        self.assertNotEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.reason, "idle")

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

        session.apply_snapshot(
            snapshot(ignition=IgnitionState.OFF, timestamp=60.0)
        )
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(len(session.history), 0)

    def test_idle_ignition_episode_then_normal_dropoff_completes(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(
                ignition=IgnitionState.ON,
                cabin_temp_c=24.0,
                timestamp=0.0,
            )
        )
        self.assertEqual(session.state, SessionState.IDLE)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                ignition=IgnitionState.ON,
                timestamp=60.0,
            )
        )
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(session.history[-1].reason, "rear_door_opened")

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                timestamp=120.0,
            )
        )
        self.assertEqual(session.state, SessionState.BOARDING)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.CLOSED,
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                hvac_on=True,
                timestamp=180.0,
            )
        )
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(
            session.history[-2].from_state, SessionState.BOARDING
        )
        self.assertEqual(
            session.history[-2].to_state, SessionState.ONBOARD
        )
        self.assertEqual(
            session.history[-2].reason, "passenger_onboard"
        )
        self.assertEqual(
            session.history[-1].from_state, SessionState.ONBOARD
        )
        self.assertEqual(
            session.history[-1].to_state, SessionState.DRIVING
        )
        self.assertEqual(session.history[-1].reason, "ignition_on")

        session.apply_snapshot(
            snapshot(rear_seat_belt_buckled=True, timestamp=240.0)
        )
        self.assertEqual(session.state, SessionState.ARRIVED)

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=300.0)
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)

        session.apply_snapshot(snapshot(timestamp=360.0))
        self.assertEqual(session.state, SessionState.COMPLETED)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_idle_ignition_on_then_belt_buckled_jumps_to_driving(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(
                ignition=IgnitionState.ON,
                rear_seat_belt_buckled=True,
                cabin_temp_c=24.0,
                timestamp=10.0,
            )
        )

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 2)
        self.assertEqual(session.history[0].from_state, SessionState.IDLE)
        self.assertEqual(
            session.history[0].to_state, SessionState.ONBOARD
        )
        self.assertEqual(
            session.history[0].reason, "passenger_onboard"
        )
        self.assertEqual(session.history[0].timestamp, 10.0)
        self.assertEqual(
            session.history[1].from_state, SessionState.ONBOARD
        )
        self.assertEqual(
            session.history[1].to_state, SessionState.DRIVING
        )
        self.assertEqual(session.history[1].reason, "ignition_on")
        self.assertEqual(session.history[1].timestamp, 10.0)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")

        report = report_for_session(session)
        self.assertEqual(report.transition_count, 2)
        self.assertEqual(report.duration_seconds, 0.0)

    def test_idle_ignition_on_belt_locked_still_driving_no_exception(
        self,
    ):
        session = CareSession()

        session.apply_snapshot(
            snapshot(
                ignition=IgnitionState.ON,
                rear_seat_belt_buckled=True,
                lock=LockState.LOCKED,
                timestamp=10.0,
            )
        )

        self.assertEqual(session.state, SessionState.DRIVING)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)


if __name__ == "__main__":
    unittest.main()

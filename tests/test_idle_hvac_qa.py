"""QA scenarios for HVAC input alone while IDLE."""

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


class IdleHvacQATest(unittest.TestCase):
    def test_idle_hvac_on_alone_stays_idle(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(hvac_on=True, cabin_temp_c=24.0, timestamp=10.0)
        )

        self.assertEqual(session.state, SessionState.IDLE)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 0)
        self.assertTrue(session.current_snapshot.hvac_on)

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
            SignalEvent(type=SignalEventType.HVAC_ON, timestamp=10.0)
        )
        self.assertEqual(event_session.state, SessionState.IDLE)
        self.assertEqual(len(event_session.history), 0)
        self.assertTrue(event_session.current_snapshot.hvac_on)

    def test_idle_hvac_on_repeated_is_idempotent_and_toggles_off(self):
        session = CareSession()

        for timestamp in (10.0, 20.0):
            session.apply_snapshot(
                snapshot(hvac_on=True, timestamp=timestamp)
            )
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(len(session.history), 0)
            self.assertTrue(session.current_snapshot.hvac_on)

        session.apply_snapshot(
            snapshot(hvac_on=False, timestamp=30.0)
        )
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(len(session.history), 0)
        self.assertFalse(session.current_snapshot.hvac_on)

        event_session = CareSession()
        event_session.apply_event(
            SignalEvent(type=SignalEventType.HVAC_ON, timestamp=10.0)
        )
        self.assertTrue(event_session.current_snapshot.hvac_on)

        event_session.apply_event(
            SignalEvent(type=SignalEventType.HVAC_OFF, timestamp=20.0)
        )
        self.assertEqual(event_session.state, SessionState.IDLE)
        self.assertEqual(len(event_session.history), 0)
        self.assertFalse(event_session.current_snapshot.hvac_on)

    def test_idle_hvac_on_high_temp_without_passenger_no_exception(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(hvac_on=True, cabin_temp_c=35.5, timestamp=10.0)
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

    def test_idle_hvac_episode_then_normal_dropoff_completes(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(hvac_on=True, cabin_temp_c=24.0, timestamp=0.0)
        )
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(len(session.history), 0)

        for item in dropoff_normal_snapshots(start=60.0):
            session.apply_snapshot(item)

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_idle_hvac_on_belt_buckled_enters_onboard(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(
                hvac_on=True,
                rear_seat_belt_buckled=True,
                cabin_temp_c=24.0,
                timestamp=10.0,
            )
        )

        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 1)
        self.assertEqual(session.history[0].from_state, SessionState.IDLE)
        self.assertEqual(
            session.history[0].to_state, SessionState.ONBOARD
        )
        self.assertEqual(session.history[0].reason, "passenger_onboard")
        self.assertEqual(session.history[0].timestamp, 10.0)
        self.assertTrue(session.current_snapshot.hvac_on)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "passenger_onboard")

    def test_idle_hvac_on_locked_high_temp_without_passenger_stays_idle(
        self,
    ):
        session = CareSession()

        session.apply_snapshot(
            snapshot(
                hvac_on=True,
                lock=LockState.LOCKED,
                cabin_temp_c=35.5,
                timestamp=10.0,
            )
        )

        self.assertEqual(session.state, SessionState.IDLE)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 0)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.NONE)
        self.assertEqual(guidance.reason, "idle")

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)


if __name__ == "__main__":
    unittest.main()

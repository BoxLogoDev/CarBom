"""QA scenarios for cabin temperature input alone while IDLE."""

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


class IdleTempQATest(unittest.TestCase):
    def test_idle_temp_alone_stays_idle(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(cabin_temp_c=24.0, timestamp=10.0)
        )

        self.assertEqual(session.state, SessionState.IDLE)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 0)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 24.0)

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

    def test_idle_temp_sequence_updates_current_and_max(self):
        session = CareSession()

        for cabin_temp_c, timestamp in (
            (24.0, 10.0),
            (32.0, 20.0),
            (35.5, 30.0),
            (28.0, 40.0),
        ):
            session.apply_snapshot(
                snapshot(cabin_temp_c=cabin_temp_c, timestamp=timestamp)
            )
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(len(session.history), 0)
            self.assertEqual(
                session.current_snapshot.cabin_temp_c, cabin_temp_c
            )
            self.assertEqual(
                report_for_session(session).max_cabin_temp_c,
                cabin_temp_c,
            )

    def test_idle_high_temp_without_passenger_no_exception(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(cabin_temp_c=35.5, timestamp=10.0)
        )

        self.assertEqual(session.state, SessionState.IDLE)
        self.assertNotEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 0)
        self.assertFalse(session.passenger_present)

        guidance = guidance_for_session(session)
        self.assertEqual(guidance.level, GuidanceLevel.NONE)
        self.assertNotEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.reason, "idle")

        for context in (
            DestinationContext.GENERAL,
            DestinationContext.DROPOFF,
            DestinationContext.PICKUP,
        ):
            context_guidance = guidance_for_session(
                session, context=context
            )
            self.assertEqual(context_guidance.level, GuidanceLevel.NONE)
            self.assertEqual(context_guidance.reason, "idle")
            self.assertEqual(context_guidance.text, "")

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_idle_temp_event_path_matches_snapshot_path(self):
        session = CareSession()

        session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=10.0,
                cabin_temp_c=32.0,
            )
        )
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(len(session.history), 0)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 32.0)

        session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=20.0,
                cabin_temp_c=35.5,
            )
        )
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(len(session.history), 0)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)

        snapshot_session = CareSession()
        snapshot_session.apply_snapshot(
            snapshot(cabin_temp_c=32.0, timestamp=10.0)
        )
        snapshot_session.apply_snapshot(
            snapshot(cabin_temp_c=35.5, timestamp=20.0)
        )
        self.assertEqual(session.state, snapshot_session.state)
        self.assertEqual(session.history, snapshot_session.history)
        self.assertEqual(len(session.history), len(snapshot_session.history))

        empty_session = CareSession()
        empty_session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=10.0,
            )
        )
        self.assertEqual(empty_session.state, SessionState.IDLE)
        self.assertEqual(len(empty_session.history), 0)
        self.assertIsNone(empty_session.current_snapshot.cabin_temp_c)
        self.assertIsNone(
            report_for_session(empty_session).max_cabin_temp_c
        )

    def test_idle_temp_episode_then_normal_dropoff_completes(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(cabin_temp_c=24.0, timestamp=0.0)
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

    def test_idle_temp_with_belt_enters_onboard_and_locked_stays_idle(
        self,
    ):
        session = CareSession()

        session.apply_snapshot(
            snapshot(
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

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "passenger_onboard")

        locked_session = CareSession()
        locked_session.apply_snapshot(
            snapshot(
                lock=LockState.LOCKED,
                cabin_temp_c=35.5,
                timestamp=10.0,
            )
        )

        self.assertEqual(locked_session.state, SessionState.IDLE)
        self.assertFalse(locked_session.passenger_present)
        self.assertEqual(len(locked_session.history), 0)

        locked_guidance = guidance_for_session(
            locked_session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(locked_guidance.level, GuidanceLevel.NONE)
        self.assertEqual(locked_guidance.reason, "idle")

        report = report_for_session(locked_session)
        self.assertEqual(report.exception_count, 0)


if __name__ == "__main__":
    unittest.main()

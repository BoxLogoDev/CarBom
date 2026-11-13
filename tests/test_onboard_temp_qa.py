"""QA scenarios for cabin temperature input alone while ONBOARD."""

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


class OnboardTempQATest(unittest.TestCase):
    def test_onboard_temp_alone_stays_onboard(self):
        session = onboard_session()

        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertEqual(len(session.history), 2)
        self.assertTrue(session.passenger_present)

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                cabin_temp_c=24.0,
                timestamp=90.0,
            )
        )

        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertEqual(len(session.history), 2)
        self.assertTrue(session.passenger_present)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 24.0)

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

    def test_onboard_temp_sequence_updates_current_and_max(self):
        session = onboard_session()

        for cabin_temp_c, timestamp in (
            (24.0, 90.0),
            (32.0, 120.0),
            (35.5, 150.0),
            (28.0, 180.0),
        ):
            session.apply_snapshot(
                snapshot(
                    rear_seat_belt_buckled=True,
                    cabin_temp_c=cabin_temp_c,
                    timestamp=timestamp,
                )
            )
            self.assertEqual(session.state, SessionState.ONBOARD)
            self.assertEqual(len(session.history), 2)
            self.assertTrue(session.passenger_present)
            self.assertEqual(
                session.current_snapshot.cabin_temp_c, cabin_temp_c
            )
            self.assertEqual(
                report_for_session(session).max_cabin_temp_c,
                cabin_temp_c,
            )

            guidance = guidance_for_session(
                session, context=DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "passenger_onboard")

    def test_onboard_high_temp_unlocked_no_exception_all_contexts(self):
        session = onboard_session()

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                cabin_temp_c=35.5,
                timestamp=90.0,
            )
        )

        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertNotEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 2)
        self.assertTrue(session.passenger_present)

        for context in (
            DestinationContext.GENERAL,
            DestinationContext.DROPOFF,
            DestinationContext.PICKUP,
        ):
            context_guidance = guidance_for_session(
                session, context=context
            )
            self.assertEqual(context_guidance.level, GuidanceLevel.INFO)
            self.assertNotEqual(
                context_guidance.level, GuidanceLevel.URGENT
            )
            self.assertEqual(context_guidance.reason, "passenger_onboard")
            self.assertEqual(
                context_guidance.text,
                "뒷좌석 승차가 확인되었습니다. 출발 전 안전벨트를 확인해 주세요.",
            )
            self.assertNotIn("35.5", context_guidance.text)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

        locked_session = onboard_session()
        locked_session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                cabin_temp_c=35.5,
                lock=LockState.LOCKED,
                timestamp=90.0,
            )
        )

        self.assertEqual(locked_session.state, SessionState.EXCEPTION)
        self.assertEqual(len(locked_session.history), 3)
        self.assertEqual(
            locked_session.history[-1].from_state, SessionState.ONBOARD
        )
        self.assertEqual(
            locked_session.history[-1].to_state, SessionState.EXCEPTION
        )
        self.assertEqual(
            locked_session.history[-1].reason,
            "ignition_off_locked_passenger_present",
        )

        locked_guidance = guidance_for_session(
            locked_session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(locked_guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            locked_guidance.reason,
            "passenger_left_locked_dangerous_cabin_temp",
        )
        self.assertEqual(
            report_for_session(locked_session).exception_count, 1
        )

    def test_onboard_temp_event_path_matches_snapshot_path(self):
        snapshot_session = onboard_session()
        snapshot_session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                cabin_temp_c=32.0,
                timestamp=90.0,
            )
        )
        snapshot_session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                cabin_temp_c=35.5,
                timestamp=120.0,
            )
        )

        event_session = onboard_session()
        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=90.0,
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
            [
                (
                    transition.from_state,
                    transition.to_state,
                    transition.reason,
                )
                for transition in event_session.history
            ],
            [
                (
                    transition.from_state,
                    transition.to_state,
                    transition.reason,
                )
                for transition in snapshot_session.history
            ],
        )
        self.assertEqual(
            event_session.current_snapshot.cabin_temp_c,
            snapshot_session.current_snapshot.cabin_temp_c,
        )
        self.assertEqual(event_session.current_snapshot.cabin_temp_c, 35.5)
        self.assertTrue(
            event_session.current_snapshot.rear_seat_belt_buckled
        )
        self.assertEqual(
            event_session.current_snapshot.rear_door, DoorState.CLOSED
        )

        empty_session = onboard_session()
        empty_session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=90.0,
            )
        )
        self.assertEqual(empty_session.state, SessionState.ONBOARD)
        self.assertEqual(len(empty_session.history), 2)
        self.assertIsNone(empty_session.current_snapshot.cabin_temp_c)
        self.assertIsNone(
            report_for_session(empty_session).max_cabin_temp_c
        )

    def test_onboard_temp_episode_then_normal_dropoff_completes(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )
        self.assertEqual(session.state, SessionState.BOARDING)

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                cabin_temp_c=24.0,
                timestamp=60.0,
            )
        )
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertEqual(len(session.history), 2)
        self.assertEqual(
            report_for_session(session).max_cabin_temp_c, 24.0
        )

        for item in dropoff_normal_snapshots()[2:]:
            session.apply_snapshot(item)

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.max_cabin_temp_c, 24.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_onboard_temp_with_ignition_departs_and_door_unbuckle_alights(
        self,
    ):
        session = onboard_session()

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                cabin_temp_c=35.5,
                timestamp=90.0,
            )
        )

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)
        self.assertEqual(
            session.history[-1].from_state, SessionState.ONBOARD
        )
        self.assertEqual(
            session.history[-1].to_state, SessionState.DRIVING
        )
        self.assertEqual(session.history[-1].reason, "ignition_on")

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

        door_session = onboard_session()
        door_session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                cabin_temp_c=24.0,
                timestamp=90.0,
            )
        )
        self.assertEqual(door_session.state, SessionState.ONBOARD)
        self.assertEqual(len(door_session.history), 2)
        self.assertTrue(door_session.passenger_present)

        door_session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=False,
                cabin_temp_c=24.0,
                timestamp=120.0,
            )
        )
        self.assertEqual(door_session.state, SessionState.ALIGHTING)
        self.assertEqual(len(door_session.history), 3)
        self.assertEqual(
            door_session.history[-1].reason, "passenger_alighting"
        )
        self.assertFalse(door_session.passenger_present)

        door_guidance = guidance_for_session(
            door_session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(door_guidance.level, GuidanceLevel.INFO)
        self.assertEqual(door_guidance.reason, "alighting")


if __name__ == "__main__":
    unittest.main()

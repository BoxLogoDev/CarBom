"""QA scenarios for cabin temperature input alone while COMPLETED.

본 파일은 전체 신호를 명시한 스냅샷 기준이다.
"""

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
from engine.adapters.simulator import replay_scenario


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


def completed_session():
    session = CareSession()
    replay_scenario(session, "dropoff_normal")
    return session


class CompletedTempQATest(unittest.TestCase):
    def test_completed_temp_alone_stays_completed(self):
        session = completed_session()

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        self.assertFalse(session.passenger_present)
        self.assertEqual(
            session.current_snapshot.rear_door, DoorState.CLOSED
        )
        self.assertFalse(
            session.current_snapshot.rear_seat_belt_buckled
        )
        self.assertEqual(
            session.current_snapshot.ignition, IgnitionState.OFF
        )
        self.assertFalse(session.current_snapshot.hvac_on)
        self.assertIsNone(session.current_snapshot.cabin_temp_c)
        self.assertEqual(
            session.current_snapshot.lock, LockState.UNLOCKED
        )
        self.assertEqual(session.current_snapshot.timestamp, 300.0)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        self.assertEqual(guidance.text, "하차 확인이 완료되었습니다.")

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.started_at, 0.0)
        self.assertEqual(report.ended_at, 300.0)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertIsNone(report.max_cabin_temp_c)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

        session.apply_snapshot(
            snapshot(cabin_temp_c=24.0, timestamp=360.0)
        )

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        self.assertFalse(session.passenger_present)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 24.0)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        self.assertEqual(guidance.text, "하차 확인이 완료되었습니다.")

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.max_cabin_temp_c, 24.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_completed_temp_sequence_updates_current_and_max_only(
        self,
    ):
        session = completed_session()

        for cabin_temp_c, timestamp in (
            (24.0, 360.0),
            (32.0, 420.0),
            (35.5, 480.0),
            (28.0, 540.0),
        ):
            session.apply_snapshot(
                snapshot(cabin_temp_c=cabin_temp_c, timestamp=timestamp)
            )
            self.assertEqual(session.state, SessionState.COMPLETED)
            self.assertEqual(len(session.history), 6)
            self.assertFalse(session.passenger_present)
            self.assertEqual(
                session.current_snapshot.cabin_temp_c, cabin_temp_c
            )

            guidance = guidance_for_session(
                session, context=DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "completed")
            self.assertEqual(
                guidance.text, "하차 확인이 완료되었습니다."
            )

            report = report_for_session(session)
            self.assertEqual(report.max_cabin_temp_c, cabin_temp_c)
            self.assertEqual(report.duration_seconds, 300.0)

    def test_completed_temp_boundaries_do_not_escalate_in_any_context(
        self,
    ):
        for cabin_temp_c in (31.9, 32.0, 34.9, 35.0, 35.5):
            session = completed_session()
            session.apply_snapshot(
                snapshot(cabin_temp_c=cabin_temp_c, timestamp=360.0)
            )

            guidance = guidance_for_session(
                session, context=DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "completed")
            self.assertEqual(
                guidance.text, "하차 확인이 완료되었습니다."
            )
            self.assertNotIn(str(cabin_temp_c), guidance.text)
            self.assertFalse(
                any(
                    character.isdigit()
                    for character in guidance.text
                )
            )

        for cabin_temp_c in (32.0, 35.5):
            context_session = completed_session()
            context_session.apply_snapshot(
                snapshot(cabin_temp_c=cabin_temp_c, timestamp=360.0)
            )
            guidances = [
                guidance_for_session(context_session, context=context)
                for context in (
                    DestinationContext.GENERAL,
                    DestinationContext.DROPOFF,
                    DestinationContext.PICKUP,
                )
            ]
            self.assertEqual(guidances[0].level, GuidanceLevel.INFO)
            self.assertEqual(guidances[0].reason, "completed")
            self.assertEqual(
                guidances[0].text, "하차 확인이 완료되었습니다."
            )
            for context_guidance in guidances[1:]:
                self.assertEqual(
                    context_guidance.level, guidances[0].level
                )
                self.assertEqual(
                    context_guidance.text, guidances[0].text
                )
                self.assertEqual(
                    context_guidance.reason, guidances[0].reason
                )

    def test_completed_temp_event_path_matches_snapshot_path(self):
        snapshot_session = completed_session()
        snapshot_session.apply_snapshot(
            snapshot(cabin_temp_c=32.0, timestamp=360.0)
        )
        snapshot_session.apply_snapshot(
            snapshot(cabin_temp_c=24.0, timestamp=420.0)
        )

        event_session = completed_session()
        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=360.0,
                cabin_temp_c=32.0,
            )
        )
        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=420.0,
                cabin_temp_c=24.0,
            )
        )

        self.assertEqual(event_session.state, snapshot_session.state)
        self.assertEqual(event_session.state, SessionState.COMPLETED)
        self.assertEqual(
            len(event_session.history), len(snapshot_session.history)
        )
        self.assertEqual(len(event_session.history), 6)
        self.assertEqual(
            [
                (
                    transition.from_state,
                    transition.to_state,
                    transition.reason,
                    transition.timestamp,
                )
                for transition in event_session.history
            ],
            [
                (
                    transition.from_state,
                    transition.to_state,
                    transition.reason,
                    transition.timestamp,
                )
                for transition in snapshot_session.history
            ],
        )
        self.assertEqual(
            event_session.current_snapshot,
            snapshot_session.current_snapshot,
        )
        self.assertEqual(event_session.current_snapshot.cabin_temp_c, 24.0)

        empty_session = completed_session()
        empty_session.apply_event(
            SignalEvent(
                type=SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=360.0,
            )
        )
        self.assertEqual(empty_session.state, SessionState.COMPLETED)
        self.assertEqual(len(empty_session.history), 6)
        self.assertIsNone(empty_session.current_snapshot.cabin_temp_c)
        self.assertIsNone(
            report_for_session(empty_session).max_cabin_temp_c
        )

        empty_guidance = guidance_for_session(
            empty_session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(empty_guidance.level, GuidanceLevel.INFO)
        self.assertEqual(empty_guidance.reason, "completed")

    def test_completed_temp_episode_then_reset_and_new_flow(self):
        session = completed_session()

        session.apply_snapshot(
            snapshot(cabin_temp_c=35.5, timestamp=360.0)
        )
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(
            report_for_session(session).max_cabin_temp_c, 35.5
        )

        session.reset()

        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])
        self.assertFalse(session.passenger_present)
        self.assertIsNone(session.current_snapshot.cabin_temp_c)

        replay_scenario(session, "forgotten_rising_temp")

        self.assertEqual(session.state, SessionState.EXCEPTION)
        report = report_for_session(session)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_completed_temp_with_belt_ignition_lock_and_door_signals(
        self,
    ):
        belt_session = completed_session()
        belt_session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                cabin_temp_c=35.5,
                timestamp=360.0,
            )
        )

        self.assertEqual(belt_session.state, SessionState.COMPLETED)
        self.assertEqual(len(belt_session.history), 6)
        self.assertTrue(belt_session.passenger_present)

        report = report_for_session(belt_session)
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

        belt_session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=False,
                cabin_temp_c=35.5,
                timestamp=420.0,
            )
        )

        self.assertEqual(belt_session.state, SessionState.COMPLETED)
        self.assertEqual(len(belt_session.history), 6)
        self.assertFalse(belt_session.passenger_present)

        ignition_session = completed_session()
        ignition_session.apply_snapshot(
            snapshot(
                ignition=IgnitionState.ON,
                cabin_temp_c=35.5,
                timestamp=360.0,
            )
        )

        self.assertEqual(
            ignition_session.state, SessionState.COMPLETED
        )
        self.assertEqual(len(ignition_session.history), 6)
        self.assertFalse(ignition_session.passenger_present)

        locked_session = completed_session()
        locked_session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                cabin_temp_c=35.5,
                lock=LockState.LOCKED,
                timestamp=360.0,
            )
        )

        self.assertEqual(locked_session.state, SessionState.COMPLETED)
        self.assertEqual(len(locked_session.history), 6)
        self.assertEqual(
            report_for_session(locked_session).exception_count, 0
        )


if __name__ == "__main__":
    unittest.main()

"""QA scenarios for re-boarding after an aborted boarding.

기존 테스트(test_session_edge_qa)는 동승자 없이 뒷문을 열었다 닫으면
BOARDING에서 IDLE로 복귀하는 것까지만 다뤘다. 이 파일은 그 뒤를
고정한다: 중단된 세션은 reset 없이 같은 세션에서 다시 승차해 등원
완주(COMPLETED)나 하차 깜빡 예외(EXCEPTION)까지 그대로 이어지고,
중단 이력은 지워지지 않아 리포트의 전이 횟수에 그대로 남는다.
이벤트 경로(REAR_DOOR_OPENED/CLOSED)의 중단도 스냅샷 경로와
히스토리가 동일하다.
"""

import unittest

from engine import (
    CareSession,
    DoorState,
    GuidanceLevel,
    SessionState,
    SignalEvent,
    SignalEventType,
    SignalSnapshot,
)
from engine.adapters.simulator import (
    dropoff_normal_snapshots,
    forgotten_rising_temp_snapshots,
    replay,
)
from engine.guidance import DestinationContext, guidance_for_session
from engine.report import report_for_session


def abort_boarding(session):
    """뒷문을 열었다가 동승자 없이 닫아 승차를 중단한다."""
    session.apply_snapshot(
        SignalSnapshot(rear_door=DoorState.OPEN, timestamp=0.0)
    )
    session.apply_snapshot(SignalSnapshot(timestamp=60.0))
    return session


def history_signature(session):
    return tuple(
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    )


class ReboardingQATest(unittest.TestCase):
    def test_aborted_boarding_state_guidance_and_report(self):
        session = abort_boarding(CareSession())

        self.assertEqual(session.state, SessionState.IDLE)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 2)
        self.assertEqual(
            [t.reason for t in session.history],
            ["rear_door_opened", "boarding_without_passenger"],
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
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.transition_count, 2)
        self.assertEqual(report.duration_seconds, 60.0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_reboard_after_abort_completes_dropoff(self):
        session = abort_boarding(CareSession())

        final = replay(session, dropoff_normal_snapshots(start=120.0))

        self.assertEqual(final, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 8)
        self.assertEqual(
            [t.reason for t in session.history],
            [
                "rear_door_opened",
                "boarding_without_passenger",
                "rear_door_opened",
                "passenger_onboard",
                "ignition_on",
                "ignition_off",
                "alighting_started",
                "alighting_confirmed",
            ],
        )

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 8)
        self.assertEqual(report.duration_seconds, 420.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_double_abort_then_reboard_completes(self):
        session = abort_boarding(CareSession())
        session.apply_snapshot(
            SignalSnapshot(rear_door=DoorState.OPEN, timestamp=120.0)
        )
        session.apply_snapshot(SignalSnapshot(timestamp=180.0))
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(len(session.history), 4)

        final = replay(session, dropoff_normal_snapshots(start=300.0))

        self.assertEqual(final, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 10)
        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.transition_count, 10)
        self.assertEqual(report.duration_seconds, 600.0)

    def test_reboard_after_abort_can_still_raise_exception(self):
        session = abort_boarding(CareSession())

        final = replay(
            session, forgotten_rising_temp_snapshots(start=120.0)
        )

        self.assertEqual(final, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 7)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason,
            "passenger_left_locked_dangerous_cabin_temp",
        )
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)

        report = report_for_session(session)
        self.assertFalse(report.completed)
        self.assertTrue(report.exception_occurred)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_event_path_abort_matches_snapshot_path(self):
        snapshot_session = abort_boarding(CareSession())

        event_session = CareSession()
        self.assertEqual(
            event_session.apply_event(
                SignalEvent(
                    SignalEventType.REAR_DOOR_OPENED, timestamp=0.0
                )
            ),
            SessionState.BOARDING,
        )
        self.assertEqual(
            event_session.apply_event(
                SignalEvent(
                    SignalEventType.REAR_DOOR_CLOSED, timestamp=60.0
                )
            ),
            SessionState.IDLE,
        )
        self.assertEqual(
            history_signature(event_session),
            history_signature(snapshot_session),
        )

        final = replay(
            event_session, dropoff_normal_snapshots(start=120.0)
        )
        self.assertEqual(final, SessionState.COMPLETED)
        self.assertEqual(len(event_session.history), 8)

    def test_abort_history_is_preserved_in_report(self):
        reboarded = abort_boarding(CareSession())
        replay(reboarded, dropoff_normal_snapshots(start=120.0))

        fresh = CareSession()
        replay(fresh, dropoff_normal_snapshots())

        reboarded_report = report_for_session(reboarded)
        fresh_report = report_for_session(fresh)
        self.assertEqual(reboarded_report.transition_count, 8)
        self.assertEqual(fresh_report.transition_count, 6)
        self.assertTrue(reboarded_report.completed)
        self.assertTrue(fresh_report.completed)

        reboarded_guidance = guidance_for_session(
            reboarded, context=DestinationContext.DROPOFF
        )
        fresh_guidance = guidance_for_session(
            fresh, context=DestinationContext.DROPOFF
        )
        self.assertEqual(reboarded_guidance.level, fresh_guidance.level)
        self.assertEqual(reboarded_guidance.text, fresh_guidance.text)
        self.assertEqual(
            reboarded_guidance.reason, fresh_guidance.reason
        )


if __name__ == "__main__":
    unittest.main()

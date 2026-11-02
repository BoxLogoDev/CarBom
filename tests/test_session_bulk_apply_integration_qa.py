"""QA: 세션 대량 적용 메서드의 안내·리포트·누적함 통합 검증.

전제: CareSession.apply_snapshots / apply_events / apply_updates 는
단건 apply_snapshot / apply_event / update 를 순서대로 적용하는
대량 경로이며, 최종 판정은 입력 경로가 아니라 신호 값으로만
이뤄진다(engine/session.py). 기존 tests/test_session.py는 대량
메서드의 단위 동작(최종 상태·빈 입력·개별 호출 동등성)만 다뤄,
대량 경로로 구동한 세션의 안내(guidance_for_session)·케어 리포트
(report_for_session)·누적함(CareReportLog)까지 잇는 각도는 없었다.
이 파일은 고정 시나리오 3종을 대량 경로로 구동해 그 통합 동작을
고정한다.
"""

import unittest

from engine import (
    CareReportLog,
    CareSession,
    DestinationContext,
    GuidanceLevel,
    SessionState,
    SignalEvent,
    SignalEventType,
    guidance_for_session,
    report_for_session,
    reports_for_sessions,
)
from engine.adapters.simulator import (
    dropoff_normal_snapshots,
    forgotten_rising_temp_snapshots,
    pet_dropoff_snapshots,
    replay_scenario,
)


class BulkSnapshotsIntegrationTest(unittest.TestCase):
    def test_bulk_snapshots_dropoff_guidance_and_report(self):
        session = CareSession()

        result = session.apply_snapshots(dropoff_normal_snapshots())

        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        self.assertFalse(session.passenger_present)

        guidance = guidance_for_session(session, DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.state, SessionState.COMPLETED)
        self.assertEqual(guidance.reason, "completed")

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_bulk_snapshots_forgotten_guidance_and_report(self):
        session = CareSession()

        result = session.apply_snapshots(forgotten_rising_temp_snapshots())

        self.assertEqual(result, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)
        self.assertTrue(session.passenger_present)

        guidance = guidance_for_session(session, DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.state, SessionState.EXCEPTION)
        self.assertEqual(
            guidance.reason, "passenger_left_locked_dangerous_cabin_temp"
        )
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)

        report = report_for_session(session)
        self.assertFalse(report.completed)
        self.assertTrue(report.exception_occurred)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")


class BulkEventsIntegrationTest(unittest.TestCase):
    def test_bulk_events_dropoff_flow_reasons_and_report(self):
        event_types = (
            SignalEventType.REAR_DOOR_OPENED,
            SignalEventType.REAR_BELT_BUCKLED,
            SignalEventType.REAR_DOOR_CLOSED,
            SignalEventType.IGNITION_ON,
            SignalEventType.IGNITION_OFF,
            SignalEventType.REAR_DOOR_OPENED,
            SignalEventType.REAR_BELT_UNBUCKLED,
            SignalEventType.REAR_DOOR_CLOSED,
        )
        session = CareSession()

        result = session.apply_events(
            SignalEvent(event_type) for event_type in event_types
        )

        self.assertEqual(result, SessionState.COMPLETED)
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
        self.assertFalse(session.passenger_present)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.transition_count, 6)
        # 이벤트에 시각이 없으면 전이 시각도 없어 소요 시간은 None이다.
        self.assertIsNone(report.duration_seconds)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")


class BulkUpdatesIntegrationTest(unittest.TestCase):
    def test_bulk_updates_mixed_input_matches_replay_scenario(self):
        snapshots = dropoff_normal_snapshots()
        items = [
            *snapshots[:3],
            SignalEvent(SignalEventType.IGNITION_OFF, timestamp=180.0),
            SignalEvent(SignalEventType.REAR_DOOR_OPENED, timestamp=240.0),
            SignalEvent(SignalEventType.REAR_BELT_UNBUCKLED, timestamp=240.0),
            SignalEvent(SignalEventType.REAR_DOOR_CLOSED, timestamp=300.0),
        ]
        session = CareSession()

        result = session.apply_updates(items)

        self.assertEqual(result, SessionState.COMPLETED)

        baseline = CareSession()
        replay_scenario(baseline, "dropoff_normal")
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
                    transition.from_state,
                    transition.to_state,
                    transition.reason,
                    transition.timestamp,
                )
                for transition in baseline.history
            ],
        )

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)


class BulkApplyReportLogTest(unittest.TestCase):
    def test_log_accumulates_bulk_applied_scenario_sessions(self):
        sessions = []
        for snapshots in (
            dropoff_normal_snapshots(),
            forgotten_rising_temp_snapshots(),
            pet_dropoff_snapshots(),
        ):
            session = CareSession()
            session.apply_snapshots(snapshots)
            sessions.append(session)

        log = CareReportLog()
        added = log.add_sessions(sessions)

        self.assertEqual(added, reports_for_sessions(sessions))
        self.assertEqual(len(log), 3)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.average_duration_seconds, 280.0)


class BulkEmptyInputIntegrationTest(unittest.TestCase):
    def test_empty_bulk_inputs_keep_mid_session_unchanged(self):
        session = CareSession()
        session.apply_snapshots(dropoff_normal_snapshots()[:2])
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertTrue(session.passenger_present)
        history_before = list(session.history)
        self.assertEqual(len(history_before), 2)

        self.assertEqual(session.apply_snapshots([]), SessionState.ONBOARD)
        self.assertEqual(session.apply_events([]), SessionState.ONBOARD)
        self.assertEqual(session.apply_updates([]), SessionState.ONBOARD)

        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertEqual(session.history, history_before)
        self.assertTrue(session.passenger_present)


if __name__ == "__main__":
    unittest.main()

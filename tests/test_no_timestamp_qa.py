"""시각(timestamp) 없는 신호 흐름 QA.

실제 차량 SDK 신호에는 시각이 없을 수 있다.
엔진 판정은 시각이 아니라 신호 값으로만 이뤄져야 한다.
시각은 리포트의 started_at, ended_at, duration_seconds 계산에만 쓰여야 한다.
고정 시나리오 스냅샷의 timestamp를 전부 None으로 바꾼 흐름과
timestamp가 없는 이벤트 흐름으로 이를 검증한다.
"""

import dataclasses
import unittest

from engine.adapters.simulator import SCENARIO_NAMES, replay, scenario_snapshots
from engine.guidance import (
    DestinationContext,
    GuidanceLevel,
    guidance_for_session,
)
from engine.report import CareReportLog, report_for_session
from engine.session import CareSession, SessionState
from engine.signals import SignalEvent, SignalEventType


def _run_without_timestamps(name):
    session = CareSession()
    snapshots = tuple(
        dataclasses.replace(s, timestamp=None)
        for s in scenario_snapshots(name)
    )
    final = replay(session, snapshots)
    return session, final


class NoTimestampQATest(unittest.TestCase):
    def test_dropoff_normal_without_timestamps_completes(self):
        session, final = _run_without_timestamps("dropoff_normal")

        self.assertIs(final, SessionState.COMPLETED)
        self.assertIs(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        for transition in session.history:
            self.assertIsNone(transition.timestamp)
        self.assertFalse(session.passenger_present)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertIsNone(report.started_at)
        self.assertIsNone(report.ended_at)
        self.assertIsNone(report.duration_seconds)
        self.assertIsNone(report.max_cabin_temp_c)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_forgotten_without_timestamps_stays_exception_with_temperature(
        self,
    ):
        session, final = _run_without_timestamps("forgotten_rising_temp")

        self.assertIs(final, SessionState.EXCEPTION)
        self.assertIs(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)
        for transition in session.history:
            self.assertIsNone(transition.timestamp)
        self.assertTrue(session.passenger_present)

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
        self.assertEqual(report.exception_count, 1)
        self.assertIsNone(report.duration_seconds)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_pet_dropoff_without_timestamps_completes(self):
        session, final = _run_without_timestamps("pet_dropoff")

        self.assertIs(final, SessionState.COMPLETED)
        self.assertIs(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        for transition in session.history:
            self.assertIsNone(transition.timestamp)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertIsNone(report.duration_seconds)

    def test_events_without_timestamps_complete(self):
        session = CareSession()
        for event_type in (
            SignalEventType.REAR_DOOR_OPENED,
            SignalEventType.REAR_BELT_BUCKLED,
            SignalEventType.REAR_DOOR_CLOSED,
            SignalEventType.IGNITION_ON,
            SignalEventType.IGNITION_OFF,
            SignalEventType.REAR_DOOR_OPENED,
            SignalEventType.REAR_BELT_UNBUCKLED,
            SignalEventType.REAR_DOOR_CLOSED,
        ):
            session.apply_event(SignalEvent(event_type))

        self.assertIs(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        for transition in session.history:
            self.assertIsNone(transition.timestamp)
        self.assertFalse(session.passenger_present)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertIsNone(report.started_at)
        self.assertIsNone(report.ended_at)
        self.assertIsNone(report.duration_seconds)

    def test_report_log_aggregates_without_durations(self):
        log = CareReportLog()
        for name in SCENARIO_NAMES:
            session, _ = _run_without_timestamps(name)
            log.add_session(session)

        self.assertEqual(len(log), 3)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertIsNone(log.average_duration_seconds)


if __name__ == "__main__":
    unittest.main()

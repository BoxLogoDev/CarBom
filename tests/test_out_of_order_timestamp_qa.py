"""비단조(non-monotonic) 타임스탬프 입력 QA.

엔진은 타임스탬프를 전이 판정에 쓰지 않고 전이 이력에 기록만 한다.
시각이 없는 입력(test_no_timestamp_qa)과 부분적으로만 있는 입력
(test_report_boundary_qa)은 이미 검증됐으나, 시각이 단조 증가하지
않는 입력(역행·엇갈림)은 미검증이었다.
이 파일은 고정 시나리오에 역행·비단조 타임스탬프를 부여해 재생하고,
이벤트 경로와 누적함 집계까지 같은 각도로 검증한다.

관측 사항: 리포트의 duration_seconds는 첫 전이 시각과 마지막 전이
시각을 그대로 빼는 정의라, 역행 입력에서는 음수가 된다.
이 값은 현행 정의를 그대로 고정한 것이며, 음수 소요 시간을 막을지는
리포트 의미가 바뀌는 설계 판단이라 별도 제안으로 남긴다.
"""

import dataclasses
import unittest

from engine.adapters.simulator import replay, scenario_snapshots
from engine.guidance import (
    DestinationContext,
    GuidanceLevel,
    guidance_for_session,
)
from engine.report import CareReportLog, report_for_session
from engine.session import CareSession, SessionState
from engine.signals import SignalEvent, SignalEventType

START = 1000.0
STEP = 60.0


def _run_with_timestamps(name, timestamps):
    session = CareSession()
    snapshots = tuple(
        dataclasses.replace(snapshot, timestamp=timestamp)
        for snapshot, timestamp in zip(
            scenario_snapshots(name, start=START), timestamps
        )
    )
    final = replay(session, snapshots)
    return session, final


def _decreasing(count):
    return [START - STEP * index for index in range(count)]


def _transition_keys(session):
    return [
        (transition.from_state, transition.to_state, transition.reason)
        for transition in session.history
    ]


def _history_timestamps(session):
    return [transition.timestamp for transition in session.history]


class OutOfOrderTimestampQATest(unittest.TestCase):
    def test_decreasing_timestamps_complete_dropoff_with_same_transitions(
        self,
    ):
        monotonic, _ = _run_with_timestamps(
            "dropoff_normal",
            [START + STEP * index for index in range(6)],
        )
        session, final = _run_with_timestamps(
            "dropoff_normal", _decreasing(6)
        )

        self.assertIs(final, SessionState.COMPLETED)
        self.assertIs(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(
            _transition_keys(session), _transition_keys(monotonic)
        )
        self.assertEqual(
            _history_timestamps(session),
            [1000.0, 940.0, 880.0, 820.0, 760.0, 700.0],
        )

    def test_decreasing_timestamps_report_duration_is_negative(self):
        session, _ = _run_with_timestamps(
            "dropoff_normal", _decreasing(6)
        )

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.started_at, 1000.0)
        self.assertEqual(report.ended_at, 700.0)
        # 현행 정의(마지막 전이 시각 - 첫 전이 시각)를 그대로 고정한다.
        self.assertEqual(report.duration_seconds, -300.0)

    def test_decreasing_timestamps_forgotten_stays_exception_with_urgent_guidance(
        self,
    ):
        session, final = _run_with_timestamps(
            "forgotten_rising_temp", _decreasing(8)
        )

        self.assertIs(final, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)

        report = report_for_session(session)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.started_at, 1000.0)
        self.assertEqual(report.ended_at, 760.0)
        self.assertEqual(report.duration_seconds, -240.0)

    def test_non_monotonic_timestamps_forgotten_exception_and_report_uses_transition_times(
        self,
    ):
        session, final = _run_with_timestamps(
            "forgotten_rising_temp",
            [0.0, 300.0, 120.0, 400.0, 50.0, 900.0, 200.0, 700.0],
        )

        self.assertIs(final, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        # 전이는 앞쪽 5개 스냅샷에서만 일어난다.
        self.assertEqual(
            _history_timestamps(session),
            [0.0, 300.0, 120.0, 400.0, 50.0],
        )

        report = report_for_session(session)
        # 전이를 일으키지 않은 뒤쪽 스냅샷의 시각(900.0 등)은
        # 리포트 구간에 반영되지 않는다.
        self.assertEqual(report.started_at, 0.0)
        self.assertEqual(report.ended_at, 50.0)
        self.assertEqual(report.duration_seconds, 50.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_decreasing_timestamps_event_path_completes_with_negative_duration(
        self,
    ):
        session = CareSession()
        for event_type, timestamp in (
            (SignalEventType.REAR_DOOR_OPENED, 500.0),
            (SignalEventType.REAR_BELT_BUCKLED, 400.0),
            (SignalEventType.REAR_DOOR_CLOSED, 300.0),
            (SignalEventType.IGNITION_ON, 200.0),
            (SignalEventType.IGNITION_OFF, 100.0),
            (SignalEventType.REAR_DOOR_OPENED, 50.0),
            (SignalEventType.REAR_BELT_UNBUCKLED, 40.0),
            (SignalEventType.REAR_DOOR_CLOSED, 0.0),
        ):
            session.apply_event(
                SignalEvent(event_type, timestamp=timestamp)
            )

        self.assertIs(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(
            _history_timestamps(session),
            [500.0, 300.0, 200.0, 100.0, 50.0, 0.0],
        )

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.duration_seconds, -500.0)

    def test_report_log_aggregates_include_negative_duration_literally(
        self,
    ):
        monotonic, _ = _run_with_timestamps(
            "dropoff_normal",
            [START + STEP * index for index in range(6)],
        )
        decreasing, _ = _run_with_timestamps(
            "dropoff_normal", _decreasing(6)
        )
        log = CareReportLog()
        log.add_session(monotonic)
        log.add_session(decreasing)

        self.assertEqual(len(log.reports), 2)
        self.assertEqual(log.total_duration_seconds, 0.0)
        self.assertEqual(log.average_duration_seconds, 0.0)
        self.assertEqual(log.max_duration_seconds, 300.0)
        self.assertEqual(log.min_duration_seconds, -300.0)


if __name__ == "__main__":
    unittest.main()

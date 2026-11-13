"""QA: 중복 스냅샷 배달(at-least-once delivery) 전 흐름 멱등성.

전제: 고정 시나리오의 SignalSnapshot 시퀀스에서 각 스냅샷이 같은
값·같은 timestamp로 연속해서 중복 배달돼도 세션 결과는 1회 배달과
완전히 같아야 한다. 기존 tests/test_duplicate_event_delivery_qa.py는
첨부 스냅샷 없는 SignalEvent의 중복 배달만 다뤘고, 상태별 단일 입력
테스트는 같은 스냅샷 반복을 상태마다 따로 다뤘다. 이 파일은 시나리오
전 흐름을 스냅샷 단위로 중복 배달했을 때 전이 이력·예외 횟수·안내·
리포트가 중복으로 부풀지 않는지를 고정한다. 특히 EXCEPTION 진입
스냅샷이 중복 배달되면 exception_count가 2로 부풀 위험이 있어, 그
값을 명시적으로 고정한다. 시퀀스 전체를 통째로 다시 보내는 재전송은
건별 중복 배달과 다르다는 대조도 함께 고정한다.
"""

import unittest

from engine import CareSession, SessionState
from engine.adapters.simulator import SCENARIO_NAMES, scenario_snapshots
from engine.guidance import (
    DestinationContext,
    GuidanceLevel,
    guidance_for_session,
)
from engine.report import CareReportLog, report_for_session


def _run_single(snapshots):
    session = CareSession()
    for snapshot in snapshots:
        session.apply_snapshot(snapshot)
    return session


def _run_duplicated(snapshots, times=2):
    session = CareSession()
    for snapshot in snapshots:
        for _ in range(times):
            session.apply_snapshot(snapshot)
    return session


def _history_keys(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


def _report_key(report):
    return (
        report.final_state,
        report.completed,
        report.exception_occurred,
        report.exception_count,
        report.transition_count,
        report.passenger_present,
        report.duration_seconds,
        report.max_cabin_temp_c,
        report.summary,
    )


def _surfaces(session):
    guidance = guidance_for_session(
        session, context=DestinationContext.DROPOFF
    )
    return (
        session.state,
        session.passenger_present,
        _history_keys(session),
        session.current_snapshot,
        (guidance.level, guidance.text, guidance.reason),
        _report_key(report_for_session(session)),
    )


class DuplicateSnapshotDeliveryQATest(unittest.TestCase):
    def test_normal_flow_duplicated_matches_single(self):
        snapshots = scenario_snapshots("dropoff_normal")
        single = _run_single(snapshots)
        duplicated = _run_duplicated(snapshots)

        self.assertEqual(_surfaces(duplicated), _surfaces(single))
        self.assertIs(duplicated.state, SessionState.COMPLETED)
        self.assertFalse(duplicated.passenger_present)
        self.assertEqual(len(duplicated.history), 6)
        guidance = guidance_for_session(
            duplicated, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        report = report_for_session(duplicated)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertIsNone(report.max_cabin_temp_c)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_exception_flow_duplicated_does_not_double_count(self):
        snapshots = scenario_snapshots("forgotten_rising_temp")
        single = _run_single(snapshots)
        duplicated = _run_duplicated(snapshots)

        self.assertEqual(_surfaces(duplicated), _surfaces(single))
        self.assertIs(duplicated.state, SessionState.EXCEPTION)
        self.assertTrue(duplicated.passenger_present)
        self.assertEqual(len(duplicated.history), 5)
        self.assertEqual(
            _history_keys(duplicated)[-1],
            (
                SessionState.ARRIVED,
                SessionState.EXCEPTION,
                "ignition_off_locked_passenger_present",
                240.0,
            ),
        )
        guidance = guidance_for_session(
            duplicated, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason, "passenger_left_locked_dangerous_cabin_temp"
        )
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)
        report = report_for_session(duplicated)
        self.assertFalse(report.completed)
        # 중복 배달이 예외 횟수를 부풀리지 않는다.
        self.assertEqual(report.exception_count, 1)
        self.assertNotEqual(report.exception_count, 2)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_pet_flow_duplicated_matches_single(self):
        snapshots = scenario_snapshots("pet_dropoff")
        single = _run_single(snapshots)
        duplicated = _run_duplicated(snapshots)

        self.assertEqual(_surfaces(duplicated), _surfaces(single))
        self.assertIs(duplicated.state, SessionState.COMPLETED)
        self.assertFalse(duplicated.passenger_present)
        self.assertEqual(len(duplicated.history), 6)
        report = report_for_session(duplicated)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertIsNone(report.max_cabin_temp_c)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_triple_and_bulk_generator_duplication_match_single(self):
        self.assertEqual(
            SCENARIO_NAMES,
            ("dropoff_normal", "forgotten_rising_temp", "pet_dropoff"),
        )
        for name in SCENARIO_NAMES:
            with self.subTest(scenario=name):
                snapshots = scenario_snapshots(name)
                single = _run_single(snapshots)

                tripled = _run_duplicated(snapshots, times=3)
                self.assertEqual(_surfaces(tripled), _surfaces(single))

                bulk = CareSession()
                result = bulk.apply_snapshots(
                    snapshot
                    for snapshot in snapshots
                    for _ in range(2)
                )
                self.assertIs(result, single.state)
                self.assertEqual(_surfaces(bulk), _surfaces(single))

    def test_full_sequence_redelivery_differs_from_duplication(self):
        snapshots = scenario_snapshots("forgotten_rising_temp")
        redelivered = CareSession()
        for _ in range(2):
            for snapshot in snapshots:
                redelivered.apply_snapshot(snapshot)

        # 시퀀스 전체 재전송은 건별 중복 배달과 다르다: 두 번째 패스의
        # 뒷문 열림이 EXCEPTION을 ALIGHTING으로 풀고, 잠금 스냅샷이
        # 다시 EXCEPTION으로 되돌려 예외가 2회로 집계된다.
        self.assertIs(redelivered.state, SessionState.EXCEPTION)
        self.assertEqual(len(redelivered.history), 7)
        self.assertEqual(
            _history_keys(redelivered)[5:],
            [
                (
                    SessionState.EXCEPTION,
                    SessionState.ALIGHTING,
                    "rear_door_opened_after_exception",
                    0.0,
                ),
                (
                    SessionState.ALIGHTING,
                    SessionState.EXCEPTION,
                    "ignition_off_locked_passenger_present",
                    240.0,
                ),
            ],
        )
        report = report_for_session(redelivered)
        self.assertEqual(report.exception_count, 2)
        self.assertEqual(report.transition_count, 7)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

        # 완료된 시나리오는 종단성 때문에 전체 재전송에도 불변이다.
        normal = scenario_snapshots("dropoff_normal")
        redelivered_normal = CareSession()
        for _ in range(2):
            for snapshot in normal:
                redelivered_normal.apply_snapshot(snapshot)
        self.assertIs(redelivered_normal.state, SessionState.COMPLETED)
        self.assertEqual(len(redelivered_normal.history), 6)
        self.assertEqual(
            _surfaces(redelivered_normal),
            _surfaces(_run_single(normal)),
        )

    def test_report_log_aggregates_match_for_duplicated_runs(self):
        single_log = CareReportLog()
        duplicated_log = CareReportLog()
        for name in SCENARIO_NAMES:
            snapshots = scenario_snapshots(name)
            single_log.add_report(
                report_for_session(_run_single(snapshots))
            )
            duplicated_log.add_report(
                report_for_session(_run_duplicated(snapshots))
            )

        for log in (single_log, duplicated_log):
            self.assertEqual(len(log), 3)
            self.assertEqual(log.completed_count, 2)
            self.assertEqual(log.sessions_with_exception, 1)
            self.assertEqual(log.total_exception_count, 1)
            self.assertEqual(log.total_transition_count, 17)
            self.assertEqual(log.max_cabin_temp_c, 35.5)
            self.assertEqual(log.average_duration_seconds, 280.0)
        self.assertEqual(
            [_report_key(r) for r in duplicated_log.reports],
            [_report_key(r) for r in single_log.reports],
        )


if __name__ == "__main__":
    unittest.main()

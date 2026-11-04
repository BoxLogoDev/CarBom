"""케어 리포트 누적함 집계 통합 QA.

집계 속성 하나하나는 tests/test_report.py 가 속성별로 검증하지만,
여러 리포트가 섞인 누적함에서 모든 집계가 동시에 서로 모순 없이
맞아떨어지는지, 그리고 온도·소요시간 집계(값이 있는 리포트만 대상)와
예외·전이 집계(모든 리포트 대상, 빈 세션의 0 포함)의 비대칭이
통합 상황에서도 유지되는지는 검증하지 않았다. 이 파일이 그 각도다.
기대값은 고정 시나리오 3종과 빈 세션을 실측한 값이다.
"""

import dataclasses
import unittest

from engine.adapters.simulator import replay, replay_scenario, scenario_snapshots
from engine.report import CareReportLog, report_for_session
from engine.session import CareSession


def _run(name):
    session = CareSession()
    replay_scenario(session, name)
    return session


def _run_without_timestamps(name):
    """시나리오 스냅샷의 시각을 전부 None으로 바꿔 재생한 세션.

    소요시간은 전이 시각 차이로만 계산되므로, 이렇게 재생하면
    온도도 소요시간도 없는 리포트가 된다(65회차 QA와 같은 방식).
    """
    session = CareSession()
    snapshots = [
        dataclasses.replace(snapshot, timestamp=None)
        for snapshot in scenario_snapshots(name)
    ]
    replay(session, snapshots)
    return session


def _mixed_log():
    """고정 시나리오 3종 + 빈 세션 1개를 누적한 로그."""
    log = CareReportLog()
    sessions = [
        _run("dropoff_normal"),
        _run("forgotten_rising_temp"),
        _run("pet_dropoff"),
        CareSession(),
    ]
    log.add_sessions(sessions)
    return log


class MixedLogAggregationsTest(unittest.TestCase):
    def test_all_aggregations_at_once(self):
        log = _mixed_log()

        self.assertEqual(len(log), 4)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.incomplete_count, 2)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.sessions_without_exception, 3)

        # 예외·전이 집계는 빈 세션의 0까지 모든 리포트를 대상으로 한다.
        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(log.max_exception_count, 1)
        self.assertEqual(log.min_exception_count, 0)
        self.assertEqual(log.average_exception_count, 0.25)
        self.assertEqual(log.total_transition_count, 17)
        self.assertEqual(log.max_transition_count, 6)
        self.assertEqual(log.min_transition_count, 0)
        self.assertEqual(log.average_transition_count, 4.25)

        # 온도 집계는 온도가 있는 리포트(하차 깜빡 1건)만 대상이다.
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.min_cabin_temp_c, 35.5)
        self.assertEqual(log.average_cabin_temp_c, 35.5)
        self.assertEqual(log.total_cabin_temp_c, 35.5)

        # 소요시간 집계는 소요시간이 있는 리포트(시나리오 3건)만 대상이다.
        self.assertEqual(log.total_duration_seconds, 840.0)
        self.assertEqual(log.max_duration_seconds, 300.0)
        self.assertEqual(log.min_duration_seconds, 240.0)
        self.assertEqual(log.average_duration_seconds, 280.0)

    def test_aggregation_consistency_invariants(self):
        log = _mixed_log()

        self.assertEqual(
            log.completed_count + log.incomplete_count, len(log)
        )
        self.assertEqual(
            log.sessions_with_exception + log.sessions_without_exception,
            len(log),
        )
        self.assertEqual(len(log.completed_reports), log.completed_count)
        self.assertEqual(
            len(log.exception_reports), log.sessions_with_exception
        )
        self.assertEqual(
            len(log.reports_without_exception),
            log.sessions_without_exception,
        )
        self.assertEqual(len(log.incomplete_reports), log.incomplete_count)

        self.assertEqual(
            log.average_exception_count,
            log.total_exception_count / len(log),
        )
        self.assertEqual(
            log.average_transition_count,
            log.total_transition_count / len(log),
        )
        # 소요시간 평균의 분모는 전체가 아니라 값이 있는 리포트 수(3)다.
        self.assertEqual(
            log.average_duration_seconds, log.total_duration_seconds / 3
        )

        self.assertGreaterEqual(
            log.max_exception_count, log.min_exception_count
        )
        self.assertGreaterEqual(
            log.max_transition_count, log.min_transition_count
        )
        self.assertGreaterEqual(log.max_cabin_temp_c, log.min_cabin_temp_c)
        self.assertGreaterEqual(
            log.max_duration_seconds, log.min_duration_seconds
        )


class EmptyLogAggregationsTest(unittest.TestCase):
    def test_empty_log(self):
        log = CareReportLog()

        self.assertEqual(len(log), 0)
        self.assertEqual(log.completed_count, 0)
        self.assertEqual(log.incomplete_count, 0)
        self.assertEqual(log.sessions_with_exception, 0)
        self.assertEqual(log.sessions_without_exception, 0)
        self.assertEqual(log.total_exception_count, 0)
        self.assertEqual(log.total_transition_count, 0)

        self.assertIsNone(log.max_exception_count)
        self.assertIsNone(log.min_exception_count)
        self.assertIsNone(log.average_exception_count)
        self.assertIsNone(log.max_transition_count)
        self.assertIsNone(log.min_transition_count)
        self.assertIsNone(log.average_transition_count)
        self.assertIsNone(log.max_cabin_temp_c)
        self.assertIsNone(log.min_cabin_temp_c)
        self.assertIsNone(log.average_cabin_temp_c)
        self.assertIsNone(log.total_cabin_temp_c)
        self.assertIsNone(log.total_duration_seconds)
        self.assertIsNone(log.max_duration_seconds)
        self.assertIsNone(log.min_duration_seconds)
        self.assertIsNone(log.average_duration_seconds)

        self.assertEqual(log.completed_reports, ())
        self.assertEqual(log.exception_reports, ())
        self.assertEqual(log.reports_without_exception, ())
        self.assertEqual(log.incomplete_reports, ())


class SingleReportAggregationsTest(unittest.TestCase):
    def test_single_forgotten_report(self):
        log = CareReportLog()
        log.add_session(_run("forgotten_rising_temp"))

        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(log.max_exception_count, 1)
        self.assertEqual(log.min_exception_count, 1)
        self.assertEqual(log.average_exception_count, 1.0)
        self.assertEqual(log.total_transition_count, 5)
        self.assertEqual(log.max_transition_count, 5)
        self.assertEqual(log.min_transition_count, 5)
        self.assertEqual(log.average_transition_count, 5.0)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.min_cabin_temp_c, 35.5)
        self.assertEqual(log.average_cabin_temp_c, 35.5)
        self.assertEqual(log.total_cabin_temp_c, 35.5)
        self.assertEqual(log.total_duration_seconds, 240.0)
        self.assertEqual(log.max_duration_seconds, 240.0)
        self.assertEqual(log.min_duration_seconds, 240.0)
        self.assertEqual(log.average_duration_seconds, 240.0)


class DuplicateReportAggregationsTest(unittest.TestCase):
    def test_same_report_added_twice(self):
        report = report_for_session(_run("forgotten_rising_temp"))
        log = CareReportLog()
        log.add_report(report)
        log.add_report(report)

        self.assertEqual(len(log), 2)
        # 합계는 2배가 되고 최대·최소·평균은 단일일 때와 같다.
        self.assertEqual(log.total_exception_count, 2)
        self.assertEqual(log.total_transition_count, 10)
        self.assertEqual(log.total_cabin_temp_c, 71.0)
        self.assertEqual(log.total_duration_seconds, 480.0)
        self.assertEqual(log.max_exception_count, 1)
        self.assertEqual(log.min_exception_count, 1)
        self.assertEqual(log.average_exception_count, 1.0)
        self.assertEqual(log.max_transition_count, 5)
        self.assertEqual(log.average_transition_count, 5.0)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.average_cabin_temp_c, 35.5)
        self.assertEqual(log.average_duration_seconds, 240.0)


class NoTempNoDurationAggregationsTest(unittest.TestCase):
    def test_none_exclusion_asymmetry(self):
        log = CareReportLog()
        log.add_sessions(
            [
                _run_without_timestamps("dropoff_normal"),
                _run_without_timestamps("pet_dropoff"),
                CareSession(),
            ]
        )

        # 온도·소요시간이 있는 리포트가 하나도 없으면 그 집계는 전부 None.
        self.assertIsNone(log.max_cabin_temp_c)
        self.assertIsNone(log.min_cabin_temp_c)
        self.assertIsNone(log.average_cabin_temp_c)
        self.assertIsNone(log.total_cabin_temp_c)
        self.assertIsNone(log.total_duration_seconds)
        self.assertIsNone(log.max_duration_seconds)
        self.assertIsNone(log.min_duration_seconds)
        self.assertIsNone(log.average_duration_seconds)

        # 그래도 예외·전이 집계는 숫자로 나온다.
        self.assertEqual(log.total_exception_count, 0)
        self.assertEqual(log.max_exception_count, 0)
        self.assertEqual(log.min_exception_count, 0)
        self.assertEqual(log.average_exception_count, 0.0)
        self.assertEqual(log.total_transition_count, 12)
        self.assertEqual(log.max_transition_count, 6)
        self.assertEqual(log.min_transition_count, 0)
        self.assertEqual(log.average_transition_count, 4.0)


if __name__ == "__main__":
    unittest.main()

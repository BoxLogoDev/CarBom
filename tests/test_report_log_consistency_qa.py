"""케어 리포트 누적함 집계 일관성 QA.

집계 절대값과 평균, 온도·소요시간 None 비대칭은
tests/test_report_aggregations_integration_qa.py가 검증한다.
이 파일은 그 파일이 다루지 않는 일관성 각도를 검증한다.
세 쌍의 여집합 분할 합이 전체와 같은지 본다.
필터 길이와 카운트가 일치하고 분할이 서로소이며 합집합이 전체인지 본다.
log.reports를 직접 순회해 재계산한 값이 각 속성과 같은지 본다.
기대값은 고정 시나리오 3종과 빈 세션, 부분 세션, 회복 세션을 실측한 값이다.
"""

import unittest
from collections import Counter

from engine.adapters.simulator import (
    dropoff_normal_snapshots,
    forgotten_rising_temp_snapshots,
    replay,
    replay_scenario,
)
from engine.report import CareReportLog, report_for_session
from engine.session import CareSession
from engine.signals import DoorState, IgnitionState, LockState, SignalSnapshot


def _run(name):
    session = CareSession()
    replay_scenario(session, name)
    return session


def _partial_driving_session():
    session = CareSession()
    replay(session, dropoff_normal_snapshots()[:3])
    return session


def _recovered_session():
    session = CareSession()
    replay(session, forgotten_rising_temp_snapshots())
    session.apply_snapshot(
        SignalSnapshot(
            rear_door=DoorState.OPEN,
            rear_seat_belt_buckled=True,
            ignition=IgnitionState.OFF,
            cabin_temp_c=35.5,
            lock=LockState.UNLOCKED,
            timestamp=480.0,
        )
    )
    session.apply_snapshot(
        SignalSnapshot(
            rear_door=DoorState.OPEN,
            rear_seat_belt_buckled=False,
            ignition=IgnitionState.OFF,
            cabin_temp_c=35.5,
            lock=LockState.UNLOCKED,
            timestamp=540.0,
        )
    )
    session.apply_snapshot(
        SignalSnapshot(
            rear_door=DoorState.CLOSED,
            rear_seat_belt_buckled=False,
            ignition=IgnitionState.OFF,
            cabin_temp_c=35.5,
            lock=LockState.UNLOCKED,
            timestamp=600.0,
        )
    )
    return session


def _log_from_sessions(sessions):
    log = CareReportLog()
    log.add_sessions(sessions)
    return log


def _fixed_log():
    return _log_from_sessions(
        [
            _run("dropoff_normal"),
            _run("forgotten_rising_temp"),
            _run("pet_dropoff"),
        ]
    )


def _mixed_six_log():
    return _log_from_sessions(
        [
            _run("dropoff_normal"),
            _run("forgotten_rising_temp"),
            _run("pet_dropoff"),
            CareSession(),
            _partial_driving_session(),
            _recovered_session(),
        ]
    )


def _filter_lengths(log):
    return (
        len(log.completed_reports),
        len(log.incomplete_reports),
        len(log.exception_reports),
        len(log.reports_without_exception),
        len(log.reports_with_passenger),
        len(log.reports_without_passenger),
    )


def _counts(log):
    return (
        log.completed_count,
        log.incomplete_count,
        log.sessions_with_exception,
        log.sessions_without_exception,
        log.sessions_with_passenger,
        log.sessions_without_passenger,
    )


class ReportLogConsistencyQaTest(unittest.TestCase):
    def test_empty_log_partitions_are_all_zero(self):
        log = CareReportLog()

        self.assertEqual(len(log), 0)
        self.assertEqual(log.completed_count, 0)
        self.assertEqual(log.incomplete_count, 0)
        self.assertEqual(log.completed_count + log.incomplete_count, 0)
        self.assertEqual(log.sessions_with_exception, 0)
        self.assertEqual(log.sessions_without_exception, 0)
        self.assertEqual(
            log.sessions_with_exception + log.sessions_without_exception, 0
        )
        self.assertEqual(log.sessions_with_passenger, 0)
        self.assertEqual(log.sessions_without_passenger, 0)
        self.assertEqual(
            log.sessions_with_passenger + log.sessions_without_passenger, 0
        )
        self.assertEqual(log.total_transition_count, 0)
        self.assertEqual(log.total_exception_count, 0)
        self.assertEqual(log.completed_reports, ())
        self.assertEqual(log.incomplete_reports, ())
        self.assertEqual(log.exception_reports, ())
        self.assertEqual(log.reports_without_exception, ())
        self.assertEqual(log.reports_with_passenger, ())
        self.assertEqual(log.reports_without_passenger, ())

    def test_fixed_scenarios_partition_sums(self):
        log = _fixed_log()

        self.assertEqual(len(log), 3)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.incomplete_count, 1)
        self.assertEqual(log.completed_count + log.incomplete_count, 3)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.sessions_without_exception, 2)
        self.assertEqual(
            log.sessions_with_exception + log.sessions_without_exception, 3
        )
        self.assertEqual(log.sessions_with_passenger, 1)
        self.assertEqual(log.sessions_without_passenger, 2)
        self.assertEqual(
            log.sessions_with_passenger + log.sessions_without_passenger, 3
        )
        self.assertEqual(log.total_transition_count, 17)
        self.assertEqual(
            log.total_transition_count,
            sum(report.transition_count for report in log.reports),
        )
        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(
            log.total_exception_count,
            sum(report.exception_count for report in log.reports),
        )
        self.assertEqual(_filter_lengths(log), _counts(log))

    def test_mixed_six_partition_sums(self):
        log = _mixed_six_log()

        self.assertEqual(len(log), 6)
        self.assertEqual(log.completed_count, 3)
        self.assertEqual(log.incomplete_count, 3)
        self.assertEqual(log.completed_count + log.incomplete_count, 6)
        self.assertEqual(log.sessions_with_exception, 2)
        self.assertEqual(log.sessions_without_exception, 4)
        self.assertEqual(
            log.sessions_with_exception + log.sessions_without_exception, 6
        )
        self.assertEqual(log.sessions_with_passenger, 2)
        self.assertEqual(log.sessions_without_passenger, 4)
        self.assertEqual(
            log.sessions_with_passenger + log.sessions_without_passenger, 6
        )
        self.assertEqual(log.total_transition_count, 27)
        self.assertEqual(log.total_exception_count, 2)
        self.assertEqual(_filter_lengths(log), _counts(log))

    def test_duplicate_report_is_not_deduplicated(self):
        report = report_for_session(_run("forgotten_rising_temp"))
        log = CareReportLog()
        log.add_report(report)
        log.add_report(report)

        self.assertEqual(len(log), 2)
        self.assertEqual(log.completed_count, 0)
        self.assertEqual(log.incomplete_count, 2)
        self.assertEqual(log.completed_count + log.incomplete_count, 2)
        self.assertEqual(log.sessions_with_exception, 2)
        self.assertEqual(log.sessions_without_exception, 0)
        self.assertEqual(
            log.sessions_with_exception + log.sessions_without_exception, 2
        )
        self.assertEqual(log.sessions_with_passenger, 2)
        self.assertEqual(log.sessions_without_passenger, 0)
        self.assertEqual(
            log.sessions_with_passenger + log.sessions_without_passenger, 2
        )
        self.assertEqual(log.total_transition_count, 10)
        self.assertEqual(log.total_exception_count, 2)

    def test_recomputed_values_match_log_attributes(self):
        cases = (
            ("empty", CareReportLog()),
            ("single_dropoff", _log_from_sessions([_run("dropoff_normal")])),
            (
                "single_forgotten",
                _log_from_sessions([_run("forgotten_rising_temp")]),
            ),
            ("fixed_three", _fixed_log()),
            ("mixed_six", _mixed_six_log()),
        )
        for case, log in cases:
            with self.subTest(case=case):
                reports = log.reports
                completed = sum(1 for report in reports if report.completed)
                incomplete = sum(
                    1 for report in reports if not report.completed
                )
                with_exception = sum(
                    1 for report in reports if report.exception_occurred
                )
                without_exception = sum(
                    1 for report in reports if not report.exception_occurred
                )
                with_passenger = sum(
                    1 for report in reports if report.passenger_present
                )
                without_passenger = sum(
                    1 for report in reports if not report.passenger_present
                )

                self.assertEqual(len(reports), len(log))
                self.assertEqual(completed, log.completed_count)
                self.assertEqual(incomplete, log.incomplete_count)
                self.assertEqual(with_exception, log.sessions_with_exception)
                self.assertEqual(
                    without_exception, log.sessions_without_exception
                )
                self.assertEqual(with_passenger, log.sessions_with_passenger)
                self.assertEqual(
                    without_passenger, log.sessions_without_passenger
                )
                self.assertEqual(completed + incomplete, len(log))
                self.assertEqual(with_exception + without_exception, len(log))
                self.assertEqual(with_passenger + without_passenger, len(log))
                self.assertEqual(
                    sum(report.transition_count for report in reports),
                    log.total_transition_count,
                )
                self.assertEqual(
                    sum(report.exception_count for report in reports),
                    log.total_exception_count,
                )
                self.assertEqual(len(log.completed_reports), completed)
                self.assertEqual(len(log.incomplete_reports), incomplete)
                self.assertEqual(len(log.exception_reports), with_exception)
                self.assertEqual(
                    len(log.reports_without_exception), without_exception
                )
                self.assertEqual(len(log.reports_with_passenger), with_passenger)
                self.assertEqual(
                    len(log.reports_without_passenger), without_passenger
                )

    def test_partitions_are_disjoint_and_queries_do_not_mutate(self):
        log = _mixed_six_log()
        partitions = (
            (log.completed_reports, log.incomplete_reports),
            (log.exception_reports, log.reports_without_exception),
            (log.reports_with_passenger, log.reports_without_passenger),
        )
        all_ids = Counter(id(report) for report in log.reports)

        for left, right in partitions:
            left_ids = {id(report) for report in left}
            right_ids = {id(report) for report in right}
            self.assertTrue(left_ids.isdisjoint(right_ids))
            self.assertEqual(len(left_ids | right_ids), len(log))
            self.assertEqual(
                Counter(id(report) for report in left + right), all_ids
            )

        reports_before = log.reports
        ids_before = [id(report) for report in reports_before]
        counts_before = _counts(log)
        totals_before = (log.total_transition_count, log.total_exception_count)

        for _ in range(3):
            _filter_lengths(log)
            _counts(log)
            log.reports
            log.total_transition_count
            log.total_exception_count

        self.assertEqual(log.reports, reports_before)
        self.assertEqual(
            [id(report) for report in log.reports], ids_before
        )
        self.assertEqual(len(log), len(reports_before))
        self.assertEqual(_counts(log), counts_before)
        self.assertEqual(
            (log.total_transition_count, log.total_exception_count),
            totals_before,
        )
        self.assertEqual(_filter_lengths(log), counts_before)


if __name__ == "__main__":
    unittest.main()

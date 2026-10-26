"""케어 리포트 경계 조건 QA 테스트.

기존 tests/test_report.py 가 다루지 않은 각도:
- 타임스탬프가 앞/뒤 한쪽만 있는 부분 기록에서의 duration 처리
- 전이 1건일 때 duration 이 None 이 아니라 0.0 인 점
- CareReport frozen 불변성
- 현재 스냅샷 온도가 전이 이력보다 높을 때 max 반영
- CareReportLog.reports 복사본 격리와 중복 추가 집계
"""

import dataclasses
import unittest

from engine import (
    CareReport,
    CareReportLog,
    CareSession,
    DoorState,
    IgnitionState,
    LockState,
    SessionState,
    SignalSnapshot,
    report_for_session,
)


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


def board(session, first_ts, second_ts):
    session.apply_snapshot(
        snapshot(rear_door=DoorState.OPEN, timestamp=first_ts)
    )
    session.apply_snapshot(
        snapshot(rear_seat_belt_buckled=True, timestamp=second_ts)
    )


class ReportPartialTimestampTest(unittest.TestCase):
    def test_duration_none_when_only_first_timestamp_present(self):
        session = CareSession()
        board(session, 1000.0, 1010.0)
        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                timestamp=None,
            )
        )

        report = report_for_session(session)

        self.assertEqual(report.final_state, SessionState.DRIVING)
        self.assertEqual(report.transition_count, 3)
        self.assertEqual(report.started_at, 1000.0)
        self.assertIsNone(report.ended_at)
        self.assertIsNone(report.duration_seconds)

    def test_duration_none_when_only_last_timestamp_present(self):
        session = CareSession()
        board(session, None, None)
        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                timestamp=1030.0,
            )
        )

        report = report_for_session(session)

        self.assertEqual(report.final_state, SessionState.DRIVING)
        self.assertEqual(report.transition_count, 3)
        self.assertIsNone(report.started_at)
        self.assertEqual(report.ended_at, 1030.0)
        self.assertIsNone(report.duration_seconds)

    def test_single_transition_duration_is_zero_not_none(self):
        session = CareSession()
        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=500.0)
        )

        report = report_for_session(session)

        self.assertEqual(report.transition_count, 1)
        self.assertEqual(report.started_at, 500.0)
        self.assertEqual(report.ended_at, 500.0)
        self.assertIsNotNone(report.duration_seconds)
        self.assertEqual(report.duration_seconds, 0.0)


class ReportImmutabilityAndCurrentTempTest(unittest.TestCase):
    def test_report_is_frozen(self):
        report = report_for_session(CareSession())

        with self.assertRaises(dataclasses.FrozenInstanceError):
            report.completed = True  # type: ignore[misc]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            report.max_cabin_temp_c = 99.0  # type: ignore[misc]

    def test_max_temp_comes_from_current_snapshot_without_transition(self):
        session = CareSession()
        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                cabin_temp_c=24.0,
                timestamp=1000.0,
            )
        )
        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                cabin_temp_c=26.0,
                timestamp=1010.0,
            )
        )
        transitions_before = len(session.history)
        # ONBOARD에서 같은 신호를 다시 주면 전이는 없고 현재 스냅샷만 갱신된다.
        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                cabin_temp_c=36.5,
                timestamp=1020.0,
            )
        )

        report = report_for_session(session)

        self.assertEqual(len(session.history), transitions_before)
        self.assertEqual(report.transition_count, transitions_before)
        self.assertEqual(report.max_cabin_temp_c, 36.5)


def make_report(**overrides):
    values = {
        "final_state": SessionState.COMPLETED,
        "completed": True,
        "exception_occurred": True,
        "exception_count": 1,
        "transition_count": 5,
        "passenger_present": False,
        "started_at": 1000.0,
        "ended_at": 1120.0,
        "duration_seconds": 120.0,
        "max_cabin_temp_c": 30.0,
        "transitions": (),
    }
    values.update(overrides)
    return CareReport(**values)


class ReportLogCopyIsolationTest(unittest.TestCase):
    def test_reports_tuple_is_isolated_from_later_adds(self):
        log = CareReportLog()
        first_report = make_report()
        log.add_report(first_report)

        taken = log.reports
        log.add_report(make_report(exception_count=2))

        self.assertEqual(taken, (first_report,))
        self.assertEqual(len(taken), 1)
        self.assertEqual(len(log.reports), 2)
        self.assertEqual(log.reports[0], first_report)

    def test_adding_same_report_twice_counts_twice(self):
        log = CareReportLog()
        report = make_report()

        log.add_report(report)
        log.add_report(report)

        self.assertEqual(len(log), 2)
        self.assertEqual(log.reports, (report, report))
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 2)
        self.assertEqual(log.total_exception_count, 2)
        self.assertEqual(log.max_cabin_temp_c, 30.0)
        self.assertEqual(log.average_duration_seconds, 120.0)


if __name__ == "__main__":
    unittest.main()

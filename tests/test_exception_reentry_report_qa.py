"""EXCEPTION 재진입 세션과 케어 리포트·누적 집계·안내의 교차 검증.

기존 tests/test_exception_reentry_qa.py는 재진입 세션의 상태 전이와
단일 리포트의 exception_count만 다루고,
tests/test_report_aggregations_integration_qa.py는 재진입 없는
세션들의 누적 집계만 다룬다. 이 파일은 그 사이 교차 지점 —
예외를 두 번 이상 겪은 세션의 리포트가 CareReportLog 집계와
필터, 소요 시간 제외 규약, 안내와 어떻게 맞물리는지 — 를 검증한다.
"""

import unittest

from engine import (
    CareReportLog,
    CareSession,
    DoorState,
    GuidanceLevel,
    IgnitionState,
    LockState,
    SessionState,
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


def board_and_drive(session):
    session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
    session.apply_snapshot(snapshot(rear_seat_belt_buckled=True))
    session.apply_snapshot(
        snapshot(rear_seat_belt_buckled=True, ignition=IgnitionState.ON)
    )


def arrive(session):
    session.apply_snapshot(snapshot(rear_seat_belt_buckled=True))


def enter_exception(session):
    session.apply_snapshot(
        snapshot(rear_seat_belt_buckled=True, lock=LockState.LOCKED)
    )


def recover_to_driving(session):
    session.apply_snapshot(
        snapshot(rear_seat_belt_buckled=True, ignition=IgnitionState.ON)
    )


def drive_to_second_exception(session):
    board_and_drive(session)
    arrive(session)
    enter_exception(session)
    recover_to_driving(session)
    arrive(session)
    enter_exception(session)


def recovered_reentry_session():
    session = CareSession()
    drive_to_second_exception(session)
    session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
    session.apply_snapshot(snapshot())
    return session


def mixed_log():
    session_a = recovered_reentry_session()
    session_b = CareSession()
    replay_scenario(session_b, "dropoff_normal")
    session_c = CareSession()
    replay_scenario(session_c, "forgotten_rising_temp")
    log = CareReportLog()
    reports = log.add_sessions([session_a, session_b, session_c])
    return log, reports


class ExceptionReentryReportQaTest(unittest.TestCase):
    def test_second_exception_unresolved_report(self):
        session = CareSession()
        drive_to_second_exception(session)
        self.assertEqual(session.state, SessionState.EXCEPTION)

        report = report_for_session(session)

        self.assertEqual(report.final_state, SessionState.EXCEPTION)
        self.assertFalse(report.completed)
        self.assertTrue(report.exception_occurred)
        self.assertEqual(report.exception_count, 2)
        self.assertEqual(report.transition_count, 9)
        self.assertEqual(report.transition_count, len(session.history))
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_third_reentry_counts_three(self):
        session = CareSession()
        drive_to_second_exception(session)
        recover_to_driving(session)
        arrive(session)
        enter_exception(session)
        self.assertEqual(session.state, SessionState.EXCEPTION)

        report = report_for_session(session)

        self.assertEqual(report.exception_count, 3)
        self.assertEqual(report.transition_count, 13)
        self.assertEqual(report.transition_count, len(session.history))

    def test_second_exception_guidance_is_urgent(self):
        session = CareSession()
        drive_to_second_exception(session)

        guidance = guidance_for_session(session)

        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.reason, "passenger_left_locked")

    def test_reentry_log_aggregations(self):
        log, reports = mixed_log()

        self.assertEqual(
            [report.exception_count for report in reports], [2, 0, 1]
        )
        self.assertEqual(
            [report.transition_count for report in reports], [11, 6, 5]
        )
        self.assertEqual(len(log), 3)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.incomplete_count, 1)
        self.assertEqual(log.sessions_with_exception, 2)
        self.assertEqual(log.sessions_without_exception, 1)
        self.assertEqual(log.total_exception_count, 3)
        self.assertEqual(log.max_exception_count, 2)
        self.assertEqual(log.min_exception_count, 0)
        self.assertEqual(log.average_exception_count, 1.0)
        self.assertEqual(log.total_transition_count, 22)
        self.assertEqual(log.max_transition_count, 11)
        self.assertEqual(log.min_transition_count, 5)
        self.assertEqual(log.average_transition_count, 22 / 3)

    def test_reentry_report_in_both_filters(self):
        log, reports = mixed_log()
        report_a = reports[0]

        self.assertIn(report_a, log.completed_reports)
        self.assertIn(report_a, log.exception_reports)
        self.assertEqual(len(log.exception_reports), 2)
        self.assertEqual(len(log.completed_reports), 2)
        self.assertEqual(len(log.incomplete_reports), 1)

    def test_reentry_duration_excluded_from_log_duration(self):
        log, reports = mixed_log()

        self.assertIsNone(reports[0].duration_seconds)
        self.assertEqual(reports[1].duration_seconds, 300.0)
        self.assertEqual(reports[2].duration_seconds, 240.0)
        self.assertEqual(log.total_duration_seconds, 540.0)
        self.assertEqual(log.average_duration_seconds, 270.0)


if __name__ == "__main__":
    unittest.main()

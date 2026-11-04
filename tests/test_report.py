"""케어 리포트의 단위 테스트."""

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
    reports_for_sessions,
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


def board_and_drive(session, start=1000.0):
    session.apply_snapshot(
        snapshot(rear_door=DoorState.OPEN, timestamp=start)
    )
    session.apply_snapshot(
        snapshot(rear_seat_belt_buckled=True, timestamp=start + 10.0)
    )
    session.apply_snapshot(
        snapshot(
            rear_seat_belt_buckled=True,
            ignition=IgnitionState.ON,
            timestamp=start + 20.0,
        )
    )


def drive_to_exception(session, start=1000.0):
    board_and_drive(session, start=start)
    session.apply_snapshot(
        snapshot(rear_seat_belt_buckled=True, timestamp=start + 100.0)
    )
    session.apply_snapshot(
        snapshot(
            rear_seat_belt_buckled=True,
            lock=LockState.LOCKED,
            timestamp=start + 110.0,
        )
    )


def complete_normally(session, start=1000.0):
    board_and_drive(session, start=start)
    session.apply_snapshot(
        snapshot(rear_seat_belt_buckled=True, timestamp=start + 100.0)
    )
    session.apply_snapshot(
        snapshot(rear_door=DoorState.OPEN, timestamp=start + 110.0)
    )
    session.apply_snapshot(snapshot(timestamp=start + 120.0))


class CareReportTest(unittest.TestCase):
    def test_empty_session(self):
        report = report_for_session(CareSession())

        self.assertEqual(report.final_state, SessionState.IDLE)
        self.assertFalse(report.completed)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 0)
        self.assertFalse(report.passenger_present)
        self.assertIsNone(report.started_at)
        self.assertIsNone(report.ended_at)
        self.assertIsNone(report.duration_seconds)
        self.assertIsNone(report.max_cabin_temp_c)
        self.assertEqual(report.transitions, ())
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_normal_school_run_is_completed(self):
        session = CareSession()
        complete_normally(session, start=1000.0)

        report = report_for_session(session)

        self.assertEqual(report.final_state, SessionState.COMPLETED)
        self.assertTrue(report.completed)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.started_at, 1000.0)
        self.assertEqual(report.ended_at, 1120.0)
        self.assertEqual(report.duration_seconds, 120.0)
        self.assertEqual(report.transition_count, len(session.history))
        self.assertEqual(report.transitions, tuple(session.history))
        self.assertFalse(report.passenger_present)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_forgotten_alighting_recovers_to_completed(self):
        session = CareSession()
        drive_to_exception(session, start=1000.0)
        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=1130.0)
        )
        session.apply_snapshot(snapshot(timestamp=1140.0))

        report = report_for_session(session)

        self.assertEqual(report.final_state, SessionState.COMPLETED)
        self.assertTrue(report.completed)
        self.assertTrue(report.exception_occurred)
        self.assertGreaterEqual(report.exception_count, 1)
        self.assertEqual(report.summary, "예외 발생 후 하차 확인 완료")

    def test_unresolved_exception_is_not_completed(self):
        session = CareSession()
        drive_to_exception(session, start=1000.0)

        report = report_for_session(session)

        self.assertEqual(report.final_state, SessionState.EXCEPTION)
        self.assertFalse(report.completed)
        self.assertTrue(report.exception_occurred)
        self.assertGreaterEqual(report.exception_count, 1)
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_driving_session_is_in_progress(self):
        session = CareSession()
        board_and_drive(session, start=1000.0)

        report = report_for_session(session)

        self.assertEqual(report.final_state, SessionState.DRIVING)
        self.assertFalse(report.completed)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_max_cabin_temp_uses_history_and_current_snapshot(self):
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
                cabin_temp_c=31.5,
                timestamp=1010.0,
            )
        )
        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                cabin_temp_c=28.0,
                timestamp=1020.0,
            )
        )

        report = report_for_session(session)

        self.assertEqual(report.max_cabin_temp_c, 31.5)

    def test_max_cabin_temp_includes_current_snapshot_without_transition(self):
        session = CareSession()
        session.apply_snapshot(snapshot(cabin_temp_c=33.0, timestamp=1000.0))

        report = report_for_session(session)

        self.assertEqual(report.transition_count, 0)
        self.assertEqual(report.max_cabin_temp_c, 33.0)

    def test_max_cabin_temp_is_none_without_any_temp(self):
        session = CareSession()
        board_and_drive(session, start=1000.0)

        report = report_for_session(session)

        self.assertIsNone(report.max_cabin_temp_c)

    def test_duration_is_none_without_timestamps(self):
        session = CareSession()
        session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
        session.apply_snapshot(snapshot(rear_seat_belt_buckled=True))
        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True, ignition=IgnitionState.ON
            )
        )

        report = report_for_session(session)

        self.assertGreater(report.transition_count, 0)
        self.assertIsNone(report.started_at)
        self.assertIsNone(report.ended_at)
        self.assertIsNone(report.duration_seconds)

    def test_report_for_session_does_not_mutate_session(self):
        session = CareSession()
        board_and_drive(session, start=1000.0)
        state_before = session.state
        history_before = list(session.history)
        passenger_before = session.passenger_present
        snapshot_before = session.current_snapshot

        report = report_for_session(session)

        self.assertEqual(session.state, state_before)
        self.assertEqual(session.history, history_before)
        self.assertEqual(session.passenger_present, passenger_before)
        self.assertEqual(session.current_snapshot, snapshot_before)
        self.assertIsInstance(report, CareReport)
        self.assertIsInstance(report.transitions, tuple)

        session.apply_snapshot(
            snapshot(rear_seat_belt_buckled=True, timestamp=1100.0)
        )
        self.assertEqual(report.transition_count, len(history_before))
        self.assertEqual(report.transitions, tuple(history_before))


class CareReportLogTest(unittest.TestCase):
    def test_add_session_accumulates_reports(self):
        completed = CareSession()
        complete_normally(completed, start=1000.0)
        exception = CareSession()
        drive_to_exception(exception, start=2000.0)
        log = CareReportLog()

        first = log.add_session(completed)
        second = log.add_session(exception)

        self.assertIsInstance(first, CareReport)
        self.assertIsInstance(second, CareReport)
        self.assertEqual(len(log), 2)
        self.assertEqual(log.completed_count, 1)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertIsInstance(log.reports, tuple)
        self.assertEqual(log.reports, (first, second))

    def test_add_report_accumulates_reports(self):
        session = CareSession()
        complete_normally(session, start=1000.0)
        report = report_for_session(session)
        log = CareReportLog()

        log.add_report(report)

        self.assertEqual(len(log), 1)
        self.assertEqual(log.completed_count, 1)
        self.assertEqual(log.sessions_with_exception, 0)
        self.assertEqual(log.reports, (report,))


def make_report(**overrides):
    values = {
        "final_state": SessionState.COMPLETED,
        "completed": True,
        "exception_occurred": False,
        "exception_count": 0,
        "transition_count": 0,
        "passenger_present": False,
        "started_at": None,
        "ended_at": None,
        "duration_seconds": None,
        "max_cabin_temp_c": None,
        "transitions": (),
    }
    values.update(overrides)
    if "exception_occurred" not in overrides:
        values["exception_occurred"] = values["exception_count"] > 0
    return CareReport(**values)


class CareReportLogStatsTest(unittest.TestCase):
    def test_empty_log_stats_are_zero_and_none(self):
        log = CareReportLog()

        self.assertEqual(log.total_exception_count, 0)
        self.assertIsNone(log.max_cabin_temp_c)
        self.assertIsNone(log.average_duration_seconds)

    def test_total_exception_count_sums_all_reports(self):
        log = CareReportLog()
        log.add_report(make_report(exception_count=2))
        log.add_report(make_report(exception_count=3))
        log.add_report(make_report(exception_count=0))

        self.assertEqual(log.total_exception_count, 5)

    def test_max_cabin_temp_is_max_across_reports(self):
        log = CareReportLog()
        log.add_report(make_report(max_cabin_temp_c=24.0))
        log.add_report(make_report(max_cabin_temp_c=31.5))
        log.add_report(make_report(max_cabin_temp_c=28.0))

        self.assertEqual(log.max_cabin_temp_c, 31.5)

    def test_max_cabin_temp_ignores_none_temps(self):
        log = CareReportLog()
        log.add_report(make_report(max_cabin_temp_c=None))
        log.add_report(make_report(max_cabin_temp_c=29.0))
        log.add_report(make_report(max_cabin_temp_c=None))

        self.assertEqual(log.max_cabin_temp_c, 29.0)

    def test_max_cabin_temp_is_none_when_all_temps_none(self):
        log = CareReportLog()
        log.add_report(make_report(max_cabin_temp_c=None))
        log.add_report(make_report(max_cabin_temp_c=None))

        self.assertIsNone(log.max_cabin_temp_c)

    def test_average_duration_ignores_none_durations(self):
        log = CareReportLog()
        log.add_report(make_report(duration_seconds=100.0))
        log.add_report(make_report(duration_seconds=None))
        log.add_report(make_report(duration_seconds=200.0))

        self.assertEqual(log.average_duration_seconds, 150.0)

    def test_average_duration_is_none_when_all_durations_none(self):
        log = CareReportLog()
        log.add_report(make_report(duration_seconds=None))
        log.add_report(make_report(duration_seconds=None))

        self.assertIsNone(log.average_duration_seconds)

    def test_stats_from_real_sessions_via_add_session(self):
        normal = CareSession()
        complete_normally(normal, start=1000.0)
        recovered = CareSession()
        drive_to_exception(recovered, start=2000.0)
        recovered.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=2130.0)
        )
        recovered.apply_snapshot(snapshot(timestamp=2140.0))
        log = CareReportLog()

        first = log.add_session(normal)
        second = log.add_session(recovered)

        self.assertTrue(first.completed)
        self.assertTrue(second.completed)
        self.assertTrue(second.exception_occurred)
        self.assertEqual(first.duration_seconds, 120.0)
        self.assertEqual(second.duration_seconds, 140.0)
        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(log.average_duration_seconds, 130.0)
        self.assertIsNone(log.max_cabin_temp_c)


class ReportsForSessionsTest(unittest.TestCase):
    def test_empty_input_returns_empty_tuple(self):
        self.assertEqual(reports_for_sessions([]), ())
        self.assertEqual(reports_for_sessions(()), ())

    def test_converts_sessions_in_order_matching_individual_reports(self):
        completed = CareSession()
        complete_normally(completed, start=1000.0)
        exception = CareSession()
        drive_to_exception(exception, start=2000.0)

        reports = reports_for_sessions([completed, exception])

        self.assertIsInstance(reports, tuple)
        self.assertEqual(len(reports), 2)
        self.assertEqual(reports[0], report_for_session(completed))
        self.assertEqual(reports[1], report_for_session(exception))
        self.assertEqual(reports[0].final_state, SessionState.COMPLETED)
        self.assertTrue(reports[0].completed)
        self.assertFalse(reports[0].exception_occurred)
        self.assertEqual(reports[1].final_state, SessionState.EXCEPTION)
        self.assertFalse(reports[1].completed)
        self.assertTrue(reports[1].exception_occurred)

    def test_does_not_mutate_sessions(self):
        session = CareSession()
        board_and_drive(session, start=1000.0)
        state_before = session.state
        history_before = list(session.history)
        passenger_before = session.passenger_present
        snapshot_before = session.current_snapshot

        reports_for_sessions([session, session])

        self.assertEqual(session.state, state_before)
        self.assertEqual(session.history, history_before)
        self.assertEqual(session.passenger_present, passenger_before)
        self.assertEqual(session.current_snapshot, snapshot_before)

    def test_accepts_generator_input(self):
        completed = CareSession()
        complete_normally(completed, start=1000.0)

        reports = reports_for_sessions(s for s in [completed])

        self.assertEqual(len(reports), 1)
        self.assertTrue(reports[0].completed)

    def test_add_sessions_accumulates_and_returns_reports(self):
        completed = CareSession()
        complete_normally(completed, start=1000.0)
        exception = CareSession()
        drive_to_exception(exception, start=2000.0)
        log = CareReportLog()

        returned = log.add_sessions([completed, exception])

        self.assertIsInstance(returned, tuple)
        self.assertEqual(returned, log.reports)
        self.assertEqual(len(log), 2)
        self.assertEqual(log.completed_count, 1)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.total_exception_count, 1)

    def test_add_sessions_empty_input_leaves_log_unchanged(self):
        log = CareReportLog()
        log.add_session(CareSession())
        reports_before = log.reports

        returned = log.add_sessions([])

        self.assertEqual(returned, ())
        self.assertEqual(len(log), 1)
        self.assertEqual(log.reports, reports_before)


class AddReportsTest(unittest.TestCase):
    def test_empty_input_returns_empty_tuple_and_leaves_log_empty(self):
        log = CareReportLog()

        returned = log.add_reports([])

        self.assertEqual(returned, ())
        self.assertEqual(len(log), 0)
        self.assertEqual(log.reports, ())

    def test_add_reports_preserves_order_and_object_identity(self):
        completed = CareSession()
        complete_normally(completed, start=1000.0)
        exception = CareSession()
        drive_to_exception(exception, start=2000.0)
        first = report_for_session(completed)
        second = report_for_session(exception)
        log = CareReportLog()

        returned = log.add_reports([first, second])

        self.assertIsInstance(returned, tuple)
        self.assertEqual(returned, (first, second))
        self.assertIs(returned[0], first)
        self.assertIs(returned[1], second)
        self.assertEqual(log.reports, (first, second))

    def test_add_reports_accumulates_and_updates_aggregates(self):
        completed = CareSession()
        complete_normally(completed, start=1000.0)
        exception = CareSession()
        drive_to_exception(exception, start=2000.0)
        exception_report = report_for_session(exception)
        log = CareReportLog()

        log.add_reports([report_for_session(completed), exception_report])

        self.assertEqual(len(log), 2)
        self.assertEqual(log.completed_count, 1)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(
            log.total_exception_count, exception_report.exception_count
        )

    def test_add_reports_accepts_generator_input(self):
        completed = CareSession()
        complete_normally(completed, start=1000.0)
        report = report_for_session(completed)
        list_log = CareReportLog()
        generator_log = CareReportLog()

        list_log.add_reports([report])
        returned = generator_log.add_reports(r for r in [report])

        self.assertEqual(returned, (report,))
        self.assertEqual(generator_log.reports, list_log.reports)

    def test_add_reports_empty_input_leaves_nonempty_log_unchanged(self):
        log = CareReportLog()
        log.add_session(CareSession())
        reports_before = log.reports

        returned = log.add_reports([])

        self.assertEqual(returned, ())
        self.assertEqual(len(log), 1)
        self.assertEqual(log.reports, reports_before)

    def test_add_reports_matches_add_sessions_result(self):
        completed = CareSession()
        complete_normally(completed, start=1000.0)
        exception = CareSession()
        drive_to_exception(exception, start=2000.0)
        via_reports = CareReportLog()
        via_sessions = CareReportLog()

        returned = via_reports.add_reports(
            reports_for_sessions([completed, exception])
        )
        via_sessions.add_sessions([completed, exception])

        self.assertEqual(returned, via_sessions.reports)
        self.assertEqual(via_reports.reports, via_sessions.reports)
        self.assertEqual(len(via_reports), len(via_sessions))
        self.assertEqual(
            via_reports.completed_count, via_sessions.completed_count
        )
        self.assertEqual(
            via_reports.sessions_with_exception,
            via_sessions.sessions_with_exception,
        )
        self.assertEqual(
            via_reports.total_exception_count,
            via_sessions.total_exception_count,
        )


class CareReportLogFilterTest(unittest.TestCase):
    def test_empty_log_filters_are_empty_tuples(self):
        log = CareReportLog()

        self.assertEqual(log.completed_reports, ())
        self.assertEqual(log.exception_reports, ())
        self.assertEqual(log.incomplete_reports, ())

    def test_completed_reports_keeps_only_completed_in_order(self):
        completed = CareSession()
        complete_normally(completed, start=1000.0)
        exception = CareSession()
        drive_to_exception(exception, start=2000.0)
        in_progress = CareSession()
        log = CareReportLog()
        returned = log.add_sessions([completed, exception, in_progress])

        self.assertEqual(log.completed_reports, (returned[0],))
        self.assertTrue(log.completed_reports[0].completed)
        self.assertEqual(
            log.completed_reports,
            tuple(r for r in log.reports if r.completed),
        )

    def test_exception_reports_includes_recovered_and_unresolved(self):
        recovered = CareSession()
        drive_to_exception(recovered, start=1000.0)
        recovered.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=1130.0)
        )
        recovered.apply_snapshot(snapshot(timestamp=1140.0))
        unresolved = CareSession()
        drive_to_exception(unresolved, start=2000.0)
        normal = CareSession()
        complete_normally(normal, start=3000.0)
        log = CareReportLog()
        returned = log.add_sessions([recovered, unresolved, normal])

        self.assertEqual(log.exception_reports, (returned[0], returned[1]))
        self.assertTrue(returned[0].completed)
        self.assertTrue(returned[0].exception_occurred)
        # 예외 뒤 회복 완료한 리포트는 완료 필터에도 함께 들어간다.
        self.assertIn(returned[0], log.completed_reports)

    def test_incomplete_reports_is_complement_of_completed(self):
        recovered = CareSession()
        drive_to_exception(recovered, start=1000.0)
        recovered.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=1130.0)
        )
        recovered.apply_snapshot(snapshot(timestamp=1140.0))
        unresolved = CareSession()
        drive_to_exception(unresolved, start=2000.0)
        in_progress = CareSession()
        board_and_drive(in_progress, start=3000.0)
        log = CareReportLog()
        returned = log.add_sessions([recovered, unresolved, in_progress])

        self.assertEqual(log.incomplete_reports, (returned[1], returned[2]))
        self.assertEqual(
            len(log.completed_reports) + len(log.incomplete_reports),
            len(log.reports),
        )

    def test_filters_from_fixed_scenarios_via_add_sessions(self):
        from engine.adapters.simulator import replay_scenario

        sessions = []
        for name in (
            "dropoff_normal",
            "forgotten_rising_temp",
            "pet_dropoff",
        ):
            session = CareSession()
            replay_scenario(session, name)
            sessions.append(session)
        log = CareReportLog()
        returned = log.add_sessions(sessions)

        self.assertEqual(len(log.completed_reports), 2)
        self.assertEqual(len(log.exception_reports), 1)
        self.assertEqual(len(log.incomplete_reports), 1)
        self.assertEqual(log.completed_reports, (returned[0], returned[2]))
        self.assertEqual(log.exception_reports, (returned[1],))
        self.assertEqual(log.incomplete_reports, (returned[1],))
        self.assertEqual(
            log.exception_reports,
            tuple(r for r in log.reports if r.exception_occurred),
        )
        self.assertEqual(
            log.incomplete_reports,
            tuple(r for r in log.reports if not r.completed),
        )

    def test_filter_results_are_isolated_tuples(self):
        completed = CareSession()
        complete_normally(completed, start=1000.0)
        log = CareReportLog()
        log.add_session(completed)

        completed_before = log.completed_reports
        exception_before = log.exception_reports
        incomplete_before = log.incomplete_reports

        self.assertIsInstance(completed_before, tuple)
        self.assertIsInstance(exception_before, tuple)
        self.assertIsInstance(incomplete_before, tuple)

        exception = CareSession()
        drive_to_exception(exception, start=2000.0)
        log.add_session(exception)

        self.assertEqual(completed_before, log.completed_reports)
        self.assertEqual(exception_before, ())
        self.assertEqual(incomplete_before, ())
        self.assertEqual(len(log.exception_reports), 1)
        self.assertEqual(len(log.incomplete_reports), 1)


class CareReportLogIncompleteCountTest(unittest.TestCase):
    def test_empty_log_incomplete_count_is_zero(self):
        log = CareReportLog()

        self.assertEqual(log.incomplete_count, 0)
        self.assertEqual(log.completed_count, 0)
        self.assertEqual(len(log), 0)

    def test_completed_only_reports_have_zero_incomplete_count(self):
        log = CareReportLog()
        log.add_report(make_report())
        log.add_report(make_report(exception_count=1))

        self.assertEqual(log.incomplete_count, 0)
        self.assertEqual(log.completed_count, 2)

    def test_in_progress_only_reports_count_as_incomplete(self):
        log = CareReportLog()
        log.add_report(
            make_report(
                final_state=SessionState.DRIVING,
                completed=False,
            )
        )
        log.add_report(
            make_report(
                final_state=SessionState.BOARDING,
                completed=False,
            )
        )

        self.assertEqual(log.incomplete_count, 2)
        self.assertEqual(log.completed_count, 0)

    def test_mixed_reports_incomplete_count_is_complement(self):
        log = CareReportLog()
        log.add_report(make_report())
        log.add_report(make_report(exception_count=2))
        log.add_report(
            make_report(
                final_state=SessionState.EXCEPTION,
                completed=False,
                exception_count=1,
            )
        )
        log.add_report(
            make_report(
                final_state=SessionState.DRIVING,
                completed=False,
            )
        )

        self.assertEqual(len(log), 4)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.incomplete_count, 2)
        self.assertEqual(log.incomplete_count, len(log) - log.completed_count)
        self.assertEqual(log.incomplete_count, len(log.incomplete_reports))

    def test_duplicate_incomplete_report_counts_twice(self):
        report = make_report(
            final_state=SessionState.EXCEPTION,
            completed=False,
            exception_count=1,
        )
        log = CareReportLog()
        log.add_report(report)
        log.add_report(report)

        self.assertEqual(log.incomplete_count, 2)

    def test_incomplete_count_from_real_sessions(self):
        completed = CareSession()
        complete_normally(completed, start=1000.0)
        unresolved = CareSession()
        drive_to_exception(unresolved, start=2000.0)
        log = CareReportLog()
        log.add_sessions([completed, unresolved])

        self.assertEqual(log.incomplete_count, 1)
        self.assertEqual(log.completed_count, 1)


class CareReportLogTotalTransitionCountTest(unittest.TestCase):
    def test_empty_log_total_transition_count_is_zero(self):
        log = CareReportLog()

        self.assertEqual(log.total_transition_count, 0)

    def test_completed_only_reports_sum_transition_counts(self):
        log = CareReportLog()
        log.add_report(make_report(transition_count=6))
        log.add_report(make_report(transition_count=6))

        self.assertEqual(log.total_transition_count, 12)

    def test_in_progress_only_report_counts_transitions(self):
        log = CareReportLog()
        log.add_report(
            make_report(
                final_state=SessionState.DRIVING,
                completed=False,
                transition_count=2,
            )
        )

        self.assertEqual(log.total_transition_count, 2)

    def test_mixed_reports_match_sum_of_transition_counts(self):
        log = CareReportLog()
        log.add_report(make_report(transition_count=6))
        log.add_report(
            make_report(
                final_state=SessionState.EXCEPTION,
                completed=False,
                exception_count=1,
                transition_count=5,
            )
        )
        log.add_report(
            make_report(
                final_state=SessionState.DRIVING,
                completed=False,
                transition_count=2,
            )
        )
        log.add_report(make_report(transition_count=0))

        self.assertEqual(log.total_transition_count, 13)
        self.assertEqual(
            log.total_transition_count,
            sum(r.transition_count for r in log.reports),
        )

    def test_duplicate_report_counts_twice_without_dedup(self):
        report = make_report(transition_count=4)
        log = CareReportLog()
        log.add_report(report)
        log.add_report(report)

        self.assertEqual(log.total_transition_count, 8)
        self.assertEqual(
            log.total_transition_count, 2 * report.transition_count
        )

    def test_total_transition_count_from_fixed_scenarios(self):
        from engine.adapters.simulator import replay_scenario

        sessions = []
        for name in ("dropoff_normal", "forgotten_rising_temp"):
            session = CareSession()
            replay_scenario(session, name)
            sessions.append(session)
        log = CareReportLog()
        returned = log.add_sessions(sessions)

        self.assertEqual(returned[0].transition_count, 6)
        self.assertEqual(returned[1].transition_count, 5)
        self.assertEqual(log.total_transition_count, 11)


class CareReportLogSessionsWithoutExceptionTest(unittest.TestCase):
    def test_empty_log_sessions_without_exception_is_zero(self):
        log = CareReportLog()

        self.assertEqual(log.sessions_without_exception, 0)
        self.assertEqual(log.sessions_with_exception, 0)
        self.assertEqual(len(log), 0)

    def test_exception_free_only_reports_count_all(self):
        log = CareReportLog()
        log.add_report(make_report())
        log.add_report(
            make_report(
                final_state=SessionState.DRIVING,
                completed=False,
            )
        )

        self.assertEqual(log.sessions_without_exception, 2)
        self.assertEqual(log.sessions_with_exception, 0)

    def test_exception_only_reports_have_zero_without_exception(self):
        log = CareReportLog()
        log.add_report(make_report(exception_count=1))
        log.add_report(
            make_report(
                final_state=SessionState.EXCEPTION,
                completed=False,
                exception_count=1,
            )
        )

        self.assertEqual(log.sessions_without_exception, 0)
        self.assertEqual(log.sessions_with_exception, 2)

    def test_mixed_reports_split_between_with_and_without_exception(self):
        log = CareReportLog()
        log.add_report(make_report())
        log.add_report(make_report(exception_count=2))
        log.add_report(
            make_report(
                final_state=SessionState.EXCEPTION,
                completed=False,
                exception_count=1,
            )
        )
        log.add_report(
            make_report(
                final_state=SessionState.DRIVING,
                completed=False,
            )
        )

        self.assertEqual(len(log), 4)
        self.assertEqual(log.sessions_without_exception, 2)
        self.assertEqual(log.sessions_with_exception, 2)
        self.assertEqual(
            log.sessions_without_exception + log.sessions_with_exception,
            len(log),
        )

    def test_duplicate_exception_free_report_counts_twice(self):
        report = make_report()
        log = CareReportLog()
        log.add_report(report)
        log.add_report(report)

        self.assertEqual(log.sessions_without_exception, 2)

    def test_sessions_without_exception_from_fixed_scenarios(self):
        from engine.adapters.simulator import replay_scenario

        sessions = []
        for name in (
            "dropoff_normal",
            "forgotten_rising_temp",
            "pet_dropoff",
        ):
            session = CareSession()
            replay_scenario(session, name)
            sessions.append(session)
        log = CareReportLog()
        log.add_sessions(sessions)

        self.assertEqual(log.sessions_without_exception, 2)
        self.assertEqual(log.sessions_with_exception, 1)


class CareReportLogTotalDurationSecondsTest(unittest.TestCase):
    def test_empty_log_total_duration_is_none(self):
        log = CareReportLog()

        self.assertIsNone(log.total_duration_seconds)
        self.assertIsNone(log.average_duration_seconds)

    def test_total_duration_sums_durations(self):
        log = CareReportLog()
        log.add_report(make_report(duration_seconds=300.0))
        log.add_report(make_report(duration_seconds=240.0))

        self.assertEqual(log.total_duration_seconds, 540.0)

    def test_total_duration_ignores_none_durations(self):
        log = CareReportLog()
        log.add_report(make_report(duration_seconds=300.0))
        log.add_report(make_report(duration_seconds=None))
        log.add_report(make_report(duration_seconds=240.0))

        self.assertEqual(log.total_duration_seconds, 540.0)

    def test_total_duration_is_none_when_all_durations_none(self):
        log = CareReportLog()
        log.add_report(make_report(duration_seconds=None))
        log.add_report(make_report(duration_seconds=None))

        self.assertIsNone(log.total_duration_seconds)

    def test_duplicate_report_counts_twice_without_dedup(self):
        report = make_report(duration_seconds=300.0)
        log = CareReportLog()
        log.add_report(report)
        log.add_report(report)

        self.assertEqual(log.total_duration_seconds, 600.0)

    def test_total_duration_from_fixed_scenarios(self):
        from engine.adapters.simulator import replay_scenario

        sessions = []
        for name in (
            "dropoff_normal",
            "forgotten_rising_temp",
            "pet_dropoff",
        ):
            session = CareSession()
            replay_scenario(session, name)
            sessions.append(session)
        log = CareReportLog()
        returned = log.add_sessions(sessions)

        self.assertEqual(returned[0].duration_seconds, 300.0)
        self.assertEqual(returned[1].duration_seconds, 240.0)
        self.assertEqual(returned[2].duration_seconds, 300.0)
        self.assertEqual(log.total_duration_seconds, 840.0)
        self.assertEqual(
            log.total_duration_seconds,
            log.average_duration_seconds * 3,
        )


class CareReportLogMaxDurationSecondsTest(unittest.TestCase):
    def test_empty_log_max_duration_is_none(self):
        log = CareReportLog()

        self.assertIsNone(log.max_duration_seconds)
        self.assertIsNone(log.total_duration_seconds)
        self.assertIsNone(log.average_duration_seconds)

    def test_max_duration_picks_largest_duration(self):
        log = CareReportLog()
        log.add_report(make_report(duration_seconds=300.0))
        log.add_report(make_report(duration_seconds=240.0))

        self.assertEqual(log.max_duration_seconds, 300.0)

    def test_max_duration_ignores_none_durations(self):
        log = CareReportLog()
        log.add_report(make_report(duration_seconds=None))
        log.add_report(make_report(duration_seconds=300.0))
        log.add_report(make_report(duration_seconds=240.0))

        self.assertEqual(log.max_duration_seconds, 300.0)

    def test_max_duration_is_none_when_all_durations_none(self):
        log = CareReportLog()
        log.add_report(make_report(duration_seconds=None))
        log.add_report(make_report(duration_seconds=None))

        self.assertIsNone(log.max_duration_seconds)

    def test_duplicate_report_max_stays_and_lookup_does_not_mutate(self):
        report = make_report(duration_seconds=300.0)
        log = CareReportLog()
        log.add_report(report)
        log.add_report(report)
        reports_before = log.reports

        self.assertEqual(log.max_duration_seconds, 300.0)
        self.assertEqual(log.max_duration_seconds, 300.0)
        self.assertEqual(log.reports, reports_before)
        self.assertEqual(len(log), 2)

    def test_max_duration_from_fixed_scenarios(self):
        from engine.adapters.simulator import replay_scenario

        sessions = []
        for name in (
            "dropoff_normal",
            "forgotten_rising_temp",
            "pet_dropoff",
        ):
            session = CareSession()
            replay_scenario(session, name)
            sessions.append(session)
        log = CareReportLog()
        returned = log.add_sessions(sessions)

        self.assertEqual(returned[0].duration_seconds, 300.0)
        self.assertEqual(returned[1].duration_seconds, 240.0)
        self.assertEqual(returned[2].duration_seconds, 300.0)
        self.assertEqual(log.max_duration_seconds, 300.0)
        self.assertEqual(log.total_duration_seconds, 840.0)


class CareReportLogMinDurationSecondsTest(unittest.TestCase):
    def test_empty_log_min_duration_is_none(self):
        log = CareReportLog()

        self.assertIsNone(log.min_duration_seconds)

    def test_min_duration_picks_smallest_duration(self):
        log = CareReportLog()
        log.add_report(make_report(duration_seconds=300.0))
        log.add_report(make_report(duration_seconds=240.0))

        self.assertEqual(log.min_duration_seconds, 240.0)

    def test_min_duration_ignores_none_durations(self):
        log = CareReportLog()
        log.add_report(make_report(duration_seconds=None))
        log.add_report(make_report(duration_seconds=240.0))

        self.assertEqual(log.min_duration_seconds, 240.0)

    def test_min_duration_is_none_when_all_durations_none(self):
        log = CareReportLog()
        log.add_report(make_report(duration_seconds=None))
        log.add_report(make_report(duration_seconds=None))

        self.assertIsNone(log.min_duration_seconds)

    def test_duplicate_report_min_stays_and_lookup_does_not_mutate(self):
        report = make_report(duration_seconds=300.0)
        log = CareReportLog()
        log.add_report(report)
        log.add_report(report)
        reports_before = log.reports

        self.assertEqual(log.min_duration_seconds, 300.0)
        self.assertEqual(log.min_duration_seconds, 300.0)
        self.assertEqual(log.reports, reports_before)
        self.assertEqual(len(log), 2)

    def test_min_duration_from_fixed_scenarios(self):
        from engine.adapters.simulator import replay_scenario

        sessions = []
        for name in (
            "dropoff_normal",
            "forgotten_rising_temp",
            "pet_dropoff",
        ):
            session = CareSession()
            replay_scenario(session, name)
            sessions.append(session)
        log = CareReportLog()
        returned = log.add_sessions(sessions)

        self.assertEqual(returned[0].duration_seconds, 300.0)
        self.assertEqual(returned[1].duration_seconds, 240.0)
        self.assertEqual(returned[2].duration_seconds, 300.0)
        self.assertEqual(log.min_duration_seconds, 240.0)
        self.assertEqual(log.total_duration_seconds, 840.0)


class CareReportLogMinCabinTempCTest(unittest.TestCase):
    def test_empty_log_min_cabin_temp_is_none(self):
        log = CareReportLog()

        self.assertIsNone(log.min_cabin_temp_c)

    def test_min_cabin_temp_picks_smallest_peak_temp(self):
        log = CareReportLog()
        log.add_report(make_report(max_cabin_temp_c=35.5))
        log.add_report(make_report(max_cabin_temp_c=28.0))

        self.assertEqual(log.min_cabin_temp_c, 28.0)

    def test_min_cabin_temp_ignores_none_temps(self):
        log = CareReportLog()
        log.add_report(make_report(max_cabin_temp_c=None))
        log.add_report(make_report(max_cabin_temp_c=28.0))

        self.assertEqual(log.min_cabin_temp_c, 28.0)

    def test_min_cabin_temp_is_none_when_all_temps_none(self):
        log = CareReportLog()
        log.add_report(make_report(max_cabin_temp_c=None))
        log.add_report(make_report(max_cabin_temp_c=None))

        self.assertIsNone(log.min_cabin_temp_c)

    def test_duplicate_report_min_stays_and_lookup_does_not_mutate(self):
        report = make_report(max_cabin_temp_c=35.5)
        log = CareReportLog()
        log.add_report(report)
        log.add_report(report)
        reports_before = log.reports

        self.assertEqual(log.min_cabin_temp_c, 35.5)
        self.assertEqual(log.min_cabin_temp_c, 35.5)
        self.assertEqual(log.reports, reports_before)
        self.assertEqual(len(log), 2)

    def test_min_cabin_temp_from_fixed_scenarios(self):
        from engine.adapters.simulator import replay_scenario

        sessions = []
        for name in (
            "dropoff_normal",
            "forgotten_rising_temp",
            "pet_dropoff",
        ):
            session = CareSession()
            replay_scenario(session, name)
            sessions.append(session)
        log = CareReportLog()
        returned = log.add_sessions(sessions)

        self.assertIsNone(returned[0].max_cabin_temp_c)
        self.assertEqual(returned[1].max_cabin_temp_c, 35.5)
        self.assertIsNone(returned[2].max_cabin_temp_c)
        self.assertEqual(log.min_cabin_temp_c, 35.5)
        self.assertEqual(log.max_cabin_temp_c, 35.5)


class CareReportLogAverageCabinTempCTest(unittest.TestCase):
    def test_empty_log_average_cabin_temp_is_none(self):
        log = CareReportLog()

        self.assertIsNone(log.average_cabin_temp_c)

    def test_average_cabin_temp_averages_peak_temps(self):
        log = CareReportLog()
        log.add_report(make_report(max_cabin_temp_c=35.5))
        log.add_report(make_report(max_cabin_temp_c=28.0))

        self.assertEqual(log.average_cabin_temp_c, 31.75)

    def test_average_cabin_temp_ignores_none_temps(self):
        log = CareReportLog()
        log.add_report(make_report(max_cabin_temp_c=None))
        log.add_report(make_report(max_cabin_temp_c=28.0))

        self.assertEqual(log.average_cabin_temp_c, 28.0)

    def test_average_cabin_temp_is_none_when_all_temps_none(self):
        log = CareReportLog()
        log.add_report(make_report(max_cabin_temp_c=None))
        log.add_report(make_report(max_cabin_temp_c=None))

        self.assertIsNone(log.average_cabin_temp_c)

    def test_duplicate_report_average_stays_and_lookup_does_not_mutate(self):
        report = make_report(max_cabin_temp_c=35.5)
        log = CareReportLog()
        log.add_report(report)
        log.add_report(report)
        reports_before = log.reports

        self.assertEqual(log.average_cabin_temp_c, 35.5)
        self.assertEqual(log.average_cabin_temp_c, 35.5)
        self.assertEqual(log.reports, reports_before)
        self.assertEqual(len(log), 2)

    def test_average_cabin_temp_from_fixed_scenarios(self):
        from engine.adapters.simulator import replay_scenario

        sessions = []
        for name in (
            "dropoff_normal",
            "forgotten_rising_temp",
            "pet_dropoff",
        ):
            session = CareSession()
            replay_scenario(session, name)
            sessions.append(session)
        log = CareReportLog()
        returned = log.add_sessions(sessions)

        self.assertIsNone(returned[0].max_cabin_temp_c)
        self.assertEqual(returned[1].max_cabin_temp_c, 35.5)
        self.assertIsNone(returned[2].max_cabin_temp_c)
        self.assertEqual(log.average_cabin_temp_c, 35.5)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.min_cabin_temp_c, 35.5)


class CareReportLogTotalCabinTempCTest(unittest.TestCase):
    def test_empty_log_total_cabin_temp_is_none(self):
        log = CareReportLog()

        self.assertIsNone(log.total_cabin_temp_c)

    def test_total_cabin_temp_sums_peak_temps(self):
        log = CareReportLog()
        log.add_report(make_report(max_cabin_temp_c=35.5))
        log.add_report(make_report(max_cabin_temp_c=28.0))

        self.assertEqual(log.total_cabin_temp_c, 63.5)

    def test_total_cabin_temp_ignores_none_temps(self):
        log = CareReportLog()
        log.add_report(make_report(max_cabin_temp_c=None))
        log.add_report(make_report(max_cabin_temp_c=28.0))

        self.assertEqual(log.total_cabin_temp_c, 28.0)

    def test_total_cabin_temp_is_none_when_all_temps_none(self):
        log = CareReportLog()
        log.add_report(make_report(max_cabin_temp_c=None))
        log.add_report(make_report(max_cabin_temp_c=None))

        self.assertIsNone(log.total_cabin_temp_c)

    def test_duplicate_report_counts_twice_and_lookup_does_not_mutate(self):
        report = make_report(max_cabin_temp_c=35.5)
        log = CareReportLog()
        log.add_report(report)
        log.add_report(report)
        reports_before = log.reports

        self.assertEqual(log.total_cabin_temp_c, 71.0)
        self.assertEqual(log.total_cabin_temp_c, 71.0)
        self.assertEqual(log.reports, reports_before)
        self.assertEqual(len(log), 2)

    def test_total_cabin_temp_from_fixed_scenarios(self):
        from engine.adapters.simulator import replay_scenario

        sessions = []
        for name in (
            "dropoff_normal",
            "forgotten_rising_temp",
            "pet_dropoff",
        ):
            session = CareSession()
            replay_scenario(session, name)
            sessions.append(session)
        log = CareReportLog()
        returned = log.add_sessions(sessions)

        self.assertIsNone(returned[0].max_cabin_temp_c)
        self.assertEqual(returned[1].max_cabin_temp_c, 35.5)
        self.assertIsNone(returned[2].max_cabin_temp_c)
        self.assertEqual(log.total_cabin_temp_c, 35.5)
        self.assertEqual(log.total_cabin_temp_c, log.average_cabin_temp_c)


class CareReportLogReportsWithoutExceptionTest(unittest.TestCase):
    def test_empty_log_reports_without_exception_is_empty_tuple(self):
        log = CareReportLog()

        self.assertEqual(log.reports_without_exception, ())
        self.assertIsInstance(log.reports_without_exception, tuple)

    def test_non_exception_only_reports_are_all_returned_in_order(self):
        first = make_report()
        second = make_report(exception_count=0, completed=False)
        log = CareReportLog()
        log.add_report(first)
        log.add_report(second)

        self.assertEqual(log.reports_without_exception, (first, second))
        self.assertTrue(
            all(
                not report.exception_occurred
                for report in log.reports_without_exception
            )
        )
        self.assertEqual(log.exception_reports, ())

    def test_exception_only_reports_return_empty_tuple(self):
        log = CareReportLog()
        log.add_report(make_report(exception_count=1))
        log.add_report(make_report(exception_count=2))

        self.assertEqual(log.reports_without_exception, ())
        self.assertEqual(len(log.exception_reports), 2)

    def test_mixed_reports_partition_with_exception_reports(self):
        clean_completed = make_report()
        with_exception = make_report(exception_count=1)
        clean_in_progress = make_report(completed=False)
        recovered = make_report(exception_count=1, completed=True)
        log = CareReportLog()
        for report in (
            clean_completed,
            with_exception,
            clean_in_progress,
            recovered,
        ):
            log.add_report(report)

        self.assertEqual(
            log.reports_without_exception,
            (clean_completed, clean_in_progress),
        )
        self.assertEqual(
            log.exception_reports, (with_exception, recovered)
        )
        self.assertEqual(
            len(log.reports_without_exception) + len(log.exception_reports),
            len(log.reports),
        )
        self.assertEqual(
            len(log.reports_without_exception),
            log.sessions_without_exception,
        )
        self.assertEqual(
            log.reports_without_exception,
            tuple(r for r in log.reports if not r.exception_occurred),
        )

    def test_duplicate_report_kept_twice_and_lookup_does_not_mutate(self):
        report = make_report()
        log = CareReportLog()
        log.add_report(report)
        log.add_report(report)
        reports_before = log.reports

        self.assertEqual(log.reports_without_exception, (report, report))
        self.assertEqual(log.reports_without_exception, (report, report))
        self.assertEqual(log.reports, reports_before)
        self.assertEqual(len(log), 2)

    def test_reports_without_exception_from_fixed_scenarios(self):
        from engine.adapters.simulator import replay_scenario

        sessions = []
        for name in (
            "dropoff_normal",
            "forgotten_rising_temp",
            "pet_dropoff",
        ):
            session = CareSession()
            replay_scenario(session, name)
            sessions.append(session)
        log = CareReportLog()
        returned = log.add_sessions(sessions)

        self.assertEqual(
            log.reports_without_exception, (returned[0], returned[2])
        )
        self.assertEqual(log.exception_reports, (returned[1],))
        self.assertEqual(len(log.reports_without_exception), 2)
        self.assertEqual(
            log.reports_without_exception,
            tuple(r for r in log.reports if not r.exception_occurred),
        )


class CareReportLogMaxExceptionCountTest(unittest.TestCase):
    def test_empty_log_max_exception_count_is_none(self):
        log = CareReportLog()

        self.assertIsNone(log.max_exception_count)

    def test_max_exception_count_picks_largest_count(self):
        log = CareReportLog()
        log.add_report(make_report(exception_count=0))
        log.add_report(make_report(exception_count=2))
        log.add_report(make_report(exception_count=1))

        self.assertEqual(log.max_exception_count, 2)

    def test_max_exception_count_is_zero_when_no_exceptions(self):
        log = CareReportLog()
        log.add_report(make_report(exception_count=0))
        log.add_report(make_report(exception_count=0))

        self.assertEqual(log.max_exception_count, 0)
        self.assertIsNotNone(log.max_exception_count)

    def test_single_report_max_exception_count_is_its_count(self):
        log = CareReportLog()
        log.add_report(make_report(exception_count=3))

        self.assertEqual(log.max_exception_count, 3)

    def test_duplicate_report_max_stays_and_lookup_does_not_mutate(self):
        report = make_report(exception_count=2)
        log = CareReportLog()
        log.add_report(report)
        log.add_report(report)
        reports_before = log.reports

        self.assertEqual(log.max_exception_count, 2)
        self.assertEqual(log.max_exception_count, 2)
        self.assertEqual(log.reports, reports_before)
        self.assertEqual(len(log), 2)

    def test_max_exception_count_from_fixed_scenarios(self):
        from engine.adapters.simulator import replay_scenario

        sessions = []
        for name in (
            "dropoff_normal",
            "forgotten_rising_temp",
            "pet_dropoff",
        ):
            session = CareSession()
            replay_scenario(session, name)
            sessions.append(session)
        log = CareReportLog()
        returned = log.add_sessions(sessions)

        self.assertEqual(returned[0].exception_count, 0)
        self.assertEqual(returned[1].exception_count, 1)
        self.assertEqual(returned[2].exception_count, 0)
        self.assertEqual(log.max_exception_count, 1)
        self.assertEqual(log.total_exception_count, 1)


if __name__ == "__main__":
    unittest.main()

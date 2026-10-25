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


if __name__ == "__main__":
    unittest.main()

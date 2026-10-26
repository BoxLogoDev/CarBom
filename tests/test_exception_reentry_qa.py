"""같은 케어 세션에서 EXCEPTION 재진입 경로의 단위 테스트."""

import unittest

from engine import (
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


class ExceptionReentryTest(unittest.TestCase):
    def test_exception_reentry_count_is_two(self):
        session = CareSession()
        board_and_drive(session)
        arrive(session)
        self.assertEqual(session.state, SessionState.ARRIVED)

        enter_exception(session)
        self.assertEqual(session.state, SessionState.EXCEPTION)

        recover_to_driving(session)
        self.assertEqual(session.state, SessionState.DRIVING)

        arrive(session)
        self.assertEqual(session.state, SessionState.ARRIVED)

        enter_exception(session)
        self.assertEqual(session.state, SessionState.EXCEPTION)

        report = report_for_session(session)

        self.assertTrue(report.exception_occurred)
        self.assertEqual(report.exception_count, 2)

    def test_second_exception_recovers_to_completed(self):
        session = CareSession()
        drive_to_second_exception(session)
        self.assertEqual(session.state, SessionState.EXCEPTION)

        session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)

        session.apply_snapshot(snapshot())
        self.assertEqual(session.state, SessionState.COMPLETED)

        report = report_for_session(session)

        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 2)
        self.assertEqual(report.summary, "예외 발생 후 하차 확인 완료")

    def test_recovery_history_records_onboard_then_driving(self):
        session = CareSession()
        board_and_drive(session)
        arrive(session)
        enter_exception(session)
        self.assertEqual(session.state, SessionState.EXCEPTION)

        recover_to_driving(session)
        self.assertEqual(session.state, SessionState.DRIVING)

        transitions = [
            (t.from_state, t.to_state, t.reason)
            for t in session.history
        ]
        recovery = (
            SessionState.EXCEPTION,
            SessionState.ONBOARD,
            "unlocked_and_ignition_on_after_exception",
        )
        self.assertIn(recovery, transitions)
        index = transitions.index(recovery)
        self.assertLess(index + 1, len(transitions))
        self.assertEqual(
            transitions[index + 1][:2],
            (SessionState.ONBOARD, SessionState.DRIVING),
        )


if __name__ == "__main__":
    unittest.main()

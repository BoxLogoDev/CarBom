"""뒷문 열림 시 예외 판정 회귀에 대한 QA 단위 테스트.

69회차에서 발견한 결함의 회귀 테스트다. 뒷문이 열린 스냅샷에서는
예외 선행 판정이 발동하지 않아야 하며, EXCEPTION과 ALIGHTING 사이를
진동하지 않고 하차·구조가 진행 중인 상태로 전이해야 한다.
"""

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
from engine.adapters.simulator import (
    dropoff_normal_snapshots,
    replay_scenario,
)


def door_open_locked_snapshot(**overrides):
    values = {
        "rear_door": DoorState.OPEN,
        "rear_seat_belt_buckled": True,
        "ignition": IgnitionState.OFF,
        "hvac_on": False,
        "cabin_temp_c": 35.5,
        "lock": LockState.LOCKED,
        "timestamp": 999.0,
    }
    values.update(overrides)
    return SignalSnapshot(**values)


class ExceptionDoorOpenQATest(unittest.TestCase):
    def test_exception_recovers_to_alighting_without_oscillation(self):
        session = CareSession()
        replay_scenario(session, "forgotten_rising_temp")
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)
        self.assertEqual(report_for_session(session).exception_count, 1)

        session.apply_snapshot(door_open_locked_snapshot())

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertEqual(len(session.history), 6)
        self.assertEqual(
            (
                session.history[-1].from_state,
                session.history[-1].to_state,
                session.history[-1].reason,
            ),
            (
                SessionState.EXCEPTION,
                SessionState.ALIGHTING,
                "rear_door_opened_after_exception",
            ),
        )
        self.assertTrue(session.passenger_present)
        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)
        self.assertTrue(report.exception_occurred)

    def test_idle_with_door_open_goes_boarding_not_exception(self):
        session = CareSession()

        session.apply_snapshot(door_open_locked_snapshot())

        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)
        self.assertEqual(
            (
                session.history[-1].from_state,
                session.history[-1].to_state,
                session.history[-1].reason,
            ),
            (
                SessionState.IDLE,
                SessionState.BOARDING,
                "rear_door_opened",
            ),
        )
        self.assertTrue(session.passenger_present)
        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertFalse(report.exception_occurred)

    def test_arrived_with_door_open_goes_alighting_not_exception(self):
        session = CareSession()
        for snap in dropoff_normal_snapshots()[:4]:
            session.apply_snapshot(snap)
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)

        session.apply_snapshot(door_open_locked_snapshot())

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertEqual(len(session.history), 5)
        self.assertEqual(
            (
                session.history[-1].from_state,
                session.history[-1].to_state,
                session.history[-1].reason,
            ),
            (
                SessionState.ARRIVED,
                SessionState.ALIGHTING,
                "alighting_started",
            ),
        )
        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertFalse(report.exception_occurred)

    def test_door_closed_exception_entry_still_works(self):
        session = CareSession()

        final_state = replay_scenario(session, "forgotten_rising_temp")

        self.assertEqual(final_state, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)
        self.assertTrue(session.passenger_present)
        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)
        self.assertTrue(report.exception_occurred)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_alighting_after_exception_completes(self):
        session = CareSession()
        replay_scenario(session, "forgotten_rising_temp")
        session.apply_snapshot(door_open_locked_snapshot())
        self.assertEqual(session.state, SessionState.ALIGHTING)

        session.apply_snapshot(
            door_open_locked_snapshot(
                rear_seat_belt_buckled=False, timestamp=1000.0
            )
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 6)

        session.apply_snapshot(
            door_open_locked_snapshot(
                rear_door=DoorState.CLOSED,
                rear_seat_belt_buckled=False,
                cabin_temp_c=None,
                timestamp=1010.0,
            )
        )
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(
            (
                session.history[-1].from_state,
                session.history[-1].to_state,
                session.history[-1].reason,
            ),
            (
                SessionState.ALIGHTING,
                SessionState.COMPLETED,
                "alighting_confirmed",
            ),
        )
        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 1)
        self.assertTrue(report.exception_occurred)
        self.assertEqual(report.summary, "예외 발생 후 하차 확인 완료")


if __name__ == "__main__":
    unittest.main()

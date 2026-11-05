"""EXCEPTION 상태에서 부분 해제만으로는 예외가 풀리지 않는 경계 QA.

예외 해제는 잠금 해제와 시동 ON이 함께 갖춰지거나 뒷문이 열릴 때만
일어난다. 잠금만 풀거나, 시동만 켜거나, 후석 벨트만 푸는 부분 해제는
동승자 잔류 판정과 EXCEPTION 상태를 그대로 유지해야 한다.
"""

import unittest
from dataclasses import replace

from engine import (
    CareSession,
    DoorState,
    GuidanceLevel,
    IgnitionState,
    LockState,
    SessionState,
    guidance_for_session,
    report_for_session,
)
from engine.adapters.simulator import replay_scenario
from engine.guidance import DestinationContext


def exception_session():
    session = CareSession()
    replay_scenario(session, "forgotten_rising_temp")
    assert session.state is SessionState.EXCEPTION
    assert session.passenger_present
    assert len(session.history) == 5
    return session


class ExceptionPartialReleaseTest(unittest.TestCase):
    def test_unlock_only_keeps_exception(self):
        session = exception_session()
        unlocked = replace(
            session.current_snapshot, lock=LockState.UNLOCKED
        )

        state = session.apply_snapshot(unlocked)

        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 5)

    def test_unlock_only_repeated_is_idempotent(self):
        session = exception_session()
        unlocked = replace(
            session.current_snapshot, lock=LockState.UNLOCKED
        )

        session.apply_snapshot(unlocked)
        state = session.apply_snapshot(unlocked)

        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 5)

    def test_ignition_on_only_while_locked_keeps_exception(self):
        session = exception_session()
        ignition_on = replace(
            session.current_snapshot, ignition=IgnitionState.ON
        )

        state = session.apply_snapshot(ignition_on)

        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 5)
        self.assertEqual(
            session.current_snapshot.lock, LockState.LOCKED
        )

    def test_partial_release_keeps_urgent_guidance_and_report(self):
        for overrides in (
            {"lock": LockState.UNLOCKED},
            {"ignition": IgnitionState.ON},
        ):
            session = exception_session()
            session.apply_snapshot(
                replace(session.current_snapshot, **overrides)
            )

            guidance = guidance_for_session(
                session, DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.URGENT)
            self.assertEqual(
                guidance.reason,
                "passenger_left_locked_dangerous_cabin_temp",
            )
            self.assertIn("35.5도", guidance.text)
            self.assertIn("즉시", guidance.text)

            report = report_for_session(session)
            self.assertEqual(report.final_state, SessionState.EXCEPTION)
            self.assertEqual(report.exception_count, 1)
            self.assertEqual(report.transition_count, 5)
            self.assertEqual(report.max_cabin_temp_c, 35.5)
            self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_unbuckle_only_keeps_passenger_and_exception(self):
        session = exception_session()
        unbuckled = replace(
            session.current_snapshot, rear_seat_belt_buckled=False
        )

        state = session.apply_snapshot(unbuckled)

        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 5)

    def test_unbuckle_then_door_open_recovers_to_completed(self):
        session = exception_session()
        unbuckled = replace(
            session.current_snapshot, rear_seat_belt_buckled=False
        )
        session.apply_snapshot(unbuckled)
        self.assertEqual(session.state, SessionState.EXCEPTION)

        opened = replace(unbuckled, rear_door=DoorState.OPEN)
        state = session.apply_snapshot(opened)

        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        last = session.history[-1]
        self.assertEqual(last.from_state, SessionState.EXCEPTION)
        self.assertEqual(last.to_state, SessionState.ALIGHTING)
        self.assertEqual(
            last.reason, "rear_door_opened_after_exception"
        )

        closed = replace(opened, rear_door=DoorState.CLOSED)
        state = session.apply_snapshot(closed)

        self.assertEqual(state, SessionState.COMPLETED)
        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.summary, "예외 발생 후 하차 확인 완료")


if __name__ == "__main__":
    unittest.main()

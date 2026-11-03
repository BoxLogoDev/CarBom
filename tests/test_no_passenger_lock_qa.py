"""동승자 없는 빈 차와 운전자 단독 주행 잠금 QA.

동승자가 없을 때는 차량 잠금과 높은 실내 온도만으로 EXCEPTION이 되면 안 된다.
빈 세션에 잠금 스냅샷이나 잠금 이벤트를 적용한 경우를 검증한다.
운전자만 타고 주행한 뒤 잠근 경우도 검증한다.
뒷문이 열렸다가 동승자 없이 닫혀 잠긴 경우도 검증한다.
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
    SignalEvent,
    SignalEventType,
    SignalSnapshot,
    guidance_for_session,
    report_for_session,
)


def _locked_hot_snapshot():
    return SignalSnapshot(
        lock=LockState.LOCKED,
        cabin_temp_c=35.5,
        timestamp=100.0,
    )


def _solo_driver_snapshots():
    return [
        SignalSnapshot(
            rear_door=DoorState.CLOSED,
            rear_seat_belt_buckled=False,
            ignition=IgnitionState.ON,
        ),
        SignalSnapshot(
            rear_door=DoorState.CLOSED,
            rear_seat_belt_buckled=False,
            ignition=IgnitionState.ON,
        ),
        SignalSnapshot(
            rear_door=DoorState.CLOSED,
            rear_seat_belt_buckled=False,
            ignition=IgnitionState.OFF,
        ),
        SignalSnapshot(
            rear_door=DoorState.CLOSED,
            rear_seat_belt_buckled=False,
            ignition=IgnitionState.OFF,
            lock=LockState.LOCKED,
            cabin_temp_c=34.0,
        ),
    ]


class NoPassengerLockQATest(unittest.TestCase):
    def test_empty_locked_hot_car_stays_idle(self):
        session = CareSession()

        result = session.apply_snapshot(_locked_hot_snapshot())

        self.assertEqual(result, SessionState.IDLE)
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 0)

        guidance = guidance_for_session(session)
        self.assertEqual(guidance.level, GuidanceLevel.NONE)
        self.assertEqual(guidance.text, "")
        self.assertEqual(guidance.reason, "idle")

        report = report_for_session(session)
        self.assertFalse(report.completed)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 0)

    def test_repeated_locked_snapshot_stays_idle(self):
        session = CareSession()
        snapshot = _locked_hot_snapshot()

        for _ in range(3):
            result = session.apply_snapshot(snapshot)
            self.assertEqual(result, SessionState.IDLE)
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(len(session.history), 0)

        self.assertFalse(session.passenger_present)

    def test_solo_driver_then_lock_stays_idle(self):
        session = CareSession()

        for snapshot in _solo_driver_snapshots():
            result = session.apply_snapshot(snapshot)
            self.assertEqual(result, SessionState.IDLE)
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(len(session.history), 0)
            self.assertFalse(session.passenger_present)
            self.assertEqual(
                guidance_for_session(session).level,
                GuidanceLevel.NONE,
            )

    def test_locked_event_alone_stays_idle(self):
        session = CareSession()

        result = session.apply_event(
            SignalEvent(SignalEventType.LOCKED, timestamp=10.0)
        )

        self.assertEqual(result, SessionState.IDLE)
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(len(session.history), 0)
        self.assertTrue(session.current_snapshot.locked)

    def test_boarding_without_passenger_returns_to_idle_on_lock(self):
        session = CareSession()
        session.apply_snapshot(
            SignalSnapshot(rear_door=DoorState.OPEN)
        )
        self.assertEqual(session.state, SessionState.BOARDING)

        result = session.apply_snapshot(
            SignalSnapshot(
                rear_door=DoorState.CLOSED,
                lock=LockState.LOCKED,
            )
        )

        self.assertEqual(result, SessionState.IDLE)
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertFalse(session.passenger_present)
        self.assertEqual(
            [transition.reason for transition in session.history],
            ["rear_door_opened", "boarding_without_passenger"],
        )

    def test_report_log_for_empty_and_solo_sessions_has_no_exception(self):
        empty = CareSession()
        empty.apply_snapshot(_locked_hot_snapshot())

        solo = CareSession()
        for snapshot in _solo_driver_snapshots():
            solo.apply_snapshot(snapshot)

        log = CareReportLog()
        log.add_session(empty)
        log.add_session(solo)

        self.assertEqual(len(log), 2)
        self.assertEqual(log.completed_count, 0)
        self.assertEqual(log.sessions_with_exception, 0)
        self.assertEqual(log.total_exception_count, 0)
        self.assertIsNone(log.average_duration_seconds)


if __name__ == "__main__":
    unittest.main()

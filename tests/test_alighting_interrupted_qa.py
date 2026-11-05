"""하차 중단과 재개와 예외 회복에 대한 QA 단위 테스트."""

import unittest

from engine import (
    CareSession,
    DestinationContext,
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
from engine.adapters.simulator import dropoff_normal_snapshots, replay


def snapshot(**overrides):
    values = {
        "rear_door": DoorState.CLOSED,
        "rear_seat_belt_buckled": False,
        "ignition": IgnitionState.OFF,
        "hvac_on": False,
        "cabin_temp_c": 24.0,
        "lock": LockState.UNLOCKED,
        "timestamp": None,
    }
    values.update(overrides)
    return SignalSnapshot(**values)


def arrived_session():
    session = CareSession()
    replay(session, dropoff_normal_snapshots()[:4])
    return session


def alighting_session():
    session = arrived_session()
    session.apply_snapshot(
        snapshot(
            rear_door=DoorState.OPEN,
            rear_seat_belt_buckled=True,
            ignition=IgnitionState.OFF,
            lock=LockState.UNLOCKED,
            cabin_temp_c=24.0,
            timestamp=240.0,
        )
    )
    return session


def history_projection(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


class AlightingInterruptedQATest(unittest.TestCase):
    def test_alighting_holds_passenger_with_info_guidance(self):
        session = arrived_session()
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 4)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.OFF,
                lock=LockState.UNLOCKED,
                cabin_temp_c=24.0,
                timestamp=240.0,
            )
        )

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 5)
        self.assertEqual(
            history_projection(session)[-1],
            (
                SessionState.ARRIVED,
                SessionState.ALIGHTING,
                "alighting_started",
                240.0,
            ),
        )

        guidance = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.state, SessionState.ALIGHTING)
        self.assertEqual(guidance.reason, "alighting")
        self.assertEqual(
            guidance.text,
            "하차 중입니다. 뒷좌석이 비었는지 확인해 주세요.",
        )

    def test_buckled_door_close_holds_alighting_idempotently(self):
        session = alighting_session()
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertEqual(len(session.history), 5)

        closed = snapshot(
            rear_door=DoorState.CLOSED,
            rear_seat_belt_buckled=True,
            ignition=IgnitionState.OFF,
            lock=LockState.UNLOCKED,
            cabin_temp_c=24.0,
            timestamp=300.0,
        )
        session.apply_snapshot(closed)

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertNotEqual(session.state, SessionState.COMPLETED)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 5)

        before = history_projection(session)
        session.apply_snapshot(closed)
        session.apply_snapshot(closed)

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 5)
        self.assertEqual(history_projection(session), before)

    def test_interrupted_alighting_resumes_to_completed(self):
        session = alighting_session()
        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.CLOSED,
                rear_seat_belt_buckled=True,
                timestamp=300.0,
            )
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertEqual(len(session.history), 5)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=False,
                timestamp=360.0,
            )
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 5)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.CLOSED,
                rear_seat_belt_buckled=False,
                timestamp=420.0,
            )
        )

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(
            history_projection(session)[-1],
            (
                SessionState.ALIGHTING,
                SessionState.COMPLETED,
                "alighting_confirmed",
                420.0,
            ),
        )

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 420.0)
        self.assertEqual(report.final_state, SessionState.COMPLETED)

    def test_lock_during_interrupted_alighting_enters_exception(self):
        session = alighting_session()

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.CLOSED,
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.OFF,
                lock=LockState.LOCKED,
                cabin_temp_c=24.0,
                timestamp=300.0,
            )
        )

        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 6)
        self.assertEqual(
            history_projection(session)[-1],
            (
                SessionState.ALIGHTING,
                SessionState.EXCEPTION,
                "ignition_off_locked_passenger_present",
                300.0,
            ),
        )

        guidance = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.state, SessionState.EXCEPTION)
        self.assertEqual(guidance.reason, "passenger_left_locked")

        report = report_for_session(session)
        self.assertFalse(report.completed)
        self.assertTrue(report.exception_occurred)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.final_state, SessionState.EXCEPTION)

    def test_exception_during_alighting_recovers_to_completed(self):
        session = alighting_session()
        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.CLOSED,
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.OFF,
                lock=LockState.LOCKED,
                cabin_temp_c=24.0,
                timestamp=300.0,
            )
        )
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 6)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=False,
                ignition=IgnitionState.OFF,
                lock=LockState.UNLOCKED,
                timestamp=360.0,
            )
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(
            history_projection(session)[-1],
            (
                SessionState.EXCEPTION,
                SessionState.ALIGHTING,
                "rear_door_opened_after_exception",
                360.0,
            ),
        )

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.CLOSED,
                rear_seat_belt_buckled=False,
                ignition=IgnitionState.OFF,
                lock=LockState.UNLOCKED,
                timestamp=420.0,
            )
        )

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(
            history_projection(session)[-1],
            (
                SessionState.ALIGHTING,
                SessionState.COMPLETED,
                "alighting_confirmed",
                420.0,
            ),
        )

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertTrue(report.exception_occurred)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 8)
        self.assertEqual(report.duration_seconds, 420.0)
        self.assertEqual(report.summary, "예외 발생 후 하차 확인 완료")

    def test_event_path_matches_snapshot_history_to_exception(self):
        via_snapshot = alighting_session()
        via_snapshot.apply_snapshot(
            snapshot(
                rear_door=DoorState.CLOSED,
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.OFF,
                lock=LockState.UNLOCKED,
                cabin_temp_c=24.0,
                timestamp=300.0,
            )
        )
        self.assertEqual(via_snapshot.state, SessionState.ALIGHTING)
        via_snapshot.apply_snapshot(
            snapshot(
                rear_door=DoorState.CLOSED,
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.OFF,
                lock=LockState.LOCKED,
                cabin_temp_c=24.0,
                timestamp=360.0,
            )
        )
        self.assertEqual(via_snapshot.state, SessionState.EXCEPTION)

        via_events = alighting_session()
        via_events.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_CLOSED, timestamp=300.0
            )
        )
        self.assertEqual(via_events.state, SessionState.ALIGHTING)
        self.assertTrue(via_events.passenger_present)
        via_events.apply_event(
            SignalEvent(SignalEventType.LOCKED, timestamp=360.0)
        )

        self.assertEqual(via_events.state, SessionState.EXCEPTION)
        self.assertTrue(via_events.passenger_present)
        self.assertEqual(
            history_projection(via_events),
            history_projection(via_snapshot),
        )
        self.assertEqual(
            history_projection(via_events)[-1],
            (
                SessionState.ALIGHTING,
                SessionState.EXCEPTION,
                "ignition_off_locked_passenger_present",
                360.0,
            ),
        )
        self.assertEqual(len(via_events.history), 6)


if __name__ == "__main__":
    unittest.main()

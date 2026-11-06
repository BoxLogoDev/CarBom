"""QA scenarios for rear door open input alone while IDLE."""

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


def snapshot(**overrides):
    values = {
        "rear_door": DoorState.CLOSED,
        "rear_seat_belt_buckled": False,
        "ignition": IgnitionState.OFF,
        "hvac_on": False,
        "cabin_temp_c": 24.0,
        "lock": LockState.UNLOCKED,
        "timestamp": 0.0,
    }
    values.update(overrides)
    return SignalSnapshot(**values)


def history_of(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


class IdleDoorOpenQATest(unittest.TestCase):
    def test_idle_rear_door_open_alone_enters_boarding(self):
        session = CareSession()

        session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))

        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 1)
        self.assertEqual(session.history[0].from_state, SessionState.IDLE)
        self.assertEqual(
            session.history[0].to_state, SessionState.BOARDING
        )
        self.assertEqual(session.history[0].reason, "rear_door_opened")
        self.assertEqual(session.history[0].timestamp, 0.0)
        self.assertTrue(session.current_snapshot.rear_door_open)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "boarding_dropoff")
        self.assertEqual(
            guidance.text,
            "등원 준비 중입니다. 뒷좌석 승차와 안전벨트를 확인해 주세요.",
        )

        report = report_for_session(session)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 1)
        self.assertEqual(report.duration_seconds, 0.0)
        self.assertEqual(report.max_cabin_temp_c, 24.0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_idle_rear_door_open_repeated_is_idempotent(self):
        session = CareSession()

        session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=60.0)
        )
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)

    def test_rear_door_opened_event_matches_snapshot_path(self):
        session = CareSession()
        session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))

        event_session = CareSession()
        event_session.apply_event(
            SignalEvent(
                type=SignalEventType.REAR_DOOR_OPENED, timestamp=0.0
            )
        )

        self.assertEqual(event_session.state, SessionState.BOARDING)
        self.assertEqual(history_of(event_session), history_of(session))
        self.assertIsNone(event_session.current_snapshot.cabin_temp_c)

        report = report_for_session(event_session)
        self.assertIsNone(report.max_cabin_temp_c)

    def test_idle_rear_door_open_high_temp_stays_boarding(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, cabin_temp_c=35.5)
        )

        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertNotEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 1)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "boarding_dropoff")
        self.assertEqual(
            guidance.text,
            "등원 준비 중입니다. 뒷좌석 승차와 안전벨트를 확인해 주세요.",
        )
        self.assertNotIn("35.5", guidance.text)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_idle_door_open_belt_locked_high_temp_stays_boarding(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                lock=LockState.LOCKED,
                cabin_temp_c=35.5,
            )
        )

        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertNotEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 1)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)

    def test_idle_door_open_episode_then_full_journey_completes(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )
        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                timestamp=60.0,
            )
        )
        session.apply_snapshot(
            snapshot(rear_seat_belt_buckled=True, timestamp=120.0)
        )
        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                hvac_on=True,
                timestamp=180.0,
            )
        )
        session.apply_snapshot(
            snapshot(rear_seat_belt_buckled=True, timestamp=240.0)
        )
        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=300.0)
        )
        session.apply_snapshot(snapshot(timestamp=360.0))

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 360.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")


if __name__ == "__main__":
    unittest.main()

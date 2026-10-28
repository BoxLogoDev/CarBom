"""출발 전 하차와 동승자 해제 경계에 대한 QA 단위 테스트."""

import unittest

from engine import (
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
from engine.adapters.simulator import dropoff_normal_snapshots


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


class PredepartureAlightingQATest(unittest.TestCase):
    def test_onboard_to_alighting_without_driving(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )
        self.assertEqual(session.state, SessionState.BOARDING)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.CLOSED,
                rear_seat_belt_buckled=True,
                timestamp=10.0,
            )
        )
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertTrue(session.passenger_present)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=False,
                timestamp=20.0,
            )
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(session.history[-1].reason, "passenger_alighting")

        guidance = guidance_for_session(session)
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "alighting")

        self.assertEqual(
            [
                (t.from_state, t.to_state, t.reason)
                for t in session.history
            ],
            [
                (
                    SessionState.IDLE,
                    SessionState.BOARDING,
                    "rear_door_opened",
                ),
                (
                    SessionState.BOARDING,
                    SessionState.ONBOARD,
                    "passenger_onboard",
                ),
                (
                    SessionState.ONBOARD,
                    SessionState.ALIGHTING,
                    "passenger_alighting",
                ),
            ],
        )

    def test_predeparture_alighting_completes(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )
        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.CLOSED,
                rear_seat_belt_buckled=True,
                timestamp=10.0,
            )
        )
        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=False,
                timestamp=20.0,
            )
        )
        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.CLOSED,
                rear_seat_belt_buckled=False,
                timestamp=30.0,
            )
        )

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(session.history[-1].reason, "alighting_confirmed")

        to_states = [t.to_state for t in session.history]
        self.assertNotIn(SessionState.DRIVING, to_states)
        self.assertNotIn(SessionState.ARRIVED, to_states)
        self.assertEqual(
            to_states,
            [
                SessionState.BOARDING,
                SessionState.ONBOARD,
                SessionState.ALIGHTING,
                SessionState.COMPLETED,
            ],
        )

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 4)
        self.assertEqual(report.duration_seconds, 30.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

        guidance = guidance_for_session(session)
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")

    def test_boarding_holds_while_door_open_even_with_belt(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )
        self.assertEqual(session.state, SessionState.BOARDING)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                timestamp=10.0,
            )
        )
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 1)

        guidance = guidance_for_session(session)
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "boarding")

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.CLOSED,
                rear_seat_belt_buckled=True,
                timestamp=20.0,
            )
        )
        self.assertEqual(session.state, SessionState.ONBOARD)

    def test_onboard_holds_when_door_opens_but_belt_still_buckled(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )
        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.CLOSED,
                rear_seat_belt_buckled=True,
                timestamp=10.0,
            )
        )
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertEqual(len(session.history), 2)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                timestamp=20.0,
            )
        )
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 2)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.CLOSED,
                rear_seat_belt_buckled=True,
                timestamp=30.0,
            )
        )
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertEqual(len(session.history), 2)

    def test_arrived_holds_when_belt_unbuckled_but_door_stays_closed(self):
        session = CareSession()

        for snap in dropoff_normal_snapshots()[:4]:
            session.apply_snapshot(snap)
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertTrue(session.passenger_present)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.CLOSED,
                rear_seat_belt_buckled=False,
                ignition=IgnitionState.OFF,
                timestamp=240.0,
            )
        )
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 4)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=False,
                ignition=IgnitionState.OFF,
                timestamp=300.0,
            )
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(session.history[-1].reason, "alighting_started")

    def test_predeparture_alighting_via_events(self):
        session = CareSession()

        session.apply_event(
            SignalEvent(SignalEventType.REAR_DOOR_OPENED, timestamp=0.0)
        )
        self.assertEqual(session.state, SessionState.BOARDING)

        session.apply_event(
            SignalEvent(SignalEventType.REAR_BELT_BUCKLED, timestamp=10.0)
        )
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertTrue(session.passenger_present)

        session.apply_event(
            SignalEvent(SignalEventType.REAR_DOOR_CLOSED, timestamp=20.0)
        )
        self.assertEqual(session.state, SessionState.ONBOARD)

        session.apply_event(
            SignalEvent(SignalEventType.REAR_BELT_UNBUCKLED, timestamp=30.0)
        )
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertTrue(session.passenger_present)

        session.apply_event(
            SignalEvent(SignalEventType.REAR_DOOR_OPENED, timestamp=40.0)
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)

        session.apply_event(
            SignalEvent(SignalEventType.REAR_DOOR_CLOSED, timestamp=50.0)
        )
        self.assertEqual(session.state, SessionState.COMPLETED)

        self.assertEqual(
            [
                (t.from_state, t.to_state, t.reason, t.timestamp)
                for t in session.history
            ],
            [
                (
                    SessionState.IDLE,
                    SessionState.BOARDING,
                    "rear_door_opened",
                    0.0,
                ),
                (
                    SessionState.BOARDING,
                    SessionState.ONBOARD,
                    "passenger_onboard",
                    20.0,
                ),
                (
                    SessionState.ONBOARD,
                    SessionState.ALIGHTING,
                    "passenger_alighting",
                    40.0,
                ),
                (
                    SessionState.ALIGHTING,
                    SessionState.COMPLETED,
                    "alighting_confirmed",
                    50.0,
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()

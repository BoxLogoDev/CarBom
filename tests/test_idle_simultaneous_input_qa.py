"""QA scenarios for simultaneous door open and belt input while IDLE.

Existing IDLE tests cover the rear door alone and the rear belt alone.
This file covers both signals arriving together in one snapshot.
The belt alone goes straight from IDLE to ONBOARD.
The simultaneous input stops at BOARDING while the door stays open.
"""

import unittest

from engine import (
    CareSession,
    DestinationContext,
    DoorState,
    GuidanceLevel,
    IgnitionState,
    SessionState,
    SignalEvent,
    SignalEventType,
    SignalSnapshot,
    guidance_for_session,
    report_for_session,
)


def history_of(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


class IdleSimultaneousInputQATest(unittest.TestCase):
    def test_simultaneous_snapshot_enters_boarding_only(self):
        session = CareSession()

        result = session.apply_snapshot(
            SignalSnapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                timestamp=10.0,
            )
        )

        self.assertEqual(result, SessionState.BOARDING)
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(
            history_of(session),
            [
                (
                    SessionState.IDLE,
                    SessionState.BOARDING,
                    "rear_door_opened",
                    10.0,
                )
            ],
        )
        self.assertNotIn(
            SessionState.ONBOARD,
            [t.to_state for t in session.history],
        )

    def test_door_close_reaches_onboard_via_boarding(self):
        session = CareSession()
        session.apply_snapshot(
            SignalSnapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                timestamp=10.0,
            )
        )

        result = session.apply_snapshot(
            SignalSnapshot(
                rear_seat_belt_buckled=True, timestamp=20.0
            )
        )

        self.assertEqual(result, SessionState.ONBOARD)
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertTrue(session.passenger_present)
        self.assertEqual(
            history_of(session),
            [
                (
                    SessionState.IDLE,
                    SessionState.BOARDING,
                    "rear_door_opened",
                    10.0,
                ),
                (
                    SessionState.BOARDING,
                    SessionState.ONBOARD,
                    "passenger_onboard",
                    20.0,
                ),
            ],
        )

    def test_event_path_matches_snapshot_path(self):
        snapshot_session = CareSession()
        snapshot_session.apply_snapshot(
            SignalSnapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                timestamp=10.0,
            )
        )
        snapshot_session.apply_snapshot(
            SignalSnapshot(
                rear_seat_belt_buckled=True, timestamp=20.0
            )
        )

        event_session = CareSession()
        event_session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_OPENED, timestamp=10.0
            )
        )
        event_session.apply_event(
            SignalEvent(
                SignalEventType.REAR_BELT_BUCKLED, timestamp=10.0
            )
        )

        self.assertEqual(event_session.state, SessionState.BOARDING)
        self.assertTrue(event_session.passenger_present)
        self.assertEqual(len(event_session.history), 1)

        event_session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_CLOSED, timestamp=20.0
            )
        )

        self.assertEqual(event_session.state, SessionState.ONBOARD)
        self.assertEqual(
            history_of(event_session),
            history_of(snapshot_session),
        )

    def test_event_with_attached_snapshot_matches_direct_snapshot(
        self,
    ):
        direct_session = CareSession()
        direct_session.apply_snapshot(
            SignalSnapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                timestamp=10.0,
            )
        )

        event_session = CareSession()
        event_session.apply_event(
            SignalEvent(
                SignalEventType.REAR_BELT_BUCKLED,
                timestamp=10.0,
                snapshot=SignalSnapshot(
                    rear_door=DoorState.OPEN,
                    rear_seat_belt_buckled=True,
                    timestamp=10.0,
                ),
            )
        )

        self.assertEqual(event_session.state, SessionState.BOARDING)
        self.assertTrue(event_session.passenger_present)
        self.assertEqual(
            history_of(event_session), history_of(direct_session)
        )

    def test_simultaneous_start_full_journey_completes(self):
        session = CareSession()
        session.apply_snapshot(
            SignalSnapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                timestamp=10.0,
            )
        )
        session.apply_snapshot(
            SignalSnapshot(
                rear_seat_belt_buckled=True, timestamp=20.0
            )
        )
        self.assertEqual(session.state, SessionState.ONBOARD)

        session.apply_snapshot(
            SignalSnapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                timestamp=30.0,
            )
        )
        self.assertEqual(session.state, SessionState.DRIVING)

        session.apply_snapshot(
            SignalSnapshot(
                rear_seat_belt_buckled=True, timestamp=40.0
            )
        )
        self.assertEqual(session.state, SessionState.ARRIVED)

        session.apply_snapshot(
            SignalSnapshot(
                rear_door=DoorState.OPEN, timestamp=50.0
            )
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)

        session.apply_snapshot(SignalSnapshot(timestamp=60.0))
        self.assertEqual(session.state, SessionState.COMPLETED)

        self.assertEqual(len(session.history), 6)
        self.assertEqual(
            history_of(session),
            [
                (
                    SessionState.IDLE,
                    SessionState.BOARDING,
                    "rear_door_opened",
                    10.0,
                ),
                (
                    SessionState.BOARDING,
                    SessionState.ONBOARD,
                    "passenger_onboard",
                    20.0,
                ),
                (
                    SessionState.ONBOARD,
                    SessionState.DRIVING,
                    "ignition_on",
                    30.0,
                ),
                (
                    SessionState.DRIVING,
                    SessionState.ARRIVED,
                    "ignition_off",
                    40.0,
                ),
                (
                    SessionState.ARRIVED,
                    SessionState.ALIGHTING,
                    "alighting_started",
                    50.0,
                ),
                (
                    SessionState.ALIGHTING,
                    SessionState.COMPLETED,
                    "alighting_confirmed",
                    60.0,
                ),
            ],
        )

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 50.0)
        self.assertIn("하차 확인 완료", report.summary)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")


if __name__ == "__main__":
    unittest.main()

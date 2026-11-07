"""QA scenarios for simultaneous BOARDING inputs in one snapshot.

Existing IDLE simultaneous tests cover the rear door and belt together.
Existing BOARDING tests cover a belt or ignition input after boarding starts.
This file covers the rear door, belt, and ignition together from IDLE.
The open door holds the session at BOARDING.
Closing the door moves through ONBOARD to DRIVING in one snapshot.
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


def simultaneous_snapshot(timestamp=10.0):
    return SignalSnapshot(
        rear_door=DoorState.OPEN,
        rear_seat_belt_buckled=True,
        ignition=IgnitionState.ON,
        timestamp=timestamp,
    )


class BoardingSimultaneousInputQATest(unittest.TestCase):
    def test_simultaneous_snapshot_stays_boarding(self):
        session = CareSession()

        result = session.apply_snapshot(simultaneous_snapshot(10.0))

        self.assertEqual(result, SessionState.BOARDING)
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertTrue(session.passenger_present)
        self.assertTrue(session.current_snapshot.ignition_on)
        self.assertTrue(session.current_snapshot.rear_door_open)
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
        self.assertNotIn(
            SessionState.DRIVING,
            [t.to_state for t in session.history],
        )

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
        self.assertEqual(report.final_state, SessionState.BOARDING)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 1)
        self.assertEqual(report.duration_seconds, 0.0)
        self.assertIsNone(report.max_cabin_temp_c)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")
        self.assertTrue(report.passenger_present)

    def test_door_close_multistep_to_driving(self):
        session = CareSession()
        session.apply_snapshot(simultaneous_snapshot(10.0))

        result = session.apply_snapshot(
            SignalSnapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                timestamp=20.0,
            )
        )

        self.assertEqual(result, SessionState.DRIVING)
        self.assertEqual(session.state, SessionState.DRIVING)
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
                    20.0,
                ),
            ],
        )
        self.assertEqual(session.history[-2].timestamp, 20.0)
        self.assertEqual(session.history[-1].timestamp, 20.0)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")

        report = report_for_session(session)
        self.assertEqual(report.transition_count, 3)
        self.assertEqual(report.duration_seconds, 10.0)

    def test_simultaneous_snapshot_repeated_is_idempotent(self):
        session = CareSession()
        session.apply_snapshot(simultaneous_snapshot(10.0))

        result = session.apply_snapshot(simultaneous_snapshot(15.0))

        self.assertEqual(result, SessionState.BOARDING)
        self.assertEqual(session.state, SessionState.BOARDING)
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

    def test_event_path_matches_snapshot_path(self):
        snapshot_session = CareSession()
        snapshot_session.apply_snapshot(simultaneous_snapshot(10.0))
        snapshot_session.apply_snapshot(
            SignalSnapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                timestamp=20.0,
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
        event_session.apply_event(
            SignalEvent(
                SignalEventType.IGNITION_ON, timestamp=10.0
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

        self.assertEqual(event_session.state, SessionState.DRIVING)
        self.assertEqual(
            history_of(event_session),
            history_of(snapshot_session),
        )
        self.assertEqual(
            history_of(event_session),
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
                    20.0,
                ),
            ],
        )

    def test_event_with_attached_snapshot_matches_direct_snapshot(
        self,
    ):
        direct_session = CareSession()
        direct_session.apply_snapshot(simultaneous_snapshot(10.0))

        event_session = CareSession()
        event_session.apply_event(
            SignalEvent(
                SignalEventType.IGNITION_ON,
                timestamp=10.0,
                snapshot=simultaneous_snapshot(10.0),
            )
        )

        self.assertEqual(event_session.state, SessionState.BOARDING)
        self.assertTrue(event_session.passenger_present)
        self.assertEqual(
            history_of(event_session), history_of(direct_session)
        )

        boarding_session = CareSession()
        boarding_session.apply_snapshot(
            SignalSnapshot(
                rear_door=DoorState.OPEN, timestamp=0.0
            )
        )
        self.assertEqual(
            boarding_session.state, SessionState.BOARDING
        )

        boarding_session.apply_snapshot(simultaneous_snapshot(10.0))

        self.assertEqual(
            boarding_session.state, SessionState.BOARDING
        )
        self.assertEqual(
            history_of(boarding_session),
            [
                (
                    SessionState.IDLE,
                    SessionState.BOARDING,
                    "rear_door_opened",
                    0.0,
                )
            ],
        )

        boarding_session.apply_snapshot(
            SignalSnapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                timestamp=20.0,
            )
        )

        self.assertEqual(
            boarding_session.state, SessionState.DRIVING
        )
        self.assertEqual(
            history_of(boarding_session),
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
                    SessionState.DRIVING,
                    "ignition_on",
                    20.0,
                ),
            ],
        )

    def test_simultaneous_start_full_journey_completes(self):
        session = CareSession()
        session.apply_snapshot(simultaneous_snapshot(10.0))
        session.apply_snapshot(
            SignalSnapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                timestamp=20.0,
            )
        )
        self.assertEqual(session.state, SessionState.DRIVING)

        session.apply_snapshot(
            SignalSnapshot(
                rear_seat_belt_buckled=True, timestamp=30.0
            )
        )
        self.assertEqual(session.state, SessionState.ARRIVED)

        session.apply_snapshot(
            SignalSnapshot(
                rear_door=DoorState.OPEN, timestamp=40.0
            )
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)

        session.apply_snapshot(SignalSnapshot(timestamp=50.0))
        self.assertEqual(session.state, SessionState.COMPLETED)

        self.assertEqual(len(session.history), 6)
        self.assertEqual(
            [t.reason for t in session.history],
            [
                "rear_door_opened",
                "passenger_onboard",
                "ignition_on",
                "ignition_off",
                "alighting_started",
                "alighting_confirmed",
            ],
        )
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
                    20.0,
                ),
                (
                    SessionState.DRIVING,
                    SessionState.ARRIVED,
                    "ignition_off",
                    30.0,
                ),
                (
                    SessionState.ARRIVED,
                    SessionState.ALIGHTING,
                    "alighting_started",
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

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 40.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")


if __name__ == "__main__":
    unittest.main()





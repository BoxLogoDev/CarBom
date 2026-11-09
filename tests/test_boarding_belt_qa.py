"""QA scenarios for changing only the rear belt while BOARDING.

Boarding has started: the rear door is open and the session is
waiting for the passenger to settle. The passenger latch follows
the belt: a buckled belt latches the passenger present, and a
released belt clears the latch while the rear door is open.
Changing the belt flag on its own in this window therefore flips
passenger_present without moving the session out of BOARDING and
without growing the transition history, because BOARDING only
advances once the door closes. The latch decided at belt time is
what the door close then reads: closing the door with the latch
set moves to ONBOARD, while closing it with no latch returns to
IDLE as a boarding without a passenger.

Unlike the simultaneous-input scenarios, each belt step here is
derived from the current snapshot with dataclasses.replace,
changing only rear_seat_belt_buckled and timestamp. The setup is
the first dropoff_normal snapshot (0.0, rear door open, belt
released), which leaves BOARDING with no passenger and a single
transition. The scenarios cover the snapshot path and the event
path, plus the guidance and report views of the held boarding
state.
"""

import dataclasses
import unittest

from engine import (
    CareSession,
    DestinationContext,
    DoorState,
    GuidanceLevel,
    SessionState,
    SignalEvent,
    SignalEventType,
    guidance_for_session,
    report_for_session,
)
from engine.adapters.simulator import dropoff_normal_snapshots

BOARDING_TEXT = "등원 준비 중입니다. 뒷좌석 승차와 안전벨트를 확인해 주세요."


def boarding_session():
    session = CareSession()
    session.apply_snapshot(dropoff_normal_snapshots()[0])
    return session


def with_belt(session, buckled, timestamp):
    return dataclasses.replace(
        session.current_snapshot,
        rear_seat_belt_buckled=buckled,
        timestamp=timestamp,
    )


def history_of(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


BOARDING_HISTORY = [
    (SessionState.IDLE, SessionState.BOARDING, "rear_door_opened", 0.0),
]


class BoardingBeltQATest(unittest.TestCase):
    def test_buckle_alone_in_boarding_latches_passenger_without_transition(
        self,
    ):
        session = boarding_session()

        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), BOARDING_HISTORY)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "boarding_dropoff")
        self.assertEqual(guidance.text, BOARDING_TEXT)
        report = report_for_session(session)
        self.assertEqual(report.transition_count, 1)
        self.assertEqual(report.started_at, 0.0)
        self.assertEqual(report.ended_at, 0.0)
        self.assertEqual(report.duration_seconds, 0.0)
        self.assertFalse(report.passenger_present)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

        session.apply_snapshot(with_belt(session, True, 60.0))

        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), BOARDING_HISTORY)
        self.assertTrue(session.current_snapshot.rear_seat_belt_buckled)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "boarding_dropoff")
        self.assertEqual(guidance.text, BOARDING_TEXT)
        report = report_for_session(session)
        self.assertEqual(report.transition_count, 1)
        self.assertEqual(report.duration_seconds, 0.0)
        self.assertEqual(report.ended_at, 0.0)
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_buckle_repeated_in_boarding_is_idempotent(self):
        session = boarding_session()

        session.apply_snapshot(with_belt(session, True, 60.0))
        session.apply_snapshot(with_belt(session, True, 70.0))

        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), BOARDING_HISTORY)
        self.assertEqual(len(session.history), 1)
        self.assertTrue(session.current_snapshot.rear_seat_belt_buckled)
        self.assertEqual(session.current_snapshot.timestamp, 70.0)

    def test_belt_toggles_in_boarding_flip_passenger_only(self):
        session = boarding_session()
        session.apply_snapshot(with_belt(session, True, 60.0))

        for timestamp, buckled, present in (
            (80.0, False, False),
            (90.0, True, True),
            (100.0, False, False),
        ):
            session.apply_snapshot(with_belt(session, buckled, timestamp))

            self.assertEqual(session.state, SessionState.BOARDING)
            self.assertEqual(session.passenger_present, present)
            self.assertEqual(history_of(session), BOARDING_HISTORY)
            self.assertEqual(len(session.history), 1)
            guidance = guidance_for_session(
                session, context=DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "boarding_dropoff")
            self.assertEqual(guidance.text, BOARDING_TEXT)
            report = report_for_session(session)
            self.assertEqual(report.transition_count, 1)

    def test_belt_latch_in_boarding_decides_door_close_outcome(self):
        latched = boarding_session()
        latched.apply_snapshot(with_belt(latched, True, 60.0))
        latched.apply_snapshot(
            dataclasses.replace(
                latched.current_snapshot,
                rear_door=DoorState.CLOSED,
                timestamp=120.0,
            )
        )

        self.assertEqual(latched.state, SessionState.ONBOARD)
        self.assertTrue(latched.passenger_present)
        self.assertEqual(
            history_of(latched),
            BOARDING_HISTORY
            + [
                (
                    SessionState.BOARDING,
                    SessionState.ONBOARD,
                    "passenger_onboard",
                    120.0,
                )
            ],
        )

        unlatched = boarding_session()
        unlatched.apply_snapshot(
            dataclasses.replace(
                unlatched.current_snapshot,
                rear_door=DoorState.CLOSED,
                timestamp=60.0,
            )
        )

        self.assertEqual(unlatched.state, SessionState.IDLE)
        self.assertFalse(unlatched.passenger_present)
        self.assertEqual(
            history_of(unlatched),
            BOARDING_HISTORY
            + [
                (
                    SessionState.BOARDING,
                    SessionState.IDLE,
                    "boarding_without_passenger",
                    60.0,
                )
            ],
        )

    def test_event_path_buckle_in_boarding_matches_snapshot_path(self):
        snapshot_session = boarding_session()
        snapshot_session.apply_snapshot(
            with_belt(snapshot_session, True, 60.0)
        )
        snapshot_session.apply_snapshot(
            dataclasses.replace(
                snapshot_session.current_snapshot,
                rear_door=DoorState.CLOSED,
                timestamp=120.0,
            )
        )
        self.assertEqual(snapshot_session.state, SessionState.ONBOARD)

        event_session = boarding_session()
        state = event_session.apply_event(
            SignalEvent(SignalEventType.REAR_BELT_BUCKLED, timestamp=60.0)
        )

        self.assertEqual(state, SessionState.BOARDING)
        self.assertEqual(event_session.state, SessionState.BOARDING)
        self.assertTrue(event_session.passenger_present)
        self.assertEqual(history_of(event_session), BOARDING_HISTORY)
        self.assertEqual(len(event_session.history), 1)

        state = event_session.apply_event(
            SignalEvent(SignalEventType.REAR_DOOR_CLOSED, timestamp=120.0)
        )

        self.assertEqual(state, SessionState.ONBOARD)
        self.assertEqual(event_session.state, SessionState.ONBOARD)
        self.assertEqual(len(event_session.history), 2)
        self.assertEqual(
            history_of(event_session), history_of(snapshot_session)
        )

    def test_buckle_with_high_temperature_in_boarding_keeps_info_guidance(
        self,
    ):
        session = boarding_session()

        session.apply_snapshot(
            dataclasses.replace(
                session.current_snapshot,
                rear_seat_belt_buckled=True,
                cabin_temp_c=35.5,
                timestamp=60.0,
            )
        )

        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(session.current_snapshot.rear_door, DoorState.OPEN)
        self.assertEqual(history_of(session), BOARDING_HISTORY)
        self.assertEqual(len(session.history), 1)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertNotEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertNotEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(guidance.reason, "boarding_dropoff")
        self.assertEqual(guidance.text, BOARDING_TEXT)
        self.assertNotIn("35.5도", guidance.text)
        self.assertNotIn("즉시", guidance.text)
        report = report_for_session(session)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 1)


if __name__ == "__main__":
    unittest.main()

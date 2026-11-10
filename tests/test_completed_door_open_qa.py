"""QA scenarios for changing only the rear door while COMPLETED.

COMPLETED is the terminal state: alighting has been confirmed and
the session is closed. Opening or closing the rear door on its own
after completion drives nothing — the session never leaves
COMPLETED, the transition history never grows, and the completed
guidance and report verdicts stay exactly as they were. The door
flag itself still lands on the current snapshot, and that is the
only effect a door-only step may have.

Unlike the ALIGHTING door-open file (where the session is still
mid-alighting, so the door interacts with the passenger latch and
the completion flow), every step here starts from a finished
session. Each door step is derived from the current snapshot with
dataclasses.replace, changing only rear_door and timestamp, except
for the high-temperature scenario, which also sets cabin_temp_c.
The setup is all six dropoff_normal snapshots (0.0 to 300.0),
which leave COMPLETED with no passenger present and six
transitions. The scenarios cover the snapshot path and the event
path, plus the guidance in every destination context and the
completed report. This file closes the door-only series: IDLE,
BOARDING, ONBOARD, DRIVING, ARRIVED, ALIGHTING and EXCEPTION
already have one.
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

COMPLETED_TEXT = "하차 확인이 완료되었습니다."


def completed_session():
    session = CareSession()
    for snapshot in dropoff_normal_snapshots():
        session.apply_snapshot(snapshot)
    return session


def with_door(session, door_state, timestamp):
    return dataclasses.replace(
        session.current_snapshot,
        rear_door=door_state,
        timestamp=timestamp,
    )


def history_of(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


COMPLETED_HISTORY = [
    (SessionState.IDLE, SessionState.BOARDING, "rear_door_opened", 0.0),
    (
        SessionState.BOARDING,
        SessionState.ONBOARD,
        "passenger_onboard",
        60.0,
    ),
    (SessionState.ONBOARD, SessionState.DRIVING, "ignition_on", 120.0),
    (SessionState.DRIVING, SessionState.ARRIVED, "ignition_off", 180.0),
    (
        SessionState.ARRIVED,
        SessionState.ALIGHTING,
        "alighting_started",
        240.0,
    ),
    (
        SessionState.ALIGHTING,
        SessionState.COMPLETED,
        "alighting_confirmed",
        300.0,
    ),
]


def assert_completed_report(test_case, session):
    report = report_for_session(session)
    test_case.assertEqual(report.final_state, SessionState.COMPLETED)
    test_case.assertTrue(report.completed)
    test_case.assertFalse(report.exception_occurred)
    test_case.assertEqual(report.exception_count, 0)
    test_case.assertEqual(report.transition_count, 6)
    test_case.assertEqual(report.started_at, 0.0)
    test_case.assertEqual(report.ended_at, 300.0)
    test_case.assertEqual(report.duration_seconds, 300.0)
    test_case.assertFalse(report.passenger_present)
    test_case.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")
    return report


class CompletedDoorOpenQATest(unittest.TestCase):
    def test_door_open_alone_in_completed_keeps_terminal_state(self):
        session = completed_session()

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertEqual(
            session.current_snapshot.rear_door, DoorState.CLOSED
        )
        self.assertEqual(session.current_snapshot.timestamp, 300.0)

        session.apply_snapshot(with_door(session, DoorState.OPEN, 360.0))

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertEqual(session.current_snapshot.rear_door, DoorState.OPEN)
        self.assertEqual(session.current_snapshot.timestamp, 360.0)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        self.assertEqual(guidance.text, COMPLETED_TEXT)
        report = assert_completed_report(self, session)
        self.assertIsNone(report.max_cabin_temp_c)

    def test_door_open_repeated_and_reclose_in_completed_idempotent(self):
        session = completed_session()

        for door_state, timestamp in (
            (DoorState.OPEN, 360.0),
            (DoorState.OPEN, 420.0),
            (DoorState.CLOSED, 480.0),
        ):
            session.apply_snapshot(
                with_door(session, door_state, timestamp)
            )

            self.assertEqual(session.state, SessionState.COMPLETED)
            self.assertFalse(session.passenger_present)
            self.assertEqual(history_of(session), COMPLETED_HISTORY)
            self.assertEqual(len(session.history), 6)

        self.assertEqual(
            session.current_snapshot.rear_door, DoorState.CLOSED
        )
        self.assertEqual(session.current_snapshot.timestamp, 480.0)
        report = assert_completed_report(self, session)
        self.assertIsNone(report.max_cabin_temp_c)

    def test_door_open_event_in_completed_matches_snapshot_path(self):
        event_session = completed_session()
        event_session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_OPENED, timestamp=360.0
            )
        )

        self.assertEqual(event_session.state, SessionState.COMPLETED)
        self.assertFalse(event_session.passenger_present)
        self.assertEqual(history_of(event_session), COMPLETED_HISTORY)
        self.assertEqual(
            event_session.current_snapshot.rear_door, DoorState.OPEN
        )

        snapshot_session = completed_session()
        snapshot_session.apply_snapshot(
            with_door(snapshot_session, DoorState.OPEN, 360.0)
        )

        self.assertEqual(
            history_of(event_session), history_of(snapshot_session)
        )
        self.assertEqual(event_session.state, snapshot_session.state)
        self.assertEqual(
            event_session.current_snapshot.rear_door,
            snapshot_session.current_snapshot.rear_door,
        )
        self.assertEqual(
            event_session.current_snapshot.timestamp,
            snapshot_session.current_snapshot.timestamp,
        )

    def test_door_open_with_high_temperature_in_completed_no_exception(
        self,
    ):
        session = completed_session()

        session.apply_snapshot(
            dataclasses.replace(
                session.current_snapshot,
                rear_door=DoorState.OPEN,
                cabin_temp_c=35.5,
                timestamp=360.0,
            )
        )

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertNotEqual(session.state, SessionState.EXCEPTION)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertEqual(len(session.history), 6)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        self.assertEqual(guidance.text, COMPLETED_TEXT)
        self.assertNotIn("35.5도", guidance.text)
        self.assertNotIn("즉시", guidance.text)
        report = assert_completed_report(self, session)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_door_open_guidance_completed_in_every_context(self):
        session = completed_session()
        session.apply_snapshot(with_door(session, DoorState.OPEN, 360.0))
        self.assertEqual(session.state, SessionState.COMPLETED)

        guidances = [
            guidance_for_session(session, context=context)
            for context in (
                DestinationContext.GENERAL,
                DestinationContext.DROPOFF,
                DestinationContext.PICKUP,
            )
        ]
        for guidance in guidances:
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.state, SessionState.COMPLETED)
            self.assertEqual(guidance.reason, "completed")
            self.assertEqual(guidance.text, COMPLETED_TEXT)
        self.assertEqual(guidances[0].text, guidances[1].text)
        self.assertEqual(guidances[1].text, guidances[2].text)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        assert_completed_report(self, session)

    def test_door_toggle_in_completed_only_updates_snapshot(self):
        session = completed_session()

        for door_state, timestamp in (
            (DoorState.OPEN, 360.0),
            (DoorState.CLOSED, 420.0),
            (DoorState.OPEN, 480.0),
        ):
            session.apply_snapshot(
                with_door(session, door_state, timestamp)
            )

            self.assertEqual(session.state, SessionState.COMPLETED)
            self.assertFalse(session.passenger_present)
            self.assertEqual(history_of(session), COMPLETED_HISTORY)
            self.assertEqual(
                session.current_snapshot.rear_door, door_state
            )
            self.assertEqual(
                session.current_snapshot.timestamp, timestamp
            )

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        report = assert_completed_report(self, session)
        self.assertIsNone(report.max_cabin_temp_c)


if __name__ == "__main__":
    unittest.main()

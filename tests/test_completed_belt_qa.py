"""QA scenarios for changing only the rear belt while COMPLETED.

The session has reached its terminal state: alighting has been
confirmed, the rear door is closed, and no passenger is latched
present. COMPLETED never advances again, so changing the belt on
its own adds no transition and leaves the state untouched. The
passenger latch still runs on every snapshot, though, independent
of the session state: a buckled belt re-latches the passenger
present even in COMPLETED, and the latch clears again only when
the rear door is open while the belt is released. Guidance and
the report judge completion from the terminal state and the
transition history, so a re-latched passenger flag alone changes
neither the completed guidance nor the completed report fields:
only the report's passenger_present copy of the live flag moves.

Unlike the simultaneous-input scenarios, each belt step here is
derived from the current snapshot with dataclasses.replace,
changing only rear_seat_belt_buckled and timestamp. The setup is
all six dropoff_normal snapshots (0.0 to 300.0), which leave
COMPLETED with no passenger present and six transitions. The
scenarios cover the snapshot path and the event path, plus the
guidance and report views of the held terminal state.
"""

import dataclasses
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


COMPLETED_HISTORY = [
    (SessionState.IDLE, SessionState.BOARDING, "rear_door_opened", 0.0),
    (
        SessionState.BOARDING,
        SessionState.ONBOARD,
        "passenger_onboard",
        60.0,
    ),
    (
        SessionState.ONBOARD,
        SessionState.DRIVING,
        "ignition_on",
        120.0,
    ),
    (
        SessionState.DRIVING,
        SessionState.ARRIVED,
        "ignition_off",
        180.0,
    ),
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


class CompletedBeltQATest(unittest.TestCase):
    def test_buckle_alone_in_completed_relatches_passenger_but_keeps_terminal_state(
        self,
    ):
        session = completed_session()

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertEqual(session.current_snapshot.rear_door, DoorState.CLOSED)
        self.assertFalse(session.current_snapshot.rear_seat_belt_buckled)
        self.assertEqual(
            session.current_snapshot.ignition, IgnitionState.OFF
        )
        self.assertEqual(session.current_snapshot.lock, LockState.UNLOCKED)
        self.assertEqual(session.current_snapshot.timestamp, 300.0)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        self.assertEqual(guidance.text, COMPLETED_TEXT)
        report = report_for_session(session)
        self.assertEqual(report.final_state, SessionState.COMPLETED)
        self.assertTrue(report.completed)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.started_at, 0.0)
        self.assertEqual(report.ended_at, 300.0)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertFalse(report.passenger_present)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

        session.apply_snapshot(with_belt(session, True, 360.0))

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertEqual(len(session.history), 6)
        self.assertTrue(session.current_snapshot.rear_seat_belt_buckled)
        self.assertEqual(session.current_snapshot.timestamp, 360.0)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        self.assertEqual(guidance.text, COMPLETED_TEXT)
        report = report_for_session(session)
        self.assertEqual(report.final_state, SessionState.COMPLETED)
        self.assertTrue(report.completed)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.started_at, 0.0)
        self.assertEqual(report.ended_at, 300.0)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_buckle_repeated_in_completed_is_idempotent(self):
        session = completed_session()

        session.apply_snapshot(with_belt(session, True, 360.0))
        session.apply_snapshot(with_belt(session, True, 370.0))

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertEqual(len(session.history), 6)
        self.assertTrue(session.current_snapshot.rear_seat_belt_buckled)
        self.assertEqual(session.current_snapshot.timestamp, 370.0)

    def test_belt_toggles_in_completed_flip_snapshot_flag_and_latch_only_on_buckle(
        self,
    ):
        session = completed_session()

        for timestamp, buckled in (
            (360.0, True),
            (370.0, False),
            (380.0, True),
        ):
            session.apply_snapshot(with_belt(session, buckled, timestamp))

            self.assertEqual(session.state, SessionState.COMPLETED)
            self.assertTrue(session.passenger_present)
            self.assertEqual(
                session.current_snapshot.rear_seat_belt_buckled, buckled
            )
            self.assertEqual(history_of(session), COMPLETED_HISTORY)
            self.assertEqual(len(session.history), 6)
            guidance = guidance_for_session(
                session, context=DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "completed")
            self.assertEqual(guidance.text, COMPLETED_TEXT)
            report = report_for_session(session)
            self.assertEqual(report.transition_count, 6)

    def test_belt_flag_at_door_open_in_completed_decides_passenger_latch(
        self,
    ):
        buckled = completed_session()
        buckled.apply_snapshot(with_belt(buckled, True, 360.0))
        buckled.apply_snapshot(
            dataclasses.replace(
                buckled.current_snapshot,
                rear_door=DoorState.OPEN,
                timestamp=420.0,
            )
        )

        self.assertEqual(buckled.state, SessionState.COMPLETED)
        self.assertTrue(buckled.passenger_present)
        self.assertTrue(buckled.current_snapshot.rear_seat_belt_buckled)
        self.assertEqual(history_of(buckled), COMPLETED_HISTORY)
        self.assertEqual(len(buckled.history), 6)
        guidance = guidance_for_session(
            buckled, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        self.assertEqual(guidance.text, COMPLETED_TEXT)
        report = report_for_session(buckled)
        self.assertTrue(report.completed)
        self.assertEqual(report.transition_count, 6)
        self.assertTrue(report.passenger_present)

        unbuckled = completed_session()
        unbuckled.apply_snapshot(with_belt(unbuckled, True, 360.0))
        unbuckled.apply_snapshot(with_belt(unbuckled, False, 370.0))

        self.assertEqual(unbuckled.state, SessionState.COMPLETED)
        self.assertTrue(unbuckled.passenger_present)
        self.assertFalse(
            unbuckled.current_snapshot.rear_seat_belt_buckled
        )
        self.assertEqual(
            unbuckled.current_snapshot.rear_door, DoorState.CLOSED
        )
        self.assertEqual(history_of(unbuckled), COMPLETED_HISTORY)

        unbuckled.apply_snapshot(
            dataclasses.replace(
                unbuckled.current_snapshot,
                rear_door=DoorState.OPEN,
                timestamp=420.0,
            )
        )

        self.assertEqual(unbuckled.state, SessionState.COMPLETED)
        self.assertFalse(unbuckled.passenger_present)
        self.assertFalse(
            unbuckled.current_snapshot.rear_seat_belt_buckled
        )
        self.assertEqual(history_of(unbuckled), COMPLETED_HISTORY)
        self.assertEqual(len(unbuckled.history), 6)
        guidance = guidance_for_session(
            unbuckled, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        self.assertEqual(guidance.text, COMPLETED_TEXT)
        report = report_for_session(unbuckled)
        self.assertTrue(report.completed)
        self.assertEqual(report.transition_count, 6)
        self.assertFalse(report.passenger_present)

    def test_event_path_buckle_in_completed_matches_snapshot_path(self):
        snapshot_session = completed_session()
        snapshot_session.apply_snapshot(
            with_belt(snapshot_session, True, 360.0)
        )
        snapshot_session.apply_snapshot(
            dataclasses.replace(
                snapshot_session.current_snapshot,
                rear_door=DoorState.OPEN,
                timestamp=420.0,
            )
        )
        self.assertEqual(snapshot_session.state, SessionState.COMPLETED)
        self.assertTrue(snapshot_session.passenger_present)
        self.assertEqual(
            history_of(snapshot_session), COMPLETED_HISTORY
        )

        event_session = completed_session()
        state = event_session.apply_event(
            SignalEvent(
                SignalEventType.REAR_BELT_BUCKLED, timestamp=360.0
            )
        )

        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(event_session.state, SessionState.COMPLETED)
        self.assertTrue(event_session.passenger_present)
        self.assertEqual(history_of(event_session), COMPLETED_HISTORY)
        self.assertEqual(len(event_session.history), 6)

        state = event_session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_OPENED, timestamp=420.0
            )
        )

        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(event_session.state, SessionState.COMPLETED)
        self.assertTrue(event_session.passenger_present)
        self.assertEqual(history_of(event_session), COMPLETED_HISTORY)
        self.assertEqual(len(event_session.history), 6)
        self.assertEqual(
            event_session.state, snapshot_session.state
        )
        self.assertEqual(
            event_session.passenger_present,
            snapshot_session.passenger_present,
        )
        self.assertEqual(
            history_of(event_session), history_of(snapshot_session)
        )

    def test_buckle_with_high_temperature_in_completed_keeps_completed_guidance(
        self,
    ):
        session = completed_session()

        session.apply_snapshot(
            dataclasses.replace(
                session.current_snapshot,
                rear_seat_belt_buckled=True,
                cabin_temp_c=35.5,
                timestamp=360.0,
            )
        )

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertTrue(session.passenger_present)
        self.assertEqual(session.current_snapshot.rear_door, DoorState.CLOSED)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertEqual(len(session.history), 6)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertNotEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertNotEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(guidance.reason, "completed")
        self.assertEqual(guidance.text, COMPLETED_TEXT)
        self.assertNotIn("35.5도", guidance.text)
        self.assertNotIn("즉시", guidance.text)
        report = report_for_session(session)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertTrue(report.completed)


if __name__ == "__main__":
    unittest.main()


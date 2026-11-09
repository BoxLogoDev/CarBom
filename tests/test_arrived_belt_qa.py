"""QA scenarios for changing only the rear belt while ARRIVED.

Driving is complete and the ignition is off: the rear door is
closed and the passenger is latched present. The passenger latch
follows the belt only while the rear door is open: a buckled belt
latches the passenger present, and a released belt clears the
latch only when the rear door is open. Changing the belt flag on
its own behind the closed door therefore keeps the passenger
latched, without moving the session out of ARRIVED and without
growing the transition history, because ARRIVED only advances
once the rear door opens. The belt flag held at door time is what
the door open then reads for the latch: opening the door moves to
ALIGHTING either way, but a still buckled belt holds the passenger
present, while a belt released before the door opens clears the
latch as alighting starts.

Unlike the simultaneous-input scenarios, each belt step here is
derived from the current snapshot with dataclasses.replace,
changing only rear_seat_belt_buckled and timestamp. The setup is
the first four dropoff_normal snapshots (0.0, rear door open,
60.0, belt buckled with the door closed, 120.0, ignition on, and
180.0, ignition off), which leave ARRIVED with a passenger
present and four transitions. The scenarios cover the snapshot
path and the event path, plus the guidance and report views of
the held arrived state.
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

ARRIVED_TEXT = "도착했습니다. 등원 하차 전 뒷좌석을 확인해 주세요."


def arrived_session():
    session = CareSession()
    for snapshot in dropoff_normal_snapshots()[:4]:
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


ARRIVED_HISTORY = [
    (SessionState.IDLE, SessionState.BOARDING, "rear_door_opened", 0.0),
    (
        SessionState.BOARDING,
        SessionState.ONBOARD,
        "passenger_onboard",
        60.0,
    ),
    (SessionState.ONBOARD, SessionState.DRIVING, "ignition_on", 120.0),
    (SessionState.DRIVING, SessionState.ARRIVED, "ignition_off", 180.0),
]


class ArrivedBeltQATest(unittest.TestCase):
    def test_unbuckle_alone_in_arrived_keeps_passenger_while_door_closed(
        self,
    ):
        session = arrived_session()

        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), ARRIVED_HISTORY)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(
            guidance.reason, "arrived_dropoff_check_rear_seat"
        )
        self.assertEqual(guidance.text, ARRIVED_TEXT)
        report = report_for_session(session)
        self.assertEqual(report.transition_count, 4)
        self.assertEqual(report.started_at, 0.0)
        self.assertEqual(report.ended_at, 180.0)
        self.assertEqual(report.duration_seconds, 180.0)
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

        session.apply_snapshot(with_belt(session, False, 240.0))

        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), ARRIVED_HISTORY)
        self.assertFalse(session.current_snapshot.rear_seat_belt_buckled)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(
            guidance.reason, "arrived_dropoff_check_rear_seat"
        )
        self.assertEqual(guidance.text, ARRIVED_TEXT)
        report = report_for_session(session)
        self.assertEqual(report.transition_count, 4)
        self.assertEqual(report.duration_seconds, 180.0)
        self.assertEqual(report.ended_at, 180.0)
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_unbuckle_repeated_in_arrived_is_idempotent(self):
        session = arrived_session()

        session.apply_snapshot(with_belt(session, False, 240.0))
        session.apply_snapshot(with_belt(session, False, 250.0))

        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), ARRIVED_HISTORY)
        self.assertEqual(len(session.history), 4)
        self.assertFalse(session.current_snapshot.rear_seat_belt_buckled)
        self.assertEqual(session.current_snapshot.timestamp, 250.0)

    def test_belt_toggles_in_arrived_flip_snapshot_flag_only(self):
        session = arrived_session()

        for timestamp, buckled in (
            (260.0, True),
            (270.0, False),
            (280.0, True),
        ):
            session.apply_snapshot(with_belt(session, buckled, timestamp))

            self.assertEqual(session.state, SessionState.ARRIVED)
            self.assertTrue(session.passenger_present)
            self.assertEqual(
                session.current_snapshot.rear_seat_belt_buckled, buckled
            )
            self.assertEqual(history_of(session), ARRIVED_HISTORY)
            self.assertEqual(len(session.history), 4)
            guidance = guidance_for_session(
                session, context=DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.REMIND)
            self.assertEqual(
                guidance.reason, "arrived_dropoff_check_rear_seat"
            )
            self.assertEqual(guidance.text, ARRIVED_TEXT)
            report = report_for_session(session)
            self.assertEqual(report.transition_count, 4)

    def test_belt_flag_at_door_open_in_arrived_decides_passenger_latch(
        self,
    ):
        buckled = arrived_session()
        buckled.apply_snapshot(
            dataclasses.replace(
                buckled.current_snapshot,
                rear_door=DoorState.OPEN,
                timestamp=300.0,
            )
        )

        self.assertEqual(buckled.state, SessionState.ALIGHTING)
        self.assertTrue(buckled.passenger_present)
        self.assertTrue(buckled.current_snapshot.rear_seat_belt_buckled)
        self.assertEqual(
            history_of(buckled),
            ARRIVED_HISTORY
            + [
                (
                    SessionState.ARRIVED,
                    SessionState.ALIGHTING,
                    "alighting_started",
                    300.0,
                )
            ],
        )
        self.assertEqual(len(buckled.history), 5)
        guidance = guidance_for_session(
            buckled, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "alighting")

        unbuckled = arrived_session()
        unbuckled.apply_snapshot(with_belt(unbuckled, False, 240.0))
        unbuckled.apply_snapshot(
            dataclasses.replace(
                unbuckled.current_snapshot,
                rear_door=DoorState.OPEN,
                timestamp=300.0,
            )
        )

        self.assertEqual(unbuckled.state, SessionState.ALIGHTING)
        self.assertFalse(unbuckled.passenger_present)
        self.assertFalse(
            unbuckled.current_snapshot.rear_seat_belt_buckled
        )
        self.assertEqual(
            history_of(unbuckled),
            ARRIVED_HISTORY
            + [
                (
                    SessionState.ARRIVED,
                    SessionState.ALIGHTING,
                    "alighting_started",
                    300.0,
                )
            ],
        )
        self.assertEqual(len(unbuckled.history), 5)
        guidance = guidance_for_session(
            unbuckled, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "alighting")

    def test_event_path_unbuckle_in_arrived_matches_snapshot_path(self):
        snapshot_session = arrived_session()
        snapshot_session.apply_snapshot(
            with_belt(snapshot_session, False, 240.0)
        )
        snapshot_session.apply_snapshot(
            dataclasses.replace(
                snapshot_session.current_snapshot,
                rear_door=DoorState.OPEN,
                timestamp=300.0,
            )
        )
        self.assertEqual(snapshot_session.state, SessionState.ALIGHTING)

        event_session = arrived_session()
        state = event_session.apply_event(
            SignalEvent(
                SignalEventType.REAR_BELT_UNBUCKLED, timestamp=240.0
            )
        )

        self.assertEqual(state, SessionState.ARRIVED)
        self.assertEqual(event_session.state, SessionState.ARRIVED)
        self.assertTrue(event_session.passenger_present)
        self.assertEqual(history_of(event_session), ARRIVED_HISTORY)
        self.assertEqual(len(event_session.history), 4)

        state = event_session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_OPENED, timestamp=300.0
            )
        )

        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertEqual(event_session.state, SessionState.ALIGHTING)
        self.assertFalse(event_session.passenger_present)
        self.assertEqual(len(event_session.history), 5)
        self.assertEqual(
            history_of(event_session), history_of(snapshot_session)
        )

    def test_unbuckle_with_high_temperature_in_arrived_escalates_remind(
        self,
    ):
        session = arrived_session()

        session.apply_snapshot(
            dataclasses.replace(
                session.current_snapshot,
                rear_seat_belt_buckled=False,
                cabin_temp_c=35.5,
                timestamp=240.0,
            )
        )

        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertTrue(session.passenger_present)
        self.assertEqual(session.current_snapshot.rear_door, DoorState.CLOSED)
        self.assertEqual(history_of(session), ARRIVED_HISTORY)
        self.assertEqual(len(session.history), 4)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertNotEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason,
            "arrived_dropoff_check_rear_seat_dangerous_cabin_temp",
        )
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)
        report = report_for_session(session)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 4)


if __name__ == "__main__":
    unittest.main()

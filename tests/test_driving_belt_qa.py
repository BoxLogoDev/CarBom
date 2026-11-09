"""QA scenarios for changing only the rear belt while DRIVING.

Driving is underway: the rear door is closed and the passenger is
latched present. The passenger latch follows the belt only while
the rear door is open: a buckled belt latches the passenger
present, and a released belt clears the latch only when the rear
door is open. Changing the belt flag on its own behind the closed
door therefore keeps the passenger latched, without moving the
session out of DRIVING and without growing the transition history,
because DRIVING only advances once the ignition goes off. Opening
the rear door while DRIVING also creates no transition on its own.
The door open still reads the belt flag held at door time for the
latch: a still buckled belt holds the passenger present, while a
belt released before the door opens clears the latch with the
session still in DRIVING.

Unlike the simultaneous-input scenarios, each belt step here is
derived from the current snapshot with dataclasses.replace,
changing only rear_seat_belt_buckled and timestamp. The setup is
the first three dropoff_normal snapshots (0.0, rear door open,
60.0, belt buckled with the door closed, and 120.0, ignition on),
which leave DRIVING with a passenger present and three
transitions. The scenarios cover the snapshot path and the event
path, plus the guidance and report views of the held driving
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

DRIVING_TEXT = "안전 운전 중입니다. 운전 중에는 화면을 조작하지 마세요."


def driving_session():
    session = CareSession()
    for snapshot in dropoff_normal_snapshots()[:3]:
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


DRIVING_HISTORY = [
    (SessionState.IDLE, SessionState.BOARDING, "rear_door_opened", 0.0),
    (
        SessionState.BOARDING,
        SessionState.ONBOARD,
        "passenger_onboard",
        60.0,
    ),
    (SessionState.ONBOARD, SessionState.DRIVING, "ignition_on", 120.0),
]


class DrivingBeltQATest(unittest.TestCase):
    def test_unbuckle_alone_in_driving_keeps_passenger_while_door_closed(
        self,
    ):
        session = driving_session()

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), DRIVING_HISTORY)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")
        self.assertEqual(guidance.text, DRIVING_TEXT)
        report = report_for_session(session)
        self.assertEqual(report.transition_count, 3)
        self.assertEqual(report.started_at, 0.0)
        self.assertEqual(report.ended_at, 120.0)
        self.assertEqual(report.duration_seconds, 120.0)
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

        session.apply_snapshot(with_belt(session, False, 180.0))

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), DRIVING_HISTORY)
        self.assertFalse(session.current_snapshot.rear_seat_belt_buckled)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")
        self.assertEqual(guidance.text, DRIVING_TEXT)
        report = report_for_session(session)
        self.assertEqual(report.transition_count, 3)
        self.assertEqual(report.duration_seconds, 120.0)
        self.assertEqual(report.ended_at, 120.0)
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_unbuckle_repeated_in_driving_is_idempotent(self):
        session = driving_session()

        session.apply_snapshot(with_belt(session, False, 180.0))
        session.apply_snapshot(with_belt(session, False, 190.0))

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), DRIVING_HISTORY)
        self.assertEqual(len(session.history), 3)
        self.assertFalse(session.current_snapshot.rear_seat_belt_buckled)
        self.assertEqual(session.current_snapshot.timestamp, 190.0)

    def test_belt_toggles_in_driving_flip_snapshot_flag_only(self):
        session = driving_session()

        for timestamp, buckled in (
            (200.0, True),
            (210.0, False),
            (220.0, True),
        ):
            session.apply_snapshot(with_belt(session, buckled, timestamp))

            self.assertEqual(session.state, SessionState.DRIVING)
            self.assertTrue(session.passenger_present)
            self.assertEqual(
                session.current_snapshot.rear_seat_belt_buckled, buckled
            )
            self.assertEqual(history_of(session), DRIVING_HISTORY)
            self.assertEqual(len(session.history), 3)
            guidance = guidance_for_session(
                session, context=DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "driving")
            self.assertEqual(guidance.text, DRIVING_TEXT)
            report = report_for_session(session)
            self.assertEqual(report.transition_count, 3)

    def test_belt_flag_at_door_open_in_driving_decides_passenger_latch(
        self,
    ):
        buckled = driving_session()
        buckled.apply_snapshot(
            dataclasses.replace(
                buckled.current_snapshot,
                rear_door=DoorState.OPEN,
                timestamp=240.0,
            )
        )

        self.assertEqual(buckled.state, SessionState.DRIVING)
        self.assertTrue(buckled.passenger_present)
        self.assertTrue(buckled.current_snapshot.rear_seat_belt_buckled)
        self.assertEqual(history_of(buckled), DRIVING_HISTORY)
        self.assertEqual(len(buckled.history), 3)
        report = report_for_session(buckled)
        self.assertEqual(report.transition_count, 3)

        unbuckled = driving_session()
        unbuckled.apply_snapshot(with_belt(unbuckled, False, 180.0))
        unbuckled.apply_snapshot(
            dataclasses.replace(
                unbuckled.current_snapshot,
                rear_door=DoorState.OPEN,
                timestamp=240.0,
            )
        )

        self.assertEqual(unbuckled.state, SessionState.DRIVING)
        self.assertFalse(unbuckled.passenger_present)
        self.assertFalse(
            unbuckled.current_snapshot.rear_seat_belt_buckled
        )
        self.assertEqual(history_of(unbuckled), DRIVING_HISTORY)
        self.assertEqual(len(unbuckled.history), 3)
        guidance = guidance_for_session(
            unbuckled, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.NONE)
        self.assertEqual(guidance.reason, "no_passenger")
        self.assertEqual(guidance.text, "")
        report = report_for_session(unbuckled)
        self.assertEqual(report.transition_count, 3)

    def test_event_path_unbuckle_in_driving_matches_snapshot_path(self):
        snapshot_session = driving_session()
        snapshot_session.apply_snapshot(
            with_belt(snapshot_session, False, 180.0)
        )
        snapshot_session.apply_snapshot(
            dataclasses.replace(
                snapshot_session.current_snapshot,
                rear_door=DoorState.OPEN,
                timestamp=240.0,
            )
        )
        self.assertEqual(snapshot_session.state, SessionState.DRIVING)
        self.assertFalse(snapshot_session.passenger_present)

        event_session = driving_session()
        state = event_session.apply_event(
            SignalEvent(
                SignalEventType.REAR_BELT_UNBUCKLED, timestamp=180.0
            )
        )

        self.assertEqual(state, SessionState.DRIVING)
        self.assertEqual(event_session.state, SessionState.DRIVING)
        self.assertTrue(event_session.passenger_present)
        self.assertEqual(history_of(event_session), DRIVING_HISTORY)
        self.assertEqual(len(event_session.history), 3)

        state = event_session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_OPENED, timestamp=240.0
            )
        )

        self.assertEqual(state, SessionState.DRIVING)
        self.assertEqual(event_session.state, SessionState.DRIVING)
        self.assertFalse(event_session.passenger_present)
        self.assertEqual(history_of(event_session), DRIVING_HISTORY)
        self.assertEqual(len(event_session.history), 3)
        self.assertEqual(
            history_of(event_session), history_of(snapshot_session)
        )

    def test_unbuckle_with_high_temperature_in_driving_keeps_driving_guidance(
        self,
    ):
        session = driving_session()

        session.apply_snapshot(
            dataclasses.replace(
                session.current_snapshot,
                rear_seat_belt_buckled=False,
                cabin_temp_c=35.5,
                timestamp=180.0,
            )
        )

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(session.current_snapshot.rear_door, DoorState.CLOSED)
        self.assertEqual(history_of(session), DRIVING_HISTORY)
        self.assertEqual(len(session.history), 3)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertNotEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertNotEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(guidance.reason, "driving")
        self.assertEqual(guidance.text, DRIVING_TEXT)
        self.assertNotIn("35.5도", guidance.text)
        self.assertNotIn("즉시", guidance.text)
        report = report_for_session(session)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 3)


if __name__ == "__main__":
    unittest.main()

    def test_belt_flag_at_door_open_in_driving_decides_passenger_latch(
        self,
    ):
        buckled = driving_session()
        buckled.apply_snapshot(
            dataclasses.replace(
                buckled.current_snapshot,
                rear_door=DoorState.OPEN,
                timestamp=240.0,
            )
        )

        self.assertEqual(buckled.state, SessionState.DRIVING)
        self.assertTrue(buckled.passenger_present)
        self.assertTrue(buckled.current_snapshot.rear_seat_belt_buckled)
        self.assertEqual(history_of(buckled), DRIVING_HISTORY)
        self.assertEqual(len(buckled.history), 3)
        guidance = guidance_for_session(
            buckled, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")
        self.assertEqual(guidance.text, DRIVING_TEXT)
        report = report_for_session(buckled)
        self.assertEqual(report.transition_count, 3)
        self.assertTrue(report.passenger_present)

        unbuckled = driving_session()
        unbuckled.apply_snapshot(with_belt(unbuckled, False, 180.0))
        unbuckled.apply_snapshot(
            dataclasses.replace(
                unbuckled.current_snapshot,
                rear_door=DoorState.OPEN,
                timestamp=240.0,
            )
        )

        self.assertEqual(unbuckled.state, SessionState.DRIVING)
        self.assertFalse(unbuckled.passenger_present)
        self.assertFalse(
            unbuckled.current_snapshot.rear_seat_belt_buckled
        )
        self.assertEqual(history_of(unbuckled), DRIVING_HISTORY)
        self.assertEqual(len(unbuckled.history), 3)
        guidance = guidance_for_session(
            unbuckled, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.NONE)
        self.assertEqual(guidance.reason, "no_passenger")
        self.assertEqual(guidance.text, "")
        report = report_for_session(unbuckled)
        self.assertEqual(report.transition_count, 3)
        self.assertFalse(report.passenger_present)

    def test_event_path_unbuckle_in_driving_matches_snapshot_path(self):
        snapshot_session = driving_session()
        snapshot_session.apply_snapshot(
            with_belt(snapshot_session, False, 180.0)
        )
        snapshot_session.apply_snapshot(
            dataclasses.replace(
                snapshot_session.current_snapshot,
                rear_door=DoorState.OPEN,
                timestamp=240.0,
            )
        )
        self.assertEqual(snapshot_session.state, SessionState.DRIVING)
        self.assertFalse(snapshot_session.passenger_present)

        event_session = driving_session()
        state = event_session.apply_event(
            SignalEvent(
                SignalEventType.REAR_BELT_UNBUCKLED, timestamp=180.0
            )
        )

        self.assertEqual(state, SessionState.DRIVING)
        self.assertEqual(event_session.state, SessionState.DRIVING)
        self.assertTrue(event_session.passenger_present)
        self.assertEqual(history_of(event_session), DRIVING_HISTORY)
        self.assertEqual(len(event_session.history), 3)

        state = event_session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_OPENED, timestamp=240.0
            )
        )

        self.assertEqual(state, SessionState.DRIVING)
        self.assertEqual(event_session.state, SessionState.DRIVING)
        self.assertFalse(event_session.passenger_present)
        self.assertEqual(len(event_session.history), 3)
        self.assertEqual(
            history_of(event_session), history_of(snapshot_session)
        )

    def test_unbuckle_with_high_temperature_in_driving_keeps_driving_guidance(
        self,
    ):
        session = driving_session()

        session.apply_snapshot(
            dataclasses.replace(
                session.current_snapshot,
                rear_seat_belt_buckled=False,
                cabin_temp_c=35.5,
                timestamp=180.0,
            )
        )

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(session.current_snapshot.rear_door, DoorState.CLOSED)
        self.assertEqual(history_of(session), DRIVING_HISTORY)
        self.assertEqual(len(session.history), 3)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertNotEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.reason, "driving")
        self.assertEqual(guidance.text, DRIVING_TEXT)
        self.assertNotIn("35.5도", guidance.text)
        self.assertNotIn("즉시", guidance.text)
        report = report_for_session(session)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 3)


if __name__ == "__main__":
    unittest.main()

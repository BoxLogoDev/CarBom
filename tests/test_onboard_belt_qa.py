"""QA scenarios for changing only the rear belt while ONBOARD.

Boarding is complete and the vehicle has not departed yet: the
rear door is closed and the passenger is latched present. The
passenger latch follows the belt only while the rear door is open:
a buckled belt latches the passenger present, and a released belt
clears the latch only when the rear door is open. Changing the
belt flag on its own behind the closed door therefore keeps the
passenger latched, without moving the session out of ONBOARD and
without growing the transition history, because ONBOARD only
advances once the ignition comes on. The belt flag held at door
time is what the door open then reads: opening the door with the
belt still buckled holds ONBOARD, while opening it after the belt
was released clears the latch and moves to ALIGHTING as a
pre-departure alighting.

Unlike the simultaneous-input scenarios, each belt step here is
derived from the current snapshot with dataclasses.replace,
changing only rear_seat_belt_buckled and timestamp. The setup is
the first two dropoff_normal snapshots (0.0, rear door open, and
60.0, belt buckled with the door closed), which leave ONBOARD
with a passenger present and two transitions. The scenarios cover
the snapshot path and the event path, plus the guidance and
report views of the held onboard state.
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

ONBOARD_TEXT = "뒷좌석 승차가 확인되었습니다. 출발 전 안전벨트를 확인해 주세요."


def onboard_session():
    session = CareSession()
    for snapshot in dropoff_normal_snapshots()[:2]:
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


ONBOARD_HISTORY = [
    (SessionState.IDLE, SessionState.BOARDING, "rear_door_opened", 0.0),
    (
        SessionState.BOARDING,
        SessionState.ONBOARD,
        "passenger_onboard",
        60.0,
    ),
]


class OnboardBeltQATest(unittest.TestCase):
    def test_unbuckle_alone_in_onboard_keeps_passenger_while_door_closed(
        self,
    ):
        session = onboard_session()

        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), ONBOARD_HISTORY)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "passenger_onboard")
        self.assertEqual(guidance.text, ONBOARD_TEXT)
        report = report_for_session(session)
        self.assertEqual(report.transition_count, 2)
        self.assertEqual(report.started_at, 0.0)
        self.assertEqual(report.ended_at, 60.0)
        self.assertEqual(report.duration_seconds, 60.0)
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

        session.apply_snapshot(with_belt(session, False, 120.0))

        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), ONBOARD_HISTORY)
        self.assertFalse(session.current_snapshot.rear_seat_belt_buckled)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "passenger_onboard")
        self.assertEqual(guidance.text, ONBOARD_TEXT)
        report = report_for_session(session)
        self.assertEqual(report.transition_count, 2)
        self.assertEqual(report.duration_seconds, 60.0)
        self.assertEqual(report.ended_at, 60.0)
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_unbuckle_repeated_in_onboard_is_idempotent(self):
        session = onboard_session()

        session.apply_snapshot(with_belt(session, False, 120.0))
        session.apply_snapshot(with_belt(session, False, 130.0))

        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), ONBOARD_HISTORY)
        self.assertEqual(len(session.history), 2)
        self.assertFalse(session.current_snapshot.rear_seat_belt_buckled)
        self.assertEqual(session.current_snapshot.timestamp, 130.0)

    def test_belt_toggles_in_onboard_flip_snapshot_flag_only(self):
        session = onboard_session()

        for timestamp, buckled in (
            (140.0, True),
            (150.0, False),
            (160.0, True),
        ):
            session.apply_snapshot(with_belt(session, buckled, timestamp))

            self.assertEqual(session.state, SessionState.ONBOARD)
            self.assertTrue(session.passenger_present)
            self.assertEqual(
                session.current_snapshot.rear_seat_belt_buckled, buckled
            )
            self.assertEqual(history_of(session), ONBOARD_HISTORY)
            self.assertEqual(len(session.history), 2)
            guidance = guidance_for_session(
                session, context=DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "passenger_onboard")
            self.assertEqual(guidance.text, ONBOARD_TEXT)
            report = report_for_session(session)
            self.assertEqual(report.transition_count, 2)

    def test_belt_flag_at_door_open_in_onboard_decides_alighting(self):
        buckled = onboard_session()
        buckled.apply_snapshot(
            dataclasses.replace(
                buckled.current_snapshot,
                rear_door=DoorState.OPEN,
                timestamp=180.0,
            )
        )

        self.assertEqual(buckled.state, SessionState.ONBOARD)
        self.assertTrue(buckled.passenger_present)
        self.assertEqual(history_of(buckled), ONBOARD_HISTORY)
        self.assertEqual(len(buckled.history), 2)

        unbuckled = onboard_session()
        unbuckled.apply_snapshot(with_belt(unbuckled, False, 120.0))
        unbuckled.apply_snapshot(
            dataclasses.replace(
                unbuckled.current_snapshot,
                rear_door=DoorState.OPEN,
                timestamp=180.0,
            )
        )

        self.assertEqual(unbuckled.state, SessionState.ALIGHTING)
        self.assertFalse(unbuckled.passenger_present)
        self.assertFalse(
            unbuckled.current_snapshot.rear_seat_belt_buckled
        )
        self.assertEqual(
            history_of(unbuckled),
            ONBOARD_HISTORY
            + [
                (
                    SessionState.ONBOARD,
                    SessionState.ALIGHTING,
                    "passenger_alighting",
                    180.0,
                )
            ],
        )
        guidance = guidance_for_session(
            unbuckled, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "alighting")

    def test_event_path_unbuckle_in_onboard_matches_snapshot_path(self):
        snapshot_session = onboard_session()
        snapshot_session.apply_snapshot(
            with_belt(snapshot_session, False, 120.0)
        )
        snapshot_session.apply_snapshot(
            dataclasses.replace(
                snapshot_session.current_snapshot,
                rear_door=DoorState.OPEN,
                timestamp=180.0,
            )
        )
        self.assertEqual(snapshot_session.state, SessionState.ALIGHTING)

        event_session = onboard_session()
        state = event_session.apply_event(
            SignalEvent(
                SignalEventType.REAR_BELT_UNBUCKLED, timestamp=120.0
            )
        )

        self.assertEqual(state, SessionState.ONBOARD)
        self.assertEqual(event_session.state, SessionState.ONBOARD)
        self.assertTrue(event_session.passenger_present)
        self.assertEqual(history_of(event_session), ONBOARD_HISTORY)
        self.assertEqual(len(event_session.history), 2)

        state = event_session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_OPENED, timestamp=180.0
            )
        )

        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertEqual(event_session.state, SessionState.ALIGHTING)
        self.assertEqual(len(event_session.history), 3)
        self.assertEqual(
            history_of(event_session), history_of(snapshot_session)
        )

    def test_unbuckle_with_high_temperature_in_onboard_keeps_info_guidance(
        self,
    ):
        session = onboard_session()

        session.apply_snapshot(
            dataclasses.replace(
                session.current_snapshot,
                rear_seat_belt_buckled=False,
                cabin_temp_c=35.5,
                timestamp=120.0,
            )
        )

        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertTrue(session.passenger_present)
        self.assertEqual(session.current_snapshot.rear_door, DoorState.CLOSED)
        self.assertEqual(history_of(session), ONBOARD_HISTORY)
        self.assertEqual(len(session.history), 2)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertNotEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertNotEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(guidance.reason, "passenger_onboard")
        self.assertEqual(guidance.text, ONBOARD_TEXT)
        self.assertNotIn("35.5도", guidance.text)
        self.assertNotIn("즉시", guidance.text)
        report = report_for_session(session)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 2)


if __name__ == "__main__":
    unittest.main()

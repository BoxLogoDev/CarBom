"""QA scenarios for changing only the rear belt while ALIGHTING.

Alighting has started at the destination: the rear door is open and
the session is waiting for the door to close so it can confirm
completion. The passenger latch follows the belt: a buckled belt
latches the passenger present, and a released belt clears the latch
while the rear door is open. Changing the belt flag on its own in
this window therefore flips passenger_present without moving the
session out of ALIGHTING and without growing the transition
history. Completion still needs the latch clear and the door
closed, so re-buckling in a cleared alighting blocks completion
until the belt is released again with the door open.

Unlike the simultaneous-input scenarios, each belt step here is
derived from the current snapshot with dataclasses.replace,
changing only rear_seat_belt_buckled and timestamp. The two setups
are the dropoff_normal snapshots: latched applies the first four
(0.0 to 180.0) and then the fifth (240.0) with only
rear_seat_belt_buckled set to True, leaving ALIGHTING with a
passenger present; cleared applies the first five as they are,
leaving ALIGHTING with no passenger. The scenarios cover the
snapshot path and the event path, plus the guidance and report
views of the held alighting state.
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

ALIGHTING_TEXT = "하차 중입니다. 뒷좌석이 비었는지 확인해 주세요."


def latched_alighting_session():
    session = CareSession()
    snapshots = dropoff_normal_snapshots()
    for item in snapshots[:4]:
        session.apply_snapshot(item)
    session.apply_snapshot(
        dataclasses.replace(snapshots[4], rear_seat_belt_buckled=True)
    )
    return session


def cleared_alighting_session():
    session = CareSession()
    for item in dropoff_normal_snapshots()[:5]:
        session.apply_snapshot(item)
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


ALIGHTING_HISTORY = [
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
]


class AlightingBeltQATest(unittest.TestCase):
    def test_unbuckle_alone_in_latched_alighting_clears_passenger(self):
        session = latched_alighting_session()

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), ALIGHTING_HISTORY)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "alighting")
        self.assertEqual(guidance.text, ALIGHTING_TEXT)
        report = report_for_session(session)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.started_at, 0.0)
        self.assertEqual(report.ended_at, 240.0)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

        session.apply_snapshot(with_belt(session, False, 300.0))

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), ALIGHTING_HISTORY)
        self.assertFalse(session.current_snapshot.rear_seat_belt_buckled)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "alighting")
        self.assertEqual(guidance.text, ALIGHTING_TEXT)
        report = report_for_session(session)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.ended_at, 240.0)
        self.assertFalse(report.passenger_present)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_unbuckle_repeated_in_latched_alighting_is_idempotent(self):
        session = latched_alighting_session()

        session.apply_snapshot(with_belt(session, False, 300.0))
        session.apply_snapshot(with_belt(session, False, 310.0))

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), ALIGHTING_HISTORY)
        self.assertEqual(len(session.history), 5)
        self.assertFalse(session.current_snapshot.rear_seat_belt_buckled)
        self.assertEqual(session.current_snapshot.timestamp, 310.0)

    def test_belt_toggles_in_latched_alighting_flip_passenger_only(self):
        session = latched_alighting_session()

        for timestamp, buckled, present in (
            (250.0, True, True),
            (260.0, False, False),
            (270.0, True, True),
            (280.0, False, False),
        ):
            session.apply_snapshot(with_belt(session, buckled, timestamp))

            self.assertEqual(session.state, SessionState.ALIGHTING)
            self.assertEqual(session.passenger_present, present)
            self.assertEqual(history_of(session), ALIGHTING_HISTORY)
            self.assertEqual(len(session.history), 5)
            guidance = guidance_for_session(
                session, context=DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "alighting")
            self.assertEqual(guidance.text, ALIGHTING_TEXT)
            report = report_for_session(session)
            self.assertEqual(report.transition_count, 5)

    def test_rebuckle_in_cleared_alighting_blocks_completion_until_unbuckled(
        self,
    ):
        session = cleared_alighting_session()

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), ALIGHTING_HISTORY)

        session.apply_snapshot(with_belt(session, True, 300.0))

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(session.current_snapshot.rear_door, DoorState.OPEN)
        self.assertEqual(history_of(session), ALIGHTING_HISTORY)

        session.apply_snapshot(
            dataclasses.replace(
                session.current_snapshot,
                rear_door=DoorState.CLOSED,
                timestamp=360.0,
            )
        )

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertNotEqual(session.state, SessionState.COMPLETED)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), ALIGHTING_HISTORY)
        self.assertEqual(len(session.history), 5)

        session.apply_snapshot(
            dataclasses.replace(
                session.current_snapshot,
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=False,
                timestamp=420.0,
            )
        )

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), ALIGHTING_HISTORY)

        session.apply_snapshot(
            dataclasses.replace(
                session.current_snapshot,
                rear_door=DoorState.CLOSED,
                timestamp=480.0,
            )
        )

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        self.assertEqual(
            history_of(session),
            ALIGHTING_HISTORY
            + [
                (
                    SessionState.ALIGHTING,
                    SessionState.COMPLETED,
                    "alighting_confirmed",
                    480.0,
                )
            ],
        )
        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 480.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_event_path_unbuckle_in_latched_alighting_matches_snapshot_path(
        self,
    ):
        snapshot_session = latched_alighting_session()
        snapshot_session.apply_snapshot(
            with_belt(snapshot_session, False, 300.0)
        )
        snapshot_session.apply_snapshot(
            dataclasses.replace(
                snapshot_session.current_snapshot,
                rear_door=DoorState.CLOSED,
                timestamp=360.0,
            )
        )
        self.assertEqual(snapshot_session.state, SessionState.COMPLETED)

        event_session = latched_alighting_session()
        state = event_session.apply_event(
            SignalEvent(
                SignalEventType.REAR_BELT_UNBUCKLED, timestamp=300.0
            )
        )

        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertEqual(event_session.state, SessionState.ALIGHTING)
        self.assertFalse(event_session.passenger_present)
        self.assertEqual(history_of(event_session), ALIGHTING_HISTORY)
        self.assertEqual(len(event_session.history), 5)

        state = event_session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_CLOSED, timestamp=360.0
            )
        )

        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(event_session.state, SessionState.COMPLETED)
        self.assertEqual(len(event_session.history), 6)
        self.assertEqual(
            history_of(event_session), history_of(snapshot_session)
        )

    def test_unbuckle_with_high_temperature_in_latched_alighting_keeps_info_guidance(
        self,
    ):
        session = latched_alighting_session()

        session.apply_snapshot(
            dataclasses.replace(
                session.current_snapshot,
                rear_seat_belt_buckled=False,
                cabin_temp_c=35.5,
                timestamp=300.0,
            )
        )

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(session.current_snapshot.rear_door, DoorState.OPEN)
        self.assertEqual(history_of(session), ALIGHTING_HISTORY)
        self.assertEqual(len(session.history), 5)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertNotEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertNotEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(guidance.reason, "alighting")
        self.assertEqual(guidance.text, ALIGHTING_TEXT)
        self.assertNotIn("35.5도", guidance.text)
        self.assertNotIn("즉시", guidance.text)
        report = report_for_session(session)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 5)


if __name__ == "__main__":
    unittest.main()

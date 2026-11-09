"""QA scenarios for changing only the rear door while ALIGHTING.

This angle is not covered by the ARRIVED door-open file. In
ARRIVED, opening the rear door creates the transition to
ALIGHTING with reason alighting_started. Here the session is
already in ALIGHTING, so opening the door must create no
transition at all.

The key sub-state is a closed alighting. Closing the door while
the rear belt is still buckled does not confirm completion,
because a passenger remains latched. The session therefore
stays in ALIGHTING with the door shut. Reopening the door from
that sub-state must keep ALIGHTING, keep the passenger latch
while the belt stays buckled, and leave the transition history
unchanged. Only releasing the belt with the door open and
then closing the door completes the session.

Other ALIGHTING files change a single different flag, such as
the belt. This file changes only rear_door and timestamp from
the current snapshot, except for the high-temperature scenario,
which also sets cabin_temp_c. The scenarios cover the
snapshot path and the event path, plus the guidance and
report views of the reopened alighting state.
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


def closed_latched_alighting_session():
    session = latched_alighting_session()
    session.apply_snapshot(
        dataclasses.replace(
            session.current_snapshot,
            rear_door=DoorState.CLOSED,
            timestamp=300.0,
        )
    )
    return session


def cleared_alighting_session():
    session = CareSession()
    for item in dropoff_normal_snapshots()[:5]:
        session.apply_snapshot(item)
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


class AlightingDoorOpenQATest(unittest.TestCase):
    def test_reopen_alone_in_closed_alighting_keeps_alighting_and_passenger(
        self,
    ):
        session = closed_latched_alighting_session()

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), ALIGHTING_HISTORY)
        self.assertEqual(len(session.history), 5)
        self.assertEqual(
            session.current_snapshot.rear_door, DoorState.CLOSED
        )

        session.apply_snapshot(with_door(session, DoorState.OPEN, 360.0))

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), ALIGHTING_HISTORY)
        self.assertEqual(session.current_snapshot.rear_door, DoorState.OPEN)
        self.assertEqual(session.current_snapshot.timestamp, 360.0)
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
        self.assertEqual(report.exception_count, 0)
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_door_open_repeated_and_reclose_while_belted_stay_alighting(
        self,
    ):
        session = closed_latched_alighting_session()

        for door_state, timestamp in (
            (DoorState.OPEN, 360.0),
            (DoorState.OPEN, 420.0),
            (DoorState.CLOSED, 480.0),
        ):
            session.apply_snapshot(
                with_door(session, door_state, timestamp)
            )

            self.assertEqual(session.state, SessionState.ALIGHTING)
            self.assertTrue(session.passenger_present)
            self.assertEqual(history_of(session), ALIGHTING_HISTORY)
            self.assertEqual(len(session.history), 5)

        self.assertEqual(
            session.current_snapshot.rear_door, DoorState.CLOSED
        )

        latched = latched_alighting_session()
        self.assertEqual(
            latched.current_snapshot.rear_door, DoorState.OPEN
        )
        latched.apply_snapshot(with_door(latched, DoorState.OPEN, 300.0))
        self.assertEqual(latched.state, SessionState.ALIGHTING)
        self.assertTrue(latched.passenger_present)
        self.assertEqual(history_of(latched), ALIGHTING_HISTORY)
        self.assertEqual(len(latched.history), 5)

        cleared = cleared_alighting_session()
        cleared.apply_snapshot(with_door(cleared, DoorState.OPEN, 300.0))
        self.assertEqual(cleared.state, SessionState.ALIGHTING)
        self.assertFalse(cleared.passenger_present)
        self.assertEqual(history_of(cleared), ALIGHTING_HISTORY)
        self.assertEqual(len(cleared.history), 5)

    def test_door_open_event_in_closed_alighting_matches_snapshot_path(
        self,
    ):
        event_session = closed_latched_alighting_session()
        event_session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_OPENED, timestamp=360.0
            )
        )

        self.assertEqual(event_session.state, SessionState.ALIGHTING)
        self.assertTrue(event_session.passenger_present)
        self.assertEqual(history_of(event_session), ALIGHTING_HISTORY)
        self.assertEqual(len(event_session.history), 5)
        self.assertEqual(
            event_session.current_snapshot.rear_door, DoorState.OPEN
        )

        snapshot_session = closed_latched_alighting_session()
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

    def test_reopen_with_high_temperature_in_closed_alighting_no_exception(
        self,
    ):
        session = closed_latched_alighting_session()

        session.apply_snapshot(
            dataclasses.replace(
                session.current_snapshot,
                rear_door=DoorState.OPEN,
                cabin_temp_c=35.5,
                timestamp=360.0,
            )
        )

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertNotEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), ALIGHTING_HISTORY)
        self.assertEqual(len(session.history), 5)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "alighting")
        self.assertEqual(guidance.text, ALIGHTING_TEXT)
        self.assertNotIn("35.5도", guidance.text)
        self.assertNotIn("즉시", guidance.text)
        report = report_for_session(session)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.exception_count, 0)
        self.assertFalse(report.exception_occurred)

    def test_reopened_alighting_guidance_same_all_contexts(self):
        session = closed_latched_alighting_session()
        session.apply_snapshot(with_door(session, DoorState.OPEN, 360.0))
        self.assertEqual(session.state, SessionState.ALIGHTING)

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
            self.assertEqual(guidance.reason, "alighting")
            self.assertEqual(guidance.text, ALIGHTING_TEXT)
        self.assertEqual(guidances[0].text, guidances[1].text)
        self.assertEqual(guidances[1].text, guidances[2].text)

    def test_reopen_then_unbuckle_and_close_completes(self):
        session = closed_latched_alighting_session()

        session.apply_snapshot(with_door(session, DoorState.OPEN, 360.0))

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), ALIGHTING_HISTORY)

        session.apply_snapshot(
            dataclasses.replace(
                session.current_snapshot,
                rear_seat_belt_buckled=False,
                timestamp=420.0,
            )
        )

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), ALIGHTING_HISTORY)
        self.assertEqual(len(session.history), 5)

        session.apply_snapshot(
            with_door(session, DoorState.CLOSED, 480.0)
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
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")


if __name__ == "__main__":
    unittest.main()




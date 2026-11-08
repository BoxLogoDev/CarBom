"""QA scenarios for simultaneous inputs arriving while DRIVING.

Existing simultaneous-input QA covers IDLE, BOARDING, and ONBOARD:
several signals named in one snapshot before departure. Existing
DRIVING QA covers single signals one at a time: the rear door
opening, a mid-drive unbuckle, or HVAC changes on their own. This
file covers the rear door, rear belt, ignition, and lock all named
in one snapshot taken from DRIVING. In one snapshot the precedence
rules decide the outcome: the exception check runs first (ignition
off, locked, door closed, passenger latched) and can take the
session straight to EXCEPTION without an ARRIVED stop; an open door
blocks that exception, so ignition-off then walks through ARRIVED
into ALIGHTING in the same snapshot; and ignition-on holds DRIVING
no matter what the door, belt, and lock flags say, while the
passenger latch still follows its own rule (it clears only when the
belt is released while the door is open).
"""

import unittest

from engine import (
    CareSession,
    DestinationContext,
    DoorState,
    GuidanceLevel,
    IgnitionState,
    LockState,
    SessionState,
    SignalSnapshot,
    guidance_for_session,
    report_for_session,
)


def snapshot(
    timestamp,
    *,
    door_open=False,
    belt=False,
    ignition=False,
    locked=False,
    cabin_temp_c=None,
):
    return SignalSnapshot(
        rear_door=DoorState.OPEN if door_open else DoorState.CLOSED,
        rear_seat_belt_buckled=belt,
        ignition=IgnitionState.ON if ignition else IgnitionState.OFF,
        lock=LockState.LOCKED if locked else LockState.UNLOCKED,
        cabin_temp_c=cabin_temp_c,
        timestamp=timestamp,
    )


def driving_session():
    """DRIVING reached by opening the rear door, belting, ignition."""
    session = CareSession()
    session.apply_snapshot(snapshot(0.0, door_open=True))
    session.apply_snapshot(snapshot(10.0, belt=True))
    session.apply_snapshot(snapshot(20.0, belt=True, ignition=True))
    return session


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
        10.0,
    ),
    (
        SessionState.ONBOARD,
        SessionState.DRIVING,
        "ignition_on",
        20.0,
    ),
]


class DrivingSimultaneousInputQATest(unittest.TestCase):
    def test_door_open_unbelted_ignition_off_walks_to_alighting(self):
        session = driving_session()
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(history_of(session), DRIVING_HISTORY)

        result = session.apply_snapshot(
            snapshot(30.0, door_open=True, belt=False, ignition=False)
        )

        # One snapshot: the belt release with the door open clears
        # the latch, and ignition-off walks ARRIVED into ALIGHTING
        # at the same timestamp instead of stopping at ARRIVED.
        self.assertEqual(result, SessionState.ALIGHTING)
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(
            history_of(session),
            DRIVING_HISTORY
            + [
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
                    30.0,
                ),
            ],
        )

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "alighting")

        result = session.apply_snapshot(snapshot(40.0))
        self.assertEqual(result, SessionState.COMPLETED)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 40.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_door_closed_belted_ignition_off_locked_enters_exception(self):
        session = driving_session()

        result = session.apply_snapshot(
            snapshot(
                30.0,
                door_open=False,
                belt=True,
                ignition=False,
                locked=True,
                cabin_temp_c=35.5,
            )
        )

        # The exception check runs before the arrival transition:
        # DRIVING goes straight to EXCEPTION with no ARRIVED stop.
        self.assertEqual(result, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(
            history_of(session),
            DRIVING_HISTORY
            + [
                (
                    SessionState.DRIVING,
                    SessionState.EXCEPTION,
                    "ignition_off_locked_passenger_present",
                    30.0,
                )
            ],
        )

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason,
            "passenger_left_locked_dangerous_cabin_temp",
        )
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.transition_count, 4)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_door_closed_belted_ignition_off_unlocked_stops_at_arrived(self):
        session = driving_session()

        result = session.apply_snapshot(
            snapshot(30.0, door_open=False, belt=True, ignition=False)
        )

        # Same snapshot as the exception case but unlocked: this is
        # a plain arrival, and the closed door with a latched
        # passenger holds ARRIVED instead of starting alighting.
        self.assertEqual(result, SessionState.ARRIVED)
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertTrue(session.passenger_present)
        self.assertEqual(
            history_of(session),
            DRIVING_HISTORY
            + [
                (
                    SessionState.DRIVING,
                    SessionState.ARRIVED,
                    "ignition_off",
                    30.0,
                )
            ],
        )

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(guidance.reason, "arrived_dropoff_check_rear_seat")

        result = session.apply_snapshot(
            snapshot(30.0, door_open=False, belt=True, ignition=False)
        )
        self.assertEqual(result, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 4)
        self.assertEqual(report.duration_seconds, 30.0)

    def test_door_open_belted_ignition_off_locked_walks_to_alighting(self):
        session = driving_session()

        result = session.apply_snapshot(
            snapshot(
                30.0, door_open=True, belt=True, ignition=False, locked=True
            )
        )

        # The open door blocks the exception even though the vehicle
        # is locked, so ignition-off walks through ARRIVED into
        # ALIGHTING in one snapshot, passenger still latched.
        self.assertEqual(result, SessionState.ALIGHTING)
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(
            history_of(session),
            DRIVING_HISTORY
            + [
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
                    30.0,
                ),
            ],
        )

        result = session.apply_snapshot(
            snapshot(40.0, door_open=True, belt=False)
        )
        self.assertEqual(result, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 5)

        result = session.apply_snapshot(snapshot(50.0))
        self.assertEqual(result, SessionState.COMPLETED)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 50.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_door_closed_unbelted_ignition_on_locked_holds_driving(self):
        session = driving_session()

        result = session.apply_snapshot(
            snapshot(
                30.0, door_open=False, belt=False, ignition=True, locked=True
            )
        )

        # Ignition-on blocks the exception, and the closed door keeps
        # the latch even though the belt flag is off in the same
        # snapshot: the drive continues with the passenger counted.
        self.assertEqual(result, SessionState.DRIVING)
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), DRIVING_HISTORY)
        self.assertTrue(session.current_snapshot.locked)
        self.assertFalse(session.current_snapshot.rear_seat_belt_buckled)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")

        result = session.apply_snapshot(
            snapshot(
                30.0, door_open=False, belt=False, ignition=True, locked=True
            )
        )
        self.assertEqual(result, SessionState.DRIVING)
        self.assertEqual(history_of(session), DRIVING_HISTORY)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 3)

    def test_door_open_unbelted_ignition_on_locked_clears_then_completes(self):
        session = driving_session()

        result = session.apply_snapshot(
            snapshot(
                30.0, door_open=True, belt=False, ignition=True, locked=True
            )
        )

        # One snapshot: the belt release with the door open clears
        # the latch, yet ignition-on holds DRIVING and the lock
        # cannot raise an exception for a passenger who is gone.
        self.assertEqual(result, SessionState.DRIVING)
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), DRIVING_HISTORY)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.NONE)
        self.assertEqual(guidance.reason, "no_passenger")
        self.assertEqual(guidance.text, "")

        result = session.apply_snapshot(
            snapshot(
                40.0, door_open=False, belt=False, ignition=False, locked=True
            )
        )

        # With no passenger latched, the locked ignition-off snapshot
        # is not an exception: it walks ARRIVED and ALIGHTING
        # straight to COMPLETED at one timestamp.
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(
            history_of(session),
            DRIVING_HISTORY
            + [
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
                    40.0,
                ),
                (
                    SessionState.ALIGHTING,
                    SessionState.COMPLETED,
                    "alighting_confirmed",
                    40.0,
                ),
            ],
        )

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 40.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")


if __name__ == "__main__":
    unittest.main()

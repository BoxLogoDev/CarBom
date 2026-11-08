"""QA scenarios for simultaneous inputs arriving while EXCEPTION.

Existing simultaneous-input QA covers IDLE, BOARDING, ONBOARD,
DRIVING, ARRIVED, and ALIGHTING. Those files name several signals in
one snapshot before any exception has happened. Existing EXCEPTION
QA covers single signals one at a time. It recovers by unlocking
with the ignition on, or by opening the rear door, or it re-enters
EXCEPTION after a recovery. This file covers the rear door, rear
belt, ignition, and lock all named in one snapshot taken from
EXCEPTION. In one snapshot the precedence rules decide the outcome.
The passenger latch updates before any state step runs, so a belt
release with the door open clears the latch first, while a belt
release behind a closed door clears nothing. An open door then
moves EXCEPTION to ALIGHTING. An unlock with the ignition on
recovers through ONBOARD to DRIVING in the same snapshot. Either
half of that recovery on its own holds EXCEPTION. A snapshot that
repeats the exception shape does not re-enter EXCEPTION, so the
exception is never counted twice. Every test starts from the same
EXCEPTION session. The forgotten_rising_temp scenario leaves the
passenger latched in a locked vehicle with the ignition off.
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
from engine.adapters.simulator import replay_scenario


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


def exception_session():
    """EXCEPTION reached by replaying forgotten_rising_temp."""
    session = CareSession()
    replay_scenario(session, "forgotten_rising_temp")
    return session


def history_of(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


EXCEPTION_HISTORY = [
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
        SessionState.EXCEPTION,
        "ignition_off_locked_passenger_present",
        240.0,
    ),
]


class ExceptionSimultaneousInputQATest(unittest.TestCase):
    def test_door_open_belted_ignition_off_locked_moves_to_alighting_then_completes(self):
        session = exception_session()
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), EXCEPTION_HISTORY)

        result = session.apply_snapshot(
            snapshot(
                480.0,
                door_open=True,
                belt=True,
                ignition=False,
                locked=True,
                cabin_temp_c=35.5,
            )
        )

        # The open door is the only exit this snapshot offers. The
        # belt stays buckled, so the passenger stays latched and
        # ALIGHTING waits for the passenger to leave.
        self.assertEqual(result, SessionState.ALIGHTING)
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(
            history_of(session),
            EXCEPTION_HISTORY
            + [
                (
                    SessionState.EXCEPTION,
                    SessionState.ALIGHTING,
                    "rear_door_opened_after_exception",
                    480.0,
                )
            ],
        )

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "alighting")

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

        result = session.apply_snapshot(
            snapshot(540.0, door_open=True, belt=False)
        )
        self.assertEqual(result, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 6)

        result = session.apply_snapshot(snapshot(600.0))
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(
            history_of(session),
            EXCEPTION_HISTORY
            + [
                (
                    SessionState.EXCEPTION,
                    SessionState.ALIGHTING,
                    "rear_door_opened_after_exception",
                    480.0,
                ),
                (
                    SessionState.ALIGHTING,
                    SessionState.COMPLETED,
                    "alighting_confirmed",
                    600.0,
                ),
            ],
        )

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.transition_count, 7)
        self.assertEqual(report.duration_seconds, 600.0)
        self.assertEqual(report.summary, "예외 발생 후 하차 확인 완료")

    def test_door_closed_unbelted_ignition_on_unlocked_recovers_to_driving(self):
        session = exception_session()

        result = session.apply_snapshot(
            snapshot(
                480.0,
                door_open=False,
                belt=False,
                ignition=True,
                locked=False,
            )
        )

        # Unlock and ignition-on together recover in two steps at
        # the same timestamp. The belt release cannot clear the
        # latch while the door is closed, so the passenger stays
        # latched through the recovery.
        self.assertEqual(result, SessionState.DRIVING)
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(
            history_of(session),
            EXCEPTION_HISTORY
            + [
                (
                    SessionState.EXCEPTION,
                    SessionState.ONBOARD,
                    "unlocked_and_ignition_on_after_exception",
                    480.0,
                ),
                (
                    SessionState.ONBOARD,
                    SessionState.DRIVING,
                    "ignition_on",
                    480.0,
                ),
            ],
        )

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 7)

    def test_door_open_unbelted_ignition_on_locked_clears_latch_then_completes(self):
        session = exception_session()

        result = session.apply_snapshot(
            snapshot(
                480.0,
                door_open=True,
                belt=False,
                ignition=True,
                locked=True,
            )
        )

        # The belt release with the door open clears the latch
        # before any state step runs. The open door then takes
        # EXCEPTION to ALIGHTING even though the ignition is on
        # and the vehicle is locked.
        self.assertEqual(result, SessionState.ALIGHTING)
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(
            history_of(session),
            EXCEPTION_HISTORY
            + [
                (
                    SessionState.EXCEPTION,
                    SessionState.ALIGHTING,
                    "rear_door_opened_after_exception",
                    480.0,
                )
            ],
        )

        result = session.apply_snapshot(snapshot(540.0))
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(
            history_of(session),
            EXCEPTION_HISTORY
            + [
                (
                    SessionState.EXCEPTION,
                    SessionState.ALIGHTING,
                    "rear_door_opened_after_exception",
                    480.0,
                ),
                (
                    SessionState.ALIGHTING,
                    SessionState.COMPLETED,
                    "alighting_confirmed",
                    540.0,
                ),
            ],
        )

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.transition_count, 7)
        self.assertEqual(report.duration_seconds, 540.0)
        self.assertEqual(report.summary, "예외 발생 후 하차 확인 완료")

    def test_door_closed_unbelted_ignition_off_unlocked_holds_exception_idempotently(self):
        session = exception_session()

        simultaneous = snapshot(
            480.0,
            door_open=False,
            belt=False,
            ignition=False,
            locked=False,
            cabin_temp_c=35.5,
        )
        result = session.apply_snapshot(simultaneous)

        # Unlocking on its own is not a recovery. The door is
        # closed, so the belt release cannot clear the latch. The
        # ignition is off, so the unlock-and-ignition recovery
        # does not fire either.
        self.assertEqual(result, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), EXCEPTION_HISTORY)

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

        result = session.apply_snapshot(
            snapshot(
                540.0,
                door_open=False,
                belt=False,
                ignition=False,
                locked=False,
                cabin_temp_c=35.5,
            )
        )
        self.assertEqual(result, SessionState.EXCEPTION)
        self.assertEqual(history_of(session), EXCEPTION_HISTORY)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 5)

    def test_door_closed_belted_ignition_on_locked_holds_exception(self):
        session = exception_session()

        result = session.apply_snapshot(
            snapshot(
                480.0,
                door_open=False,
                belt=True,
                ignition=True,
                locked=True,
            )
        )

        # Ignition-on on its own is not a recovery either.
        # Recovery needs the unlock and the ignition in the same
        # snapshot, and this vehicle is still locked.
        self.assertEqual(result, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), EXCEPTION_HISTORY)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.reason, "passenger_left_locked")

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 5)

    def test_exception_shape_repeated_holds_exception_without_double_counting(self):
        session = exception_session()

        result = session.apply_snapshot(
            snapshot(
                480.0,
                door_open=False,
                belt=True,
                ignition=False,
                locked=True,
                cabin_temp_c=35.5,
            )
        )

        # The snapshot matches the exception shape exactly, but
        # the session is already in EXCEPTION. Nothing re-enters,
        # and the exception is not counted twice.
        self.assertEqual(result, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), EXCEPTION_HISTORY)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason,
            "passenger_left_locked_dangerous_cabin_temp",
        )

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 5)


if __name__ == "__main__":
    unittest.main()

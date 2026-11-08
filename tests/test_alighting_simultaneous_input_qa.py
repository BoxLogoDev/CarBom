"""QA scenarios for simultaneous inputs arriving while ALIGHTING.

Existing simultaneous-input QA covers IDLE, BOARDING, ONBOARD,
DRIVING, and ARRIVED: several signals named in one snapshot before
the alighting phase. Existing ALIGHTING QA covers single signals
one at a time: HVAC changes, ignition changes, a lock on its own,
or an interrupted alighting. This file covers the rear door, rear
belt, ignition, and lock all named in one snapshot taken from
ALIGHTING. In one snapshot the precedence rules decide the
outcome: the exception check runs first (ignition off, locked,
door closed, passenger latched) and can take the session straight
to EXCEPTION, even after the passenger latch had already cleared,
if the same snapshot re-buckles the belt; an open door blocks that
exception and holds ALIGHTING; and ALIGHTING completes only when
the passenger latch is clear and the door is closed, so a lock on
its own never blocks completion.
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


def _drive_to_arrived(session):
    session.apply_snapshot(snapshot(0.0, door_open=True))
    session.apply_snapshot(snapshot(10.0, belt=True))
    session.apply_snapshot(snapshot(20.0, belt=True, ignition=True))
    session.apply_snapshot(snapshot(30.0, belt=True))
    return session


def alighting_cleared_session():
    """ALIGHTING reached with the passenger latch already cleared."""
    session = _drive_to_arrived(CareSession())
    session.apply_snapshot(snapshot(40.0, door_open=True, belt=False))
    return session


def alighting_latched_session():
    """ALIGHTING reached with the passenger still latched."""
    session = _drive_to_arrived(CareSession())
    session.apply_snapshot(snapshot(40.0, door_open=True, belt=True))
    return session


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
        10.0,
    ),
    (
        SessionState.ONBOARD,
        SessionState.DRIVING,
        "ignition_on",
        20.0,
    ),
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
        40.0,
    ),
]


class AlightingSimultaneousInputQATest(unittest.TestCase):
    def test_cleared_door_closed_unbelted_ignition_off_unlocked_completes(self):
        session = alighting_cleared_session()
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), ALIGHTING_HISTORY)

        result = session.apply_snapshot(
            snapshot(50.0, door_open=False, belt=False, ignition=False)
        )

        # One snapshot: latch already clear and the door closed, so
        # ALIGHTING confirms completion in a single step.
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(
            history_of(session),
            ALIGHTING_HISTORY
            + [
                (
                    SessionState.ALIGHTING,
                    SessionState.COMPLETED,
                    "alighting_confirmed",
                    50.0,
                )
            ],
        )

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 50.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

        # COMPLETED is terminal: a further simultaneous snapshot
        # changes nothing.
        result = session.apply_snapshot(
            snapshot(
                60.0, door_open=True, belt=False, ignition=True, locked=True
            )
        )
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)

    def test_cleared_rebuckled_door_closed_ignition_off_locked_enters_exception(self):
        session = alighting_cleared_session()
        self.assertFalse(session.passenger_present)

        result = session.apply_snapshot(
            snapshot(
                50.0,
                door_open=False,
                belt=True,
                ignition=False,
                locked=True,
                cabin_temp_c=35.5,
            )
        )

        # The belt flag in the same snapshot re-latches the
        # passenger before any state step runs, so the exception
        # check preempts completion: ALIGHTING goes straight to
        # EXCEPTION even though the latch had been clear.
        self.assertEqual(result, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(
            history_of(session),
            ALIGHTING_HISTORY
            + [
                (
                    SessionState.ALIGHTING,
                    SessionState.EXCEPTION,
                    "ignition_off_locked_passenger_present",
                    50.0,
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
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_cleared_door_closed_unbelted_ignition_off_locked_still_completes(self):
        session = alighting_cleared_session()

        result = session.apply_snapshot(
            snapshot(
                50.0, door_open=False, belt=False, ignition=False, locked=True
            )
        )

        # Same shape as the exception case but with no passenger
        # latched: a lock on its own never blocks completion.
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(
            history_of(session),
            ALIGHTING_HISTORY
            + [
                (
                    SessionState.ALIGHTING,
                    SessionState.COMPLETED,
                    "alighting_confirmed",
                    50.0,
                )
            ],
        )

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 50.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_cleared_door_open_unbelted_ignition_on_locked_holds_then_completes(self):
        session = alighting_cleared_session()

        result = session.apply_snapshot(
            snapshot(
                50.0, door_open=True, belt=False, ignition=True, locked=True
            )
        )

        # The latch is clear, but the open door blocks completion:
        # ALIGHTING holds even with the ignition on and the vehicle
        # locked.
        self.assertEqual(result, SessionState.ALIGHTING)
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), ALIGHTING_HISTORY)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "alighting")

        result = session.apply_snapshot(snapshot(60.0))
        self.assertEqual(result, SessionState.COMPLETED)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 60.0)

    def test_latched_door_closed_unbelted_ignition_on_locked_holds_alighting(self):
        session = alighting_latched_session()
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), ALIGHTING_HISTORY)

        result = session.apply_snapshot(
            snapshot(
                50.0, door_open=False, belt=False, ignition=True, locked=True
            )
        )

        # Ignition-on blocks the exception, and the belt release
        # cannot clear the latch while the door is closed: ALIGHTING
        # holds with the passenger still latched.
        self.assertEqual(result, SessionState.ALIGHTING)
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), ALIGHTING_HISTORY)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "alighting")

        result = session.apply_snapshot(
            snapshot(
                50.0, door_open=False, belt=False, ignition=True, locked=True
            )
        )
        self.assertEqual(result, SessionState.ALIGHTING)
        self.assertEqual(history_of(session), ALIGHTING_HISTORY)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 5)

    def test_latched_door_open_belted_ignition_off_locked_holds_then_completes(self):
        session = alighting_latched_session()

        result = session.apply_snapshot(
            snapshot(
                50.0, door_open=True, belt=True, ignition=False, locked=True
            )
        )

        # The open door blocks the exception even though the vehicle
        # is locked with the ignition off: ALIGHTING holds.
        self.assertEqual(result, SessionState.ALIGHTING)
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(history_of(session), ALIGHTING_HISTORY)

        result = session.apply_snapshot(
            snapshot(60.0, door_open=True, belt=False)
        )
        self.assertEqual(result, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 5)

        result = session.apply_snapshot(snapshot(70.0))
        self.assertEqual(result, SessionState.COMPLETED)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 70.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")


if __name__ == "__main__":
    unittest.main()

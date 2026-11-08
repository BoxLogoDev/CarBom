"""QA scenarios for simultaneous inputs arriving while ONBOARD.

Existing simultaneous-input QA covers IDLE and BOARDING: several
signals in one snapshot before departure preparation finishes.
Existing ONBOARD QA covers single signals one at a time: the rear
door opening, a lock, or HVAC changes on their own. This file covers
the rear door, rear belt, ignition, and lock all named in one
snapshot taken from ONBOARD. In one snapshot the precedence rules
decide the outcome: the exception check runs first (ignition off,
locked, door closed, passenger latched), then ignition, then the
pre-departure alighting path. The passenger latch only clears when
the belt is released while the door is open, so the same unbuckled
flag means different things depending on the door flag in the same
snapshot.
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


def onboard_session():
    """ONBOARD reached by opening the rear door, then belting shut."""
    session = CareSession()
    session.apply_snapshot(snapshot(0.0, door_open=True))
    session.apply_snapshot(snapshot(10.0, belt=True))
    return session


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
        10.0,
    ),
]


class OnboardSimultaneousInputQATest(unittest.TestCase):
    def test_door_open_belted_locked_ignition_off_holds_onboard(self):
        session = onboard_session()
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertEqual(history_of(session), ONBOARD_HISTORY)

        result = session.apply_snapshot(
            snapshot(20.0, door_open=True, belt=True, locked=True)
        )

        # The open door blocks the exception even though the vehicle
        # is locked, and the ignition is off so nothing departs.
        self.assertEqual(result, SessionState.ONBOARD)
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertEqual(history_of(session), ONBOARD_HISTORY)
        self.assertTrue(session.passenger_present)
        self.assertTrue(session.current_snapshot.rear_door_open)
        self.assertTrue(session.current_snapshot.locked)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "passenger_onboard")

        report = report_for_session(session)
        self.assertEqual(report.transition_count, 2)
        self.assertEqual(report.duration_seconds, 10.0)
        self.assertEqual(report.exception_count, 0)

    def test_door_open_belted_ignition_on_goes_driving(self):
        session = onboard_session()

        result = session.apply_snapshot(
            snapshot(20.0, door_open=True, belt=True, ignition=True)
        )

        # Ignition wins over the open door in ONBOARD.
        self.assertEqual(result, SessionState.DRIVING)
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(
            history_of(session),
            ONBOARD_HISTORY
            + [
                (
                    SessionState.ONBOARD,
                    SessionState.DRIVING,
                    "ignition_on",
                    20.0,
                )
            ],
        )
        self.assertTrue(session.passenger_present)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")

        report = report_for_session(session)
        self.assertEqual(report.transition_count, 3)
        self.assertEqual(report.duration_seconds, 20.0)
        self.assertEqual(report.exception_count, 0)

    def test_door_open_unbelted_ignition_on_goes_driving_without_passenger(
        self,
    ):
        session = onboard_session()

        result = session.apply_snapshot(
            snapshot(20.0, door_open=True, belt=False, ignition=True)
        )

        # One snapshot: the belt release with the door open clears
        # the latch, yet ignition still takes the session to DRIVING
        # instead of the pre-departure alighting path.
        self.assertEqual(result, SessionState.DRIVING)
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(
            history_of(session),
            ONBOARD_HISTORY
            + [
                (
                    SessionState.ONBOARD,
                    SessionState.DRIVING,
                    "ignition_on",
                    20.0,
                )
            ],
        )
        self.assertFalse(session.passenger_present)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.NONE)
        self.assertEqual(guidance.reason, "no_passenger")
        self.assertEqual(guidance.text, "")

        report = report_for_session(session)
        self.assertFalse(report.passenger_present)
        self.assertEqual(report.transition_count, 3)
        self.assertEqual(report.exception_count, 0)

    def test_door_closed_unbelted_locked_ignition_off_enters_exception(
        self,
    ):
        session = onboard_session()

        result = session.apply_snapshot(
            snapshot(
                20.0,
                door_open=False,
                belt=False,
                ignition=False,
                locked=True,
                cabin_temp_c=35.5,
            )
        )

        # The belt flag is off in the same snapshot, but the door is
        # closed so the latch never cleared: this is still a locked
        # passenger exception, now at a dangerous cabin temperature.
        self.assertEqual(result, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(
            history_of(session),
            ONBOARD_HISTORY
            + [
                (
                    SessionState.ONBOARD,
                    SessionState.EXCEPTION,
                    "ignition_off_locked_passenger_present",
                    20.0,
                )
            ],
        )
        self.assertTrue(session.passenger_present)

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
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_door_closed_unbelted_ignition_on_goes_driving_with_latch(
        self,
    ):
        session = onboard_session()

        result = session.apply_snapshot(
            snapshot(20.0, door_open=False, belt=False, ignition=True)
        )

        # Same unbuckled flag as the exception case, but the door is
        # closed and the ignition is on: the latch holds and the
        # session departs with the passenger still counted present.
        self.assertEqual(result, SessionState.DRIVING)
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(
            history_of(session),
            ONBOARD_HISTORY
            + [
                (
                    SessionState.ONBOARD,
                    SessionState.DRIVING,
                    "ignition_on",
                    20.0,
                )
            ],
        )
        self.assertTrue(session.passenger_present)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")

        report = report_for_session(session)
        self.assertEqual(report.transition_count, 3)
        self.assertEqual(report.exception_count, 0)
        self.assertTrue(report.passenger_present)

    def test_locked_ignition_on_departure_repeats_and_completes(self):
        session = onboard_session()

        result = session.apply_snapshot(
            snapshot(20.0, belt=True, ignition=True, locked=True)
        )

        # Locked and ignition-on in one snapshot: ignition is checked
        # before the exception can apply, so this departs normally.
        self.assertEqual(result, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)
        self.assertEqual(
            session.history[-1].reason, "ignition_on"
        )

        result = session.apply_snapshot(
            snapshot(20.0, belt=True, ignition=True, locked=True)
        )
        self.assertEqual(result, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)

        session.apply_snapshot(snapshot(30.0, belt=True))
        self.assertEqual(session.state, SessionState.ARRIVED)
        session.apply_snapshot(snapshot(40.0, door_open=True))
        self.assertEqual(session.state, SessionState.ALIGHTING)
        result = session.apply_snapshot(snapshot(50.0))
        self.assertEqual(result, SessionState.COMPLETED)

        self.assertEqual(
            [t.reason for t in session.history],
            [
                "rear_door_opened",
                "passenger_onboard",
                "ignition_on",
                "ignition_off",
                "alighting_started",
                "alighting_confirmed",
            ],
        )
        self.assertEqual(
            history_of(session),
            ONBOARD_HISTORY
            + [
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
                (
                    SessionState.ALIGHTING,
                    SessionState.COMPLETED,
                    "alighting_confirmed",
                    50.0,
                ),
            ],
        )

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 50.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")


if __name__ == "__main__":
    unittest.main()

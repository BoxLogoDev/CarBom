"""QA scenarios for simultaneous inputs arriving while COMPLETED.

The simultaneous input series covers IDLE, BOARDING, ONBOARD,
DRIVING, ARRIVED, ALIGHTING, and EXCEPTION. Each file in the series
names several signals in one snapshot and pins which one decides
the outcome. This file closes the series at COMPLETED. COMPLETED
is the terminal state. No next state ever leaves it, so the state
and the transition history never change again, whatever the input.

One premise shapes every expectation here. Each incoming snapshot
still updates the passenger latch and becomes the current snapshot
before any state step runs. Post-completion input can therefore
turn the latch back on and off and can reach report fields read
from the current snapshot, while the completed verdict stays
fixed. The COMPLETED terminal QA already characterizes that latch
effect. This file pins it as the expected behavior. It does not
treat it as a defect.

The angle here repeats no earlier file. The terminal QA sends
single triggers, events, bulk applies, and a full replay after
completion. The HVAC QA sends HVAC input alone after completion.
The earlier simultaneous input files all start before completion,
where several signals still compete for the next state. This file
names the rear door, rear belt, ignition, lock, and cabin
temperature together in one snapshot taken from COMPLETED. It
uses exception, alighting, and driving shapes, repeats them, and
mixes them in one sequence. Every test starts from the same
COMPLETED session. The dropoff_normal scenario ends it at 300.0
with no passenger latched.
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


def completed_session():
    """COMPLETED reached by replaying dropoff_normal."""
    session = CareSession()
    replay_scenario(session, "dropoff_normal")
    return session


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


class CompletedSimultaneousInputQATest(unittest.TestCase):
    def test_exception_shaped_simultaneous_keeps_completed_but_relatches(self):
        session = completed_session()
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.started_at, 0.0)
        self.assertEqual(report.ended_at, 300.0)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

        result = session.apply_snapshot(
            snapshot(
                500.0,
                door_open=False,
                belt=True,
                ignition=False,
                locked=True,
                cabin_temp_c=35.5,
            )
        )

        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        # Characterized current snapshot effect. The latch follows
        # the incoming belt signal even in the terminal state, so
        # the exception shape relatches the passenger without
        # re-entering EXCEPTION.
        self.assertTrue(session.passenger_present)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        self.assertEqual(guidance.text, "하차 확인이 완료되었습니다.")

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_alighting_shaped_simultaneous_keeps_completed(self):
        session = completed_session()
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)

        result = session.apply_snapshot(
            snapshot(
                500.0,
                door_open=True,
                belt=False,
                ignition=False,
                locked=False,
            )
        )

        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertFalse(session.passenger_present)
        self.assertEqual(
            session.current_snapshot.rear_door, DoorState.OPEN
        )

        report = report_for_session(session)
        self.assertFalse(report.passenger_present)
        self.assertIsNone(report.max_cabin_temp_c)
        self.assertEqual(report.transition_count, 6)

        result = session.apply_snapshot(snapshot(560.0))
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)

    def test_driving_shaped_simultaneous_does_not_revive_driving(self):
        session = completed_session()
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)

        result = session.apply_snapshot(
            snapshot(
                500.0,
                door_open=False,
                belt=True,
                ignition=True,
                locked=True,
            )
        )

        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertTrue(session.passenger_present)
        self.assertEqual(
            session.current_snapshot.ignition, IgnitionState.ON
        )
        self.assertEqual(
            session.current_snapshot.lock, LockState.LOCKED
        )

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")

        report = report_for_session(session)
        self.assertIsNone(report.max_cabin_temp_c)
        self.assertEqual(report.exception_count, 0)

    def test_latch_toggles_within_completed_while_verdict_fixed(self):
        session = completed_session()
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)

        result = session.apply_snapshot(snapshot(500.0, belt=True))
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertTrue(session.passenger_present)

        result = session.apply_snapshot(
            snapshot(560.0, door_open=True, belt=False)
        )
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertFalse(session.passenger_present)

        result = session.apply_snapshot(
            snapshot(
                620.0, belt=True, locked=True, cabin_temp_c=35.5
            )
        )
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertTrue(session.passenger_present)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_exception_shaped_simultaneous_repeated_is_idempotent(self):
        session = completed_session()
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)

        for timestamp in (500.0, 560.0, 620.0):
            result = session.apply_snapshot(
                snapshot(
                    timestamp,
                    belt=True,
                    locked=True,
                    cabin_temp_c=35.5,
                )
            )
            self.assertEqual(result, SessionState.COMPLETED)
            self.assertEqual(session.state, SessionState.COMPLETED)
            self.assertEqual(
                history_of(session), COMPLETED_HISTORY
            )

        self.assertTrue(session.passenger_present)
        self.assertEqual(session.current_snapshot.timestamp, 620.0)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)

    def test_mixed_simultaneous_sequence_keeps_terminal_verdict(self):
        session = completed_session()
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)

        result = session.apply_snapshot(
            snapshot(400.0, door_open=True, ignition=True)
        )
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertFalse(session.passenger_present)

        result = session.apply_snapshot(
            snapshot(
                460.0, belt=True, ignition=True, locked=True
            )
        )
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertTrue(session.passenger_present)

        result = session.apply_snapshot(
            snapshot(520.0, door_open=True, belt=False)
        )
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertFalse(session.passenger_present)

        result = session.apply_snapshot(snapshot(580.0))
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(history_of(session), COMPLETED_HISTORY)
        self.assertFalse(session.passenger_present)

        current = session.current_snapshot
        self.assertEqual(current.rear_door, DoorState.CLOSED)
        self.assertFalse(current.rear_seat_belt_buckled)
        self.assertEqual(current.ignition, IgnitionState.OFF)
        self.assertEqual(current.lock, LockState.UNLOCKED)
        self.assertEqual(current.timestamp, 580.0)

        for context in (
            DestinationContext.GENERAL,
            DestinationContext.DROPOFF,
            DestinationContext.PICKUP,
        ):
            guidance = guidance_for_session(session, context=context)
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "completed")
            self.assertEqual(
                guidance.text, "하차 확인이 완료되었습니다."
            )

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")


if __name__ == "__main__":
    unittest.main()

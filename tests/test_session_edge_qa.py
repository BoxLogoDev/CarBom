"""QA scenarios for care session state boundaries and recovery paths."""

import unittest

from engine import (
    CareSession,
    DoorState,
    IgnitionState,
    LockState,
    SessionState,
    SignalSnapshot,
)


def snapshot(**overrides):
    values = {
        "rear_door": DoorState.CLOSED,
        "rear_seat_belt_buckled": False,
        "ignition": IgnitionState.OFF,
        "hvac_on": False,
        "cabin_temp_c": None,
        "lock": LockState.UNLOCKED,
        "timestamp": None,
    }
    values.update(overrides)
    return SignalSnapshot(**values)


def board_drive_and_arrive(session):
    session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
    session.apply_snapshot(snapshot(rear_seat_belt_buckled=True))
    session.apply_snapshot(
        snapshot(rear_seat_belt_buckled=True, ignition=IgnitionState.ON)
    )
    session.apply_snapshot(snapshot(rear_seat_belt_buckled=True))


def enter_exception(session):
    board_drive_and_arrive(session)
    session.apply_snapshot(
        snapshot(rear_seat_belt_buckled=True, lock=LockState.LOCKED)
    )


def complete_session(session):
    board_drive_and_arrive(session)
    session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
    session.apply_snapshot(snapshot())


class SessionEdgeQaTest(unittest.TestCase):
    def test_boarding_without_passenger_returns_to_idle(self):
        session = CareSession()

        session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertFalse(session.passenger_present)

        session.apply_snapshot(snapshot())
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertFalse(session.passenger_present)

        last = session.history[-1]
        self.assertEqual(last.from_state, SessionState.BOARDING)
        self.assertEqual(last.to_state, SessionState.IDLE)
        self.assertEqual(last.reason, "boarding_without_passenger")

    def test_exception_recovers_via_unlock_and_ignition_to_onboard(self):
        session = CareSession()
        enter_exception(session)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                lock=LockState.UNLOCKED,
            )
        )

        self.assertTrue(session.passenger_present)
        recovery = [
            transition
            for transition in session.history
            if transition.from_state is SessionState.EXCEPTION
            and transition.to_state is SessionState.ONBOARD
        ]
        self.assertEqual(len(recovery), 1)
        self.assertEqual(
            recovery[0].reason,
            "unlocked_and_ignition_on_after_exception",
        )
        # One snapshot advances step by step. The same ignition-on signal
        # also moves the recovered ONBOARD session on to DRIVING.
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(session.history[-2].to_state, SessionState.ONBOARD)
        self.assertEqual(session.history[-1].from_state, SessionState.ONBOARD)
        self.assertEqual(session.history[-1].to_state, SessionState.DRIVING)

    def test_completed_is_terminal_under_later_snapshots(self):
        session = CareSession()
        complete_session(session)
        self.assertEqual(session.state, SessionState.COMPLETED)
        history_len = len(session.history)

        session.apply_snapshot(snapshot(lock=LockState.LOCKED))
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), history_len)

        session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
        session.apply_snapshot(
            snapshot(ignition=IgnitionState.ON, lock=LockState.LOCKED)
        )
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), history_len)

    def test_reset_allows_session_reuse(self):
        session = CareSession()
        complete_session(session)
        self.assertEqual(session.state, SessionState.COMPLETED)

        session.reset()
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])
        self.assertFalse(session.passenger_present)

        session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)
        self.assertEqual(session.history[-1].from_state, SessionState.IDLE)
        self.assertEqual(session.history[-1].to_state, SessionState.BOARDING)


if __name__ == "__main__":
    unittest.main()

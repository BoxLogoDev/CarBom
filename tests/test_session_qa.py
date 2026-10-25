"""QA scenario for forgotten alighting with rising cabin temperature."""

import unittest

from engine import (
    CareSession,
    DoorState,
    IgnitionState,
    LockState,
    SessionState,
    SignalEvent,
    SignalEventType,
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


def raise_cabin_temp(session):
    for cabin_temp_c in (28.0, 32.0, 35.5):
        session.apply_event(
            SignalEvent(
                SignalEventType.CABIN_TEMP_CHANGED,
                cabin_temp_c=cabin_temp_c,
            )
        )


class ForgottenAlightingCabinTempRisingTest(unittest.TestCase):
    def test_forgotten_alighting_enters_exception_on_lock(self):
        session = CareSession()

        session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
        self.assertEqual(session.state, SessionState.BOARDING)

        session.apply_snapshot(snapshot(rear_seat_belt_buckled=True))
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertTrue(session.passenger_present)

        session.apply_snapshot(
            snapshot(rear_seat_belt_buckled=True, ignition=IgnitionState.ON)
        )
        self.assertEqual(session.state, SessionState.DRIVING)

        session.apply_snapshot(snapshot(rear_seat_belt_buckled=True))
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertTrue(session.passenger_present)

        session.apply_snapshot(
            snapshot(rear_seat_belt_buckled=True, lock=LockState.LOCKED)
        )
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(session.current_snapshot.ignition, IgnitionState.OFF)
        self.assertEqual(session.current_snapshot.lock, LockState.LOCKED)
        self.assertTrue(session.current_snapshot.rear_seat_belt_buckled)

    def test_rising_cabin_temp_keeps_exception_and_updates_snapshot(self):
        session = CareSession()
        enter_exception(session)
        self.assertEqual(session.state, SessionState.EXCEPTION)

        session.apply_event(
            SignalEvent(
                SignalEventType.CABIN_TEMP_CHANGED, cabin_temp_c=28.0
            )
        )
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertNotEqual(session.state, SessionState.COMPLETED)
        self.assertTrue(session.passenger_present)
        self.assertFalse(session.current_snapshot.hvac_on)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 28.0)

        session.apply_event(
            SignalEvent(
                SignalEventType.CABIN_TEMP_CHANGED, cabin_temp_c=32.0
            )
        )
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertNotEqual(session.state, SessionState.COMPLETED)
        self.assertTrue(session.passenger_present)
        self.assertFalse(session.current_snapshot.hvac_on)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 32.0)

        session.apply_event(
            SignalEvent(
                SignalEventType.CABIN_TEMP_CHANGED, cabin_temp_c=35.5
            )
        )
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertNotEqual(session.state, SessionState.COMPLETED)
        self.assertTrue(session.passenger_present)
        self.assertFalse(session.current_snapshot.hvac_on)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)

        completed = [
            transition
            for transition in session.history
            if transition.to_state is SessionState.COMPLETED
        ]
        self.assertEqual(completed, [])

    def test_recovery_after_rising_temp_exception_completes(self):
        session = CareSession()
        enter_exception(session)
        raise_cabin_temp(session)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)

        session.apply_snapshot(
            snapshot(
                rear_door=DoorState.OPEN,
                hvac_on=False,
                cabin_temp_c=35.5,
            )
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)

        session.apply_snapshot(
            snapshot(hvac_on=False, cabin_temp_c=35.5)
        )
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)


if __name__ == "__main__":
    unittest.main()

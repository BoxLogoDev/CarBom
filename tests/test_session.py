"""신호 모델과 케어 세션 상태머신의 단위 테스트."""

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


def board_and_drive(session):
    session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
    session.apply_snapshot(snapshot(rear_seat_belt_buckled=True))
    session.apply_snapshot(
        snapshot(rear_seat_belt_buckled=True, ignition=IgnitionState.ON)
    )


def arrive(session):
    session.apply_snapshot(snapshot(rear_seat_belt_buckled=True))


class SignalSnapshotTest(unittest.TestCase):
    def test_defaults(self):
        snap = SignalSnapshot()

        self.assertEqual(snap.rear_door, DoorState.CLOSED)
        self.assertFalse(snap.rear_seat_belt_buckled)
        self.assertEqual(snap.ignition, IgnitionState.OFF)
        self.assertFalse(snap.hvac_on)
        self.assertIsNone(snap.cabin_temp_c)
        self.assertEqual(snap.lock, LockState.UNLOCKED)
        self.assertFalse(snap.rear_door_open)
        self.assertFalse(snap.ignition_on)
        self.assertFalse(snap.locked)

    def test_snapshot_values_and_properties(self):
        snap = SignalSnapshot(
            rear_door=DoorState.OPEN,
            rear_seat_belt_buckled=True,
            ignition=IgnitionState.ON,
            hvac_on=True,
            cabin_temp_c=31.5,
            lock=LockState.LOCKED,
            timestamp=123.0,
        )

        self.assertTrue(snap.rear_door_open)
        self.assertTrue(snap.rear_seat_belt_buckled)
        self.assertTrue(snap.ignition_on)
        self.assertTrue(snap.locked)
        self.assertEqual(snap.cabin_temp_c, 31.5)
        self.assertEqual(snap.timestamp, 123.0)


class CareSessionTest(unittest.TestCase):
    def test_normal_school_run_flow(self):
        session = CareSession()
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertFalse(session.passenger_present)

        session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
        self.assertEqual(session.state, SessionState.BOARDING)

        session.apply_snapshot(snapshot(rear_seat_belt_buckled=True))
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertTrue(session.passenger_present)

        session.apply_snapshot(
            snapshot(rear_seat_belt_buckled=True, ignition=IgnitionState.ON)
        )
        self.assertEqual(session.state, SessionState.DRIVING)

        arrive(session)
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertTrue(session.passenger_present)

        session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)

        session.apply_snapshot(snapshot())
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)

    def test_forgotten_alighting_becomes_exception_on_lock(self):
        session = CareSession()
        board_and_drive(session)
        arrive(session)
        self.assertEqual(session.state, SessionState.ARRIVED)

        session.apply_snapshot(
            snapshot(rear_seat_belt_buckled=True, lock=LockState.LOCKED)
        )

        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)

    def test_lock_while_driving_is_not_exception(self):
        session = CareSession()
        board_and_drive(session)

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                lock=LockState.LOCKED,
            )
        )

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)

    def test_lock_after_confirmed_alighting_stays_completed(self):
        session = CareSession()
        board_and_drive(session)
        arrive(session)
        session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
        session.apply_snapshot(snapshot(lock=LockState.LOCKED))

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)

    def test_exception_recovers_when_passenger_leaves(self):
        session = CareSession()
        board_and_drive(session)
        arrive(session)
        session.apply_snapshot(
            snapshot(rear_seat_belt_buckled=True, lock=LockState.LOCKED)
        )
        self.assertEqual(session.state, SessionState.EXCEPTION)

        session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)

        session.apply_snapshot(snapshot())
        self.assertEqual(session.state, SessionState.COMPLETED)

    def test_history_records_each_transition(self):
        session = CareSession()
        board_and_drive(session)
        arrive(session)
        session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
        session.apply_snapshot(snapshot())

        pairs = [(t.from_state, t.to_state) for t in session.history]
        self.assertEqual(
            pairs,
            [
                (SessionState.IDLE, SessionState.BOARDING),
                (SessionState.BOARDING, SessionState.ONBOARD),
                (SessionState.ONBOARD, SessionState.DRIVING),
                (SessionState.DRIVING, SessionState.ARRIVED),
                (SessionState.ARRIVED, SessionState.ALIGHTING),
                (SessionState.ALIGHTING, SessionState.COMPLETED),
            ],
        )

    def test_events_drive_the_same_flow(self):
        session = CareSession()

        session.apply_event(SignalEvent(SignalEventType.REAR_DOOR_OPENED))
        self.assertEqual(session.state, SessionState.BOARDING)

        session.apply_event(SignalEvent(SignalEventType.REAR_BELT_BUCKLED))
        session.apply_event(SignalEvent(SignalEventType.REAR_DOOR_CLOSED))
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertTrue(session.passenger_present)

        session.apply_event(SignalEvent(SignalEventType.IGNITION_ON))
        self.assertEqual(session.state, SessionState.DRIVING)

        session.apply_event(SignalEvent(SignalEventType.IGNITION_OFF))
        self.assertEqual(session.state, SessionState.ARRIVED)

        session.apply_event(SignalEvent(SignalEventType.REAR_BELT_UNBUCKLED))
        session.apply_event(SignalEvent(SignalEventType.REAR_DOOR_OPENED))
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)

        session.apply_event(SignalEvent(SignalEventType.REAR_DOOR_CLOSED))
        self.assertEqual(session.state, SessionState.COMPLETED)

    def test_update_accepts_snapshot_and_event(self):
        session = CareSession()

        state = session.update(snapshot(rear_door=DoorState.OPEN))
        self.assertEqual(state, SessionState.BOARDING)

        state = session.update(
            SignalEvent(
                SignalEventType.CABIN_TEMP_CHANGED, cabin_temp_c=28.0
            )
        )
        self.assertEqual(state, SessionState.BOARDING)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 28.0)


if __name__ == "__main__":
    unittest.main()

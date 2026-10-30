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


def normal_flow_events():
    types = [
        SignalEventType.REAR_DOOR_OPENED,
        SignalEventType.REAR_BELT_BUCKLED,
        SignalEventType.REAR_DOOR_CLOSED,
        SignalEventType.IGNITION_ON,
        SignalEventType.IGNITION_OFF,
        SignalEventType.REAR_DOOR_OPENED,
        SignalEventType.REAR_BELT_UNBUCKLED,
        SignalEventType.REAR_DOOR_CLOSED,
    ]
    return [
        SignalEvent(event_type, timestamp=float(index * 10))
        for index, event_type in enumerate(types)
    ]


def history_sequence(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


class ApplyEventsAndUpdatesTest(unittest.TestCase):
    def test_apply_events_empty_input_keeps_session(self):
        session = CareSession()

        result = session.apply_events([])

        self.assertEqual(result, SessionState.IDLE)
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])

    def test_apply_events_drives_normal_flow_to_completed(self):
        session = CareSession()

        result = session.apply_events(normal_flow_events())

        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(result, session.state)
        self.assertEqual(len(session.history), 6)
        self.assertFalse(session.passenger_present)

    def test_apply_events_lock_enters_exception(self):
        session = CareSession()
        prefix = [
            SignalEvent(SignalEventType.REAR_DOOR_OPENED, timestamp=0.0),
            SignalEvent(SignalEventType.REAR_BELT_BUCKLED, timestamp=10.0),
            SignalEvent(SignalEventType.REAR_DOOR_CLOSED, timestamp=20.0),
            SignalEvent(SignalEventType.IGNITION_ON, timestamp=30.0),
            SignalEvent(SignalEventType.IGNITION_OFF, timestamp=40.0),
        ]
        session.apply_events(prefix)
        self.assertEqual(session.state, SessionState.ARRIVED)

        result = session.apply_events(
            [SignalEvent(SignalEventType.LOCKED, timestamp=50.0)]
        )

        self.assertEqual(result, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertTrue(session.current_snapshot.locked)

    def test_apply_updates_empty_input_keeps_session(self):
        session = CareSession()

        result = session.apply_updates([])

        self.assertEqual(result, SessionState.IDLE)
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])

    def test_apply_updates_matches_individual_calls(self):
        items = [
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0),
            SignalEvent(SignalEventType.REAR_BELT_BUCKLED, timestamp=10.0),
            SignalEvent(SignalEventType.REAR_DOOR_CLOSED, timestamp=20.0),
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                timestamp=30.0,
            ),
            SignalEvent(SignalEventType.IGNITION_OFF, timestamp=40.0),
            snapshot(rear_door=DoorState.OPEN, timestamp=50.0),
            SignalEvent(SignalEventType.REAR_DOOR_CLOSED, timestamp=60.0),
        ]
        bulk = CareSession()
        individual = CareSession()

        bulk_result = bulk.apply_updates(items)
        individual_result = None
        for item in items:
            if isinstance(item, SignalEvent):
                individual_result = individual.apply_event(item)
            else:
                individual_result = individual.apply_snapshot(item)

        self.assertEqual(bulk_result, SessionState.COMPLETED)
        self.assertEqual(bulk_result, individual_result)
        self.assertEqual(bulk.state, individual.state)
        self.assertEqual(bulk.passenger_present, individual.passenger_present)
        self.assertEqual(
            history_sequence(bulk), history_sequence(individual)
        )

    def test_apply_bulk_accepts_generators(self):
        listed = CareSession()
        generated = CareSession()

        listed_result = listed.apply_events(normal_flow_events())
        generated_result = generated.apply_events(
            event for event in normal_flow_events()
        )

        self.assertEqual(generated_result, listed_result)
        self.assertEqual(generated.state, SessionState.COMPLETED)
        self.assertEqual(
            history_sequence(generated), history_sequence(listed)
        )

        mixed = [
            snapshot(rear_door=DoorState.OPEN, timestamp=0.0),
            SignalEvent(SignalEventType.REAR_BELT_BUCKLED, timestamp=10.0),
            SignalEvent(SignalEventType.REAR_DOOR_CLOSED, timestamp=20.0),
        ]
        listed_mixed = CareSession()
        generated_mixed = CareSession()

        listed_mixed_result = listed_mixed.apply_updates(mixed)
        generated_mixed_result = generated_mixed.apply_updates(
            item for item in mixed
        )

        self.assertEqual(generated_mixed_result, listed_mixed_result)
        self.assertEqual(generated_mixed.state, SessionState.ONBOARD)
        self.assertEqual(
            history_sequence(generated_mixed),
            history_sequence(listed_mixed),
        )


if __name__ == "__main__":
    unittest.main()

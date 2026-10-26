"""신호 모델 경계 조건 QA — 신호 스냅샷·이벤트의 불변성과 값 동등성, 열거형 문자열 값의 안정성, 같은 스냅샷 반복 적용 시 세션 멱등성을 검증한다."""

import dataclasses
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


class SignalImmutabilityTest(unittest.TestCase):
    def test_snapshot_is_frozen(self):
        snap = SignalSnapshot()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            snap.rear_seat_belt_buckled = True
        with self.assertRaises(dataclasses.FrozenInstanceError):
            snap.cabin_temp_c = 30.0

    def test_event_is_frozen_and_defaults(self):
        event = SignalEvent(SignalEventType.REAR_DOOR_OPENED)
        self.assertIsNone(event.timestamp)
        self.assertIsNone(event.cabin_temp_c)
        self.assertIsNone(event.snapshot)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            event.timestamp = 1.0


class SignalEqualityTest(unittest.TestCase):
    def test_snapshot_equality_and_hash_by_value(self):
        a = snapshot(rear_seat_belt_buckled=True, cabin_temp_c=24.5, timestamp=10.0)
        b = snapshot(rear_seat_belt_buckled=True, cabin_temp_c=24.5, timestamp=10.0)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)

    def test_snapshot_inequality_when_one_field_differs(self):
        base = snapshot()
        self.assertNotEqual(base, snapshot(rear_door=DoorState.OPEN))
        self.assertNotEqual(base, snapshot(cabin_temp_c=20.0))
        self.assertNotEqual(base, snapshot(timestamp=1.0))


class SignalDerivedPropertiesTest(unittest.TestCase):
    def test_derived_properties_are_independent(self):
        door_only = snapshot(rear_door=DoorState.OPEN)
        self.assertTrue(door_only.rear_door_open)
        self.assertFalse(door_only.ignition_on)
        self.assertFalse(door_only.locked)

        ignition_only = snapshot(ignition=IgnitionState.ON)
        self.assertFalse(ignition_only.rear_door_open)
        self.assertTrue(ignition_only.ignition_on)
        self.assertFalse(ignition_only.locked)

        lock_only = snapshot(lock=LockState.LOCKED)
        self.assertFalse(lock_only.rear_door_open)
        self.assertFalse(lock_only.ignition_on)
        self.assertTrue(lock_only.locked)


class EnumValuesTest(unittest.TestCase):
    def test_enum_values_are_stable_strings(self):
        self.assertEqual(DoorState.OPEN.value, "open")
        self.assertEqual(DoorState.CLOSED.value, "closed")
        self.assertEqual(IgnitionState.ON.value, "on")
        self.assertEqual(IgnitionState.OFF.value, "off")
        self.assertEqual(LockState.LOCKED.value, "locked")
        self.assertEqual(LockState.UNLOCKED.value, "unlocked")
        self.assertEqual(
            {member.value for member in SignalEventType},
            {
                "rear_door_opened",
                "rear_door_closed",
                "rear_belt_buckled",
                "rear_belt_unbuckled",
                "ignition_on",
                "ignition_off",
                "locked",
                "unlocked",
                "hvac_on",
                "hvac_off",
                "cabin_temp_changed",
            },
        )
        self.assertEqual(len(SignalEventType), 11)


class SessionIdempotencyTest(unittest.TestCase):
    def test_repeated_idle_snapshot_is_idempotent(self):
        session = CareSession()
        for _ in range(3):
            state = session.apply_snapshot(snapshot())
            self.assertEqual(state, SessionState.IDLE)
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(len(session.history), 0)
        self.assertFalse(session.passenger_present)

    def test_repeated_driving_snapshot_is_idempotent(self):
        session = CareSession()
        session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
        session.apply_snapshot(snapshot(rear_seat_belt_buckled=True))
        driving = snapshot(
            rear_seat_belt_buckled=True, ignition=IgnitionState.ON
        )
        session.apply_snapshot(driving)
        self.assertEqual(session.state, SessionState.DRIVING)
        history_len = len(session.history)

        for _ in range(2):
            state = session.apply_snapshot(driving)
            self.assertEqual(state, SessionState.DRIVING)
        self.assertEqual(len(session.history), history_len)
        self.assertTrue(session.passenger_present)


if __name__ == "__main__":
    unittest.main()

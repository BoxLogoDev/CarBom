"""Vehicle SDK 어댑터 경계 조건 QA 테스트.

0.0 같은 falsy 하지만 유효한 값과 truthy·falsy 입력의 변환을 검증한다.
기존 test_vehicle_sdk.py 가 다루지 않은 경계만 다룬다.
"""

import unittest

from engine.adapters import (
    apply_raw,
    raw_from_snapshot,
    snapshot_from_raw,
    snapshots_from_raws,
)
from engine.session import CareSession, SessionState
from engine.signals import DoorState, LockState, SignalSnapshot


class VehicleSdkBoundaryQaTest(unittest.TestCase):
    def test_all_false_booleans_give_default_snapshot(self):
        raw = {
            "rear_door_open": False,
            "rear_seat_belt_buckled": False,
            "ignition_on": False,
            "locked": False,
            "hvac_on": False,
        }
        self.assertEqual(snapshot_from_raw(raw), SignalSnapshot())

    def test_zero_cabin_temp_and_timestamp_are_preserved(self):
        snap = snapshot_from_raw({"cabin_temp_c": 0.0, "timestamp": 0.0})
        self.assertIsNotNone(snap.cabin_temp_c)
        self.assertEqual(snap.cabin_temp_c, 0.0)
        self.assertIsNotNone(snap.timestamp)
        self.assertEqual(snap.timestamp, 0.0)

    def test_negative_cabin_temp_is_preserved(self):
        snap = snapshot_from_raw({"cabin_temp_c": -5.0})
        self.assertEqual(snap.cabin_temp_c, -5.0)

    def test_truthy_and_falsy_inputs_convert_by_truthiness(self):
        snap = snapshot_from_raw(
            {"rear_door_open": 1, "locked": 0, "hvac_on": ""}
        )
        self.assertEqual(snap.rear_door, DoorState.OPEN)
        self.assertEqual(snap.lock, LockState.UNLOCKED)
        self.assertFalse(snap.hvac_on)

    def test_zero_values_round_trip_through_raw(self):
        raw = raw_from_snapshot(
            snapshot_from_raw({"cabin_temp_c": 0.0, "timestamp": 0.0})
        )
        self.assertIsNotNone(raw["cabin_temp_c"])
        self.assertEqual(raw["cabin_temp_c"], 0.0)
        self.assertIsNotNone(raw["timestamp"])
        self.assertEqual(raw["timestamp"], 0.0)

    def test_snapshots_from_raws_preserves_order_and_values(self):
        snaps = snapshots_from_raws(
            [
                {"cabin_temp_c": 0.0, "timestamp": 0.0},
                {"cabin_temp_c": -5.0, "timestamp": 60.0},
            ]
        )
        self.assertEqual(len(snaps), 2)
        self.assertEqual(snaps[0].cabin_temp_c, 0.0)
        self.assertEqual(snaps[0].timestamp, 0.0)
        self.assertEqual(snaps[1].cabin_temp_c, -5.0)
        self.assertEqual(snaps[1].timestamp, 60.0)

    def test_apply_raw_with_zero_timestamp_records_history_timestamp(self):
        session = CareSession()
        state = apply_raw(
            session, {"rear_door_open": True, "timestamp": 0.0}
        )
        self.assertEqual(state, SessionState.BOARDING)
        self.assertIsNotNone(session.history[0].timestamp)
        self.assertEqual(session.history[0].timestamp, 0.0)


if __name__ == "__main__":
    unittest.main()

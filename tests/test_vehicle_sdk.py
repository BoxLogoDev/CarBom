"""Vehicle SDK 어댑터 인터페이스·변환층 단위 테스트.

실 SDK는 아직 연동되지 않았으므로, 여기서 검증하는 것은
원시 신호 dict -> SignalSnapshot 변환과, 클라이언트 주입 여부에
따른 어댑터 동작(미연결 시 명시적 실패)뿐이다.
"""

import unittest

from engine.adapters import VehicleSdkAdapter, raw_from_snapshot, snapshot_from_raw
from engine.signals import DoorState, IgnitionState, LockState, SignalSnapshot


class FakeSdkClient:
    """read_raw()가 고정 dict를 돌려주는 가짜 SDK 클라이언트."""

    def __init__(self, raw):
        self._raw = raw
        self.calls = 0

    def read_raw(self):
        self.calls += 1
        return self._raw


FULL_RAW = {
    "rear_door_open": True,
    "rear_seat_belt_buckled": True,
    "ignition_on": True,
    "locked": True,
    "hvac_on": True,
    "cabin_temp_c": 33.5,
    "timestamp": 1234.5,
}


class SnapshotFromRawTest(unittest.TestCase):
    def test_empty_raw_gives_defaults(self):
        self.assertEqual(snapshot_from_raw({}), SignalSnapshot())

    def test_full_raw_converts_all_fields(self):
        snap = snapshot_from_raw(FULL_RAW)
        self.assertEqual(snap.rear_door, DoorState.OPEN)
        self.assertTrue(snap.rear_door_open)
        self.assertTrue(snap.rear_seat_belt_buckled)
        self.assertEqual(snap.ignition, IgnitionState.ON)
        self.assertTrue(snap.ignition_on)
        self.assertTrue(snap.hvac_on)
        self.assertEqual(snap.cabin_temp_c, 33.5)
        self.assertEqual(snap.lock, LockState.LOCKED)
        self.assertTrue(snap.locked)
        self.assertEqual(snap.timestamp, 1234.5)

    def test_partial_raw_keeps_other_defaults(self):
        snap = snapshot_from_raw({"locked": True, "cabin_temp_c": 28.0})
        self.assertEqual(snap.lock, LockState.LOCKED)
        self.assertEqual(snap.cabin_temp_c, 28.0)
        self.assertEqual(snap.rear_door, DoorState.CLOSED)
        self.assertFalse(snap.rear_seat_belt_buckled)
        self.assertEqual(snap.ignition, IgnitionState.OFF)
        self.assertFalse(snap.hvac_on)
        self.assertIsNone(snap.timestamp)

    def test_unknown_keys_are_ignored(self):
        snap = snapshot_from_raw({"mystery_signal": 42, "locked": True})
        self.assertEqual(snap.lock, LockState.LOCKED)

    def test_conversion_is_deterministic(self):
        self.assertEqual(snapshot_from_raw(FULL_RAW), snapshot_from_raw(FULL_RAW))


class RawFromSnapshotTest(unittest.TestCase):
    def test_default_snapshot_gives_all_false_and_none(self):
        self.assertEqual(
            raw_from_snapshot(SignalSnapshot()),
            {
                "rear_door_open": False,
                "rear_seat_belt_buckled": False,
                "ignition_on": False,
                "locked": False,
                "hvac_on": False,
                "cabin_temp_c": None,
                "timestamp": None,
            },
        )

    def test_full_raw_round_trips_through_snapshot(self):
        self.assertEqual(
            raw_from_snapshot(snapshot_from_raw(FULL_RAW)), FULL_RAW
        )

    def test_arbitrary_snapshot_round_trips_through_raw(self):
        snap = SignalSnapshot(
            rear_door=DoorState.OPEN,
            rear_seat_belt_buckled=True,
            ignition=IgnitionState.OFF,
            hvac_on=False,
            cabin_temp_c=None,
            lock=LockState.LOCKED,
            timestamp=50.0,
        )
        self.assertEqual(snapshot_from_raw(raw_from_snapshot(snap)), snap)

    def test_none_temp_and_timestamp_stay_none(self):
        raw = raw_from_snapshot(
            SignalSnapshot(cabin_temp_c=None, timestamp=None)
        )
        self.assertIsNone(raw["cabin_temp_c"])
        self.assertIsNone(raw["timestamp"])

    def test_keys_are_exactly_the_seven_raw_keys(self):
        self.assertEqual(
            set(raw_from_snapshot(snapshot_from_raw(FULL_RAW))),
            {
                "rear_door_open",
                "rear_seat_belt_buckled",
                "ignition_on",
                "locked",
                "hvac_on",
                "cabin_temp_c",
                "timestamp",
            },
        )


class VehicleSdkAdapterTest(unittest.TestCase):
    def test_adapter_without_client_is_not_connected_and_poll_fails(self):
        adapter = VehicleSdkAdapter()
        self.assertFalse(adapter.is_connected)
        with self.assertRaises(NotImplementedError):
            adapter.poll()

    def test_adapter_with_fake_client_polls_mapped_snapshot(self):
        client = FakeSdkClient(FULL_RAW)
        adapter = VehicleSdkAdapter(client)
        self.assertTrue(adapter.is_connected)
        snap = adapter.poll()
        self.assertEqual(snap, snapshot_from_raw(FULL_RAW))
        self.assertEqual(client.calls, 1)

    def test_polled_snapshot_can_drive_session_to_exception(self):
        # 잠금+벨트 체결 스냅샷은 세션 판정과 그대로 맞물린다.
        from engine.session import CareSession, SessionState

        session = CareSession()
        session.apply_snapshot(snapshot_from_raw({"rear_door_open": True}))
        session.apply_snapshot(
            snapshot_from_raw({"rear_seat_belt_buckled": True})
        )
        state = session.apply_snapshot(
            VehicleSdkAdapter(
                FakeSdkClient(
                    {"rear_seat_belt_buckled": True, "locked": True}
                )
            ).poll()
        )
        self.assertEqual(state, SessionState.EXCEPTION)


if __name__ == "__main__":
    unittest.main()

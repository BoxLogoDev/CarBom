"""Vehicle SDK 어댑터 인터페이스·변환층 단위 테스트.

실 SDK는 아직 연동되지 않았으므로, 여기서 검증하는 것은
원시 신호 dict -> SignalSnapshot 변환과, 클라이언트 주입 여부에
따른 어댑터 동작(미연결 시 명시적 실패)뿐이다.
"""

import unittest

from engine.adapters import (
    VehicleSdkAdapter,
    apply_raw,
    apply_raws,
    raw_from_snapshot,
    raws_from_snapshots,
    snapshot_from_raw,
    snapshots_from_raws,
)
from engine.adapters.simulator import scenario_snapshots
from engine.session import CareSession, SessionState
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


class BulkConversionTest(unittest.TestCase):
    RAWS = [
        {"rear_door_open": True, "timestamp": 0.0},
        {"rear_seat_belt_buckled": True, "timestamp": 60.0},
        {"locked": True, "cabin_temp_c": 35.5, "timestamp": 120.0},
    ]

    def test_empty_input_gives_empty_tuple(self):
        self.assertEqual(snapshots_from_raws([]), ())
        self.assertEqual(raws_from_snapshots([]), ())

    def test_order_and_fields_are_preserved(self):
        snaps = snapshots_from_raws(self.RAWS)
        self.assertEqual(len(snaps), 3)
        self.assertTrue(snaps[0].rear_door_open)
        self.assertEqual(snaps[0].timestamp, 0.0)
        self.assertTrue(snaps[1].rear_seat_belt_buckled)
        self.assertEqual(snaps[1].timestamp, 60.0)
        self.assertTrue(snaps[2].locked)
        self.assertEqual(snaps[2].cabin_temp_c, 35.5)
        self.assertEqual(snaps[2].timestamp, 120.0)

    def test_raws_round_trip_through_snapshots(self):
        self.assertEqual(
            raws_from_snapshots(snapshots_from_raws([FULL_RAW])),
            (FULL_RAW,),
        )

    def test_snapshots_round_trip_through_raws(self):
        snaps = snapshots_from_raws(self.RAWS)
        self.assertEqual(
            snapshots_from_raws(raws_from_snapshots(snaps)), snaps
        )

    def test_generator_input_matches_list_input(self):
        self.assertEqual(
            snapshots_from_raws(iter(self.RAWS)),
            snapshots_from_raws(self.RAWS),
        )
        snaps = snapshots_from_raws(self.RAWS)
        self.assertEqual(
            raws_from_snapshots(iter(snaps)),
            raws_from_snapshots(snaps),
        )

    def test_scenario_snapshots_round_trip(self):
        original = scenario_snapshots("dropoff_normal")
        self.assertEqual(
            snapshots_from_raws(raws_from_snapshots(original)), original
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


class FakeSequenceSdkClient:
    """read_raw()가 호출할 때마다 다음 dict를 돌려주는 가짜 SDK 클라이언트."""

    def __init__(self, raws):
        self._raws = list(raws)
        self.calls = 0

    def read_raw(self):
        raw = self._raws[self.calls]
        self.calls += 1
        return raw


class PollIntoTest(unittest.TestCase):
    def test_poll_into_without_client_fails_and_leaves_session_idle(self):
        session = CareSession()
        with self.assertRaises(NotImplementedError):
            VehicleSdkAdapter().poll_into(session)
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])

    def test_poll_into_rear_door_open_moves_session_to_boarding(self):
        session = CareSession()
        adapter = VehicleSdkAdapter(
            FakeSdkClient({"rear_door_open": True})
        )
        state = adapter.poll_into(session)
        self.assertEqual(state, SessionState.BOARDING)
        self.assertEqual(session.state, SessionState.BOARDING)

    def test_poll_into_normal_flow_reaches_completed(self):
        raws = [
            raw_from_snapshot(SignalSnapshot(rear_door=DoorState.OPEN)),
            raw_from_snapshot(SignalSnapshot(rear_seat_belt_buckled=True)),
            raw_from_snapshot(
                SignalSnapshot(
                    rear_seat_belt_buckled=True, ignition=IgnitionState.ON
                )
            ),
            raw_from_snapshot(SignalSnapshot(rear_seat_belt_buckled=True)),
            raw_from_snapshot(SignalSnapshot(rear_door=DoorState.OPEN)),
            raw_from_snapshot(SignalSnapshot()),
        ]
        session = CareSession()
        adapter = VehicleSdkAdapter(FakeSequenceSdkClient(raws))
        state = None
        for _ in raws:
            state = adapter.poll_into(session)
        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)

    def test_poll_into_locked_with_passenger_moves_session_to_exception(self):
        session = CareSession()
        session.apply_snapshot(snapshot_from_raw({"rear_door_open": True}))
        session.apply_snapshot(
            snapshot_from_raw({"rear_seat_belt_buckled": True})
        )
        adapter = VehicleSdkAdapter(
            FakeSdkClient({"rear_seat_belt_buckled": True, "locked": True})
        )
        state = adapter.poll_into(session)
        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)

    def test_poll_into_updates_session_current_snapshot(self):
        session = CareSession()
        adapter = VehicleSdkAdapter(
            FakeSdkClient({"cabin_temp_c": 35.5})
        )
        adapter.poll_into(session)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)


class ApplyRawTest(unittest.TestCase):
    def test_apply_raws_with_empty_input_leaves_session_idle(self):
        session = CareSession()
        state = apply_raws(session, [])
        self.assertEqual(state, SessionState.IDLE)
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])

    def test_apply_raw_rear_door_open_moves_session_to_boarding(self):
        session = CareSession()
        state = apply_raw(session, {"rear_door_open": True})
        self.assertEqual(state, SessionState.BOARDING)
        self.assertEqual(state, session.state)

    def test_apply_raws_normal_flow_reaches_completed(self):
        raws = raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        session = CareSession()
        state = apply_raws(session, raws)
        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)

    def test_apply_raw_locked_with_passenger_moves_session_to_exception(self):
        session = CareSession()
        apply_raw(session, {"rear_door_open": True})
        apply_raw(session, {"rear_seat_belt_buckled": True})
        state = apply_raw(
            session,
            {
                "rear_seat_belt_buckled": True,
                "locked": True,
                "cabin_temp_c": 35.5,
            },
        )
        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)

    def test_apply_raws_generator_input_matches_list_input(self):
        raws = raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        list_session = CareSession()
        generator_session = CareSession()
        list_state = apply_raws(list_session, raws)
        generator_state = apply_raws(generator_session, iter(raws))
        self.assertEqual(generator_state, list_state)
        self.assertEqual(generator_session.state, list_session.state)


if __name__ == "__main__":
    unittest.main()

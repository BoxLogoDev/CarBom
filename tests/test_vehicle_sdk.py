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
    apply_raws_for_sessions,
    dropoff_normal_snapshots,
    forgotten_rising_temp_snapshots,
    poll_into_sessions,
    poll_repeatedly_into_sessions,
    poll_snapshots,
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


class ApplyRawsForSessionsTest(unittest.TestCase):
    def test_empty_sessions_gives_empty_tuple(self):
        raws = raws_from_snapshots(dropoff_normal_snapshots())
        self.assertEqual(apply_raws_for_sessions([], raws), ())

    def test_empty_raws_leaves_sessions_unchanged(self):
        sessions = [CareSession(), CareSession()]
        states = apply_raws_for_sessions(sessions, [])
        self.assertEqual(
            states, (sessions[0].state, sessions[1].state)
        )
        for session in sessions:
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])

    def test_dropoff_normal_raws_complete_both_sessions(self):
        raws = raws_from_snapshots(dropoff_normal_snapshots())
        sessions = [CareSession(), CareSession()]
        states = apply_raws_for_sessions(sessions, raws)
        self.assertEqual(
            states, (SessionState.COMPLETED, SessionState.COMPLETED)
        )
        self.assertEqual(
            states, (sessions[0].state, sessions[1].state)
        )

    def test_forgotten_rising_temp_raws_exception_both_sessions(self):
        raws = raws_from_snapshots(forgotten_rising_temp_snapshots())
        sessions = [CareSession(), CareSession()]
        states = apply_raws_for_sessions(sessions, raws)
        self.assertEqual(
            states, (SessionState.EXCEPTION, SessionState.EXCEPTION)
        )
        for session in sessions:
            self.assertEqual(session.state, SessionState.EXCEPTION)
            self.assertTrue(session.passenger_present)
            self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)

    def test_generator_raws_are_reused_for_all_sessions(self):
        raws = raws_from_snapshots(dropoff_normal_snapshots())
        sessions = [CareSession(), CareSession()]
        states = apply_raws_for_sessions(sessions, iter(raws))
        self.assertEqual(
            states, (SessionState.COMPLETED, SessionState.COMPLETED)
        )
        for session in sessions:
            self.assertEqual(session.state, SessionState.COMPLETED)

    def test_generator_sessions_matches_list_input(self):
        raws = raws_from_snapshots(dropoff_normal_snapshots())
        list_sessions = [CareSession(), CareSession()]
        generator_sessions = [CareSession(), CareSession()]
        list_states = apply_raws_for_sessions(list_sessions, raws)
        generator_states = apply_raws_for_sessions(
            iter(generator_sessions), raws
        )
        self.assertEqual(generator_states, list_states)
        self.assertEqual(
            [session.state for session in generator_sessions],
            [session.state for session in list_sessions],
        )


class PollIntoSessionsTest(unittest.TestCase):
    def test_empty_sessions_never_polls_even_without_client(self):
        self.assertEqual(poll_into_sessions(VehicleSdkAdapter(), []), ())

    def test_single_poll_applies_same_snapshot_to_both_sessions(self):
        client = FakeSdkClient({"rear_door_open": True})
        adapter = VehicleSdkAdapter(client)
        sessions = [CareSession(), CareSession()]
        states = poll_into_sessions(adapter, sessions)
        self.assertEqual(
            states, (SessionState.BOARDING, SessionState.BOARDING)
        )
        self.assertEqual(states, (sessions[0].state, sessions[1].state))
        self.assertEqual(client.calls, 1)

    def test_locked_poll_moves_both_prepared_sessions_to_exception(self):
        sessions = [CareSession(), CareSession()]
        for session in sessions:
            session.apply_snapshot(
                snapshot_from_raw({"rear_door_open": True})
            )
            session.apply_snapshot(
                snapshot_from_raw({"rear_seat_belt_buckled": True})
            )
        adapter = VehicleSdkAdapter(
            FakeSdkClient({"rear_seat_belt_buckled": True, "locked": True})
        )
        states = poll_into_sessions(adapter, sessions)
        self.assertEqual(
            states, (SessionState.EXCEPTION, SessionState.EXCEPTION)
        )
        for session in sessions:
            self.assertTrue(session.passenger_present)

    def test_without_client_fails_and_leaves_session_unchanged(self):
        session = CareSession()
        with self.assertRaises(NotImplementedError):
            poll_into_sessions(VehicleSdkAdapter(), [session])
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])

    def test_generator_sessions_matches_list_input(self):
        list_sessions = [CareSession(), CareSession()]
        generator_sessions = [CareSession(), CareSession()]
        list_states = poll_into_sessions(
            VehicleSdkAdapter(FakeSdkClient({"rear_door_open": True})),
            list_sessions,
        )
        generator_states = poll_into_sessions(
            VehicleSdkAdapter(FakeSdkClient({"rear_door_open": True})),
            iter(generator_sessions),
        )
        self.assertEqual(generator_states, list_states)
        self.assertEqual(
            [session.state for session in generator_sessions],
            [session.state for session in list_sessions],
        )

    def test_polled_snapshot_temp_is_reflected_in_each_session(self):
        sessions = [CareSession(), CareSession()]
        adapter = VehicleSdkAdapter(
            FakeSdkClient({"cabin_temp_c": 35.5})
        )
        poll_into_sessions(adapter, sessions)
        for session in sessions:
            self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)


class PollRepeatedlyIntoTest(unittest.TestCase):
    def test_zero_times_never_polls_even_without_client(self):
        session = CareSession()
        state = VehicleSdkAdapter().poll_repeatedly_into(session, 0)
        self.assertEqual(state, SessionState.IDLE)
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])

    def test_negative_times_raises_value_error_without_polling(self):
        raws = raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        client = FakeSequenceSdkClient(raws)
        session = CareSession()
        with self.assertRaises(ValueError):
            VehicleSdkAdapter(client).poll_repeatedly_into(session, -1)
        self.assertEqual(client.calls, 0)
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])

    def test_repeated_polls_drive_normal_flow_to_completed(self):
        raws = raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        client = FakeSequenceSdkClient(raws)
        session = CareSession()
        state = VehicleSdkAdapter(client).poll_repeatedly_into(session, 6)
        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(state, session.state)
        self.assertEqual(client.calls, 6)

    def test_repeated_polls_drive_forgotten_flow_to_exception(self):
        raws = raws_from_snapshots(
            scenario_snapshots("forgotten_rising_temp")
        )
        client = FakeSequenceSdkClient(raws)
        session = CareSession()
        state = VehicleSdkAdapter(client).poll_repeatedly_into(session, 8)
        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)

    def test_without_client_fails_and_leaves_session_unchanged(self):
        session = CareSession()
        with self.assertRaises(NotImplementedError):
            VehicleSdkAdapter().poll_repeatedly_into(session, 3)
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])

    def test_partial_polls_stop_at_intermediate_state(self):
        raws = raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        client = FakeSequenceSdkClient(raws)
        session = CareSession()
        state = VehicleSdkAdapter(client).poll_repeatedly_into(session, 2)
        self.assertEqual(state, SessionState.ONBOARD)
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertEqual(client.calls, 2)


class PollRepeatedlyIntoSessionsTest(unittest.TestCase):
    def test_empty_sessions_never_polls_even_without_client(self):
        self.assertEqual(
            poll_repeatedly_into_sessions(VehicleSdkAdapter(), [], 3), ()
        )
        with self.assertRaises(ValueError):
            poll_repeatedly_into_sessions(VehicleSdkAdapter(), [], -1)

    def test_zero_times_returns_current_states_without_polling(self):
        sessions = [CareSession(), CareSession()]
        states = poll_repeatedly_into_sessions(
            VehicleSdkAdapter(), sessions, 0
        )
        self.assertEqual(states, (SessionState.IDLE, SessionState.IDLE))
        self.assertEqual(states, (sessions[0].state, sessions[1].state))
        for session in sessions:
            self.assertEqual(session.history, [])

    def test_negative_times_raises_value_error_without_polling(self):
        raws = raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        client = FakeSequenceSdkClient(raws)
        session = CareSession()
        with self.assertRaises(ValueError):
            poll_repeatedly_into_sessions(
                VehicleSdkAdapter(client), [session], -1
            )
        self.assertEqual(client.calls, 0)
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])

    def test_repeated_polls_complete_both_sessions_from_generator(self):
        raws = raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        client = FakeSequenceSdkClient(raws)
        sessions = [CareSession(), CareSession()]
        states = poll_repeatedly_into_sessions(
            VehicleSdkAdapter(client), iter(sessions), 6
        )
        self.assertEqual(
            states, (SessionState.COMPLETED, SessionState.COMPLETED)
        )
        self.assertEqual(states, (sessions[0].state, sessions[1].state))
        self.assertEqual(client.calls, 6)

    def test_repeated_polls_exception_both_sessions(self):
        raws = raws_from_snapshots(
            scenario_snapshots("forgotten_rising_temp")
        )
        client = FakeSequenceSdkClient(raws)
        sessions = [CareSession(), CareSession()]
        states = poll_repeatedly_into_sessions(
            VehicleSdkAdapter(client), sessions, 8
        )
        self.assertEqual(
            states, (SessionState.EXCEPTION, SessionState.EXCEPTION)
        )
        self.assertEqual(client.calls, 8)
        for session in sessions:
            self.assertTrue(session.passenger_present)
            self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)

    def test_without_client_fails_and_leaves_session_unchanged(self):
        session = CareSession()
        with self.assertRaises(NotImplementedError):
            poll_repeatedly_into_sessions(VehicleSdkAdapter(), [session], 3)
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])


class PollSnapshotsTest(unittest.TestCase):
    def test_zero_times_returns_empty_tuple_without_client(self):
        self.assertEqual(poll_snapshots(VehicleSdkAdapter(), 0), ())

    def test_negative_times_raises_value_error_without_polling(self):
        raws = raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        client = FakeSequenceSdkClient(raws)
        with self.assertRaises(ValueError):
            poll_snapshots(VehicleSdkAdapter(client), -1)
        self.assertEqual(client.calls, 0)
        with self.assertRaises(ValueError):
            poll_snapshots(VehicleSdkAdapter(), -1)

    def test_polls_normal_flow_snapshots_in_order(self):
        raws = raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        client = FakeSequenceSdkClient(raws)
        snapshots = poll_snapshots(VehicleSdkAdapter(client), 6)
        self.assertEqual(client.calls, 6)
        self.assertEqual(snapshots, dropoff_normal_snapshots())
        self.assertEqual(snapshots[0].rear_door, DoorState.OPEN)
        self.assertEqual(snapshots[-1].timestamp, 300.0)

    def test_polls_exception_flow_last_snapshot_is_hot_and_locked(self):
        raws = raws_from_snapshots(
            scenario_snapshots("forgotten_rising_temp")
        )
        client = FakeSequenceSdkClient(raws)
        snapshots = poll_snapshots(VehicleSdkAdapter(client), 8)
        self.assertEqual(client.calls, 8)
        self.assertEqual(snapshots, forgotten_rising_temp_snapshots())
        self.assertEqual(snapshots[-1].cabin_temp_c, 35.5)
        self.assertEqual(snapshots[-1].lock, LockState.LOCKED)
        self.assertTrue(snapshots[-1].rear_seat_belt_buckled)

    def test_without_client_positive_times_fails(self):
        with self.assertRaises(NotImplementedError):
            poll_snapshots(VehicleSdkAdapter(), 3)

    def test_returns_tuple_of_signal_snapshots(self):
        raws = raws_from_snapshots(scenario_snapshots("pet_dropoff"))
        snapshots = poll_snapshots(
            VehicleSdkAdapter(FakeSequenceSdkClient(raws)), 6
        )
        self.assertIsInstance(snapshots, tuple)
        self.assertEqual(len(snapshots), 6)
        for snapshot in snapshots:
            self.assertIsInstance(snapshot, SignalSnapshot)


if __name__ == "__main__":
    unittest.main()

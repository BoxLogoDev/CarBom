"""Vehicle SDK 어댑터 인터페이스·변환층 단위 테스트.

실 SDK는 아직 연동되지 않았으므로, 여기서 검증하는 것은
원시 신호 dict -> SignalSnapshot 변환과, 클라이언트 주입 여부에
따른 어댑터 동작(미연결 시 명시적 실패)뿐이다.
"""

import unittest

from engine.adapters import (
    VehicleSdkAdapter,
    apply_raw,
    apply_raw_for_sessions,
    apply_raws,
    apply_raws_for_sessions,
    apply_raws_paired_for_sessions,
    apply_raw_sequences_for_sessions,
    dropoff_normal_snapshots,
    forgotten_rising_temp_snapshots,
    poll_into_sessions,
    poll_once_per_adapter_into_session,
    poll_once_per_adapter_into_sessions,
    poll_paired_into_sessions,
    poll_repeatedly_into_sessions,
    poll_repeatedly_into_sessions_by_times,
    poll_repeatedly_paired_into_sessions,
    poll_repeatedly_for_adapters_into_session,
    poll_repeatedly_for_adapters_into_sessions,
    poll_snapshot,
    poll_snapshots,
    poll_snapshots_by_times,
    poll_snapshots_for_adapters,
    poll_snapshots_once_per_adapter,
    poll_snapshots_paired,
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


class ApplyRawForSessionsTest(unittest.TestCase):
    def test_empty_sessions_gives_empty_tuple(self):
        self.assertEqual(
            apply_raw_for_sessions([], {"rear_door_open": True}), ()
        )

    def test_rear_door_open_moves_both_sessions_to_boarding(self):
        sessions = [CareSession(), CareSession()]
        states = apply_raw_for_sessions(
            sessions, {"rear_door_open": True}
        )
        self.assertEqual(
            states, (SessionState.BOARDING, SessionState.BOARDING)
        )
        self.assertEqual(states, (sessions[0].state, sessions[1].state))

    def test_locked_with_passenger_moves_prepared_sessions_to_exception(self):
        sessions = [CareSession(), CareSession()]
        for session in sessions:
            apply_raw(session, {"rear_door_open": True})
            apply_raw(session, {"rear_seat_belt_buckled": True})
            apply_raw(
                session,
                {"rear_seat_belt_buckled": True, "ignition_on": True},
            )
            apply_raw(session, {"rear_seat_belt_buckled": True})
            self.assertEqual(session.state, SessionState.ARRIVED)
        states = apply_raw_for_sessions(
            sessions,
            {
                "rear_seat_belt_buckled": True,
                "locked": True,
                "cabin_temp_c": 35.5,
            },
        )
        self.assertEqual(
            states, (SessionState.EXCEPTION, SessionState.EXCEPTION)
        )
        for session in sessions:
            self.assertTrue(session.passenger_present)
            self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)

    def test_same_snapshot_is_shared_by_all_sessions(self):
        sessions = [CareSession(), CareSession()]
        apply_raw_for_sessions(
            sessions, {"rear_door_open": True, "timestamp": 50.0}
        )
        self.assertIs(
            sessions[0].current_snapshot, sessions[1].current_snapshot
        )
        self.assertEqual(sessions[0].current_snapshot.timestamp, 50.0)
        self.assertEqual(
            sessions[0].current_snapshot,
            snapshot_from_raw({"rear_door_open": True, "timestamp": 50.0}),
        )

    def test_generator_sessions_matches_list_input(self):
        list_sessions = [CareSession(), CareSession()]
        generator_sessions = [CareSession(), CareSession()]
        raw = {"rear_door_open": True}
        list_states = apply_raw_for_sessions(list_sessions, raw)
        generator_states = apply_raw_for_sessions(
            iter(generator_sessions), raw
        )
        self.assertEqual(generator_states, list_states)
        self.assertEqual(
            [session.state for session in generator_sessions],
            [session.state for session in list_sessions],
        )

    def test_returns_tuple_of_session_states(self):
        sessions = [CareSession(), CareSession()]
        states = apply_raw_for_sessions(
            sessions, {"rear_door_open": True}
        )
        self.assertIsInstance(states, tuple)
        self.assertEqual(len(states), 2)
        for state in states:
            self.assertIsInstance(state, SessionState)


class ApplyRawsPairedForSessionsTest(unittest.TestCase):
    def test_empty_inputs_give_empty_tuple(self):
        self.assertEqual(apply_raws_paired_for_sessions([], []), ())

    def test_paired_raws_apply_to_matching_sessions(self):
        sessions = [CareSession(), CareSession()]
        states = apply_raws_paired_for_sessions(
            sessions,
            [
                {"rear_door_open": True},
                {"rear_seat_belt_buckled": True},
            ],
        )
        self.assertEqual(
            states, (SessionState.BOARDING, SessionState.ONBOARD)
        )
        self.assertEqual(
            states, (sessions[0].state, sessions[1].state)
        )

    def test_paired_raws_exception_and_alighting(self):
        sessions = [CareSession(), CareSession()]
        for session in sessions:
            apply_raw(session, {"rear_door_open": True})
            apply_raw(session, {"rear_seat_belt_buckled": True})
            apply_raw(
                session,
                {"rear_seat_belt_buckled": True, "ignition_on": True},
            )
            apply_raw(session, {"rear_seat_belt_buckled": True})
            self.assertEqual(session.state, SessionState.ARRIVED)
        states = apply_raws_paired_for_sessions(
            sessions,
            [
                {
                    "rear_seat_belt_buckled": True,
                    "locked": True,
                    "cabin_temp_c": 35.5,
                },
                {"rear_door_open": True},
            ],
        )
        self.assertEqual(
            states, (SessionState.EXCEPTION, SessionState.ALIGHTING)
        )
        self.assertTrue(sessions[0].passenger_present)
        self.assertEqual(sessions[0].current_snapshot.cabin_temp_c, 35.5)

    def test_length_mismatch_raises_and_leaves_sessions_unchanged(self):
        for sessions_count, raws_count in ((2, 1), (1, 2)):
            with self.subTest(
                sessions_count=sessions_count, raws_count=raws_count
            ):
                sessions = [CareSession() for _ in range(sessions_count)]
                raws = [
                    {"rear_door_open": True} for _ in range(raws_count)
                ]
                with self.assertRaises(ValueError):
                    apply_raws_paired_for_sessions(sessions, raws)
                for session in sessions:
                    self.assertEqual(session.state, SessionState.IDLE)
                    self.assertEqual(session.history, [])

    def test_generator_inputs_match_list_input(self):
        list_sessions = [CareSession(), CareSession()]
        generator_sessions = [CareSession(), CareSession()]
        raws = [
            {"rear_door_open": True},
            {"rear_seat_belt_buckled": True},
        ]
        list_states = apply_raws_paired_for_sessions(list_sessions, raws)
        generator_states = apply_raws_paired_for_sessions(
            iter(generator_sessions), iter(raws)
        )
        self.assertEqual(generator_states, list_states)
        self.assertEqual(
            [session.state for session in generator_sessions],
            [session.state for session in list_sessions],
        )

    def test_returns_tuple_of_session_states_and_keeps_duplicates(self):
        session = CareSession()
        states = apply_raws_paired_for_sessions(
            [session, session],
            [{"rear_door_open": True}, {"rear_seat_belt_buckled": True}],
        )
        self.assertIsInstance(states, tuple)
        self.assertEqual(len(states), 2)
        for state in states:
            self.assertIsInstance(state, SessionState)
        self.assertEqual(states[-1], session.state)


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


class ApplyRawSequencesForSessionsTest(unittest.TestCase):
    def test_empty_inputs_give_empty_tuple(self):
        self.assertEqual(apply_raw_sequences_for_sessions([], []), ())

    def test_paired_sequences_apply_to_matching_sessions(self):
        dropoff_raws = raws_from_snapshots(dropoff_normal_snapshots())
        forgotten_raws = raws_from_snapshots(
            forgotten_rising_temp_snapshots()
        )
        sessions = [CareSession(), CareSession()]
        states = apply_raw_sequences_for_sessions(
            sessions, [dropoff_raws, forgotten_raws]
        )
        self.assertEqual(
            states, (SessionState.COMPLETED, SessionState.EXCEPTION)
        )
        self.assertEqual(states, (sessions[0].state, sessions[1].state))
        self.assertFalse(sessions[0].passenger_present)
        self.assertTrue(sessions[1].passenger_present)
        self.assertEqual(sessions[1].current_snapshot.cabin_temp_c, 35.5)

    def test_three_fixed_scenarios_paired(self):
        sequences = [
            raws_from_snapshots(scenario_snapshots(name))
            for name in (
                "dropoff_normal",
                "forgotten_rising_temp",
                "pet_dropoff",
            )
        ]
        sessions = [CareSession(), CareSession(), CareSession()]
        states = apply_raw_sequences_for_sessions(sessions, sequences)
        self.assertEqual(
            states,
            (
                SessionState.COMPLETED,
                SessionState.EXCEPTION,
                SessionState.COMPLETED,
            ),
        )
        self.assertEqual(
            states, tuple(session.state for session in sessions)
        )

    def test_length_mismatch_raises_and_leaves_sessions_unchanged(self):
        raws = raws_from_snapshots(dropoff_normal_snapshots())
        more_sessions = [CareSession(), CareSession()]
        with self.assertRaises(ValueError):
            apply_raw_sequences_for_sessions(more_sessions, [raws])
        fewer_sessions = [CareSession()]
        with self.assertRaises(ValueError):
            apply_raw_sequences_for_sessions(fewer_sessions, [raws, raws])
        for session in more_sessions + fewer_sessions:
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])

    def test_empty_inner_sequence_leaves_that_session_unchanged(self):
        dropoff_raws = raws_from_snapshots(dropoff_normal_snapshots())
        sessions = [CareSession(), CareSession()]
        states = apply_raw_sequences_for_sessions(
            sessions, [[], dropoff_raws]
        )
        self.assertEqual(
            states, (SessionState.IDLE, SessionState.COMPLETED)
        )
        self.assertEqual(sessions[0].history, [])
        self.assertEqual(sessions[1].state, SessionState.COMPLETED)

    def test_generator_inputs_match_list_input(self):
        dropoff_raws = raws_from_snapshots(dropoff_normal_snapshots())
        forgotten_raws = raws_from_snapshots(
            forgotten_rising_temp_snapshots()
        )
        list_sessions = [CareSession(), CareSession()]
        generator_sessions = [CareSession(), CareSession()]
        list_states = apply_raw_sequences_for_sessions(
            list_sessions, [dropoff_raws, forgotten_raws]
        )
        generator_states = apply_raw_sequences_for_sessions(
            iter(generator_sessions),
            (iter(seq) for seq in (dropoff_raws, forgotten_raws)),
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


class PollPairedIntoSessionsTest(unittest.TestCase):
    def test_empty_inputs_give_empty_tuple(self):
        self.assertEqual(poll_paired_into_sessions([], []), ())

    def test_paired_adapters_poll_into_matching_sessions(self):
        door_client = FakeSdkClient({"rear_door_open": True})
        drive_client = FakeSdkClient(
            {"rear_seat_belt_buckled": True, "ignition_on": True}
        )
        adapters = [
            VehicleSdkAdapter(door_client),
            VehicleSdkAdapter(drive_client),
        ]
        sessions = [CareSession(), CareSession()]
        states = poll_paired_into_sessions(adapters, sessions)
        self.assertEqual(
            states, (SessionState.BOARDING, SessionState.DRIVING)
        )
        self.assertEqual(
            states, (sessions[0].state, sessions[1].state)
        )
        self.assertEqual(door_client.calls, 1)
        self.assertEqual(drive_client.calls, 1)

    def test_paired_polls_exception_and_alighting(self):
        sessions = [CareSession(), CareSession()]
        for session in sessions:
            apply_raw(session, {"rear_door_open": True})
            apply_raw(session, {"rear_seat_belt_buckled": True})
            apply_raw(
                session,
                {"rear_seat_belt_buckled": True, "ignition_on": True},
            )
            apply_raw(session, {"rear_seat_belt_buckled": True})
            self.assertEqual(session.state, SessionState.ARRIVED)
        adapters = [
            VehicleSdkAdapter(
                FakeSdkClient(
                    {
                        "rear_seat_belt_buckled": True,
                        "locked": True,
                        "cabin_temp_c": 35.5,
                    }
                )
            ),
            VehicleSdkAdapter(FakeSdkClient({"rear_door_open": True})),
        ]
        states = poll_paired_into_sessions(adapters, sessions)
        self.assertEqual(
            states, (SessionState.EXCEPTION, SessionState.ALIGHTING)
        )
        self.assertTrue(sessions[0].passenger_present)
        self.assertEqual(sessions[0].current_snapshot.cabin_temp_c, 35.5)

    def test_length_mismatch_raises_without_polling_or_changing(self):
        for adapters_count, sessions_count in ((2, 1), (1, 2)):
            with self.subTest(
                adapters_count=adapters_count,
                sessions_count=sessions_count,
            ):
                clients = [
                    FakeSdkClient({"rear_door_open": True})
                    for _ in range(adapters_count)
                ]
                adapters = [VehicleSdkAdapter(c) for c in clients]
                sessions = [
                    CareSession() for _ in range(sessions_count)
                ]
                with self.assertRaises(ValueError):
                    poll_paired_into_sessions(adapters, sessions)
                for client in clients:
                    self.assertEqual(client.calls, 0)
                for session in sessions:
                    self.assertEqual(session.state, SessionState.IDLE)
                    self.assertEqual(session.history, [])

    def test_generator_inputs_match_list_input(self):
        def make_adapters():
            return [
                VehicleSdkAdapter(
                    FakeSdkClient({"rear_door_open": True})
                ),
                VehicleSdkAdapter(
                    FakeSdkClient({"rear_seat_belt_buckled": True})
                ),
            ]

        list_sessions = [CareSession(), CareSession()]
        generator_sessions = [CareSession(), CareSession()]
        list_states = poll_paired_into_sessions(
            make_adapters(), list_sessions
        )
        generator_states = poll_paired_into_sessions(
            iter(make_adapters()), iter(generator_sessions)
        )
        self.assertEqual(generator_states, list_states)
        self.assertEqual(
            [session.state for session in generator_sessions],
            [session.state for session in list_sessions],
        )

    def test_returns_tuple_of_session_states_and_keeps_duplicates(self):
        client = FakeSdkClient({"rear_door_open": True})
        adapter = VehicleSdkAdapter(client)
        session = CareSession()
        states = poll_paired_into_sessions(
            [adapter, adapter], [session, session]
        )
        self.assertIsInstance(states, tuple)
        self.assertEqual(len(states), 2)
        for state in states:
            self.assertIsInstance(state, SessionState)
        self.assertEqual(
            states, (SessionState.BOARDING, SessionState.BOARDING)
        )
        self.assertEqual(states[-1], session.state)
        self.assertEqual(client.calls, 2)


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


class PollRepeatedlyIntoSessionsByTimesTest(unittest.TestCase):
    def test_empty_input_returns_empty_tuple_without_client(self):
        self.assertEqual(
            poll_repeatedly_into_sessions_by_times(
                VehicleSdkAdapter(), [], []
            ),
            (),
        )

    def test_length_mismatch_raises_without_polling_or_changing(self):
        raws = raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        client = FakeSequenceSdkClient(raws)
        adapter = VehicleSdkAdapter(client)
        sessions = [CareSession(), CareSession()]
        with self.assertRaises(ValueError):
            poll_repeatedly_into_sessions_by_times(adapter, sessions, [6])
        with self.assertRaises(ValueError):
            poll_repeatedly_into_sessions_by_times(
                adapter, sessions[:1], [6, 8]
            )
        self.assertEqual(client.calls, 0)
        for session in sessions:
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])

    def test_negative_times_raises_without_polling_or_changing(self):
        raws = raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        client = FakeSequenceSdkClient(raws)
        sessions = [CareSession(), CareSession()]
        with self.assertRaises(ValueError):
            poll_repeatedly_into_sessions_by_times(
                VehicleSdkAdapter(client), sessions, [6, -1]
            )
        self.assertEqual(client.calls, 0)
        for session in sessions:
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])

    def test_paired_times_apply_different_poll_slices(self):
        raws = raws_from_snapshots(
            scenario_snapshots("dropoff_normal")
        ) + raws_from_snapshots(scenario_snapshots("forgotten_rising_temp"))
        client = FakeSequenceSdkClient(raws)
        sessions = [CareSession(), CareSession()]
        states = poll_repeatedly_into_sessions_by_times(
            VehicleSdkAdapter(client), iter(sessions), iter([6, 8])
        )
        self.assertEqual(
            states, (SessionState.COMPLETED, SessionState.EXCEPTION)
        )
        self.assertEqual(states, (sessions[0].state, sessions[1].state))
        self.assertEqual(client.calls, 14)
        self.assertEqual(len(sessions[0].history), 6)
        self.assertFalse(sessions[0].passenger_present)
        self.assertEqual(len(sessions[1].history), 5)
        self.assertTrue(sessions[1].passenger_present)
        self.assertEqual(sessions[1].current_snapshot.cabin_temp_c, 35.5)

    def test_zero_times_leave_sessions_unchanged(self):
        sessions = [CareSession(), CareSession()]
        states = poll_repeatedly_into_sessions_by_times(
            VehicleSdkAdapter(), sessions, [0, 0]
        )
        self.assertEqual(states, (SessionState.IDLE, SessionState.IDLE))
        raws = raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        client = FakeSequenceSdkClient(raws)
        sessions = [CareSession(), CareSession()]
        states = poll_repeatedly_into_sessions_by_times(
            VehicleSdkAdapter(client), sessions, [0, 6]
        )
        self.assertEqual(
            states, (SessionState.IDLE, SessionState.COMPLETED)
        )
        self.assertEqual(sessions[0].history, [])
        self.assertEqual(client.calls, 6)

    def test_without_client_positive_times_fails_and_keeps_sessions(self):
        sessions = [CareSession(), CareSession()]
        with self.assertRaises(NotImplementedError):
            poll_repeatedly_into_sessions_by_times(
                VehicleSdkAdapter(), sessions, [0, 3]
            )
        for session in sessions:
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])


class PollRepeatedlyPairedIntoSessionsTest(unittest.TestCase):
    def test_empty_inputs_give_empty_tuple(self):
        self.assertEqual(
            poll_repeatedly_paired_into_sessions([], [], []), ()
        )

    def test_paired_adapters_apply_different_poll_slices(self):
        normal_client = FakeSequenceSdkClient(
            raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        )
        forgotten_client = FakeSequenceSdkClient(
            raws_from_snapshots(
                scenario_snapshots("forgotten_rising_temp")
            )
        )
        adapters = [
            VehicleSdkAdapter(normal_client),
            VehicleSdkAdapter(forgotten_client),
        ]
        sessions = [CareSession(), CareSession()]
        states = poll_repeatedly_paired_into_sessions(
            iter(adapters), iter(sessions), iter([6, 8])
        )
        self.assertIsInstance(states, tuple)
        self.assertEqual(
            states, (SessionState.COMPLETED, SessionState.EXCEPTION)
        )
        self.assertEqual(states, (sessions[0].state, sessions[1].state))
        self.assertEqual(normal_client.calls, 6)
        self.assertEqual(forgotten_client.calls, 8)
        self.assertEqual(len(sessions[0].history), 6)
        self.assertFalse(sessions[0].passenger_present)
        self.assertEqual(len(sessions[1].history), 5)
        self.assertTrue(sessions[1].passenger_present)
        self.assertEqual(sessions[1].current_snapshot.cabin_temp_c, 35.5)

    def test_zero_times_leave_matching_sessions_unchanged(self):
        sessions = [CareSession(), CareSession()]
        states = poll_repeatedly_paired_into_sessions(
            [VehicleSdkAdapter(), VehicleSdkAdapter()],
            sessions,
            [0, 0],
        )
        self.assertEqual(states, (SessionState.IDLE, SessionState.IDLE))
        client = FakeSequenceSdkClient(
            raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        )
        sessions = [CareSession(), CareSession()]
        states = poll_repeatedly_paired_into_sessions(
            [VehicleSdkAdapter(), VehicleSdkAdapter(client)],
            sessions,
            [0, 6],
        )
        self.assertEqual(
            states, (SessionState.IDLE, SessionState.COMPLETED)
        )
        self.assertEqual(sessions[0].history, [])
        self.assertEqual(client.calls, 6)

    def test_length_mismatch_raises_without_polling_or_changing(self):
        for counts in ((1, 2, 2), (2, 1, 2), (2, 2, 1)):
            with self.subTest(counts=counts):
                clients = [
                    FakeSequenceSdkClient(
                        raws_from_snapshots(
                            scenario_snapshots("dropoff_normal")
                        )
                    )
                    for _ in range(counts[0])
                ]
                adapters = [VehicleSdkAdapter(c) for c in clients]
                sessions = [CareSession() for _ in range(counts[1])]
                with self.assertRaises(ValueError):
                    poll_repeatedly_paired_into_sessions(
                        adapters, sessions, [6] * counts[2]
                    )
                for client in clients:
                    self.assertEqual(client.calls, 0)
                for session in sessions:
                    self.assertEqual(session.state, SessionState.IDLE)
                    self.assertEqual(session.history, [])

    def test_negative_times_raises_without_polling_or_changing(self):
        clients = [
            FakeSequenceSdkClient(
                raws_from_snapshots(scenario_snapshots("dropoff_normal"))
            )
            for _ in range(2)
        ]
        adapters = [VehicleSdkAdapter(c) for c in clients]
        sessions = [CareSession(), CareSession()]
        with self.assertRaises(ValueError):
            poll_repeatedly_paired_into_sessions(
                adapters, sessions, [6, -1]
            )
        for client in clients:
            self.assertEqual(client.calls, 0)
        for session in sessions:
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])

    def test_unconnected_adapter_fails_before_any_session_changes(self):
        client = FakeSequenceSdkClient(
            raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        )
        adapters = [VehicleSdkAdapter(client), VehicleSdkAdapter()]
        sessions = [CareSession(), CareSession()]
        with self.assertRaises(NotImplementedError):
            poll_repeatedly_paired_into_sessions(
                adapters, sessions, [6, 3]
            )
        self.assertEqual(client.calls, 6)
        for session in sessions:
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])


class PollSnapshotTest(unittest.TestCase):
    def test_polls_exactly_once_and_returns_full_snapshot(self):
        client = FakeSdkClient(FULL_RAW)
        snap = poll_snapshot(VehicleSdkAdapter(client))
        self.assertEqual(client.calls, 1)
        self.assertEqual(snap, snapshot_from_raw(FULL_RAW))
        self.assertEqual(snap.rear_door, DoorState.OPEN)
        self.assertTrue(snap.rear_seat_belt_buckled)
        self.assertEqual(snap.ignition, IgnitionState.ON)
        self.assertTrue(snap.locked)
        self.assertTrue(snap.hvac_on)
        self.assertEqual(snap.cabin_temp_c, 33.5)
        self.assertEqual(snap.timestamp, 1234.5)

    def test_matches_single_element_of_poll_snapshots(self):
        raws = raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        single = poll_snapshot(
            VehicleSdkAdapter(FakeSequenceSdkClient(list(raws)))
        )
        client = FakeSequenceSdkClient(list(raws))
        plural = poll_snapshots(VehicleSdkAdapter(client), 1)
        self.assertIsInstance(single, SignalSnapshot)
        self.assertEqual(plural, (single,))
        self.assertEqual(client.calls, 1)

    def test_without_client_fails(self):
        with self.assertRaises(NotImplementedError):
            poll_snapshot(VehicleSdkAdapter())

    def test_read_only_leaves_existing_session_untouched(self):
        session = CareSession()
        session.apply_snapshot(
            SignalSnapshot(rear_door=DoorState.OPEN, timestamp=0.0)
        )
        state_before = session.state
        history_before = list(session.history)
        snapshot_before = session.current_snapshot
        poll_snapshot(VehicleSdkAdapter(FakeSdkClient(FULL_RAW)))
        self.assertEqual(session.state, state_before)
        self.assertEqual(session.history, history_before)
        self.assertEqual(session.current_snapshot, snapshot_before)

    def test_sequence_client_advances_in_order(self):
        raws = raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        client = FakeSequenceSdkClient(list(raws))
        adapter = VehicleSdkAdapter(client)
        first = poll_snapshot(adapter)
        second = poll_snapshot(adapter)
        expected = dropoff_normal_snapshots()
        self.assertEqual(first, expected[0])
        self.assertEqual(second, expected[1])
        self.assertEqual(client.calls, 2)

    def test_empty_raw_gives_default_snapshot(self):
        client = FakeSdkClient({})
        snap = poll_snapshot(VehicleSdkAdapter(client))
        self.assertEqual(snap, SignalSnapshot())
        self.assertEqual(client.calls, 1)


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


class PollSnapshotsByTimesTest(unittest.TestCase):
    def test_empty_input_returns_empty_tuple_without_client(self):
        self.assertEqual(
            poll_snapshots_by_times(VehicleSdkAdapter(), []), ()
        )

    def test_all_zero_times_return_empty_tuples_without_client(self):
        result = poll_snapshots_by_times(VehicleSdkAdapter(), [0, 0])
        self.assertEqual(result, ((), ()))
        raws = raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        client = FakeSequenceSdkClient(raws)
        result = poll_snapshots_by_times(
            VehicleSdkAdapter(client), [0, 0, 0]
        )
        self.assertEqual(result, ((), (), ()))
        self.assertEqual(client.calls, 0)

    def test_negative_times_raises_without_polling(self):
        raws = raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        client = FakeSequenceSdkClient(raws)
        with self.assertRaises(ValueError):
            poll_snapshots_by_times(VehicleSdkAdapter(client), [6, -1])
        self.assertEqual(client.calls, 0)
        with self.assertRaises(ValueError):
            poll_snapshots_by_times(VehicleSdkAdapter(), [-1])

    def test_paired_times_read_different_poll_slices(self):
        raws = raws_from_snapshots(
            scenario_snapshots("dropoff_normal")
        ) + raws_from_snapshots(scenario_snapshots("forgotten_rising_temp"))
        client = FakeSequenceSdkClient(raws)
        result = poll_snapshots_by_times(
            VehicleSdkAdapter(client), [6, 8]
        )
        self.assertEqual(client.calls, 14)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], dropoff_normal_snapshots())
        self.assertEqual(result[0][-1].timestamp, 300.0)
        self.assertEqual(result[1], forgotten_rising_temp_snapshots())
        self.assertEqual(result[1][-1].cabin_temp_c, 35.5)
        self.assertEqual(result[1][-1].lock, LockState.LOCKED)
        self.assertTrue(result[1][-1].rear_seat_belt_buckled)

    def test_generator_times_list_matches_list_input(self):
        raws = raws_from_snapshots(
            scenario_snapshots("dropoff_normal")
        ) + raws_from_snapshots(scenario_snapshots("pet_dropoff"))
        expected_client = FakeSequenceSdkClient(raws)
        expected = poll_snapshots_by_times(
            VehicleSdkAdapter(expected_client), [6, 6]
        )
        actual_client = FakeSequenceSdkClient(raws)
        actual = poll_snapshots_by_times(
            VehicleSdkAdapter(actual_client), iter([6, 6])
        )
        self.assertEqual(actual, expected)
        self.assertEqual(actual_client.calls, 12)
        self.assertIsInstance(actual, tuple)
        for sequence in actual:
            self.assertIsInstance(sequence, tuple)
            for snapshot in sequence:
                self.assertIsInstance(snapshot, SignalSnapshot)

    def test_without_client_positive_times_fails(self):
        with self.assertRaises(NotImplementedError):
            poll_snapshots_by_times(VehicleSdkAdapter(), [0, 3])


class PollSnapshotsPairedTest(unittest.TestCase):
    def test_empty_and_zero_inputs_return_empty_without_client(self):
        self.assertEqual(poll_snapshots_paired([], []), ())
        self.assertEqual(
            poll_snapshots_paired([VehicleSdkAdapter()], [0]), ((),)
        )

    def test_paired_adapters_read_different_slices(self):
        normal_client = FakeSequenceSdkClient(
            raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        )
        forgotten_client = FakeSequenceSdkClient(
            raws_from_snapshots(
                scenario_snapshots("forgotten_rising_temp")
            )
        )
        result = poll_snapshots_paired(
            [
                VehicleSdkAdapter(normal_client),
                VehicleSdkAdapter(forgotten_client),
            ],
            [6, 8],
        )
        self.assertEqual(normal_client.calls, 6)
        self.assertEqual(forgotten_client.calls, 8)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], dropoff_normal_snapshots())
        self.assertEqual(result[0][-1].timestamp, 300.0)
        self.assertEqual(result[1], forgotten_rising_temp_snapshots())
        self.assertEqual(result[1][-1].cabin_temp_c, 35.5)
        self.assertEqual(result[1][-1].lock, LockState.LOCKED)
        self.assertTrue(result[1][-1].rear_seat_belt_buckled)

    def test_zero_times_skip_matching_adapter(self):
        normal_client = FakeSequenceSdkClient(
            raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        )
        pet_client = FakeSequenceSdkClient(
            raws_from_snapshots(scenario_snapshots("pet_dropoff"))
        )
        result = poll_snapshots_paired(
            [
                VehicleSdkAdapter(normal_client),
                VehicleSdkAdapter(),
                VehicleSdkAdapter(pet_client),
            ],
            [6, 0, 6],
        )
        self.assertEqual(normal_client.calls, 6)
        self.assertEqual(pet_client.calls, 6)
        self.assertEqual(result[0], dropoff_normal_snapshots())
        self.assertEqual(result[1], ())
        self.assertEqual(result[2], scenario_snapshots("pet_dropoff"))

    def test_length_mismatch_raises_without_polling(self):
        for adapter_count, times_count in ((1, 2), (2, 1)):
            with self.subTest(
                adapter_count=adapter_count, times_count=times_count
            ):
                clients = [
                    FakeSequenceSdkClient(
                        raws_from_snapshots(
                            scenario_snapshots("dropoff_normal")
                        )
                    )
                    for _ in range(adapter_count)
                ]
                adapters = [VehicleSdkAdapter(c) for c in clients]
                with self.assertRaises(ValueError):
                    poll_snapshots_paired(
                        adapters, [6] * times_count
                    )
                for client in clients:
                    self.assertEqual(client.calls, 0)

    def test_negative_times_raises_without_polling(self):
        clients = [
            FakeSequenceSdkClient(
                raws_from_snapshots(scenario_snapshots("dropoff_normal"))
            )
            for _ in range(2)
        ]
        adapters = [VehicleSdkAdapter(c) for c in clients]
        with self.assertRaises(ValueError):
            poll_snapshots_paired(adapters, [6, -1])
        for client in clients:
            self.assertEqual(client.calls, 0)
        with self.assertRaises(ValueError):
            poll_snapshots_paired([VehicleSdkAdapter()], [-1])

    def test_generator_inputs_and_duplicate_adapter(self):
        raws = raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        expected_client = FakeSequenceSdkClient(raws)
        expected = poll_snapshots_paired(
            [VehicleSdkAdapter(expected_client)], [6]
        )
        actual_client = FakeSequenceSdkClient(raws)
        actual = poll_snapshots_paired(
            iter([VehicleSdkAdapter(actual_client)]), iter([6])
        )
        self.assertEqual(actual, expected)
        self.assertEqual(actual_client.calls, 6)
        self.assertIsInstance(actual, tuple)
        for sequence in actual:
            self.assertIsInstance(sequence, tuple)
            for snapshot in sequence:
                self.assertIsInstance(snapshot, SignalSnapshot)

        shared_client = FakeSequenceSdkClient(raws)
        shared_adapter = VehicleSdkAdapter(shared_client)
        result = poll_snapshots_paired(
            [shared_adapter, shared_adapter], [3, 3]
        )
        self.assertEqual(shared_client.calls, 6)
        self.assertEqual(result[0], dropoff_normal_snapshots()[:3])
        self.assertEqual(result[1], dropoff_normal_snapshots()[3:])


class PollSnapshotsForAdaptersTest(unittest.TestCase):
    def test_empty_and_zero_inputs_return_empty_without_client(self):
        self.assertEqual(poll_snapshots_for_adapters([], 6), ())
        self.assertEqual(poll_snapshots_for_adapters([], 0), ())
        self.assertEqual(
            poll_snapshots_for_adapters(
                [VehicleSdkAdapter(), VehicleSdkAdapter()], 0
            ),
            ((), ()),
        )

    def test_uniform_times_reads_each_adapter(self):
        normal_client = FakeSequenceSdkClient(
            raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        )
        forgotten_client = FakeSequenceSdkClient(
            raws_from_snapshots(
                scenario_snapshots("forgotten_rising_temp")
            )
        )
        result = poll_snapshots_for_adapters(
            [
                VehicleSdkAdapter(normal_client),
                VehicleSdkAdapter(forgotten_client),
            ],
            6,
        )
        self.assertEqual(normal_client.calls, 6)
        self.assertEqual(forgotten_client.calls, 6)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], dropoff_normal_snapshots())
        self.assertEqual(result[0][-1].timestamp, 300.0)
        self.assertEqual(
            result[1], forgotten_rising_temp_snapshots()[:6]
        )
        self.assertEqual(result[1][-1].cabin_temp_c, 28.0)
        self.assertEqual(result[1][-1].timestamp, 300.0)
        self.assertEqual(result[1][-1].lock, LockState.LOCKED)

    def test_negative_times_raises_without_polling(self):
        with self.assertRaises(ValueError):
            poll_snapshots_for_adapters([], -1)
        client = FakeSequenceSdkClient(
            raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        )
        with self.assertRaises(ValueError):
            poll_snapshots_for_adapters([VehicleSdkAdapter(client)], -1)
        self.assertEqual(client.calls, 0)
        with self.assertRaises(ValueError):
            poll_snapshots_for_adapters([VehicleSdkAdapter()], -1)

    def test_zero_times_skips_all_adapters(self):
        normal_client = FakeSequenceSdkClient(
            raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        )
        result = poll_snapshots_for_adapters(
            [VehicleSdkAdapter(normal_client), VehicleSdkAdapter()], 0
        )
        self.assertEqual(result, ((), ()))
        self.assertEqual(normal_client.calls, 0)

    def test_generator_inputs_types_and_duplicate_adapter(self):
        raws = raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        expected_client = FakeSequenceSdkClient(raws)
        expected = poll_snapshots_for_adapters(
            [VehicleSdkAdapter(expected_client)], 6
        )
        actual_client = FakeSequenceSdkClient(raws)
        actual = poll_snapshots_for_adapters(
            iter([VehicleSdkAdapter(actual_client)]), 6
        )
        self.assertEqual(actual, expected)
        self.assertEqual(actual_client.calls, 6)
        self.assertIsInstance(actual, tuple)
        for sequence in actual:
            self.assertIsInstance(sequence, tuple)
            for snapshot in sequence:
                self.assertIsInstance(snapshot, SignalSnapshot)

        shared_client = FakeSequenceSdkClient(raws)
        shared_adapter = VehicleSdkAdapter(shared_client)
        result = poll_snapshots_for_adapters(
            [shared_adapter, shared_adapter], 3
        )
        self.assertEqual(shared_client.calls, 6)
        self.assertEqual(result[0], dropoff_normal_snapshots()[:3])
        self.assertEqual(result[1], dropoff_normal_snapshots()[3:])

    def test_unconnected_positive_raises_after_prior_adapter_polled(self):
        normal_client = FakeSequenceSdkClient(
            raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        )
        with self.assertRaises(NotImplementedError):
            poll_snapshots_for_adapters(
                [VehicleSdkAdapter(normal_client), VehicleSdkAdapter()],
                2,
            )
        self.assertEqual(normal_client.calls, 2)


class PollSnapshotsOncePerAdapterTest(unittest.TestCase):
    def test_empty_input_returns_empty_tuple(self):
        self.assertEqual(poll_snapshots_once_per_adapter([]), ())
        self.assertEqual(poll_snapshots_once_per_adapter(iter([])), ())

    def test_reads_each_adapter_once_in_order_as_flat_tuple(self):
        normal_raws = raws_from_snapshots(
            scenario_snapshots("dropoff_normal")
        )
        forgotten_raws = raws_from_snapshots(
            scenario_snapshots("forgotten_rising_temp")
        )
        normal_client = FakeSdkClient(normal_raws[0])
        forgotten_client = FakeSdkClient(forgotten_raws[-1])
        result = poll_snapshots_once_per_adapter(
            [
                VehicleSdkAdapter(normal_client),
                VehicleSdkAdapter(forgotten_client),
            ]
        )
        self.assertEqual(normal_client.calls, 1)
        self.assertEqual(forgotten_client.calls, 1)
        self.assertEqual(
            result,
            (dropoff_normal_snapshots()[0], forgotten_rising_temp_snapshots()[-1]),
        )
        for snapshot in result:
            self.assertIsInstance(snapshot, SignalSnapshot)
        self.assertEqual(result[1].cabin_temp_c, 35.5)
        self.assertEqual(result[1].lock, LockState.LOCKED)
        self.assertEqual(result[1].timestamp, 420.0)

    def test_matches_heads_of_poll_snapshots_for_adapters_with_times_one(self):
        def make_clients():
            return [
                FakeSequenceSdkClient(
                    raws_from_snapshots(scenario_snapshots("dropoff_normal"))
                ),
                FakeSequenceSdkClient(
                    raws_from_snapshots(
                        scenario_snapshots("forgotten_rising_temp")
                    )
                ),
            ]

        flat_clients = make_clients()
        flat = poll_snapshots_once_per_adapter(
            [VehicleSdkAdapter(client) for client in flat_clients]
        )
        slice_clients = make_clients()
        slices = poll_snapshots_for_adapters(
            [VehicleSdkAdapter(client) for client in slice_clients], 1
        )
        self.assertEqual(flat, tuple(sequence[0] for sequence in slices))
        self.assertEqual([client.calls for client in flat_clients], [1, 1])
        self.assertEqual([client.calls for client in slice_clients], [1, 1])

    def test_generator_input_and_result_types(self):
        raws = raws_from_snapshots(scenario_snapshots("dropoff_normal"))

        def make_adapters():
            return [
                VehicleSdkAdapter(FakeSequenceSdkClient(raws)),
                VehicleSdkAdapter(FakeSdkClient(FULL_RAW)),
            ]

        expected = poll_snapshots_once_per_adapter(make_adapters())
        actual = poll_snapshots_once_per_adapter(iter(make_adapters()))
        self.assertEqual(actual, expected)
        self.assertIsInstance(actual, tuple)
        for snapshot in actual:
            self.assertIsInstance(snapshot, SignalSnapshot)

    def test_duplicate_adapter_is_polled_on_each_occurrence(self):
        raws = raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        client = FakeSequenceSdkClient(raws)
        adapter = VehicleSdkAdapter(client)
        result = poll_snapshots_once_per_adapter([adapter, adapter])
        self.assertEqual(client.calls, 2)
        self.assertEqual(result, dropoff_normal_snapshots()[:2])
        self.assertNotEqual(result[0], result[1])

    def test_unconnected_adapter_raises_after_prior_adapter_polled(self):
        client = FakeSequenceSdkClient(
            raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        )
        with self.assertRaises(NotImplementedError):
            poll_snapshots_once_per_adapter(
                [VehicleSdkAdapter(client), VehicleSdkAdapter()]
            )
        self.assertEqual(client.calls, 1)
        with self.assertRaises(NotImplementedError):
            poll_snapshots_once_per_adapter([VehicleSdkAdapter()])


class PollRepeatedlyForAdaptersIntoSessionsTest(unittest.TestCase):
    def test_empty_inputs_give_empty_tuple_and_empty_negative_raises(self):
        self.assertEqual(
            poll_repeatedly_for_adapters_into_sessions([], [], 6), ()
        )
        self.assertEqual(
            poll_repeatedly_for_adapters_into_sessions([], [], 0), ()
        )
        with self.assertRaises(ValueError):
            poll_repeatedly_for_adapters_into_sessions([], [], -1)

    def test_uniform_times_applies_each_adapter_slice(self):
        normal_client = FakeSequenceSdkClient(
            raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        )
        forgotten_client = FakeSequenceSdkClient(
            raws_from_snapshots(
                scenario_snapshots("forgotten_rising_temp")
            )
        )
        adapters = [
            VehicleSdkAdapter(normal_client),
            VehicleSdkAdapter(forgotten_client),
        ]
        sessions = [CareSession(), CareSession()]
        states = poll_repeatedly_for_adapters_into_sessions(
            adapters, sessions, 6
        )
        self.assertIsInstance(states, tuple)
        self.assertEqual(
            states, (SessionState.COMPLETED, SessionState.EXCEPTION)
        )
        self.assertEqual(states, (sessions[0].state, sessions[1].state))
        self.assertEqual(normal_client.calls, 6)
        self.assertEqual(forgotten_client.calls, 6)
        self.assertEqual(len(sessions[0].history), 6)
        self.assertFalse(sessions[0].passenger_present)
        self.assertEqual(len(sessions[1].history), 5)
        self.assertTrue(sessions[1].passenger_present)
        self.assertEqual(sessions[1].current_snapshot.cabin_temp_c, 28.0)
        self.assertEqual(sessions[1].current_snapshot.timestamp, 300.0)

    def test_zero_times_skips_all_adapters_without_client(self):
        client = FakeSequenceSdkClient(
            raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        )
        boarding = CareSession()
        boarding.apply_snapshot(
            snapshot_from_raw({"rear_door_open": True})
        )
        sessions = [boarding, CareSession()]
        states = poll_repeatedly_for_adapters_into_sessions(
            [VehicleSdkAdapter(), VehicleSdkAdapter(client)],
            sessions,
            0,
        )
        self.assertEqual(
            states, (SessionState.BOARDING, SessionState.IDLE)
        )
        self.assertEqual(client.calls, 0)
        self.assertEqual(len(sessions[0].history), 1)
        self.assertEqual(sessions[1].history, [])

    def test_length_mismatch_raises_without_polling_or_changing(self):
        for counts in ((1, 2), (2, 1)):
            with self.subTest(counts=counts):
                clients = [
                    FakeSequenceSdkClient(
                        raws_from_snapshots(
                            scenario_snapshots("dropoff_normal")
                        )
                    )
                    for _ in range(counts[0])
                ]
                adapters = [VehicleSdkAdapter(c) for c in clients]
                sessions = [CareSession() for _ in range(counts[1])]
                with self.assertRaises(ValueError):
                    poll_repeatedly_for_adapters_into_sessions(
                        adapters, sessions, 6
                    )
                for client in clients:
                    self.assertEqual(client.calls, 0)
                for session in sessions:
                    self.assertEqual(session.state, SessionState.IDLE)
                    self.assertEqual(session.history, [])

    def test_negative_times_raises_without_polling_or_changing(self):
        clients = [
            FakeSequenceSdkClient(
                raws_from_snapshots(scenario_snapshots("dropoff_normal"))
            )
            for _ in range(2)
        ]
        adapters = [VehicleSdkAdapter(c) for c in clients]
        sessions = [CareSession(), CareSession()]
        with self.assertRaises(ValueError):
            poll_repeatedly_for_adapters_into_sessions(
                adapters, sessions, -1
            )
        for client in clients:
            self.assertEqual(client.calls, 0)
        for session in sessions:
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])
        with self.assertRaises(ValueError):
            poll_repeatedly_for_adapters_into_sessions(
                [VehicleSdkAdapter(), VehicleSdkAdapter()],
                [CareSession(), CareSession()],
                -1,
            )

    def test_generator_duplicate_paired_equivalence_and_atomicity(self):
        def make_adapters():
            return [
                VehicleSdkAdapter(
                    FakeSequenceSdkClient(
                        raws_from_snapshots(
                            scenario_snapshots("dropoff_normal")
                        )
                    )
                ),
                VehicleSdkAdapter(
                    FakeSequenceSdkClient(
                        raws_from_snapshots(
                            scenario_snapshots("forgotten_rising_temp")
                        )
                    )
                ),
            ]

        uniform_sessions = [CareSession(), CareSession()]
        uniform_states = poll_repeatedly_for_adapters_into_sessions(
            iter(make_adapters()), iter(uniform_sessions), 6
        )
        paired_sessions = [CareSession(), CareSession()]
        paired_states = poll_repeatedly_paired_into_sessions(
            make_adapters(), paired_sessions, [6, 6]
        )
        self.assertEqual(uniform_states, paired_states)
        self.assertEqual(
            [s.history for s in uniform_sessions],
            [s.history for s in paired_sessions],
        )

        shared_client = FakeSequenceSdkClient(
            raws_from_snapshots(scenario_snapshots("dropoff_normal"))
            + raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        )
        shared_adapter = VehicleSdkAdapter(shared_client)
        dup_sessions = [CareSession(), CareSession()]
        dup_states = poll_repeatedly_for_adapters_into_sessions(
            [shared_adapter, shared_adapter], dup_sessions, 6
        )
        self.assertEqual(
            dup_states, (SessionState.COMPLETED, SessionState.COMPLETED)
        )
        self.assertEqual(shared_client.calls, 12)

        client = FakeSequenceSdkClient(
            raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        )
        sessions = [CareSession(), CareSession()]
        with self.assertRaises(NotImplementedError):
            poll_repeatedly_for_adapters_into_sessions(
                [VehicleSdkAdapter(client), VehicleSdkAdapter()],
                sessions,
                2,
            )
        self.assertEqual(client.calls, 2)
        for session in sessions:
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])


class PollOncePerAdapterIntoSessionTest(unittest.TestCase):
    def _adapters_for(self, scenario_name):
        raws = raws_from_snapshots(scenario_snapshots(scenario_name))
        clients = [FakeSdkClient(raw) for raw in raws]
        adapters = [VehicleSdkAdapter(client) for client in clients]
        return adapters, clients

    def test_empty_adapters_returns_idle_without_poll(self):
        session = CareSession()
        result = poll_once_per_adapter_into_session([], session)
        self.assertEqual(result, SessionState.IDLE)
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])

    def test_dropoff_sequence_across_adapters_completes(self):
        adapters, clients = self._adapters_for("dropoff_normal")
        session = CareSession()
        result = poll_once_per_adapter_into_session(adapters, session)
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(result, session.state)
        self.assertEqual(len(session.history), 6)
        for client in clients:
            self.assertEqual(client.calls, 1)

    def test_forgotten_sequence_across_adapters_enters_exception(self):
        adapters, clients = self._adapters_for("forgotten_rising_temp")
        session = CareSession()
        result = poll_once_per_adapter_into_session(adapters, session)
        self.assertEqual(result, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)
        for client in clients:
            self.assertEqual(client.calls, 1)

    def test_unconnected_second_adapter_leaves_session_unchanged(self):
        adapters, clients = self._adapters_for("dropoff_normal")
        session = CareSession()
        with self.assertRaises(NotImplementedError):
            poll_once_per_adapter_into_session(
                [adapters[0], VehicleSdkAdapter()], session
            )
        self.assertEqual(clients[0].calls, 1)
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])

    def test_generator_adapters_match_list_input(self):
        adapters_list, _ = self._adapters_for("dropoff_normal")
        list_session = CareSession()
        list_result = poll_once_per_adapter_into_session(
            adapters_list, list_session
        )
        adapters_gen, _ = self._adapters_for("dropoff_normal")
        gen_session = CareSession()
        gen_result = poll_once_per_adapter_into_session(
            iter(adapters_gen), gen_session
        )
        self.assertEqual(gen_result, list_result)
        self.assertEqual(
            [t.reason for t in gen_session.history],
            [t.reason for t in list_session.history],
        )

    def test_duplicate_adapter_polls_each_time(self):
        raw = raws_from_snapshots(scenario_snapshots("dropoff_normal"))[0]
        client = FakeSdkClient(raw)
        adapter = VehicleSdkAdapter(client)
        session = CareSession()
        result = poll_once_per_adapter_into_session(
            [adapter, adapter], session
        )
        self.assertEqual(client.calls, 2)
        self.assertIsInstance(result, SessionState)
        self.assertEqual(result, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)


class PollOncePerAdapterIntoSessionsTest(unittest.TestCase):
    def _adapters_for(self, scenario_name):
        raws = raws_from_snapshots(scenario_snapshots(scenario_name))
        clients = [FakeSdkClient(raw) for raw in raws]
        adapters = [VehicleSdkAdapter(client) for client in clients]
        return adapters, clients

    def test_empty_sessions_polls_nothing_and_returns_empty_tuple(self):
        adapters, clients = self._adapters_for("dropoff_normal")
        result = poll_once_per_adapter_into_sessions(adapters, [])
        self.assertEqual(result, ())
        for client in clients:
            self.assertEqual(client.calls, 0)

    def test_empty_adapters_returns_current_states_unchanged(self):
        sessions = [CareSession(), CareSession()]
        result = poll_once_per_adapter_into_sessions([], sessions)
        self.assertEqual(result, (SessionState.IDLE, SessionState.IDLE))
        for session in sessions:
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])

    def test_dropoff_sequence_broadcasts_to_all_sessions(self):
        adapters, clients = self._adapters_for("dropoff_normal")
        sessions = [CareSession(), CareSession()]
        result = poll_once_per_adapter_into_sessions(adapters, sessions)
        self.assertEqual(
            result, (SessionState.COMPLETED, SessionState.COMPLETED)
        )
        for session in sessions:
            self.assertEqual(session.state, SessionState.COMPLETED)
            self.assertEqual(len(session.history), 6)
        for client in clients:
            self.assertEqual(client.calls, 1)

    def test_forgotten_sequence_broadcasts_exception_to_all_sessions(self):
        adapters, clients = self._adapters_for("forgotten_rising_temp")
        sessions = [CareSession(), CareSession()]
        result = poll_once_per_adapter_into_sessions(adapters, sessions)
        self.assertEqual(
            result, (SessionState.EXCEPTION, SessionState.EXCEPTION)
        )
        for session in sessions:
            self.assertTrue(session.passenger_present)
            self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)
            self.assertEqual(len(session.history), 5)
        for client in clients:
            self.assertEqual(client.calls, 1)

    def test_unconnected_second_adapter_leaves_all_sessions_unchanged(self):
        adapters, clients = self._adapters_for("dropoff_normal")
        sessions = [CareSession(), CareSession()]
        with self.assertRaises(NotImplementedError):
            poll_once_per_adapter_into_sessions(
                [adapters[0], VehicleSdkAdapter()], sessions
            )
        self.assertEqual(clients[0].calls, 1)
        for session in sessions:
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])

    def test_generator_inputs_match_list_input(self):
        adapters_list, _ = self._adapters_for("dropoff_normal")
        list_sessions = [CareSession(), CareSession()]
        list_result = poll_once_per_adapter_into_sessions(
            adapters_list, list_sessions
        )
        adapters_gen, _ = self._adapters_for("dropoff_normal")
        gen_sessions = [CareSession(), CareSession()]
        gen_result = poll_once_per_adapter_into_sessions(
            iter(adapters_gen), iter(gen_sessions)
        )
        self.assertIsInstance(gen_result, tuple)
        for state in gen_result:
            self.assertIsInstance(state, SessionState)
        self.assertEqual(gen_result, list_result)
        for gen_session, list_session in zip(gen_sessions, list_sessions):
            self.assertEqual(
                [t.reason for t in gen_session.history],
                [t.reason for t in list_session.history],
            )


class PollRepeatedlyForAdaptersIntoSessionTest(unittest.TestCase):
    def _split_adapters(self, scenario_name, chunk_sizes):
        raws = raws_from_snapshots(scenario_snapshots(scenario_name))
        clients = []
        adapters = []
        offset = 0
        for size in chunk_sizes:
            client = FakeSequenceSdkClient(list(raws[offset:offset + size]))
            clients.append(client)
            adapters.append(VehicleSdkAdapter(client))
            offset += size
        return adapters, clients

    def test_empty_adapters_returns_current_state_unchanged(self):
        session = CareSession()
        result = poll_repeatedly_for_adapters_into_session([], session, 3)
        self.assertEqual(result, SessionState.IDLE)
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])

    def test_zero_times_never_polls_even_without_client(self):
        session = CareSession()
        result = poll_repeatedly_for_adapters_into_session(
            [VehicleSdkAdapter()], session, 0
        )
        self.assertEqual(result, SessionState.IDLE)
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])

    def test_negative_times_raises_before_any_poll(self):
        for adapters in ([], [VehicleSdkAdapter()]):
            session = CareSession()
            with self.assertRaises(ValueError):
                poll_repeatedly_for_adapters_into_session(
                    adapters, session, -1
                )
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])

    def test_dropoff_split_across_two_adapters_completes(self):
        adapters, clients = self._split_adapters("dropoff_normal", [3, 3])
        session = CareSession()
        result = poll_repeatedly_for_adapters_into_session(
            adapters, session, 3
        )
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        for client in clients:
            self.assertEqual(client.calls, 3)

    def test_forgotten_split_across_two_adapters_exceptions(self):
        adapters, clients = self._split_adapters(
            "forgotten_rising_temp", [4, 4]
        )
        session = CareSession()
        result = poll_repeatedly_for_adapters_into_session(
            adapters, session, 4
        )
        self.assertEqual(result, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)
        for client in clients:
            self.assertEqual(client.calls, 4)

    def test_unconnected_second_adapter_leaves_session_unchanged(self):
        adapters, clients = self._split_adapters("dropoff_normal", [3, 3])
        session = CareSession()
        with self.assertRaises(NotImplementedError):
            poll_repeatedly_for_adapters_into_session(
                [adapters[0], VehicleSdkAdapter()], session, 3
            )
        self.assertEqual(clients[0].calls, 3)
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])


if __name__ == "__main__":
    unittest.main()

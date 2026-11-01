"""시뮬레이션 신호 어댑터의 단위 테스트."""

import unittest

from engine import (
    CareSession,
    DoorState,
    LockState,
    SessionState,
    SignalSnapshot,
)
from engine.adapters import (
    SCENARIO_NAMES,
    dropoff_normal_snapshots,
    forgotten_rising_temp_snapshots,
    pet_dropoff_snapshots,
    replay,
    replay_scenario,
    replay_scenarios,
    replay_scenarios_by_name,
    replay_scenarios_by_name_and_start,
    replay_scenarios_by_start,
    replay_snapshot_for_sessions,
    replay_snapshots_for_sessions,
    replay_snapshot_sequence_for_sessions,
    replay_snapshot_sequences_for_sessions,
    scenario_snapshots,
    snapshots_for_scenario_by_starts,
    snapshots_for_scenarios,
    snapshots_for_scenarios_by_start,
)


class SimulatorTest(unittest.TestCase):
    def test_dropoff_normal_replays_to_completed(self):
        session = CareSession()

        state = replay(session, dropoff_normal_snapshots())

        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(session.history[-1].to_state, SessionState.COMPLETED)

    def test_forgotten_rising_temp_replays_to_exception(self):
        session = CareSession()
        snapshots = forgotten_rising_temp_snapshots()

        state = replay(session, snapshots)

        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(snapshots[-1].cabin_temp_c, 35.5)
        self.assertEqual(
            [snap.cabin_temp_c for snap in snapshots[-3:]],
            [28.0, 32.0, 35.5],
        )

    def test_pet_dropoff_replays_to_completed(self):
        session = CareSession()
        snapshots = pet_dropoff_snapshots()

        state = replay(session, snapshots)

        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertTrue(snapshots[2].hvac_on)

    def test_scenario_snapshots_matches_direct_functions(self):
        self.assertEqual(
            scenario_snapshots("dropoff_normal"),
            dropoff_normal_snapshots(),
        )
        self.assertEqual(
            scenario_snapshots("forgotten_rising_temp"),
            forgotten_rising_temp_snapshots(),
        )
        self.assertEqual(
            scenario_snapshots("pet_dropoff"),
            pet_dropoff_snapshots(),
        )
        self.assertEqual(
            SCENARIO_NAMES,
            ("dropoff_normal", "forgotten_rising_temp", "pet_dropoff"),
        )

    def test_scenario_snapshots_unknown_name_raises(self):
        with self.assertRaises(ValueError):
            scenario_snapshots("unknown_scenario")

    def test_timestamps_increase_monotonically(self):
        for snapshots in (
            dropoff_normal_snapshots(),
            forgotten_rising_temp_snapshots(),
        ):
            timestamps = [snap.timestamp for snap in snapshots]
            self.assertEqual(
                timestamps,
                [60.0 * index for index in range(len(timestamps))],
            )
            self.assertTrue(
                all(
                    later > earlier
                    for earlier, later in zip(timestamps, timestamps[1:])
                )
            )

    def test_dropoff_normal_is_deterministic(self):
        self.assertEqual(
            dropoff_normal_snapshots(), dropoff_normal_snapshots()
        )

    def test_start_shifts_timestamps(self):
        snapshots = dropoff_normal_snapshots(start=1000.0)

        self.assertEqual(snapshots[0].timestamp, 1000.0)
        self.assertEqual(snapshots[-1].timestamp, 1300.0)

    def test_pet_dropoff_timestamps_increase_by_sixty_from_start(self):
        snapshots = pet_dropoff_snapshots(start=1000.0)

        timestamps = [snap.timestamp for snap in snapshots]
        self.assertEqual(
            timestamps,
            [1000.0 + 60.0 * index for index in range(len(timestamps))],
        )
        self.assertEqual(timestamps[0], 1000.0)
        self.assertEqual(timestamps[-1], 1300.0)


class ReplayScenarioTest(unittest.TestCase):
    def test_dropoff_normal_replays_to_completed(self):
        session = CareSession()

        state = replay_scenario(session, "dropoff_normal")

        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(state, session.state)

    def test_forgotten_rising_temp_replays_to_exception(self):
        session = CareSession()

        state = replay_scenario(session, "forgotten_rising_temp")

        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)

    def test_pet_dropoff_start_shifts_first_transition(self):
        session = CareSession()

        state = replay_scenario(session, "pet_dropoff", start=1000.0)

        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(session.history[0].timestamp, 1000.0)

    def test_unknown_name_raises_and_leaves_session_untouched(self):
        session = CareSession()

        with self.assertRaises(ValueError):
            replay_scenario(session, "unknown_scenario")

        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])


class SnapshotsForScenariosTest(unittest.TestCase):
    def test_empty_input_returns_empty_tuple(self):
        self.assertEqual(snapshots_for_scenarios([]), ())

    def test_preserves_order_and_matches_individual_calls(self):
        result = snapshots_for_scenarios(SCENARIO_NAMES)

        self.assertEqual(len(result), len(SCENARIO_NAMES))
        for name, snapshots in zip(SCENARIO_NAMES, result):
            self.assertEqual(snapshots, scenario_snapshots(name))

    def test_start_propagates_to_every_scenario(self):
        result = snapshots_for_scenarios(SCENARIO_NAMES, start=1000.0)

        for snapshots in result:
            self.assertEqual(snapshots[0].timestamp, 1000.0)

    def test_generator_input_matches_list_input(self):
        self.assertEqual(
            snapshots_for_scenarios(name for name in SCENARIO_NAMES),
            snapshots_for_scenarios(list(SCENARIO_NAMES)),
        )

    def test_duplicate_names_are_kept(self):
        result = snapshots_for_scenarios(
            ["dropoff_normal", "dropoff_normal"]
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], result[1])

    def test_unknown_name_raises(self):
        with self.assertRaises(ValueError):
            snapshots_for_scenarios(["dropoff_normal", "unknown_scenario"])


class SnapshotsForScenariosByStartTest(unittest.TestCase):
    def test_empty_input_returns_empty_tuple(self):
        self.assertEqual(snapshots_for_scenarios_by_start([], []), ())

    def test_paired_starts_match_individual_calls(self):
        starts = (0.0, 1000.0, 2000.0)

        result = snapshots_for_scenarios_by_start(SCENARIO_NAMES, starts)

        self.assertEqual(len(result), len(SCENARIO_NAMES))
        for name, start, snapshots in zip(SCENARIO_NAMES, starts, result):
            self.assertEqual(snapshots, scenario_snapshots(name, start))
            self.assertEqual(snapshots[0].timestamp, start)

    def test_length_mismatch_raises_both_ways(self):
        with self.assertRaises(ValueError):
            snapshots_for_scenarios_by_start(SCENARIO_NAMES, [0.0, 1000.0])
        with self.assertRaises(ValueError):
            snapshots_for_scenarios_by_start(["dropoff_normal"], [0.0, 1000.0])

    def test_unknown_name_raises(self):
        with self.assertRaises(ValueError):
            snapshots_for_scenarios_by_start(
                ["dropoff_normal", "unknown_scenario"], [0.0, 1000.0]
            )

    def test_generator_input_and_duplicates(self):
        result = snapshots_for_scenarios_by_start(
            (name for name in ["pet_dropoff", "pet_dropoff"]),
            (start for start in [500.0, 500.0]),
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], result[1])
        self.assertEqual(result[0][0].timestamp, 500.0)

    def test_returns_tuple_of_tuples(self):
        result = snapshots_for_scenarios_by_start(SCENARIO_NAMES, [0.0, 1.0, 2.0])

        self.assertIsInstance(result, tuple)
        for snapshots in result:
            self.assertIsInstance(snapshots, tuple)


class SnapshotsForScenarioByStartsTest(unittest.TestCase):
    def test_empty_starts_returns_empty_tuple(self):
        self.assertEqual(snapshots_for_scenario_by_starts("dropoff_normal", []), ())

    def test_each_start_matches_individual_call_for_all_scenarios(self):
        starts = (0.0, 1000.0, 2000.0)

        for name in SCENARIO_NAMES:
            result = snapshots_for_scenario_by_starts(name, starts)

            self.assertEqual(len(result), len(starts))
            for start, snapshots in zip(starts, result):
                self.assertEqual(snapshots, scenario_snapshots(name, start))
                self.assertEqual(snapshots[0].timestamp, start)

    def test_duplicate_starts_are_kept(self):
        result = snapshots_for_scenario_by_starts(
            "pet_dropoff", [500.0, 500.0]
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], result[1])
        self.assertEqual(result[0][0].timestamp, 500.0)

    def test_generator_input_matches_list_input(self):
        result = snapshots_for_scenario_by_starts(
            "forgotten_rising_temp", (start for start in [100.0, 200.0])
        )

        self.assertEqual(
            result,
            snapshots_for_scenario_by_starts(
                "forgotten_rising_temp", [100.0, 200.0]
            ),
        )

    def test_unknown_name_raises_only_when_starts_not_empty(self):
        with self.assertRaises(ValueError):
            snapshots_for_scenario_by_starts("unknown_scenario", [0.0])

        self.assertEqual(
            snapshots_for_scenario_by_starts("unknown_scenario", []), ()
        )

    def test_returns_tuple_of_tuples(self):
        result = snapshots_for_scenario_by_starts(
            "dropoff_normal", [0.0, 1.0, 2.0]
        )

        self.assertIsInstance(result, tuple)
        for snapshots in result:
            self.assertIsInstance(snapshots, tuple)


class ReplayScenariosTest(unittest.TestCase):
    def test_empty_input_returns_empty_tuple(self):
        self.assertEqual(replay_scenarios([], "dropoff_normal"), ())

    def test_dropoff_normal_replays_to_completed_for_each_session(self):
        sessions = [CareSession(), CareSession()]

        result = replay_scenarios(sessions, "dropoff_normal")

        self.assertEqual(
            result, (SessionState.COMPLETED, SessionState.COMPLETED)
        )
        for state, session in zip(result, sessions):
            self.assertEqual(state, session.state)

    def test_forgotten_rising_temp_replays_to_exception(self):
        session = CareSession()

        result = replay_scenarios([session], "forgotten_rising_temp")

        self.assertEqual(result, (SessionState.EXCEPTION,))
        self.assertTrue(session.passenger_present)

    def test_pet_dropoff_start_shifts_first_transition(self):
        session = CareSession()

        result = replay_scenarios([session], "pet_dropoff", start=1000.0)

        self.assertEqual(result, (SessionState.COMPLETED,))
        self.assertEqual(session.history[0].timestamp, 1000.0)

    def test_generator_input_matches_list_input(self):
        list_sessions = [CareSession(), CareSession()]
        generator_sessions = [CareSession(), CareSession()]

        list_result = replay_scenarios(list_sessions, "dropoff_normal")
        generator_result = replay_scenarios(
            (session for session in generator_sessions), "dropoff_normal"
        )

        self.assertEqual(generator_result, list_result)
        self.assertEqual(
            [session.state for session in generator_sessions],
            [session.state for session in list_sessions],
        )

    def test_unknown_name_raises_and_leaves_sessions_untouched(self):
        sessions = [CareSession(), CareSession()]

        with self.assertRaises(ValueError):
            replay_scenarios(sessions, "unknown_scenario")

        for session in sessions:
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])


class ReplayScenariosByStartTest(unittest.TestCase):
    def test_empty_input_returns_empty_tuple(self):
        self.assertEqual(
            replay_scenarios_by_start([], "dropoff_normal", []), ()
        )

    def test_same_scenario_with_distinct_starts_completes(self):
        sessions = [CareSession(), CareSession()]

        result = replay_scenarios_by_start(
            sessions, "dropoff_normal", [0.0, 1000.0]
        )

        self.assertEqual(
            result, (SessionState.COMPLETED, SessionState.COMPLETED)
        )
        for state, session in zip(result, sessions):
            self.assertEqual(state, session.state)
        self.assertEqual(sessions[0].history[0].timestamp, 0.0)
        self.assertEqual(sessions[1].history[0].timestamp, 1000.0)
        self.assertEqual(sessions[1].history[-1].timestamp, 1300.0)

    def test_forgotten_rising_temp_with_distinct_starts(self):
        sessions = [CareSession(), CareSession()]

        result = replay_scenarios_by_start(
            sessions, "forgotten_rising_temp", [0.0, 500.0]
        )

        self.assertEqual(
            result, (SessionState.EXCEPTION, SessionState.EXCEPTION)
        )
        for session in sessions:
            self.assertTrue(session.passenger_present)
            self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)
        self.assertEqual(sessions[1].history[0].timestamp, 500.0)

    def test_length_mismatch_raises_and_leaves_sessions_untouched(self):
        sessions = [CareSession(), CareSession()]

        with self.assertRaises(ValueError):
            replay_scenarios_by_start(sessions, "dropoff_normal", [0.0])
        with self.assertRaises(ValueError):
            replay_scenarios_by_start(
                sessions[:1], "dropoff_normal", [0.0, 1000.0]
            )

        for session in sessions:
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])

    def test_unknown_name_raises_and_leaves_all_sessions_untouched(self):
        sessions = [CareSession(), CareSession()]

        with self.assertRaises(ValueError):
            replay_scenarios_by_start(
                sessions, "unknown_scenario", [0.0, 1000.0]
            )

        for session in sessions:
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])

    def test_generator_inputs_match_list_inputs_and_keep_duplicates(self):
        list_sessions = [CareSession(), CareSession(), CareSession()]
        generator_sessions = [CareSession(), CareSession(), CareSession()]
        starts = [1000.0, 1000.0, 2000.0]

        list_result = replay_scenarios_by_start(
            list_sessions, "pet_dropoff", starts
        )
        generator_result = replay_scenarios_by_start(
            (session for session in generator_sessions),
            "pet_dropoff",
            (start for start in starts),
        )

        self.assertEqual(generator_result, list_result)
        self.assertEqual(
            generator_result,
            (
                SessionState.COMPLETED,
                SessionState.COMPLETED,
                SessionState.COMPLETED,
            ),
        )
        self.assertIsInstance(generator_result, tuple)
        self.assertEqual(
            [session.history[0].timestamp for session in generator_sessions],
            [1000.0, 1000.0, 2000.0],
        )
        self.assertEqual(
            [session.state for session in generator_sessions],
            [session.state for session in list_sessions],
        )


class ReplayScenariosByNameTest(unittest.TestCase):
    def test_empty_input_returns_empty_tuple(self):
        self.assertEqual(replay_scenarios_by_name([], []), ())

    def test_pairs_distinct_scenarios_with_sessions(self):
        sessions = [CareSession(), CareSession()]

        result = replay_scenarios_by_name(
            sessions, ["dropoff_normal", "forgotten_rising_temp"]
        )

        self.assertEqual(
            result, (SessionState.COMPLETED, SessionState.EXCEPTION)
        )
        for state, session in zip(result, sessions):
            self.assertEqual(state, session.state)
        self.assertTrue(sessions[1].passenger_present)
        self.assertEqual(sessions[1].current_snapshot.cabin_temp_c, 35.5)

    def test_all_scenarios_with_start_propagates(self):
        sessions = [CareSession(), CareSession(), CareSession()]

        result = replay_scenarios_by_name(
            sessions, list(SCENARIO_NAMES), start=1000.0
        )

        self.assertEqual(
            result,
            (
                SessionState.COMPLETED,
                SessionState.EXCEPTION,
                SessionState.COMPLETED,
            ),
        )
        self.assertEqual(sessions[0].history[0].timestamp, 1000.0)

    def test_length_mismatch_raises_and_leaves_sessions_untouched(self):
        sessions = [CareSession(), CareSession()]

        with self.assertRaises(ValueError):
            replay_scenarios_by_name(sessions, ["dropoff_normal"])
        with self.assertRaises(ValueError):
            replay_scenarios_by_name(
                sessions[:1], ["dropoff_normal", "pet_dropoff"]
            )

        for session in sessions:
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])

    def test_unknown_name_raises_and_leaves_all_sessions_untouched(self):
        sessions = [CareSession(), CareSession()]

        with self.assertRaises(ValueError):
            replay_scenarios_by_name(
                sessions, ["dropoff_normal", "unknown_scenario"]
            )

        for session in sessions:
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])

    def test_generator_inputs_match_list_inputs(self):
        list_sessions = [CareSession(), CareSession()]
        generator_sessions = [CareSession(), CareSession()]
        names = ["dropoff_normal", "pet_dropoff"]

        list_result = replay_scenarios_by_name(list_sessions, names)
        generator_result = replay_scenarios_by_name(
            (session for session in generator_sessions),
            (name for name in names),
        )

        self.assertEqual(generator_result, list_result)
        self.assertEqual(
            [session.state for session in generator_sessions],
            [session.state for session in list_sessions],
        )


class ReplayScenariosByNameAndStartTest(unittest.TestCase):
    def test_empty_input_returns_empty_tuple(self):
        self.assertEqual(
            replay_scenarios_by_name_and_start([], [], []), ()
        )

    def test_pairs_distinct_scenarios_with_distinct_starts(self):
        sessions = [CareSession(), CareSession()]

        result = replay_scenarios_by_name_and_start(
            sessions,
            ["dropoff_normal", "forgotten_rising_temp"],
            [0.0, 1000.0],
        )

        self.assertEqual(
            result, (SessionState.COMPLETED, SessionState.EXCEPTION)
        )
        for state, session in zip(result, sessions):
            self.assertEqual(state, session.state)
        self.assertTrue(sessions[1].passenger_present)
        self.assertEqual(sessions[1].current_snapshot.cabin_temp_c, 35.5)
        self.assertEqual(sessions[0].history[0].timestamp, 0.0)
        self.assertEqual(sessions[1].history[0].timestamp, 1000.0)

    def test_all_scenarios_with_distinct_starts(self):
        sessions = [CareSession(), CareSession(), CareSession()]
        starts = (0.0, 1000.0, 2000.0)

        result = replay_scenarios_by_name_and_start(
            sessions, list(SCENARIO_NAMES), list(starts)
        )

        self.assertEqual(
            result,
            (
                SessionState.COMPLETED,
                SessionState.EXCEPTION,
                SessionState.COMPLETED,
            ),
        )
        for session, start in zip(sessions, starts):
            self.assertEqual(session.history[0].timestamp, start)

    def test_length_mismatch_raises_and_leaves_sessions_untouched(self):
        sessions = [CareSession(), CareSession()]

        with self.assertRaises(ValueError):
            replay_scenarios_by_name_and_start(
                sessions, ["dropoff_normal"], [0.0, 1000.0]
            )
        with self.assertRaises(ValueError):
            replay_scenarios_by_name_and_start(
                sessions,
                ["dropoff_normal", "pet_dropoff"],
                [0.0],
            )
        with self.assertRaises(ValueError):
            replay_scenarios_by_name_and_start(
                sessions[:1],
                ["dropoff_normal", "pet_dropoff"],
                [0.0, 1000.0],
            )

        for session in sessions:
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])

    def test_unknown_name_raises_and_leaves_all_sessions_untouched(self):
        sessions = [CareSession(), CareSession()]

        with self.assertRaises(ValueError):
            replay_scenarios_by_name_and_start(
                sessions,
                ["dropoff_normal", "unknown_scenario"],
                [0.0, 1000.0],
            )

        for session in sessions:
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])

    def test_generator_inputs_match_list_inputs_and_keep_duplicates(self):
        list_sessions = [CareSession(), CareSession()]
        generator_sessions = [CareSession(), CareSession()]
        names = ["pet_dropoff", "pet_dropoff"]
        starts = [500.0, 500.0]

        list_result = replay_scenarios_by_name_and_start(
            list_sessions, names, starts
        )
        generator_result = replay_scenarios_by_name_and_start(
            (session for session in generator_sessions),
            (name for name in names),
            (start for start in starts),
        )

        self.assertEqual(generator_result, list_result)
        self.assertEqual(
            list_result, (SessionState.COMPLETED, SessionState.COMPLETED)
        )
        self.assertEqual(
            [session.state for session in generator_sessions],
            [session.state for session in list_sessions],
        )
        for session in generator_sessions:
            self.assertEqual(session.history[0].timestamp, 500.0)


class ReplaySnapshotSequencesForSessionsTest(unittest.TestCase):
    def test_empty_input_returns_empty_tuple(self):
        self.assertEqual(
            replay_snapshot_sequences_for_sessions([], []), ()
        )

    def test_pairs_distinct_sequences_with_sessions(self):
        sessions = [CareSession(), CareSession()]

        result = replay_snapshot_sequences_for_sessions(
            sessions,
            [
                dropoff_normal_snapshots(),
                forgotten_rising_temp_snapshots(),
            ],
        )

        self.assertEqual(
            result, (SessionState.COMPLETED, SessionState.EXCEPTION)
        )
        for state, session in zip(result, sessions):
            self.assertEqual(state, session.state)
        self.assertTrue(sessions[1].passenger_present)
        self.assertEqual(sessions[1].current_snapshot.cabin_temp_c, 35.5)

    def test_all_scenarios_paired(self):
        sessions = [CareSession(), CareSession(), CareSession()]
        sequences = [
            scenario_snapshots(name) for name in SCENARIO_NAMES
        ]

        result = replay_snapshot_sequences_for_sessions(
            sessions, sequences
        )

        self.assertEqual(
            result,
            (
                SessionState.COMPLETED,
                SessionState.EXCEPTION,
                SessionState.COMPLETED,
            ),
        )

    def test_length_mismatch_raises_and_leaves_sessions_untouched(self):
        sessions = [CareSession(), CareSession()]

        with self.assertRaises(ValueError):
            replay_snapshot_sequences_for_sessions(
                sessions, [dropoff_normal_snapshots()]
            )
        with self.assertRaises(ValueError):
            replay_snapshot_sequences_for_sessions(
                sessions[:1],
                [dropoff_normal_snapshots(), pet_dropoff_snapshots()],
            )

        for session in sessions:
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])

    def test_empty_inner_sequence_leaves_session_untouched(self):
        sessions = [CareSession(), CareSession()]

        result = replay_snapshot_sequences_for_sessions(
            sessions, [dropoff_normal_snapshots(), []]
        )

        self.assertEqual(
            result, (SessionState.COMPLETED, SessionState.IDLE)
        )
        self.assertEqual(sessions[1].history, [])

    def test_generator_inputs_match_list_inputs(self):
        list_sessions = [CareSession(), CareSession()]
        generator_sessions = [CareSession(), CareSession()]
        sequences = [
            dropoff_normal_snapshots(),
            pet_dropoff_snapshots(),
        ]

        list_result = replay_snapshot_sequences_for_sessions(
            list_sessions, sequences
        )
        generator_result = replay_snapshot_sequences_for_sessions(
            (session for session in generator_sessions),
            (tuple(snapshot for snapshot in seq) for seq in sequences),
        )

        self.assertEqual(generator_result, list_result)
        self.assertEqual(
            [session.state for session in generator_sessions],
            [session.state for session in list_sessions],
        )


class ReplaySnapshotSequenceForSessionsTest(unittest.TestCase):
    def test_empty_sessions_returns_empty_tuple(self):
        self.assertEqual(
            replay_snapshot_sequence_for_sessions(
                [], dropoff_normal_snapshots()
            ),
            (),
        )

    def test_empty_snapshots_leave_sessions_untouched(self):
        sessions = [CareSession(), CareSession()]

        result = replay_snapshot_sequence_for_sessions(sessions, [])

        self.assertEqual(
            result, (SessionState.IDLE, SessionState.IDLE)
        )
        for session in sessions:
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])

    def test_same_sequence_applied_to_all_sessions_completed(self):
        sessions = [CareSession(), CareSession()]

        result = replay_snapshot_sequence_for_sessions(
            sessions, dropoff_normal_snapshots()
        )

        self.assertEqual(
            result, (SessionState.COMPLETED, SessionState.COMPLETED)
        )
        for state, session in zip(result, sessions):
            self.assertEqual(state, session.state)
            self.assertFalse(session.passenger_present)

    def test_same_sequence_applied_to_all_sessions_exception(self):
        sessions = [CareSession(), CareSession()]

        result = replay_snapshot_sequence_for_sessions(
            sessions, forgotten_rising_temp_snapshots()
        )

        self.assertEqual(
            result, (SessionState.EXCEPTION, SessionState.EXCEPTION)
        )
        for session in sessions:
            self.assertTrue(session.passenger_present)
            self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)

    def test_generator_snapshots_reused_across_sessions(self):
        sessions = [CareSession(), CareSession()]

        result = replay_snapshot_sequence_for_sessions(
            sessions,
            (snapshot for snapshot in dropoff_normal_snapshots()),
        )

        self.assertEqual(
            result, (SessionState.COMPLETED, SessionState.COMPLETED)
        )
        for session in sessions:
            self.assertEqual(len(session.history), 6)

    def test_generator_sessions_match_list_sessions(self):
        list_sessions = [CareSession(), CareSession()]
        generator_sessions = [CareSession(), CareSession()]

        list_result = replay_snapshot_sequence_for_sessions(
            list_sessions, pet_dropoff_snapshots()
        )
        generator_result = replay_snapshot_sequence_for_sessions(
            (session for session in generator_sessions),
            pet_dropoff_snapshots(),
        )

        self.assertIsInstance(generator_result, tuple)
        self.assertEqual(generator_result, list_result)
        self.assertEqual(
            [session.state for session in generator_sessions],
            [session.state for session in list_sessions],
        )


class ReplaySnapshotForSessionsTest(unittest.TestCase):
    def test_empty_sessions_returns_empty_tuple(self):
        self.assertEqual(
            replay_snapshot_for_sessions(
                [], SignalSnapshot(rear_door=DoorState.OPEN)
            ),
            (),
        )

    def test_rear_door_open_moves_both_sessions_to_boarding(self):
        sessions = [CareSession(), CareSession()]

        result = replay_snapshot_for_sessions(
            sessions, dropoff_normal_snapshots()[0]
        )

        self.assertEqual(
            result, (SessionState.BOARDING, SessionState.BOARDING)
        )
        self.assertEqual(result, (sessions[0].state, sessions[1].state))

    def test_locked_with_passenger_moves_prepared_sessions_to_exception(self):
        sessions = [CareSession(), CareSession()]
        for session in sessions:
            replay(session, dropoff_normal_snapshots()[:4])
            self.assertEqual(session.state, SessionState.ARRIVED)

        result = replay_snapshot_for_sessions(
            sessions,
            SignalSnapshot(
                rear_seat_belt_buckled=True,
                lock=LockState.LOCKED,
                cabin_temp_c=35.5,
                timestamp=240.0,
            ),
        )

        self.assertEqual(
            result, (SessionState.EXCEPTION, SessionState.EXCEPTION)
        )
        for session in sessions:
            self.assertTrue(session.passenger_present)
            self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)

    def test_same_snapshot_is_shared_by_all_sessions(self):
        sessions = [CareSession(), CareSession()]
        snapshot = SignalSnapshot(
            rear_door=DoorState.OPEN, timestamp=50.0
        )

        replay_snapshot_for_sessions(sessions, snapshot)

        for session in sessions:
            self.assertIs(session.current_snapshot, snapshot)
        self.assertIs(
            sessions[0].current_snapshot, sessions[1].current_snapshot
        )
        self.assertEqual(sessions[0].current_snapshot.timestamp, 50.0)

    def test_generator_sessions_match_list_sessions(self):
        list_sessions = [CareSession(), CareSession()]
        generator_sessions = [CareSession(), CareSession()]
        snapshot = dropoff_normal_snapshots()[0]

        list_result = replay_snapshot_for_sessions(list_sessions, snapshot)
        generator_result = replay_snapshot_for_sessions(
            (session for session in generator_sessions), snapshot
        )

        self.assertEqual(generator_result, list_result)
        self.assertEqual(
            [session.state for session in generator_sessions],
            [session.state for session in list_sessions],
        )

    def test_returns_tuple_of_session_states(self):
        sessions = [CareSession(), CareSession()]

        result = replay_snapshot_for_sessions(
            sessions, dropoff_normal_snapshots()[0]
        )

        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        for state in result:
            self.assertIsInstance(state, SessionState)


class ReplaySnapshotsForSessionsTest(unittest.TestCase):
    def test_empty_inputs_return_empty_tuple(self):
        self.assertEqual(replay_snapshots_for_sessions([], []), ())

    def test_paired_snapshots_move_each_session_differently(self):
        sessions = [CareSession(), CareSession()]

        result = replay_snapshots_for_sessions(
            sessions,
            [
                SignalSnapshot(rear_door=DoorState.OPEN, timestamp=0.0),
                SignalSnapshot(
                    rear_seat_belt_buckled=True, timestamp=10.0
                ),
            ],
        )

        self.assertEqual(
            result, (SessionState.BOARDING, SessionState.ONBOARD)
        )
        self.assertEqual(result, (sessions[0].state, sessions[1].state))
        self.assertFalse(sessions[0].passenger_present)
        self.assertTrue(sessions[1].passenger_present)

    def test_paired_snapshots_on_prepared_sessions(self):
        sessions = [CareSession(), CareSession()]
        for session in sessions:
            replay(session, dropoff_normal_snapshots()[:4])
            self.assertEqual(session.state, SessionState.ARRIVED)

        result = replay_snapshots_for_sessions(
            sessions,
            [
                SignalSnapshot(
                    rear_seat_belt_buckled=True,
                    lock=LockState.LOCKED,
                    cabin_temp_c=35.5,
                    timestamp=240.0,
                ),
                SignalSnapshot(
                    rear_door=DoorState.OPEN, timestamp=240.0
                ),
            ],
        )

        self.assertEqual(
            result, (SessionState.EXCEPTION, SessionState.ALIGHTING)
        )
        self.assertTrue(sessions[0].passenger_present)
        self.assertEqual(sessions[0].current_snapshot.cabin_temp_c, 35.5)

    def test_length_mismatch_raises_and_leaves_sessions_unchanged(self):
        sessions = [CareSession(), CareSession()]
        snapshot = SignalSnapshot(rear_door=DoorState.OPEN)

        with self.assertRaises(ValueError):
            replay_snapshots_for_sessions(sessions, [snapshot])
        with self.assertRaises(ValueError):
            replay_snapshots_for_sessions(
                sessions[:1], [snapshot, snapshot]
            )

        for session in sessions:
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])

    def test_generator_inputs_match_list_inputs(self):
        list_sessions = [CareSession(), CareSession()]
        generator_sessions = [CareSession(), CareSession()]
        snapshots = [
            SignalSnapshot(rear_door=DoorState.OPEN, timestamp=0.0),
            SignalSnapshot(rear_seat_belt_buckled=True, timestamp=10.0),
        ]

        list_result = replay_snapshots_for_sessions(
            list_sessions, snapshots
        )
        generator_result = replay_snapshots_for_sessions(
            (session for session in generator_sessions),
            (snapshot for snapshot in snapshots),
        )

        self.assertEqual(generator_result, list_result)
        self.assertEqual(
            [session.state for session in generator_sessions],
            [session.state for session in list_sessions],
        )

    def test_returns_tuple_of_session_states_matching_each_session(self):
        sessions = [CareSession(), CareSession(), CareSession()]
        snapshots = [
            SignalSnapshot(rear_door=DoorState.OPEN, timestamp=0.0),
            SignalSnapshot(rear_door=DoorState.OPEN, timestamp=0.0),
            SignalSnapshot(rear_seat_belt_buckled=True, timestamp=0.0),
        ]

        result = replay_snapshots_for_sessions(sessions, snapshots)

        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)
        for state, session in zip(result, sessions):
            self.assertIsInstance(state, SessionState)
            self.assertEqual(state, session.state)
        # 중복 스냅샷은 중복 그대로 적용된다.
        self.assertEqual(
            result,
            (
                SessionState.BOARDING,
                SessionState.BOARDING,
                SessionState.ONBOARD,
            ),
        )


if __name__ == "__main__":
    unittest.main()

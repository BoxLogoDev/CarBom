"""시뮬레이션 신호 어댑터의 경계 조건 테스트."""

import unittest

from engine import CareSession, SessionState
from engine.adapters import (
    SCENARIO_NAMES,
    dropoff_normal_snapshots,
    forgotten_rising_temp_snapshots,
    replay,
    scenario_snapshots,
)


class SimulatorBoundaryQaTest(unittest.TestCase):
    def test_empty_replay_stays_idle(self):
        for snapshots in ([], iter([])):
            with self.subTest(snapshots=type(snapshots).__name__):
                session = CareSession()

                state = replay(session, snapshots)

                self.assertEqual(state, SessionState.IDLE)
                self.assertEqual(session.state, SessionState.IDLE)
                self.assertEqual(session.history, [])
                self.assertFalse(session.passenger_present)

    def test_generator_replay_matches_tuple_replay(self):
        tuple_session = CareSession()
        generator_session = CareSession()

        tuple_state = replay(tuple_session, dropoff_normal_snapshots())
        generator_state = replay(
            generator_session,
            (snap for snap in dropoff_normal_snapshots()),
        )

        self.assertEqual(tuple_state, SessionState.COMPLETED)
        self.assertEqual(generator_state, SessionState.COMPLETED)
        self.assertEqual(generator_session.state, SessionState.COMPLETED)
        self.assertEqual(
            [
                (t.from_state, t.to_state, t.reason)
                for t in generator_session.history
            ],
            [
                (t.from_state, t.to_state, t.reason)
                for t in tuple_session.history
            ],
        )
        self.assertTrue(generator_session.history)

    def test_all_scenarios_replay_deterministically(self):
        self.assertEqual(len(SCENARIO_NAMES), 3)
        for name in SCENARIO_NAMES:
            with self.subTest(scenario=name):
                first_session = CareSession()
                second_session = CareSession()

                first_state = replay(
                    first_session, scenario_snapshots(name)
                )
                second_state = replay(
                    second_session, scenario_snapshots(name)
                )

                self.assertEqual(first_state, second_state)
                self.assertEqual(first_session.state, second_session.state)
                self.assertEqual(
                    first_session.passenger_present,
                    second_session.passenger_present,
                )
                self.assertEqual(
                    [
                        (t.from_state, t.to_state, t.reason, t.timestamp)
                        for t in first_session.history
                    ],
                    [
                        (t.from_state, t.to_state, t.reason, t.timestamp)
                        for t in second_session.history
                    ],
                )

    def test_forgotten_rising_temp_start_shifts_timestamps(self):
        snapshots = forgotten_rising_temp_snapshots(start=1000.0)

        timestamps = [snap.timestamp for snap in snapshots]
        self.assertEqual(timestamps[0], 1000.0)
        self.assertEqual(timestamps[-1], 1420.0)
        self.assertEqual(
            timestamps,
            [1000.0 + 60.0 * index for index in range(len(timestamps))],
        )
        self.assertTrue(
            all(
                later > earlier
                for earlier, later in zip(timestamps, timestamps[1:])
            )
        )
        self.assertEqual(
            snapshots[:4],
            dropoff_normal_snapshots(start=1000.0)[:4],
        )

    def test_scenario_snapshots_requires_exact_name(self):
        invalid_names = (
            "DROPOFF_NORMAL",
            " dropoff_normal",
            "dropoff_normal ",
            "",
            "FORGOTTEN_RISING_TEMP",
            " forgotten_rising_temp",
            "forgotten_rising_temp ",
            "PET_DROPOFF",
            " pet_dropoff ",
            "Dropoff_Normal",
            "dropoff-normal",
            "dropoff__normal",
        )
        for name in invalid_names:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    scenario_snapshots(name)

    def test_replay_return_matches_session_state(self):
        for name in SCENARIO_NAMES:
            with self.subTest(scenario=name):
                session = CareSession()

                state = replay(session, scenario_snapshots(name))

                self.assertEqual(state, session.state)


if __name__ == "__main__":
    unittest.main()

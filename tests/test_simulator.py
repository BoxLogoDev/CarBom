"""시뮬레이션 신호 어댑터의 단위 테스트."""

import unittest

from engine import CareSession, SessionState
from engine.adapters import (
    SCENARIO_NAMES,
    dropoff_normal_snapshots,
    forgotten_rising_temp_snapshots,
    replay,
    scenario_snapshots,
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
            SCENARIO_NAMES, ("dropoff_normal", "forgotten_rising_temp")
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


if __name__ == "__main__":
    unittest.main()

"""QA scenarios for care session reset and reuse boundaries."""

import unittest

from engine import CareSession, SessionState, SignalSnapshot
from engine.adapters.simulator import replay, replay_scenario, scenario_snapshots
from engine.report import report_for_session


class SessionResetQATest(unittest.TestCase):
    def test_reset_from_exception_clears_everything(self):
        session = CareSession()
        replay_scenario(session, "forgotten_rising_temp")
        self.assertIs(session.state, SessionState.EXCEPTION)

        result = session.reset()

        self.assertIsNone(result)
        self.assertIs(session.state, SessionState.IDLE)
        self.assertFalse(session.passenger_present)
        self.assertEqual(session.history, [])
        self.assertEqual(session.current_snapshot, SignalSnapshot())

    def test_reset_after_exception_does_not_leak_into_next_report(self):
        session = CareSession()
        replay_scenario(session, "forgotten_rising_temp")
        self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)

        session.reset()
        final_state = replay_scenario(session, "dropoff_normal")

        self.assertIs(final_state, SessionState.COMPLETED)
        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.exception_count, 0)
        self.assertIsNone(report.max_cabin_temp_c)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_reset_from_driving_allows_pet_scenario_reuse(self):
        session = CareSession()
        replay(session, scenario_snapshots("dropoff_normal")[:3])
        self.assertIs(session.state, SessionState.DRIVING)

        session.reset()

        self.assertIs(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])
        self.assertFalse(session.passenger_present)
        final_state = replay_scenario(session, "pet_dropoff")
        self.assertIs(final_state, SessionState.COMPLETED)

    def test_reset_from_completed_allows_new_exception(self):
        session = CareSession()
        replay_scenario(session, "dropoff_normal")
        self.assertIs(session.state, SessionState.COMPLETED)

        session.reset()
        final_state = replay_scenario(session, "forgotten_rising_temp")

        self.assertIs(final_state, SessionState.EXCEPTION)
        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)
        self.assertTrue(report.exception_occurred)

    def test_reset_on_idle_session_is_idempotent(self):
        session = CareSession()

        session.reset()
        session.reset()

        self.assertIs(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])
        self.assertFalse(session.passenger_present)
        self.assertEqual(session.current_snapshot, SignalSnapshot())

    def test_report_made_before_reset_is_not_changed_by_reset(self):
        session = CareSession()
        replay_scenario(session, "forgotten_rising_temp")
        report = report_for_session(session)

        session.reset()

        self.assertIs(report.final_state, SessionState.EXCEPTION)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.max_cabin_temp_c, 35.5)


if __name__ == "__main__":
    unittest.main()

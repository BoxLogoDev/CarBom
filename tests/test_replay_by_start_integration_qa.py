"""같은 시나리오·다른 시작 시각 재생(``replay_scenarios_by_start``) 통합 검증.

``replay_scenarios_by_start(sessions, name, starts)``는 이름이 하나인 같은
시나리오를 여러 세션에 세션마다 다른 시작 시각으로 짝지어 재생한다.
기존 테스트는 이 헬퍼의 단위 동작(최종 상태·길이 불일치·원자성)을
``test_simulator``에서만 다뤘고, 짝 시작시각 통합 검증
(``test_paired_start_replay_integration_qa``)은 세션마다 서로 다른
시나리오 이름을 짝지었다. 이 파일은 같은 이름을 다른 시작 시각으로
재생했을 때 절대 시각만 이동하고 전이 구조·소요 시간·안내·리포트는
시작 시각과 무관하게 불변임을, 개별 재생 경로와 이름 짝 재생 경로와의
동등성까지 포함해 검증한다.
"""

import unittest

from engine.adapters.simulator import (
    replay_scenario,
    replay_scenarios_by_name_and_start,
    replay_scenarios_by_start,
)
from engine.guidance import DestinationContext, GuidanceLevel, guidance_for_session
from engine.report import CareReportLog, report_for_session
from engine.session import CareSession, SessionState

DROPOFF_STARTS = (0.0, 1000.0, 5000.0)
DROPOFF_OFFSETS = (0.0, 60.0, 120.0, 180.0, 240.0, 300.0)
DROPOFF_REASONS = (
    "rear_door_opened",
    "passenger_onboard",
    "ignition_on",
    "ignition_off",
    "alighting_started",
    "alighting_confirmed",
)
FORGOTTEN_STARTS = (0.0, 1000.0)
FORGOTTEN_OFFSETS = (0.0, 60.0, 120.0, 180.0, 240.0)


def _history_sequence(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp) for t in session.history
    ]


def _sessions(count):
    return [CareSession() for _ in range(count)]


class ReplayByStartDropoffTest(unittest.TestCase):
    def test_final_states_transitions_and_shifted_timestamps(self):
        sessions = _sessions(len(DROPOFF_STARTS))

        states = replay_scenarios_by_start(
            sessions, "dropoff_normal", DROPOFF_STARTS
        )

        self.assertEqual(states, (SessionState.COMPLETED,) * 3)
        self.assertEqual(states, tuple(session.state for session in sessions))
        for session, start in zip(sessions, DROPOFF_STARTS):
            self.assertEqual(len(session.history), 6)
            self.assertEqual(
                tuple(t.timestamp for t in session.history),
                tuple(start + offset for offset in DROPOFF_OFFSETS),
            )
            self.assertEqual(
                tuple(t.reason for t in session.history), DROPOFF_REASONS
            )
            self.assertEqual(session.current_snapshot.timestamp, start + 300.0)

    def test_guidance_and_report_start_invariant(self):
        sessions = _sessions(len(DROPOFF_STARTS))
        replay_scenarios_by_start(sessions, "dropoff_normal", DROPOFF_STARTS)

        for session, start in zip(sessions, DROPOFF_STARTS):
            guidance = guidance_for_session(
                session, context=DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "completed")
            self.assertEqual(guidance.text, "하차 확인이 완료되었습니다.")

            report = report_for_session(session)
            self.assertTrue(report.completed)
            self.assertFalse(report.exception_occurred)
            self.assertEqual(report.exception_count, 0)
            self.assertEqual(report.transition_count, 6)
            # 소요 시간은 시작 시각이 달라도 300초로 불변하고,
            # 절대 구간만 시작 시각만큼 이동한다.
            self.assertEqual(report.duration_seconds, 300.0)
            self.assertEqual(report.started_at, start)
            self.assertEqual(report.ended_at, start + 300.0)
            self.assertIsNone(report.max_cabin_temp_c)
            self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")
            self.assertFalse(report.passenger_present)


class ReplayByStartForgottenTest(unittest.TestCase):
    def test_exception_outcomes_shift_with_start(self):
        sessions = _sessions(len(FORGOTTEN_STARTS))

        states = replay_scenarios_by_start(
            sessions, "forgotten_rising_temp", FORGOTTEN_STARTS
        )

        self.assertEqual(states, (SessionState.EXCEPTION,) * 2)
        for session, start in zip(sessions, FORGOTTEN_STARTS):
            self.assertTrue(session.passenger_present)
            self.assertEqual(len(session.history), 5)
            self.assertEqual(
                tuple(t.timestamp for t in session.history),
                tuple(start + offset for offset in FORGOTTEN_OFFSETS),
            )
            # 마지막 전이는 시작 +240초지만, 온도 상승 스냅샷은
            # 시작 +420초까지 이어져 현재 스냅샷에 남아 있다.
            self.assertEqual(session.current_snapshot.timestamp, start + 420.0)
            self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)

            guidance = guidance_for_session(
                session, context=DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.URGENT)
            self.assertIn("35.5도", guidance.text)
            self.assertIn("즉시", guidance.text)

            report = report_for_session(session)
            self.assertFalse(report.completed)
            self.assertTrue(report.exception_occurred)
            self.assertEqual(report.exception_count, 1)
            self.assertEqual(report.transition_count, 5)
            self.assertEqual(report.duration_seconds, 240.0)
            self.assertEqual(report.started_at, start)
            self.assertEqual(report.ended_at, start + 240.0)
            self.assertEqual(report.max_cabin_temp_c, 35.5)
            self.assertEqual(report.summary, "예외 발생 · 하차 미확인")


class ReplayByStartPathEquivalenceTest(unittest.TestCase):
    def test_matches_individual_replay_scenario(self):
        for name, starts in (
            ("dropoff_normal", (0.0, 777.0)),
            ("forgotten_rising_temp", (0.0, 777.0)),
            ("pet_dropoff", (100.0, 200.0)),
        ):
            with self.subTest(scenario=name):
                by_start_sessions = _sessions(len(starts))
                replay_scenarios_by_start(by_start_sessions, name, starts)

                for expected_session, start in zip(by_start_sessions, starts):
                    single = CareSession()
                    replay_scenario(single, name, start=start)
                    self.assertEqual(
                        _history_sequence(single),
                        _history_sequence(expected_session),
                    )
                    self.assertEqual(
                        single.current_snapshot,
                        expected_session.current_snapshot,
                    )
                    self.assertEqual(
                        single.passenger_present,
                        expected_session.passenger_present,
                    )

    def test_matches_by_name_and_start_with_repeated_name(self):
        starts = (0.0, 1000.0, 2000.0)
        by_start_sessions = _sessions(len(starts))
        by_name_sessions = _sessions(len(starts))

        by_start_states = replay_scenarios_by_start(
            by_start_sessions, "dropoff_normal", starts
        )
        by_name_states = replay_scenarios_by_name_and_start(
            by_name_sessions, ("dropoff_normal",) * len(starts), starts
        )

        self.assertEqual(by_start_states, by_name_states)
        for by_start_session, by_name_session in zip(
            by_start_sessions, by_name_sessions
        ):
            self.assertEqual(
                _history_sequence(by_start_session),
                _history_sequence(by_name_session),
            )
            self.assertEqual(
                report_for_session(by_start_session).duration_seconds,
                report_for_session(by_name_session).duration_seconds,
            )


class ReplayByStartReportLogTest(unittest.TestCase):
    def test_report_log_aggregation_is_start_invariant(self):
        sessions = _sessions(len(DROPOFF_STARTS))
        replay_scenarios_by_start(sessions, "dropoff_normal", DROPOFF_STARTS)
        log = CareReportLog()

        reports = log.add_sessions(sessions)

        self.assertEqual(len(reports), 3)
        self.assertEqual(
            tuple(report.duration_seconds for report in reports),
            (300.0, 300.0, 300.0),
        )
        self.assertEqual(len(log), 3)
        self.assertEqual(log.completed_count, 3)
        self.assertEqual(log.sessions_with_exception, 0)
        self.assertEqual(log.total_exception_count, 0)
        self.assertIsNone(log.max_cabin_temp_c)
        self.assertEqual(log.average_duration_seconds, 300.0)


if __name__ == "__main__":
    unittest.main()

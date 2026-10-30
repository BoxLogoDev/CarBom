"""짝 이름+짝 시작시각 재생(``replay_scenarios_by_name_and_start``) 통합 검증.

``replay_scenarios_by_name_and_start(sessions, names, starts)``는 세션마다
다른 시나리오를 세션마다 다른 시작 시각으로 짝지어 재생한다. 기존 테스트는
이 헬퍼의 단위 동작(최종 상태·첫 전이 시각·길이 불일치·원자성)을
``test_simulator``에서만 다뤘고, 짝 재생 동등성
(``test_paired_replay_equivalence_qa``)은 시작 시각이 모두 같았다(단일
``start`` 오프셋). 이 파일은 서로 다른 시작 시각을 짝지은 재생 결과가
안내·리포트·누적 집계까지 이어지고, 스냅샷 시퀀스 짝 재생 경로와 Vehicle
SDK raw 짝 적용 경로와 전이 이력까지 동일함을 검증한다.
"""

import unittest

from engine.adapters.simulator import (
    replay_scenarios_by_name_and_start,
    replay_snapshot_sequences_for_sessions,
    scenario_snapshots,
)
from engine.adapters.vehicle_sdk import (
    apply_raw_sequences_for_sessions,
    raws_from_snapshots,
)
from engine.guidance import DestinationContext, GuidanceLevel, guidance_for_session
from engine.report import CareReportLog, report_for_session
from engine.session import CareSession, SessionState

SCENARIO_NAMES = ("dropoff_normal", "forgotten_rising_temp", "pet_dropoff")
SCENARIO_STARTS = (0.0, 1000.0, 2000.0)
EXPECTED_STATES = (
    SessionState.COMPLETED,
    SessionState.EXCEPTION,
    SessionState.COMPLETED,
)
EXPECTED_TRANSITIONS = (6, 5, 6)
EXPECTED_DURATIONS = (300.0, 240.0, 300.0)


def _history_sequence(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp) for t in session.history
    ]


def _paired_sessions():
    return [CareSession() for _ in SCENARIO_NAMES]


def _replayed_sessions():
    sessions = _paired_sessions()
    replay_scenarios_by_name_and_start(sessions, SCENARIO_NAMES, SCENARIO_STARTS)
    return sessions


class PairedStartReplayOutcomesTest(unittest.TestCase):
    def test_final_states_transitions_and_start_timestamps(self):
        sessions = _paired_sessions()

        states = replay_scenarios_by_name_and_start(
            sessions, SCENARIO_NAMES, SCENARIO_STARTS
        )

        self.assertEqual(states, EXPECTED_STATES)
        self.assertEqual(states, tuple(session.state for session in sessions))
        for session, transitions, start, duration in zip(
            sessions,
            EXPECTED_TRANSITIONS,
            SCENARIO_STARTS,
            EXPECTED_DURATIONS,
        ):
            self.assertEqual(len(session.history), transitions)
            self.assertEqual(session.history[0].timestamp, start)
            self.assertEqual(
                session.history[-1].timestamp, start + duration
            )

    def test_guidance_and_report_absolute_values(self):
        sessions = _replayed_sessions()

        normal_guidance = guidance_for_session(
            sessions[0], context=DestinationContext.DROPOFF
        )
        self.assertEqual(normal_guidance.level, GuidanceLevel.INFO)
        self.assertEqual(normal_guidance.reason, "completed")
        normal_report = report_for_session(sessions[0])
        self.assertTrue(normal_report.completed)
        self.assertEqual(normal_report.exception_count, 0)
        self.assertEqual(normal_report.summary, "하차 확인 완료 · 예외 없음")

        forgotten = sessions[1]
        self.assertTrue(forgotten.passenger_present)
        forgotten_guidance = guidance_for_session(
            forgotten, context=DestinationContext.DROPOFF
        )
        self.assertEqual(forgotten_guidance.level, GuidanceLevel.URGENT)
        self.assertIn("35.5도", forgotten_guidance.text)
        self.assertIn("즉시", forgotten_guidance.text)
        forgotten_report = report_for_session(forgotten)
        self.assertFalse(forgotten_report.completed)
        self.assertEqual(forgotten_report.exception_count, 1)
        self.assertEqual(forgotten_report.transition_count, 5)
        self.assertEqual(forgotten_report.duration_seconds, 240.0)
        self.assertEqual(forgotten_report.max_cabin_temp_c, 35.5)
        self.assertEqual(forgotten_report.summary, "예외 발생 · 하차 미확인")

        pet_report = report_for_session(sessions[2])
        self.assertTrue(pet_report.completed)
        self.assertEqual(pet_report.transition_count, 6)
        self.assertEqual(pet_report.duration_seconds, 300.0)


class PairedStartReportLogTest(unittest.TestCase):
    def test_report_log_aggregation(self):
        sessions = _replayed_sessions()
        log = CareReportLog()

        reports = log.add_sessions(sessions)

        self.assertEqual(len(reports), 3)
        self.assertEqual(len(log.reports), 3)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.average_duration_seconds, 280.0)


class PairedStartPathEquivalenceTest(unittest.TestCase):
    def test_sdk_raw_paired_apply_matches_history(self):
        by_name_sessions = _replayed_sessions()
        sdk_sessions = _paired_sessions()
        raw_sequences = tuple(
            raws_from_snapshots(scenario_snapshots(name, start=start))
            for name, start in zip(SCENARIO_NAMES, SCENARIO_STARTS)
        )

        sdk_states = apply_raw_sequences_for_sessions(sdk_sessions, raw_sequences)

        self.assertEqual(sdk_states, EXPECTED_STATES)
        for expected_session, sdk_session in zip(by_name_sessions, sdk_sessions):
            self.assertEqual(
                _history_sequence(sdk_session),
                _history_sequence(expected_session),
            )
            self.assertEqual(
                sdk_session.current_snapshot, expected_session.current_snapshot
            )
            self.assertEqual(
                sdk_session.passenger_present, expected_session.passenger_present
            )

    def test_snapshot_sequences_paired_replay_matches_history(self):
        by_name_sessions = _replayed_sessions()
        sequence_sessions = _paired_sessions()
        snapshot_sequences = tuple(
            scenario_snapshots(name, start=start)
            for name, start in zip(SCENARIO_NAMES, SCENARIO_STARTS)
        )

        states = replay_snapshot_sequences_for_sessions(
            sequence_sessions, snapshot_sequences
        )

        self.assertEqual(states, EXPECTED_STATES)
        for expected_session, sequence_session in zip(
            by_name_sessions, sequence_sessions
        ):
            self.assertEqual(
                _history_sequence(sequence_session),
                _history_sequence(expected_session),
            )
            report = report_for_session(sequence_session)
            expected_report = report_for_session(expected_session)
            self.assertEqual(report.final_state, expected_report.final_state)
            self.assertEqual(
                report.duration_seconds, expected_report.duration_seconds
            )
            self.assertEqual(
                report.max_cabin_temp_c, expected_report.max_cabin_temp_c
            )


if __name__ == "__main__":
    unittest.main()

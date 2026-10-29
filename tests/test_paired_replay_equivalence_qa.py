"""짝 재생 두 경로(시뮬레이터 ↔ SDK raw)의 동등성 통합 검증.

세션마다 다른 시나리오를 짝지어 재생하는 경로는 두 가지다.

- 시뮬레이터: ``replay_scenarios_by_name(sessions, names)``
- Vehicle SDK raw: ``apply_raw_sequences_for_sessions(sessions, raw_sequences)``
  (raw 시퀀스는 ``raws_from_snapshots(scenario_snapshots(name))`` 으로 만든다)

기존 테스트는 각 짝 헬퍼를 따로, 그리고 단일 시나리오 동등성
(``test_adapter_equivalence_qa``)만 다뤘다. 이 파일은 고정 시나리오 3종을
서로 다른 세션에 짝지어 한 번에 재생했을 때 두 경로의 최종 상태·전이
이력·안내·리포트·누적 집계가 전부 동일함을 검증한다.
"""

import unittest

from engine.adapters.simulator import replay_scenarios_by_name, scenario_snapshots
from engine.adapters.vehicle_sdk import (
    apply_raw_sequences_for_sessions,
    raws_from_snapshots,
)
from engine.guidance import DestinationContext, GuidanceLevel, guidance_for_session
from engine.report import CareReportLog, report_for_session
from engine.session import CareSession, SessionState

SCENARIO_NAMES = ("dropoff_normal", "forgotten_rising_temp", "pet_dropoff")
EXPECTED_STATES = (
    SessionState.COMPLETED,
    SessionState.EXCEPTION,
    SessionState.COMPLETED,
)


def _history_sequence(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp) for t in session.history
    ]


def _report_fields(session):
    report = report_for_session(session)
    return (
        report.final_state,
        report.completed,
        report.exception_count,
        report.transition_count,
        report.duration_seconds,
        report.max_cabin_temp_c,
        report.summary,
    )


def _guidance_fields(session):
    guidance = guidance_for_session(session, context=DestinationContext.DROPOFF)
    return (guidance.level, guidance.text, guidance.reason)


def _raw_sequences(names=SCENARIO_NAMES, start=0.0):
    return tuple(
        raws_from_snapshots(scenario_snapshots(name, start=start)) for name in names
    )


def _paired_sessions():
    return [CareSession() for _ in SCENARIO_NAMES]


class PairedReplayFinalStatesTest(unittest.TestCase):
    def test_simulator_paired_replay_final_states(self):
        sessions = _paired_sessions()

        states = replay_scenarios_by_name(sessions, SCENARIO_NAMES)

        self.assertEqual(states, EXPECTED_STATES)
        self.assertEqual(
            states, tuple(session.state for session in sessions)
        )


class PairedSdkRawEquivalenceTest(unittest.TestCase):
    def test_sdk_raw_paired_apply_matches_simulator_history(self):
        sim_sessions = _paired_sessions()
        sdk_sessions = _paired_sessions()

        sim_states = replay_scenarios_by_name(sim_sessions, SCENARIO_NAMES)
        sdk_states = apply_raw_sequences_for_sessions(
            sdk_sessions, _raw_sequences()
        )

        self.assertEqual(sdk_states, EXPECTED_STATES)
        self.assertEqual(sdk_states, sim_states)
        for sim_session, sdk_session in zip(sim_sessions, sdk_sessions):
            self.assertEqual(
                _history_sequence(sdk_session), _history_sequence(sim_session)
            )
            self.assertEqual(
                sdk_session.current_snapshot, sim_session.current_snapshot
            )
            self.assertEqual(
                sdk_session.passenger_present, sim_session.passenger_present
            )

    def test_guidance_and_report_match_between_paths(self):
        sim_sessions = _paired_sessions()
        sdk_sessions = _paired_sessions()
        replay_scenarios_by_name(sim_sessions, SCENARIO_NAMES)
        apply_raw_sequences_for_sessions(sdk_sessions, _raw_sequences())

        for sim_session, sdk_session in zip(sim_sessions, sdk_sessions):
            self.assertEqual(
                _guidance_fields(sdk_session), _guidance_fields(sim_session)
            )
            self.assertEqual(
                _report_fields(sdk_session), _report_fields(sim_session)
            )

        normal_report = report_for_session(sim_sessions[0])
        self.assertEqual(normal_report.transition_count, 6)
        self.assertEqual(normal_report.duration_seconds, 300.0)
        self.assertEqual(normal_report.summary, "하차 확인 완료 · 예외 없음")

        forgotten = sim_sessions[1]
        forgotten_report = report_for_session(forgotten)
        self.assertEqual(forgotten_report.transition_count, 5)
        self.assertEqual(forgotten_report.duration_seconds, 240.0)
        self.assertEqual(forgotten_report.max_cabin_temp_c, 35.5)
        self.assertEqual(forgotten_report.summary, "예외 발생 · 하차 미확인")
        self.assertTrue(forgotten.passenger_present)
        forgotten_guidance = guidance_for_session(
            forgotten, context=DestinationContext.DROPOFF
        )
        self.assertEqual(forgotten_guidance.level, GuidanceLevel.URGENT)


class PairedReportLogAggregationTest(unittest.TestCase):
    def test_report_log_aggregation_matches_between_paths(self):
        sim_sessions = _paired_sessions()
        sdk_sessions = _paired_sessions()
        replay_scenarios_by_name(sim_sessions, SCENARIO_NAMES)
        apply_raw_sequences_for_sessions(sdk_sessions, _raw_sequences())

        sim_log = CareReportLog()
        sdk_log = CareReportLog()
        sim_reports = sim_log.add_sessions(sim_sessions)
        sdk_reports = sdk_log.add_sessions(sdk_sessions)

        self.assertEqual(sdk_reports, sim_reports)
        for log in (sim_log, sdk_log):
            self.assertEqual(len(log.reports), 3)
            self.assertEqual(log.completed_count, 2)
            self.assertEqual(log.sessions_with_exception, 1)
            self.assertEqual(log.total_exception_count, 1)
            self.assertEqual(log.max_cabin_temp_c, 35.5)
            self.assertEqual(log.average_duration_seconds, 280.0)


class PairedReplayStartOffsetTest(unittest.TestCase):
    def test_start_offset_matches_between_paths(self):
        sim_sessions = _paired_sessions()
        sdk_sessions = _paired_sessions()

        replay_scenarios_by_name(sim_sessions, SCENARIO_NAMES, start=1000.0)
        apply_raw_sequences_for_sessions(
            sdk_sessions, _raw_sequences(start=1000.0)
        )

        first = sim_sessions[0]
        self.assertEqual(first.history[0].timestamp, 1000.0)
        self.assertEqual(first.history[-1].timestamp, 1300.0)
        self.assertEqual(report_for_session(first).duration_seconds, 300.0)
        for sim_session, sdk_session in zip(sim_sessions, sdk_sessions):
            self.assertEqual(
                _history_sequence(sdk_session), _history_sequence(sim_session)
            )


if __name__ == "__main__":
    unittest.main()

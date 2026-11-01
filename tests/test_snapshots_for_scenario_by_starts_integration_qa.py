"""snapshots_for_scenario_by_starts 통합 QA.

``snapshots_for_scenario_by_starts(name, starts)``는 하나의 시나리오를
여러 시작 시각으로 조회하는 읽기 전용 헬퍼로, 단위 테스트
(``test_simulator``의 ``SnapshotsForScenarioByStartsTest``)에서는 개별
호출 동등성·길이·중복·제너레이터·알 수 없는 이름만 다뤘다. 이 파일은
조회 결과를 ``replay``로 세션에 재생한 뒤 안내·리포트·누적함까지 잇는
흐름, ``replay_scenarios_by_start`` 재생 경로와의 동등성, 조회 결과의
재사용성과 시작 시각만 이동하고 구조는 불변임을 검증한다. 같은 이름을
다른 시작 시각으로 재생하는 통합 검증
(``test_replay_by_start_integration_qa``)은 재생 헬퍼를 직접 쓰므로,
조회→재생으로 나눈 경로와는 중복이 아니다.
"""

import unittest

from engine.adapters.simulator import (
    replay,
    replay_scenarios_by_start,
    scenario_snapshots,
    snapshots_for_scenario_by_starts,
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
SCENARIO_NAMES = ("dropoff_normal", "forgotten_rising_temp", "pet_dropoff")


def _history_sequence(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp) for t in session.history
    ]


def _replay_all(name, starts):
    sessions = []
    for snapshots in snapshots_for_scenario_by_starts(name, starts):
        session = CareSession()
        replay(session, snapshots)
        sessions.append(session)
    return sessions


class SnapshotsForScenarioByStartsDropoffIntegrationTest(unittest.TestCase):
    def test_dropoff_replay_guidance_and_report_per_start(self):
        sequences = snapshots_for_scenario_by_starts(
            "dropoff_normal", DROPOFF_STARTS
        )

        self.assertEqual(len(sequences), len(DROPOFF_STARTS))
        for snapshots, start in zip(sequences, DROPOFF_STARTS):
            self.assertEqual(len(snapshots), 6)
            session = CareSession()
            state = replay(session, snapshots)

            self.assertEqual(state, SessionState.COMPLETED)
            self.assertEqual(state, session.state)
            self.assertFalse(session.passenger_present)
            self.assertEqual(len(session.history), 6)
            self.assertEqual(
                tuple(t.reason for t in session.history), DROPOFF_REASONS
            )
            self.assertEqual(
                tuple(t.timestamp for t in session.history),
                tuple(start + offset for offset in DROPOFF_OFFSETS),
            )
            self.assertEqual(session.current_snapshot.timestamp, start + 300.0)

            guidance = guidance_for_session(
                session, context=DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "completed")
            self.assertEqual(guidance.text, "하차 확인이 완료되었습니다.")

            report = report_for_session(session)
            self.assertEqual(report.final_state, SessionState.COMPLETED)
            self.assertTrue(report.completed)
            self.assertEqual(report.exception_count, 0)
            self.assertEqual(report.duration_seconds, 300.0)
            self.assertEqual(report.started_at, start)
            self.assertEqual(report.ended_at, start + 300.0)
            self.assertIsNone(report.max_cabin_temp_c)
            self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")


class SnapshotsForScenarioByStartsForgottenIntegrationTest(unittest.TestCase):
    def test_forgotten_replay_guidance_and_report_per_start(self):
        sequences = snapshots_for_scenario_by_starts(
            "forgotten_rising_temp", FORGOTTEN_STARTS
        )

        self.assertEqual(len(sequences), len(FORGOTTEN_STARTS))
        for snapshots, start in zip(sequences, FORGOTTEN_STARTS):
            self.assertEqual(len(snapshots), 8)
            session = CareSession()
            state = replay(session, snapshots)

            self.assertEqual(state, SessionState.EXCEPTION)
            self.assertEqual(state, session.state)
            self.assertTrue(session.passenger_present)
            self.assertEqual(len(session.history), 5)
            self.assertEqual(session.current_snapshot.timestamp, start + 420.0)
            self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)

            guidance = guidance_for_session(
                session, context=DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.URGENT)
            self.assertEqual(
                guidance.reason, "passenger_left_locked_dangerous_cabin_temp"
            )
            self.assertIn("35.5도", guidance.text)
            self.assertIn("즉시", guidance.text)

            report = report_for_session(session)
            self.assertEqual(report.final_state, SessionState.EXCEPTION)
            self.assertFalse(report.completed)
            self.assertEqual(report.exception_count, 1)
            self.assertEqual(report.duration_seconds, 240.0)
            self.assertEqual(report.max_cabin_temp_c, 35.5)
            self.assertEqual(report.summary, "예외 발생 · 하차 미확인")


class SnapshotsForScenarioByStartsEquivalenceIntegrationTest(unittest.TestCase):
    def test_query_then_replay_matches_replay_scenarios_by_start(self):
        starts = (0.0, 777.0)

        for name in SCENARIO_NAMES:
            queried = _replay_all(name, starts)
            direct = [CareSession() for _ in starts]
            replay_scenarios_by_start(direct, name, starts)

            for queried_session, direct_session in zip(queried, direct):
                self.assertEqual(queried_session.state, direct_session.state)
                self.assertEqual(
                    _history_sequence(queried_session),
                    _history_sequence(direct_session),
                )
                self.assertEqual(
                    queried_session.current_snapshot,
                    direct_session.current_snapshot,
                )
                self.assertEqual(
                    queried_session.passenger_present,
                    direct_session.passenger_present,
                )
                self.assertEqual(
                    report_for_session(queried_session),
                    report_for_session(direct_session),
                )


class SnapshotsForScenarioByStartsReuseIntegrationTest(unittest.TestCase):
    def test_sequences_are_reusable_and_unmutated_by_replay(self):
        (snapshots,) = snapshots_for_scenario_by_starts(
            "forgotten_rising_temp", (0.0,)
        )
        sessions = [CareSession(), CareSession()]

        for session in sessions:
            replay(session, snapshots)

        self.assertEqual(
            _history_sequence(sessions[0]), _history_sequence(sessions[1])
        )
        self.assertEqual(
            report_for_session(sessions[0]), report_for_session(sessions[1])
        )
        self.assertEqual(
            snapshots, scenario_snapshots("forgotten_rising_temp", 0.0)
        )

    def test_duplicate_starts_produce_identical_sessions(self):
        sessions = _replay_all("dropoff_normal", (500.0, 500.0))

        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0].state, SessionState.COMPLETED)
        self.assertEqual(sessions[1].state, SessionState.COMPLETED)
        self.assertEqual(
            _history_sequence(sessions[0]), _history_sequence(sessions[1])
        )
        self.assertEqual(
            report_for_session(sessions[0]), report_for_session(sessions[1])
        )


class SnapshotsForScenarioByStartsLogIntegrationTest(unittest.TestCase):
    def test_report_log_aggregation_across_starts(self):
        sessions = []
        sessions += _replay_all("dropoff_normal", (0.0, 1000.0))
        sessions += _replay_all("forgotten_rising_temp", (0.0,))
        sessions += _replay_all("pet_dropoff", (0.0,))

        log = CareReportLog()
        added = log.add_sessions(sessions)

        self.assertEqual(added, tuple(report_for_session(s) for s in sessions))
        self.assertEqual(len(log.reports), 4)
        self.assertEqual(log.completed_count, 3)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.average_duration_seconds, 285.0)


class SnapshotsForScenarioByStartsFailureIntegrationTest(unittest.TestCase):
    def test_empty_starts_and_unknown_name_leave_sessions_untouched(self):
        self.assertEqual(
            snapshots_for_scenario_by_starts("dropoff_normal", []), ()
        )

        sessions = [CareSession(), CareSession()]
        with self.assertRaises(ValueError):
            snapshots_for_scenario_by_starts("unknown_scenario", [0.0, 60.0])

        for session in sessions:
            self.assertEqual(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])
            self.assertFalse(session.passenger_present)


if __name__ == "__main__":
    unittest.main()

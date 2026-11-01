"""guidances_for_session_by_contexts 통합 QA.

``guidances_for_session_by_contexts(session, contexts)``는 세션 하나에
목적지 맥락 여럿을 적용하는 단일 세션 헬퍼로, 단위 테스트
(``test_guidance``의 ``GuidancesForSessionByContextsTest``)에서는 빈
입력·ARRIVED 3맥락 개별 호출 동등성·세션 무변경·제너레이터·문자열/None
정규화 위임·중복만 다뤘다. 이 파일은 시뮬레이터 고정 시나리오로 만든
실세션(BOARDING·ARRIVED·DRIVING·COMPLETED·EXCEPTION)에 맥락 여럿을
적용한 뒤 안내·리포트·누적함까지 잇는 흐름, 짝 헬퍼
``guidances_for_sessions_by_context``와의 동등성, 맥락이 표현만 바꾸는
상태와 맥락과 무관한 상태의 경계를 검증한다.
"""

import unittest

from engine.adapters.simulator import replay, scenario_snapshots
from engine.guidance import (
    DestinationContext,
    GuidanceLevel,
    guidance_for_session,
    guidances_for_session_by_contexts,
    guidances_for_sessions_by_context,
)
from engine.report import CareReportLog, report_for_session
from engine.session import CareSession, SessionState

CONTEXTS = (
    DestinationContext.GENERAL,
    DestinationContext.DROPOFF,
    DestinationContext.PICKUP,
)


def _session(name, count=None):
    session = CareSession()
    snapshots = scenario_snapshots(name)
    replay(session, snapshots if count is None else snapshots[:count])
    return session


def _history_sequence(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp) for t in session.history
    ]


class GuidancesForSessionByContextsBoardingIntegrationTest(unittest.TestCase):
    def test_boarding_session_contexts_differ_and_report_is_progress(self):
        session = _session("dropoff_normal", 1)
        self.assertEqual(session.state, SessionState.BOARDING)

        guidances = guidances_for_session_by_contexts(session, CONTEXTS)

        self.assertEqual(len(guidances), 3)
        self.assertTrue(
            all(g.level == GuidanceLevel.INFO for g in guidances)
        )
        self.assertTrue(
            all(g.state == SessionState.BOARDING for g in guidances)
        )
        self.assertEqual(
            tuple(g.reason for g in guidances),
            ("boarding", "boarding_dropoff", "boarding_pickup"),
        )
        self.assertEqual(len({g.text for g in guidances}), 3)
        self.assertIn("등원", guidances[1].text)
        self.assertIn("하원", guidances[2].text)

        report = report_for_session(session)
        self.assertEqual(report.transition_count, 1)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")


class GuidancesForSessionByContextsArrivedIntegrationTest(unittest.TestCase):
    def test_arrived_session_contexts_differ_and_report(self):
        session = _session("dropoff_normal", 4)
        self.assertEqual(session.state, SessionState.ARRIVED)

        guidances = guidances_for_session_by_contexts(session, CONTEXTS)

        self.assertTrue(
            all(g.level == GuidanceLevel.REMIND for g in guidances)
        )
        self.assertEqual(
            tuple(g.reason for g in guidances),
            (
                "arrived_check_rear_seat",
                "arrived_dropoff_check_rear_seat",
                "arrived_pickup_check_rear_seat",
            ),
        )
        self.assertEqual(len({g.text for g in guidances}), 3)
        self.assertIn("등원", guidances[1].text)
        self.assertIn("하원", guidances[2].text)

        report = report_for_session(session)
        self.assertEqual(report.transition_count, 4)
        self.assertEqual(report.duration_seconds, 180.0)


class GuidancesForSessionByContextsIndependentIntegrationTest(unittest.TestCase):
    def test_context_independent_states_produce_identical_guidance(self):
        driving = _session("dropoff_normal", 3)
        completed = _session("dropoff_normal")
        exception = _session("forgotten_rising_temp")

        for session in (driving, completed, exception):
            guidances = guidances_for_session_by_contexts(session, CONTEXTS)
            self.assertEqual(len(guidances), 3)
            self.assertEqual(guidances[0], guidances[1])
            self.assertEqual(guidances[1], guidances[2])

        completed_guidance = guidances_for_session_by_contexts(
            completed, CONTEXTS
        )[0]
        self.assertEqual(completed_guidance.level, GuidanceLevel.INFO)
        self.assertEqual(completed_guidance.reason, "completed")

        exception_guidance = guidances_for_session_by_contexts(
            exception, CONTEXTS
        )[0]
        self.assertEqual(exception_guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            exception_guidance.reason,
            "passenger_left_locked_dangerous_cabin_temp",
        )
        self.assertIn("35.5도", exception_guidance.text)
        self.assertIn("즉시", exception_guidance.text)


class GuidancesForSessionByContextsPairedEquivalenceIntegrationTest(
    unittest.TestCase
):
    def test_matches_paired_helper_and_individual_calls(self):
        sessions = [
            _session("dropoff_normal", 1),
            _session("dropoff_normal", 4),
            _session("forgotten_rising_temp"),
        ]

        for session in sessions:
            by_contexts = guidances_for_session_by_contexts(session, CONTEXTS)
            paired = guidances_for_sessions_by_context(
                (session, session, session), CONTEXTS
            )
            individual = tuple(
                guidance_for_session(session, context=c) for c in CONTEXTS
            )
            self.assertEqual(by_contexts, paired)
            self.assertEqual(by_contexts, individual)


class GuidancesForSessionByContextsScenarioLogIntegrationTest(
    unittest.TestCase
):
    def test_fixed_scenarios_final_guidance_and_report_log(self):
        sessions = [
            _session("dropoff_normal"),
            _session("forgotten_rising_temp"),
            _session("pet_dropoff"),
        ]

        dropoff_guidances = guidances_for_session_by_contexts(
            sessions[0], CONTEXTS
        )
        for guidance in dropoff_guidances:
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "completed")
            self.assertEqual(guidance.text, "하차 확인이 완료되었습니다.")

        exception_guidances = guidances_for_session_by_contexts(
            sessions[1], CONTEXTS
        )
        for guidance in exception_guidances:
            self.assertEqual(guidance.level, GuidanceLevel.URGENT)

        pet_guidances = guidances_for_session_by_contexts(sessions[2], CONTEXTS)
        for guidance in pet_guidances:
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "completed")

        log = CareReportLog()
        added = log.add_sessions(sessions)
        self.assertEqual(added, tuple(report_for_session(s) for s in sessions))
        self.assertEqual(len(log.reports), 3)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.average_duration_seconds, 280.0)


class GuidancesForSessionByContextsImmutabilityIntegrationTest(
    unittest.TestCase
):
    def test_sessions_and_reports_unchanged_by_multi_context_calls(self):
        for session in (
            _session("dropoff_normal", 4),
            _session("forgotten_rising_temp"),
        ):
            before_state = session.state
            before_history = _history_sequence(session)
            before_snapshot = session.current_snapshot
            before_passenger = session.passenger_present
            before_report = report_for_session(session)

            guidances_for_session_by_contexts(session, CONTEXTS)
            guidances_for_session_by_contexts(
                session, ("dropoff", None, "unknown", DestinationContext.PICKUP)
            )

            self.assertEqual(session.state, before_state)
            self.assertEqual(_history_sequence(session), before_history)
            self.assertEqual(session.current_snapshot, before_snapshot)
            self.assertEqual(session.passenger_present, before_passenger)
            self.assertEqual(report_for_session(session), before_report)


if __name__ == "__main__":
    unittest.main()

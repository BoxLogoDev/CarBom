"""고정 시나리오 3종 통합(end-to-end) QA.

시뮬레이터 재생(replay_scenario)으로 만든 세션에 대해
안내(guidance_for_session)와 리포트(report_for_session)가
세션 상태와 서로 일치하는지를 전 구간에서 검증한다.
기존 테스트는 모듈별 경계만 다뤄, 재생→안내→리포트→누적함까지
한 흐름으로 잇는 각도는 검증하지 않았다.
"""

import unittest

from engine.adapters.simulator import SCENARIO_NAMES, replay_scenario
from engine.guidance import (
    DestinationContext,
    GuidanceLevel,
    guidance_for_session,
)
from engine.report import CareReportLog, report_for_session
from engine.session import CareSession, SessionState


def _run(name):
    session = CareSession()
    final = replay_scenario(session, name)
    return session, final


class DropoffNormalIntegrationTest(unittest.TestCase):
    def test_dropoff_normal_end_to_end(self):
        session, final = _run("dropoff_normal")
        self.assertIs(final, SessionState.COMPLETED)
        self.assertIs(session.state, SessionState.COMPLETED)

        guidance = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        self.assertEqual(guidance.text, "하차 확인이 완료되었습니다.")
        self.assertIs(guidance.state, SessionState.COMPLETED)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertIsNone(report.max_cabin_temp_c)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")
        self.assertFalse(report.passenger_present)


class ForgottenRisingTempIntegrationTest(unittest.TestCase):
    def test_forgotten_rising_temp_end_to_end(self):
        session, final = _run("forgotten_rising_temp")
        self.assertIs(final, SessionState.EXCEPTION)
        self.assertIs(session.state, SessionState.EXCEPTION)

        guidance = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason,
            "passenger_left_locked_dangerous_cabin_temp",
        )
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)
        self.assertIs(guidance.state, SessionState.EXCEPTION)

        report = report_for_session(session)
        self.assertFalse(report.completed)
        self.assertTrue(report.exception_occurred)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")
        self.assertTrue(report.passenger_present)


class PetDropoffIntegrationTest(unittest.TestCase):
    def test_pet_dropoff_end_to_end(self):
        session, final = _run("pet_dropoff")
        self.assertIs(final, SessionState.COMPLETED)

        guidance = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")
        self.assertFalse(report.passenger_present)


class ReportLogIntegrationTest(unittest.TestCase):
    def test_log_aggregates_all_three_scenarios(self):
        log = CareReportLog()
        for name in SCENARIO_NAMES:
            session, _ = _run(name)
            log.add_session(session)

        self.assertEqual(len(log), 3)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        # (300 + 240 + 300) / 3
        self.assertEqual(log.average_duration_seconds, 280.0)


class CrossModuleConsistencyTest(unittest.TestCase):
    def test_guidance_and_report_match_session_for_all_scenarios(self):
        self.assertEqual(
            SCENARIO_NAMES,
            ("dropoff_normal", "forgotten_rising_temp", "pet_dropoff"),
        )
        for name in SCENARIO_NAMES:
            with self.subTest(scenario=name):
                session, final = _run(name)
                guidance = guidance_for_session(
                    session, DestinationContext.DROPOFF
                )
                report = report_for_session(session)

                self.assertIs(report.final_state, session.state)
                self.assertIs(report.final_state, final)
                self.assertIs(guidance.state, session.state)
                self.assertEqual(
                    report.transition_count, len(session.history)
                )
                self.assertEqual(
                    report.passenger_present, session.passenger_present
                )
                if session.state is SessionState.COMPLETED:
                    self.assertEqual(
                        guidance.level, GuidanceLevel.INFO
                    )
                    self.assertTrue(report.completed)
                if session.state is SessionState.EXCEPTION:
                    self.assertEqual(
                        guidance.level, GuidanceLevel.URGENT
                    )
                    self.assertTrue(report.exception_occurred)


if __name__ == "__main__":
    unittest.main()

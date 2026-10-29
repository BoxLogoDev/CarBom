"""poll_repeatedly_into_sessions 다중 세션 반복 적용 통합 QA.

80회차에 추가된 ``poll_repeatedly_into_sessions(adapter, sessions, times)``가
고정 시나리오 3종에서 여러 세션에 같은 스냅샷 시퀀스를 적용하는지,
그 세션들로 안내·리포트·CareReportLog 집계가 제대로 계산되는지,
simulator ``replay_scenario``와 같은 결과가 되는지를 검증한다.
기존 PollRepeatedlyIntoSessionsTest는 최종 상태·poll 호출 횟수·
동승자 잔류·최종 온도만 다뤄, 안내·리포트·누적 집계·재현 동등성은
검증하지 않았다.
"""

import unittest

from engine.adapters.simulator import replay_scenario, scenario_snapshots
from engine.adapters.vehicle_sdk import (
    VehicleSdkAdapter,
    poll_repeatedly_into_sessions,
    raws_from_snapshots,
)
from engine.guidance import (
    DestinationContext,
    GuidanceLevel,
    guidance_for_session,
)
from engine.report import (
    CareReportLog,
    report_for_session,
    reports_for_sessions,
)
from engine.session import CareSession, SessionState


class FakeSequenceSdkClient:
    """read_raw()가 호출할 때마다 다음 dict를 돌려주는 가짜 클라이언트."""

    def __init__(self, raws):
        self._raws = list(raws)
        self.calls = 0

    def read_raw(self):
        raw = self._raws[self.calls]
        self.calls += 1
        return raw


def _adapter_for(name):
    raws = raws_from_snapshots(scenario_snapshots(name))
    client = FakeSequenceSdkClient(raws)
    return VehicleSdkAdapter(client), client


def _history_key(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


class PollRepeatedlyIntoSessionsIntegrationQATest(unittest.TestCase):
    def test_dropoff_normal_completes_both_sessions_with_guidance_and_report(self):
        adapter, client = _adapter_for("dropoff_normal")
        sessions = (CareSession(), CareSession())
        states = poll_repeatedly_into_sessions(adapter, sessions, 6)
        self.assertEqual(
            states, (SessionState.COMPLETED, SessionState.COMPLETED)
        )
        self.assertEqual(client.calls, 6)

        for session in sessions:
            self.assertEqual(len(session.history), 6)
            self.assertFalse(session.passenger_present)

            guidance = guidance_for_session(
                session, DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "completed")

            report = report_for_session(session)
            self.assertTrue(report.completed)
            self.assertEqual(report.transition_count, 6)
            self.assertEqual(report.duration_seconds, 300.0)
            self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_forgotten_completes_exception_in_both_sessions(self):
        adapter, client = _adapter_for("forgotten_rising_temp")
        sessions = (CareSession(), CareSession())
        states = poll_repeatedly_into_sessions(adapter, sessions, 8)
        self.assertEqual(
            states, (SessionState.EXCEPTION, SessionState.EXCEPTION)
        )
        self.assertEqual(client.calls, 8)

        for session in sessions:
            self.assertEqual(len(session.history), 5)
            self.assertTrue(session.passenger_present)

            guidance = guidance_for_session(
                session, DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.URGENT)
            self.assertIn("35.5도", guidance.text)
            self.assertIn("즉시", guidance.text)

            report = report_for_session(session)
            self.assertFalse(report.completed)
            self.assertEqual(report.exception_count, 1)
            self.assertEqual(report.max_cabin_temp_c, 35.5)
            self.assertEqual(report.duration_seconds, 240.0)
            self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_pet_dropoff_completes_both_sessions(self):
        adapter, client = _adapter_for("pet_dropoff")
        sessions = (CareSession(), CareSession())
        states = poll_repeatedly_into_sessions(adapter, sessions, 6)
        self.assertEqual(
            states, (SessionState.COMPLETED, SessionState.COMPLETED)
        )
        self.assertEqual(client.calls, 6)

        for session in sessions:
            self.assertEqual(len(session.history), 6)

            report = report_for_session(session)
            self.assertTrue(report.completed)
            self.assertEqual(report.transition_count, 6)
            self.assertEqual(report.duration_seconds, 300.0)

    def test_matches_replay_scenario_histories_and_reports(self):
        for name in ("dropoff_normal", "forgotten_rising_temp"):
            with self.subTest(name=name):
                times = len(scenario_snapshots(name))
                adapter, _ = _adapter_for(name)
                via_poll = CareSession()
                poll_repeatedly_into_sessions(adapter, (via_poll,), times)

                via_replay = CareSession()
                replay_scenario(via_replay, name)

                self.assertEqual(
                    _history_key(via_poll), _history_key(via_replay)
                )

                poll_report = report_for_session(via_poll)
                replay_report = report_for_session(via_replay)
                self.assertEqual(
                    poll_report.final_state, replay_report.final_state
                )
                self.assertEqual(
                    poll_report.completed, replay_report.completed
                )
                self.assertEqual(
                    poll_report.exception_count,
                    replay_report.exception_count,
                )
                self.assertEqual(
                    poll_report.transition_count,
                    replay_report.transition_count,
                )
                self.assertEqual(
                    poll_report.duration_seconds,
                    replay_report.duration_seconds,
                )
                self.assertEqual(
                    poll_report.max_cabin_temp_c,
                    replay_report.max_cabin_temp_c,
                )

    def test_partial_polls_leave_both_sessions_driving(self):
        adapter, client = _adapter_for("dropoff_normal")
        sessions = (CareSession(), CareSession())
        states = poll_repeatedly_into_sessions(adapter, sessions, 3)
        self.assertEqual(
            states, (SessionState.DRIVING, SessionState.DRIVING)
        )
        self.assertEqual(client.calls, 3)

        for session in sessions:
            self.assertEqual(len(session.history), 3)

            guidance = guidance_for_session(
                session, DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "driving")

            report = report_for_session(session)
            self.assertFalse(report.completed)

    def test_report_log_aggregates_across_poll_driven_scenarios(self):
        sessions = []
        for name, times in (
            ("dropoff_normal", 6),
            ("forgotten_rising_temp", 8),
            ("pet_dropoff", 6),
        ):
            adapter, _ = _adapter_for(name)
            session = CareSession()
            poll_repeatedly_into_sessions(adapter, (session,), times)
            sessions.append(session)

        expected = reports_for_sessions(sessions)

        log = CareReportLog()
        returned = log.add_sessions(sessions)
        self.assertEqual(returned, expected)

        self.assertEqual(len(log), 3)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.average_duration_seconds, 280.0)


if __name__ == "__main__":
    unittest.main()

"""poll_once_per_adapter_into_session 다중 어댑터 단건 적용 통합 QA.

187회차에 추가된
``poll_once_per_adapter_into_session(adapters, session)``가 고정
시나리오 3종을 스냅샷마다 어댑터 하나로 나눠 세션 하나에 순서대로
적용하는 실제 통합 경로에서 쓸 수 있는지 검증한다. 적용한 세션의
안내·리포트·누적함 집계와 simulator ``replay_scenario`` 기준
동등성, 수집 단계 원자성을 다룬다.
187회차 단위 테스트(PollOncePerAdapterIntoSessionTest)는 최종
상태·호출 횟수·제너레이터 입력·중복 어댑터·미연결 전파만 다뤘고,
185회차 읽기 전용 통합 검증은 ``poll_snapshots_once_per_adapter``로
읽은 flat 스냅샷을 손으로 적용·재생하는 흐름만 다뤄, 읽기와 적용을
한 번에 하는 이 경로의 안내·리포트 연결은 검증하지 않았다.
"""

import unittest

from engine.adapters.simulator import replay_scenario, scenario_snapshots
from engine.adapters.vehicle_sdk import (
    VehicleSdkAdapter,
    poll_once_per_adapter_into_session,
    raws_from_snapshots,
)
from engine.guidance import (
    DestinationContext,
    GuidanceLevel,
    guidance_for_session,
)
from engine.report import CareReportLog, report_for_session
from engine.session import CareSession, SessionState

SCENARIO_NAMES_3 = (
    "dropoff_normal",
    "forgotten_rising_temp",
    "pet_dropoff",
)


class FakeSequenceSdkClient:
    """read_raw()가 호출할 때마다 다음 dict를 돌려주는 가짜 클라이언트."""

    def __init__(self, raws):
        self._raws = list(raws)
        self.calls = 0

    def read_raw(self):
        raw = self._raws[self.calls]
        self.calls += 1
        return raw


def _adapters_per_snapshot(name):
    raws = raws_from_snapshots(scenario_snapshots(name))
    clients = [FakeSequenceSdkClient([raw]) for raw in raws]
    adapters = [VehicleSdkAdapter(client) for client in clients]
    return adapters, clients


def _history_key(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


class PollOncePerAdapterIntoSessionIntegrationQATest(unittest.TestCase):
    def test_dropoff_normal_completes_with_guidance_and_report(self):
        adapters, clients = _adapters_per_snapshot("dropoff_normal")
        self.assertEqual(len(adapters), 6)

        session = CareSession()
        result = poll_once_per_adapter_into_session(adapters, session)

        self.assertIs(result, SessionState.COMPLETED)
        self.assertEqual(result, session.state)
        self.assertEqual(len(session.history), 6)
        self.assertEqual([c.calls for c in clients], [1, 1, 1, 1, 1, 1])

        guidance = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_forgotten_rising_temp_enters_exception(self):
        adapters, clients = _adapters_per_snapshot(
            "forgotten_rising_temp"
        )
        self.assertEqual(len(adapters), 8)

        session = CareSession()
        result = poll_once_per_adapter_into_session(adapters, session)

        self.assertIs(result, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)
        self.assertTrue(session.passenger_present)
        self.assertEqual(
            [c.calls for c in clients], [1, 1, 1, 1, 1, 1, 1, 1]
        )

        guidance = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_pet_dropoff_completes(self):
        adapters, _clients = _adapters_per_snapshot("pet_dropoff")
        self.assertEqual(len(adapters), 6)

        session = CareSession()
        result = poll_once_per_adapter_into_session(adapters, session)

        self.assertIs(result, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)

    def test_matches_replay_scenario_histories_and_reports(self):
        for name in ("dropoff_normal", "forgotten_rising_temp"):
            with self.subTest(name=name):
                adapters, _clients = _adapters_per_snapshot(name)
                via_poll = CareSession()
                poll_once_per_adapter_into_session(adapters, via_poll)

                via_replay = CareSession()
                replay_scenario(via_replay, name)

                self.assertEqual(
                    _history_key(via_poll), _history_key(via_replay)
                )
                self.assertEqual(
                    report_for_session(via_poll),
                    report_for_session(via_replay),
                )

    def test_unconnected_aborts_before_apply_and_empty_is_noop(self):
        adapters, clients = _adapters_per_snapshot("dropoff_normal")
        session = CareSession()

        with self.assertRaises(NotImplementedError):
            poll_once_per_adapter_into_session(
                [adapters[0], VehicleSdkAdapter(), adapters[1]],
                session,
            )

        self.assertIs(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])
        self.assertEqual(clients[0].calls, 1)
        self.assertEqual(clients[1].calls, 0)

        result = poll_once_per_adapter_into_session([], session)
        self.assertIs(result, SessionState.IDLE)
        self.assertIs(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])

    def test_report_log_aggregates_across_poll_driven_scenarios(self):
        sessions = []
        for name in SCENARIO_NAMES_3:
            adapters, _clients = _adapters_per_snapshot(name)
            session = CareSession()
            poll_once_per_adapter_into_session(adapters, session)
            sessions.append(session)

        log = CareReportLog()
        log.add_sessions(sessions)

        self.assertEqual(len(log), 3)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.average_duration_seconds, 280.0)


if __name__ == "__main__":
    unittest.main()

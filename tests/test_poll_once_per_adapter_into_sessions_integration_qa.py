"""poll_once_per_adapter_into_sessions 다중 세션 단건 방송 통합 QA.

191회차에 추가된
``poll_once_per_adapter_into_sessions(adapters, sessions)``가 고정
시나리오 3종을 스냅샷마다 어댑터 하나로 나눠 읽은 뒤 그 시퀀스
전체를 여러 세션 각각에 방송 적용하는 실제 통합 경로에서 쓸 수
있는지 검증한다. 방송으로 구동한 세션들의 안내·리포트·누적함
집계와 simulator ``replay_scenario`` 및 단일 세션 경로
``poll_once_per_adapter_into_session``과의 동등성, 수집 단계
원자성을 다룬다.
191회차 단위 테스트(PollOncePerAdapterIntoSessionsTest)는 최종
상태·빈 입력·제너레이터 입력만 다뤘고, 189회차 통합 검증은 세션
하나에 적용하는 경로만 다뤄, 방송 경로의 안내·리포트 연결은
검증하지 않았다.
"""

import unittest

from engine.adapters.simulator import replay_scenario, scenario_snapshots
from engine.adapters.vehicle_sdk import (
    VehicleSdkAdapter,
    poll_once_per_adapter_into_session,
    poll_once_per_adapter_into_sessions,
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


class PollOncePerAdapterIntoSessionsIntegrationQATest(unittest.TestCase):
    def test_dropoff_normal_broadcasts_to_two_sessions(self):
        adapters, clients = _adapters_per_snapshot("dropoff_normal")
        self.assertEqual(len(adapters), 6)

        sessions = [CareSession(), CareSession()]
        result = poll_once_per_adapter_into_sessions(adapters, sessions)

        self.assertEqual(
            result, (SessionState.COMPLETED, SessionState.COMPLETED)
        )
        self.assertEqual([c.calls for c in clients], [1, 1, 1, 1, 1, 1])
        for session, state in zip(sessions, result):
            self.assertEqual(state, session.state)
            self.assertEqual(len(session.history), 6)

            guidance = guidance_for_session(
                session, DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "completed")

            report = report_for_session(session)
            self.assertTrue(report.completed)
            self.assertEqual(report.duration_seconds, 300.0)
            self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_forgotten_rising_temp_broadcasts_exception(self):
        adapters, clients = _adapters_per_snapshot(
            "forgotten_rising_temp"
        )
        self.assertEqual(len(adapters), 8)

        sessions = [CareSession(), CareSession()]
        result = poll_once_per_adapter_into_sessions(adapters, sessions)

        self.assertEqual(
            result, (SessionState.EXCEPTION, SessionState.EXCEPTION)
        )
        self.assertEqual(
            [c.calls for c in clients], [1, 1, 1, 1, 1, 1, 1, 1]
        )
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
            self.assertEqual(report.exception_count, 1)
            self.assertEqual(report.max_cabin_temp_c, 35.5)
            self.assertEqual(report.duration_seconds, 240.0)
            self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_pet_dropoff_broadcasts_completed(self):
        adapters, _clients = _adapters_per_snapshot("pet_dropoff")
        self.assertEqual(len(adapters), 6)

        sessions = [CareSession(), CareSession()]
        result = poll_once_per_adapter_into_sessions(adapters, sessions)

        self.assertEqual(
            result, (SessionState.COMPLETED, SessionState.COMPLETED)
        )
        for session in sessions:
            self.assertEqual(len(session.history), 6)

    def test_matches_replay_scenario_and_single_session_path(self):
        for name in ("dropoff_normal", "forgotten_rising_temp"):
            with self.subTest(name=name):
                adapters, _clients = _adapters_per_snapshot(name)
                via_broadcast = CareSession()
                poll_once_per_adapter_into_sessions(
                    adapters, [via_broadcast]
                )

                adapters_single, _c = _adapters_per_snapshot(name)
                via_single = CareSession()
                poll_once_per_adapter_into_session(
                    adapters_single, via_single
                )

                via_replay = CareSession()
                replay_scenario(via_replay, name)

                self.assertEqual(
                    _history_key(via_broadcast), _history_key(via_replay)
                )
                self.assertEqual(
                    _history_key(via_broadcast), _history_key(via_single)
                )
                self.assertEqual(
                    report_for_session(via_broadcast),
                    report_for_session(via_replay),
                )
                self.assertEqual(
                    report_for_session(via_broadcast),
                    report_for_session(via_single),
                )

    def test_collection_atomicity_and_empty_inputs(self):
        adapters, clients = _adapters_per_snapshot("dropoff_normal")

        result = poll_once_per_adapter_into_sessions(adapters, [])
        self.assertEqual(result, ())
        self.assertEqual([c.calls for c in clients], [0, 0, 0, 0, 0, 0])

        sessions = [CareSession(), CareSession()]
        result = poll_once_per_adapter_into_sessions([], sessions)
        self.assertEqual(result, (SessionState.IDLE, SessionState.IDLE))
        for session in sessions:
            self.assertEqual(session.history, [])

        adapters2, clients2 = _adapters_per_snapshot("dropoff_normal")
        sessions2 = [CareSession(), CareSession()]
        with self.assertRaises(NotImplementedError):
            poll_once_per_adapter_into_sessions(
                [adapters2[0], VehicleSdkAdapter(), adapters2[1]],
                sessions2,
            )
        for session in sessions2:
            self.assertIs(session.state, SessionState.IDLE)
            self.assertEqual(session.history, [])
        self.assertEqual(clients2[0].calls, 1)
        self.assertEqual(clients2[1].calls, 0)

    def test_report_log_aggregates_across_broadcast_sessions(self):
        sessions = []
        for name in SCENARIO_NAMES_3:
            adapters, _clients = _adapters_per_snapshot(name)
            pair = [CareSession(), CareSession()]
            poll_once_per_adapter_into_sessions(adapters, pair)
            sessions.extend(pair)

        log = CareReportLog()
        log.add_sessions(sessions)

        self.assertEqual(len(log), 6)
        self.assertEqual(log.completed_count, 4)
        self.assertEqual(log.sessions_with_exception, 2)
        self.assertEqual(log.total_exception_count, 2)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.average_duration_seconds, 280.0)


if __name__ == "__main__":
    unittest.main()

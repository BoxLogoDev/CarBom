"""poll_repeatedly_for_adapters_into_session 단일 세션 통합 QA.

195회차에 추가된
``poll_repeatedly_for_adapters_into_session(adapters, session, times)``가
고정 시나리오 3종을 어댑터 2개에 절반씩 나눠 읽은 뒤 어댑터 순서대로
flatten해 세션 하나에 이어서 적용하는 실제 통합 경로에서 쓸 수 있는지
검증한다. 이 경로로 구동한 세션의 안내·리포트·누적함 집계와 simulator
``replay_scenario`` 및 단일 어댑터 ``poll_repeatedly_into`` 경로와의
동등성, 수집 단계 원자성을 다룬다.
195회차 단위 테스트(PollRepeatedlyForAdaptersIntoSessionTest)는 최종
상태·빈 입력·음수/0회·미연결 전파만 다뤘고, 155회차의
``poll_repeatedly_for_adapters_into_sessions`` 통합 검증은 어댑터-세션
짝 적용 경로만 다뤄, 여러 어댑터의 스냅샷이 세션 하나에 이어서
적용되는 경로의 안내·리포트 연결은 검증하지 않았다.
"""

import unittest

from engine.adapters.simulator import replay_scenario, scenario_snapshots
from engine.adapters.vehicle_sdk import (
    VehicleSdkAdapter,
    poll_repeatedly_for_adapters_into_session,
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


def _split_adapters(name):
    """시나리오 스냅샷을 앞뒤 절반으로 나눠 어댑터 2개로 만든다."""
    raws = raws_from_snapshots(scenario_snapshots(name))
    half = len(raws) // 2
    clients = [
        FakeSequenceSdkClient(raws[:half]),
        FakeSequenceSdkClient(raws[half:]),
    ]
    adapters = [VehicleSdkAdapter(client) for client in clients]
    return adapters, clients, half


def _drive_split(name):
    adapters, clients, half = _split_adapters(name)
    session = CareSession()
    result = poll_repeatedly_for_adapters_into_session(
        adapters, session, half
    )
    return result, session, clients, half


def _history_key(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


def _report_key(session):
    report = report_for_session(session)
    return (
        report.final_state,
        report.completed,
        report.transition_count,
        report.duration_seconds,
    )


class PollRepeatedlyForAdaptersIntoSessionIntegrationQATest(
    unittest.TestCase
):
    def test_dropoff_normal_split_across_two_adapters(self):
        result, session, clients, half = _drive_split("dropoff_normal")

        self.assertEqual(half, 3)
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(result, session.state)
        self.assertEqual([c.calls for c in clients], [3, 3])
        self.assertEqual(len(session.history), 6)

        guidance = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_forgotten_rising_temp_split_across_two_adapters(self):
        result, session, clients, half = _drive_split(
            "forgotten_rising_temp"
        )

        self.assertEqual(half, 4)
        self.assertEqual(result, SessionState.EXCEPTION)
        self.assertEqual(result, session.state)
        self.assertEqual([c.calls for c in clients], [4, 4])
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

    def test_pet_dropoff_split_across_two_adapters(self):
        result, session, clients, half = _drive_split("pet_dropoff")

        self.assertEqual(half, 3)
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(result, session.state)
        self.assertEqual([c.calls for c in clients], [3, 3])
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

    def test_matches_replay_scenario_and_single_adapter_path(self):
        for name in ("dropoff_normal", "forgotten_rising_temp"):
            with self.subTest(name=name):
                _, split_session, _, _ = _drive_split(name)

                replay_session = CareSession()
                replay_scenario(replay_session, name)

                raws = raws_from_snapshots(scenario_snapshots(name))
                single_client = FakeSequenceSdkClient(raws)
                single_adapter = VehicleSdkAdapter(single_client)
                single_session = CareSession()
                single_result = single_adapter.poll_repeatedly_into(
                    single_session, len(raws)
                )
                self.assertEqual(single_result, single_session.state)
                self.assertEqual(single_client.calls, len(raws))

                self.assertEqual(
                    _history_key(split_session),
                    _history_key(replay_session),
                )
                self.assertEqual(
                    _history_key(split_session),
                    _history_key(single_session),
                )
                self.assertEqual(
                    _report_key(split_session),
                    _report_key(replay_session),
                )
                self.assertEqual(
                    _report_key(split_session),
                    _report_key(single_session),
                )

    def test_collection_atomicity_and_empty_inputs(self):
        session = CareSession()
        self.assertEqual(
            poll_repeatedly_for_adapters_into_session(
                [], session, 3
            ),
            SessionState.IDLE,
        )
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(session.history, [])

        unconnected_session = CareSession()
        self.assertEqual(
            poll_repeatedly_for_adapters_into_session(
                [VehicleSdkAdapter()], unconnected_session, 0
            ),
            SessionState.IDLE,
        )
        self.assertEqual(unconnected_session.history, [])

        with self.assertRaises(ValueError):
            poll_repeatedly_for_adapters_into_session(
                [], CareSession(), -1
            )

        raws = raws_from_snapshots(
            scenario_snapshots("dropoff_normal")
        )[:3]
        ok_client = FakeSequenceSdkClient(raws)
        ok_adapter = VehicleSdkAdapter(ok_client)
        bad_adapter = VehicleSdkAdapter()
        atomic_session = CareSession()
        with self.assertRaises(NotImplementedError):
            poll_repeatedly_for_adapters_into_session(
                [ok_adapter, bad_adapter], atomic_session, 3
            )
        self.assertEqual(ok_client.calls, 3)
        self.assertEqual(atomic_session.state, SessionState.IDLE)
        self.assertEqual(atomic_session.history, [])

    def test_care_report_log_aggregation(self):
        sessions = []
        for name in SCENARIO_NAMES_3:
            _, session, _, _ = _drive_split(name)
            sessions.append(session)

        log = CareReportLog()
        added = log.add_sessions(sessions)

        self.assertEqual(len(added), 3)
        self.assertEqual(len(log.reports), 3)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.average_duration_seconds, 280.0)


if __name__ == "__main__":
    unittest.main()

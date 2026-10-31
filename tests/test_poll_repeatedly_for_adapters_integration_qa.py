"""poll_repeatedly_for_adapters_into_sessions 통합 QA.

154회차에 추가된
``poll_repeatedly_for_adapters_into_sessions(adapters, sessions, times)``는
최종 상태·호출 횟수·음수/길이 검사만 단위 테스트됐다. 여러
어댑터·세션에 같은 횟수를 직접 적용한 뒤의 안내·리포트·누적함
흐름, 기준 경로(``replay_scenario``)와의 동등성, 수집 단계
원자성, 읽기 경로(``poll_snapshots_for_adapters`` + ``replay``)와의
동등성을 검증한다. 균일 횟수라 하차 깜빡 시나리오는 times=6이면
전체 8건 중 앞 6건만 적용돼 온도 상승 중간 단계의 EXCEPTION이다.
"""

import unittest

from engine.adapters.simulator import replay, replay_scenario, scenario_snapshots
from engine.adapters.vehicle_sdk import (
    VehicleSdkAdapter,
    poll_repeatedly_for_adapters_into_sessions,
    poll_snapshots_for_adapters,
    raws_from_snapshots,
)
from engine.guidance import (
    DestinationContext,
    GuidanceLevel,
    guidance_for_session,
)
from engine.report import CareReportLog, report_for_session
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
    client = FakeSequenceSdkClient(
        raws_from_snapshots(scenario_snapshots(name))
    )
    return VehicleSdkAdapter(client), client


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
        report.exception_count,
        report.transition_count,
        report.duration_seconds,
        report.max_cabin_temp_c,
    )


_SCENARIO_NAMES = ["dropoff_normal", "forgotten_rising_temp", "pet_dropoff"]


class PollRepeatedlyForAdaptersIntegrationQATest(unittest.TestCase):
    def test_uniform_apply_completes_and_exception_prefix(self):
        adapters, clients = [], []
        for name in _SCENARIO_NAMES:
            adapter, client = _adapter_for(name)
            adapters.append(adapter)
            clients.append(client)
        sessions = [CareSession() for _ in _SCENARIO_NAMES]
        result = poll_repeatedly_for_adapters_into_sessions(
            adapters, sessions, 6
        )
        self.assertEqual(result, tuple(s.state for s in sessions))
        self.assertEqual([c.calls for c in clients], [6, 6, 6])

        done = sessions[0]
        self.assertIs(done.state, SessionState.COMPLETED)
        self.assertEqual(len(done.history), 6)
        guidance = guidance_for_session(
            done, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        report = report_for_session(done)
        self.assertTrue(report.completed)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

        stuck = sessions[1]
        self.assertIs(stuck.state, SessionState.EXCEPTION)
        self.assertEqual(len(stuck.history), 5)
        self.assertTrue(stuck.passenger_present)
        guidance = guidance_for_session(
            stuck, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.reason, "passenger_left_locked")
        self.assertNotIn("35.5도", guidance.text)
        report = report_for_session(stuck)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.max_cabin_temp_c, 28.0)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

        pet = sessions[2]
        self.assertIs(pet.state, SessionState.COMPLETED)
        self.assertEqual(len(pet.history), 6)

    def test_uniform_apply_and_log_aggregates(self):
        adapters = [_adapter_for(name)[0] for name in _SCENARIO_NAMES]
        sessions = [CareSession() for _ in _SCENARIO_NAMES]
        poll_repeatedly_for_adapters_into_sessions(adapters, sessions, 6)
        self.assertEqual(
            [s.state for s in sessions],
            [
                SessionState.COMPLETED,
                SessionState.EXCEPTION,
                SessionState.COMPLETED,
            ],
        )
        log = CareReportLog()
        reports = log.add_sessions(sessions)
        self.assertEqual(len(log), 3)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(log.max_cabin_temp_c, 28.0)
        self.assertEqual(log.average_duration_seconds, 280.0)
        self.assertEqual(
            [r.final_state for r in reports],
            [s.state for s in sessions],
        )

    def test_full_forgotten_matches_replay_scenario_baseline(self):
        adapter, client = _adapter_for("forgotten_rising_temp")
        direct = CareSession()
        result = poll_repeatedly_for_adapters_into_sessions(
            [adapter], [direct], 8
        )
        self.assertEqual(result, (SessionState.EXCEPTION,))
        self.assertEqual(client.calls, 8)

        baseline = CareSession()
        replay_scenario(baseline, "forgotten_rising_temp")
        self.assertEqual(_history_key(direct), _history_key(baseline))
        self.assertEqual(_report_key(direct), _report_key(baseline))
        self.assertEqual(
            report_for_session(direct).max_cabin_temp_c, 35.5
        )
        guidance = guidance_for_session(
            direct, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)

    def test_partial_times_stops_at_driving(self):
        adapter, client = _adapter_for("dropoff_normal")
        session = CareSession()
        result = poll_repeatedly_for_adapters_into_sessions(
            [adapter], [session], 3
        )
        self.assertEqual(result, (SessionState.DRIVING,))
        self.assertEqual(client.calls, 3)
        self.assertEqual(len(session.history), 3)
        self.assertTrue(session.passenger_present)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")
        report = report_for_session(session)
        self.assertFalse(report.completed)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_unconnected_second_adapter_leaves_all_sessions_untouched(self):
        adapter, _client = _adapter_for("dropoff_normal")
        sessions = [CareSession(), CareSession()]
        with self.assertRaises(NotImplementedError):
            poll_repeatedly_for_adapters_into_sessions(
                [adapter, VehicleSdkAdapter()], sessions, 6
            )
        self.assertEqual(
            [s.state for s in sessions],
            [SessionState.IDLE, SessionState.IDLE],
        )
        self.assertEqual([len(s.history) for s in sessions], [0, 0])

    def test_matches_poll_snapshots_for_adapters_replay(self):
        read_adapters = [_adapter_for(name)[0] for name in _SCENARIO_NAMES]
        slices = poll_snapshots_for_adapters(read_adapters, 6)
        via_replay = [CareSession() for _ in _SCENARIO_NAMES]
        for session, snapshots in zip(via_replay, slices):
            replay(session, snapshots)

        direct_adapters = [_adapter_for(name)[0] for name in _SCENARIO_NAMES]
        direct_sessions = [CareSession() for _ in _SCENARIO_NAMES]
        result = poll_repeatedly_for_adapters_into_sessions(
            direct_adapters, direct_sessions, 6
        )
        self.assertEqual(result, tuple(s.state for s in via_replay))
        for direct, replayed in zip(direct_sessions, via_replay):
            self.assertEqual(_history_key(direct), _history_key(replayed))
            self.assertEqual(
                direct.passenger_present, replayed.passenger_present
            )
            self.assertEqual(_report_key(direct), _report_key(replayed))


if __name__ == "__main__":
    unittest.main()

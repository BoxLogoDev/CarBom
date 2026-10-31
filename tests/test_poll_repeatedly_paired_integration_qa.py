"""poll_repeatedly_paired_into_sessions 짝 반복 poll 적용 통합 QA.

140회차에 추가된 ``poll_repeatedly_paired_into_sessions(adapters,
sessions, times_list)``는 최종 상태·호출 횟수·길이 불일치/음수·미연결
실패만 단위 테스트됐다. 서로 다른 어댑터를 서로 다른 횟수로 구동한
세션들의 안내·리포트·누적함 집계와, 기준 재생 경로 및 읽기 전용
슬라이스 경로와의 동등성을 검증한다.
"""

import unittest

from engine.adapters.simulator import replay, replay_scenario, scenario_snapshots
from engine.adapters.vehicle_sdk import (
    VehicleSdkAdapter,
    poll_repeatedly_paired_into_sessions,
    poll_snapshots_paired,
    raws_from_snapshots,
)
from engine.guidance import (
    DestinationContext,
    GuidanceLevel,
    guidance_for_session,
)
from engine.report import CareReportLog, report_for_session, reports_for_sessions
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


class PollRepeatedlyPairedIntegrationQATest(unittest.TestCase):
    def test_paired_times_drive_completed_and_exception(self):
        adapter_a, client_a = _adapter_for("dropoff_normal")
        adapter_b, client_b = _adapter_for("forgotten_rising_temp")
        sessions = [CareSession(), CareSession()]
        result = poll_repeatedly_paired_into_sessions(
            [adapter_a, adapter_b], sessions, [6, 8]
        )
        self.assertEqual(
            result, (SessionState.COMPLETED, SessionState.EXCEPTION)
        )
        self.assertEqual(result, tuple(s.state for s in sessions))
        self.assertEqual((client_a.calls, client_b.calls), (6, 8))

        done, stuck = sessions
        self.assertEqual(len(done.history), 6)
        guidance = guidance_for_session(
            done, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        report = report_for_session(done)
        self.assertTrue(report.completed)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

        self.assertEqual(len(stuck.history), 5)
        self.assertTrue(stuck.passenger_present)
        guidance = guidance_for_session(
            stuck, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)
        report = report_for_session(stuck)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_three_scenarios_and_log_aggregates(self):
        names = ["dropoff_normal", "forgotten_rising_temp", "pet_dropoff"]
        adapters, clients = [], []
        for name in names:
            adapter, client = _adapter_for(name)
            adapters.append(adapter)
            clients.append(client)
        sessions = [CareSession() for _ in names]
        result = poll_repeatedly_paired_into_sessions(
            adapters, sessions, [6, 8, 6]
        )
        self.assertEqual(
            result,
            (
                SessionState.COMPLETED,
                SessionState.EXCEPTION,
                SessionState.COMPLETED,
            ),
        )
        self.assertEqual([c.calls for c in clients], [6, 8, 6])
        self.assertEqual(sum(c.calls for c in clients), 20)

        log = CareReportLog()
        reports = log.add_sessions(sessions)
        self.assertEqual(reports, reports_for_sessions(sessions))
        self.assertEqual(len(log), 3)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.average_duration_seconds, 280.0)

    def test_partial_and_zero_times(self):
        adapter_a, client_a = _adapter_for("dropoff_normal")
        sessions = [CareSession(), CareSession()]
        result = poll_repeatedly_paired_into_sessions(
            [adapter_a, VehicleSdkAdapter()], sessions, [3, 0]
        )
        self.assertEqual(result, (SessionState.DRIVING, SessionState.IDLE))
        self.assertEqual(client_a.calls, 3)
        self.assertEqual(len(sessions[0].history), 3)
        self.assertEqual(len(sessions[1].history), 0)
        guidance = guidance_for_session(
            sessions[0], context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")
        self.assertFalse(report_for_session(sessions[0]).completed)

    def test_matches_replay_scenario_baseline(self):
        adapters = [
            _adapter_for("dropoff_normal")[0],
            _adapter_for("forgotten_rising_temp")[0],
        ]
        direct = [CareSession(), CareSession()]
        poll_repeatedly_paired_into_sessions(adapters, direct, [6, 8])

        baseline = [CareSession(), CareSession()]
        for session, name in zip(
            baseline, ("dropoff_normal", "forgotten_rising_temp")
        ):
            replay_scenario(session, name)
        for driven, base in zip(direct, baseline):
            self.assertEqual(driven.state, base.state)
            self.assertEqual(driven.passenger_present, base.passenger_present)
            self.assertEqual(_history_key(driven), _history_key(base))
            self.assertEqual(_report_key(driven), _report_key(base))

    def test_matches_poll_snapshots_paired_replay(self):
        read_adapters = [
            _adapter_for("dropoff_normal")[0],
            _adapter_for("forgotten_rising_temp")[0],
        ]
        slices = poll_snapshots_paired(read_adapters, [6, 8])
        via_replay = [CareSession(), CareSession()]
        for session, snapshots in zip(via_replay, slices):
            replay(session, snapshots)

        adapters = [
            _adapter_for("dropoff_normal")[0],
            _adapter_for("forgotten_rising_temp")[0],
        ]
        direct = [CareSession(), CareSession()]
        result = poll_repeatedly_paired_into_sessions(
            adapters, direct, [6, 8]
        )
        self.assertEqual(result, tuple(s.state for s in via_replay))
        for driven, replayed in zip(direct, via_replay):
            self.assertEqual(_history_key(driven), _history_key(replayed))
            self.assertEqual(_report_key(driven), _report_key(replayed))

    def test_zero_entry_between_completed_sessions(self):
        adapter_a, client_a = _adapter_for("dropoff_normal")
        adapter_c, client_c = _adapter_for("pet_dropoff")
        sessions = [CareSession() for _ in range(3)]
        result = poll_repeatedly_paired_into_sessions(
            [adapter_a, VehicleSdkAdapter(), adapter_c],
            sessions,
            [6, 0, 6],
        )
        self.assertEqual(
            result,
            (
                SessionState.COMPLETED,
                SessionState.IDLE,
                SessionState.COMPLETED,
            ),
        )
        self.assertEqual([len(s.history) for s in sessions], [6, 0, 6])
        self.assertEqual(client_a.calls + client_c.calls, 12)


if __name__ == "__main__":
    unittest.main()

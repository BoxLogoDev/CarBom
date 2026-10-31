"""poll_snapshots_for_adapters 균일 횟수 스냅샷 읽기 헬퍼 통합 QA.

151회차에 추가된 ``poll_snapshots_for_adapters(adapters, times)``는
호출 횟수·순서·타입·음수/0회/미연결만 단위 테스트됐다. 여러
어댑터에서 같은 횟수로 가져온 슬라이스들의 재생·재사용·읽기
전용성과 짝 직접 적용 헬퍼
``poll_repeatedly_paired_into_sessions``(균일 횟수 리스트)와의
동등성을 검증한다. 균일 횟수라 하차 깜빡 시나리오는 전체
8건 중 앞 6건만 읽히므로, 재생 결과는 온도 상승 중간 단계의
EXCEPTION이다.
"""

import unittest

from engine.adapters.simulator import replay, scenario_snapshots
from engine.adapters.vehicle_sdk import (
    VehicleSdkAdapter,
    poll_repeatedly_paired_into_sessions,
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


_SCENARIO_NAMES = ["dropoff_normal", "forgotten_rising_temp", "pet_dropoff"]


class PollSnapshotsForAdaptersIntegrationQATest(unittest.TestCase):
    def test_uniform_slices_replay_to_completed_and_exception_prefix(self):
        adapters, clients = [], []
        for name in _SCENARIO_NAMES:
            adapter, client = _adapter_for(name)
            adapters.append(adapter)
            clients.append(client)
        slices = poll_snapshots_for_adapters(adapters, 6)
        self.assertEqual([len(s) for s in slices], [6, 6, 6])
        self.assertEqual([c.calls for c in clients], [6, 6, 6])

        done = CareSession()
        self.assertIs(replay(done, slices[0]), SessionState.COMPLETED)
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

        stuck = CareSession()
        self.assertIs(replay(stuck, slices[1]), SessionState.EXCEPTION)
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

        pet = CareSession()
        self.assertIs(replay(pet, slices[2]), SessionState.COMPLETED)
        self.assertEqual(len(pet.history), 6)

    def test_three_scenarios_replay_and_log_aggregates(self):
        adapters = [_adapter_for(name)[0] for name in _SCENARIO_NAMES]
        slices = poll_snapshots_for_adapters(adapters, 6)
        sessions = []
        for snapshots in slices:
            session = CareSession()
            replay(session, snapshots)
            sessions.append(session)
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

    def test_poll_is_read_only_for_existing_session(self):
        existing = CareSession()
        replay(existing, scenario_snapshots("dropoff_normal")[:1])
        self.assertIs(existing.state, SessionState.BOARDING)
        before = (
            existing.state,
            _history_key(existing),
            existing.current_snapshot,
        )
        adapter, client = _adapter_for("pet_dropoff")
        slices = poll_snapshots_for_adapters([adapter], 6)
        self.assertEqual(len(slices[0]), 6)
        self.assertEqual(client.calls, 6)
        after = (
            existing.state,
            _history_key(existing),
            existing.current_snapshot,
        )
        self.assertEqual(before, after)

    def test_slices_are_reusable_across_sessions(self):
        adapter, _client = _adapter_for("forgotten_rising_temp")
        (snapshots,) = poll_snapshots_for_adapters([adapter], 6)
        first, second = CareSession(), CareSession()
        replay(first, snapshots)
        replay(second, snapshots)
        self.assertIs(first.state, SessionState.EXCEPTION)
        self.assertIs(second.state, first.state)
        self.assertEqual(_history_key(second), _history_key(first))
        self.assertEqual(
            report_for_session(second).max_cabin_temp_c,
            report_for_session(first).max_cabin_temp_c,
        )
        self.assertEqual(report_for_session(first).max_cabin_temp_c, 28.0)

    def test_matches_poll_repeatedly_paired_into_sessions_uniform(self):
        read_adapters = [_adapter_for(name)[0] for name in _SCENARIO_NAMES]
        slices = poll_snapshots_for_adapters(read_adapters, 6)
        via_replay = [CareSession() for _ in _SCENARIO_NAMES]
        for session, snapshots in zip(via_replay, slices):
            replay(session, snapshots)

        direct_adapters, direct_clients = [], []
        for name in _SCENARIO_NAMES:
            adapter, client = _adapter_for(name)
            direct_adapters.append(adapter)
            direct_clients.append(client)
        direct_sessions = [CareSession() for _ in _SCENARIO_NAMES]
        result = poll_repeatedly_paired_into_sessions(
            direct_adapters, direct_sessions, [6, 6, 6]
        )
        self.assertEqual(result, tuple(s.state for s in via_replay))
        self.assertEqual([c.calls for c in direct_clients], [6, 6, 6])
        for direct, replayed in zip(direct_sessions, via_replay):
            self.assertEqual(_history_key(direct), _history_key(replayed))
            self.assertEqual(
                direct.passenger_present, replayed.passenger_present
            )
            direct_report = report_for_session(direct)
            replay_report = report_for_session(replayed)
            self.assertEqual(
                (
                    direct_report.final_state,
                    direct_report.completed,
                    direct_report.exception_count,
                    direct_report.transition_count,
                    direct_report.duration_seconds,
                    direct_report.max_cabin_temp_c,
                ),
                (
                    replay_report.final_state,
                    replay_report.completed,
                    replay_report.exception_count,
                    replay_report.transition_count,
                    replay_report.duration_seconds,
                    replay_report.max_cabin_temp_c,
                ),
            )

    def test_zero_times_reads_nothing_and_replay_keeps_idle(self):
        adapter_a, client_a = _adapter_for("dropoff_normal")
        adapter_c, client_c = _adapter_for("pet_dropoff")
        slices = poll_snapshots_for_adapters(
            [adapter_a, VehicleSdkAdapter(), adapter_c], 0
        )
        self.assertEqual(slices, ((), (), ()))
        self.assertEqual(client_a.calls + client_c.calls, 0)
        sessions = []
        for snapshots in slices:
            session = CareSession()
            replay(session, snapshots)
            sessions.append(session)
        self.assertEqual(
            [s.state for s in sessions],
            [SessionState.IDLE, SessionState.IDLE, SessionState.IDLE],
        )
        self.assertEqual([len(s.history) for s in sessions], [0, 0, 0])


if __name__ == "__main__":
    unittest.main()

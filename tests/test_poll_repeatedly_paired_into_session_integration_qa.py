"""poll_repeatedly_paired_into_session 단일 세션 짝 횟수 통합 QA.

203회차에 추가된 ``poll_repeatedly_paired_into_session(adapters,
session, times_list)``는 최종 상태·호출 횟수·길이 불일치/음수·미연결
전파만 단위 테스트됐다. 서로 다른 어댑터를 서로 다른 횟수로 한
세션에 이어 적용했을 때의 안내·리포트·누적함 집계와, 기준 재생
경로 및 읽기 전용 짝 슬라이스 경로와의 동등성을 검증한다.
"""

import unittest

from engine.adapters.simulator import replay, replay_scenario, scenario_snapshots
from engine.adapters.vehicle_sdk import (
    VehicleSdkAdapter,
    poll_repeatedly_paired_into_session,
    poll_snapshots_paired,
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


def _adapter(raws):
    client = FakeSequenceSdkClient(raws)
    return VehicleSdkAdapter(client), client


def _split(name, cut):
    raws = raws_from_snapshots(scenario_snapshots(name))
    first, client_first = _adapter(raws[:cut])
    second, client_second = _adapter(raws[cut:])
    return [first, second], [client_first, client_second], [cut, len(raws) - cut]


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
        report.summary,
    )


class PollRepeatedlyPairedIntoSessionIntegrationQATest(unittest.TestCase):
    def test_dropoff_split_completes(self):
        adapters, clients, times = _split("dropoff_normal", 3)
        session = CareSession()
        result = poll_repeatedly_paired_into_session(adapters, session, times)
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual([c.calls for c in clients], [3, 3])
        self.assertEqual(len(session.history), 6)
        guidance = guidance_for_session(session, context=DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_forgotten_split_exception(self):
        adapters, clients, times = _split("forgotten_rising_temp", 4)
        session = CareSession()
        result = poll_repeatedly_paired_into_session(adapters, session, times)
        self.assertEqual(result, SessionState.EXCEPTION)
        self.assertEqual([c.calls for c in clients], [4, 4])
        self.assertEqual(len(session.history), 5)
        self.assertTrue(session.passenger_present)
        guidance = guidance_for_session(session, context=DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason, "passenger_left_locked_dangerous_cabin_temp"
        )
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)
        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.duration_seconds, 240.0)

    def test_pet_split_and_log_aggregates(self):
        adapters, clients, times = _split("pet_dropoff", 2)
        pet_session = CareSession()
        result = poll_repeatedly_paired_into_session(
            adapters, pet_session, times
        )
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual([c.calls for c in clients], [2, 4])
        self.assertEqual(len(pet_session.history), 6)

        sessions = []
        for name, cut in (
            ("dropoff_normal", 3),
            ("forgotten_rising_temp", 4),
            ("pet_dropoff", 2),
        ):
            adapters, _clients, times = _split(name, cut)
            session = CareSession()
            poll_repeatedly_paired_into_session(adapters, session, times)
            sessions.append(session)
        log = CareReportLog()
        log.add_sessions(sessions)
        self.assertEqual(len(log.reports), 3)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.average_duration_seconds, 280.0)

    def test_partial_application(self):
        raws = raws_from_snapshots(scenario_snapshots("dropoff_normal"))
        first, client_first = _adapter(raws[:3])
        empty, client_empty = _adapter([])
        session = CareSession()
        result = poll_repeatedly_paired_into_session(
            [first, empty], session, [3, 0]
        )
        self.assertEqual(result, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)
        self.assertEqual(client_first.calls, 3)
        self.assertEqual(client_empty.calls, 0)
        guidance = guidance_for_session(session, context=DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")

    def test_matches_baseline_and_readonly_paths(self):
        adapters, _clients, times = _split("forgotten_rising_temp", 4)
        session = CareSession()
        poll_repeatedly_paired_into_session(adapters, session, times)

        baseline = CareSession()
        replay_scenario(baseline, "forgotten_rising_temp")

        adapters2, _c2, times2 = _split("forgotten_rising_temp", 4)
        slices = poll_snapshots_paired(adapters2, times2)
        readonly = CareSession()
        replay(readonly, [snap for part in slices for snap in part])

        for other in (baseline, readonly):
            self.assertEqual(_history_key(session), _history_key(other))
            self.assertEqual(session.current_snapshot, other.current_snapshot)
            self.assertEqual(_report_key(session), _report_key(other))
            self.assertEqual(
                guidance_for_session(session, context=DestinationContext.DROPOFF),
                guidance_for_session(other, context=DestinationContext.DROPOFF),
            )

    def test_generator_inputs(self):
        adapters, clients, times = _split("dropoff_normal", 3)
        session = CareSession()
        result = poll_repeatedly_paired_into_session(
            (a for a in adapters), session, (t for t in times)
        )
        self.assertEqual(result, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        self.assertEqual([c.calls for c in clients], [3, 3])
        self.assertEqual(_report_key(session)[-1], "하차 확인 완료 · 예외 없음")


if __name__ == "__main__":
    unittest.main()

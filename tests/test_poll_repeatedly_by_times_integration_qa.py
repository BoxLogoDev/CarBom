"""poll_repeatedly_into_sessions_by_times 짝 횟수 반복 poll 통합 QA.

116회차에 추가된 ``poll_repeatedly_into_sessions_by_times``는 호출
횟수·짝 슬라이스·길이 불일치/음수·미연결만 단위 테스트됐다. 짝 횟수로
구동한 세션들의 안내·리포트·누적함 집계와 기준 재생 경로
(``replay_scenario``, ``poll_snapshots_by_times`` 슬라이스 재생)와의
동등성을 검증한다.
"""

import unittest

from engine.adapters.simulator import replay, replay_scenario, scenario_snapshots
from engine.adapters.vehicle_sdk import (
    VehicleSdkAdapter,
    poll_repeatedly_into_sessions_by_times,
    poll_snapshots_by_times,
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


def _adapter_for(names):
    raws = []
    for name in names:
        raws += list(raws_from_snapshots(scenario_snapshots(name)))
    client = FakeSequenceSdkClient(raws)
    return VehicleSdkAdapter(client), client


def _history_key(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


class PollRepeatedlyByTimesIntegrationQATest(unittest.TestCase):
    def test_paired_times_drive_to_completed_and_exception(self):
        adapter, client = _adapter_for(
            ["dropoff_normal", "forgotten_rising_temp"]
        )
        sessions = [CareSession(), CareSession()]
        finals = poll_repeatedly_into_sessions_by_times(
            adapter, sessions, [6, 8]
        )
        self.assertEqual(client.calls, 14)
        self.assertEqual(
            finals, (SessionState.COMPLETED, SessionState.EXCEPTION)
        )
        self.assertEqual(
            finals, tuple(session.state for session in sessions)
        )

        dropoff = sessions[0]
        self.assertEqual(len(dropoff.history), 6)
        self.assertFalse(dropoff.passenger_present)
        guidance = guidance_for_session(
            dropoff, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        report = report_for_session(dropoff)
        self.assertTrue(report.completed)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

        forgotten = sessions[1]
        self.assertEqual(len(forgotten.history), 5)
        self.assertTrue(forgotten.passenger_present)
        guidance = guidance_for_session(
            forgotten, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)
        report = report_for_session(forgotten)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_three_scenarios_aggregate_in_report_log(self):
        adapter, client = _adapter_for(
            ["dropoff_normal", "forgotten_rising_temp", "pet_dropoff"]
        )
        sessions = [CareSession() for _ in range(3)]
        finals = poll_repeatedly_into_sessions_by_times(
            adapter, sessions, [6, 8, 6]
        )
        self.assertEqual(client.calls, 20)
        self.assertEqual(
            finals,
            (
                SessionState.COMPLETED,
                SessionState.EXCEPTION,
                SessionState.COMPLETED,
            ),
        )

        log = CareReportLog()
        returned = log.add_sessions(sessions)
        self.assertEqual(returned, log.reports)
        self.assertEqual(len(log.reports), 3)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.average_duration_seconds, 280.0)

    def test_partial_and_zero_times(self):
        adapter, client = _adapter_for(["dropoff_normal"])
        sessions = [CareSession(), CareSession()]
        finals = poll_repeatedly_into_sessions_by_times(
            adapter, sessions, [3, 0]
        )
        self.assertEqual(client.calls, 3)
        self.assertEqual(
            finals, (SessionState.DRIVING, SessionState.IDLE)
        )

        partial = sessions[0]
        self.assertEqual(len(partial.history), 3)
        guidance = guidance_for_session(
            partial, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")
        self.assertFalse(report_for_session(partial).completed)

        untouched = sessions[1]
        self.assertEqual(len(untouched.history), 0)
        self.assertFalse(untouched.passenger_present)

    def test_matches_replay_scenario_baseline(self):
        adapter, client = _adapter_for(
            ["dropoff_normal", "forgotten_rising_temp"]
        )
        sessions = [CareSession(), CareSession()]
        poll_repeatedly_into_sessions_by_times(adapter, sessions, [6, 8])
        self.assertEqual(client.calls, 14)

        for session, name in zip(
            sessions, ["dropoff_normal", "forgotten_rising_temp"]
        ):
            baseline = CareSession()
            replay_scenario(baseline, name)
            self.assertIs(session.state, baseline.state)
            self.assertEqual(_history_key(session), _history_key(baseline))
            self.assertEqual(
                session.passenger_present, baseline.passenger_present
            )
            driven = report_for_session(session)
            expected = report_for_session(baseline)
            self.assertEqual(driven.final_state, expected.final_state)
            self.assertEqual(driven.completed, expected.completed)
            self.assertEqual(
                driven.exception_count, expected.exception_count
            )
            self.assertEqual(
                driven.transition_count, expected.transition_count
            )
            self.assertEqual(
                driven.duration_seconds, expected.duration_seconds
            )
            self.assertEqual(
                driven.max_cabin_temp_c, expected.max_cabin_temp_c
            )

    def test_matches_poll_snapshots_by_times_replay(self):
        names = ["dropoff_normal", "forgotten_rising_temp"]
        read_adapter, read_client = _adapter_for(names)
        sequences = poll_snapshots_by_times(read_adapter, [6, 8])
        self.assertEqual(read_client.calls, 14)
        via_replay = [CareSession(), CareSession()]
        replay_finals = [
            replay(session, sequence)
            for session, sequence in zip(via_replay, sequences)
        ]

        direct_adapter, direct_client = _adapter_for(names)
        via_poll = [CareSession(), CareSession()]
        direct_finals = poll_repeatedly_into_sessions_by_times(
            direct_adapter, via_poll, [6, 8]
        )
        self.assertEqual(direct_client.calls, 14)
        self.assertEqual(direct_finals, tuple(replay_finals))

        for replay_session, poll_session in zip(via_replay, via_poll):
            self.assertIs(replay_session.state, poll_session.state)
            self.assertEqual(
                _history_key(replay_session), _history_key(poll_session)
            )
            replay_report = report_for_session(replay_session)
            poll_report = report_for_session(poll_session)
            self.assertEqual(
                replay_report.final_state, poll_report.final_state
            )
            self.assertEqual(replay_report.completed, poll_report.completed)
            self.assertEqual(
                replay_report.transition_count,
                poll_report.transition_count,
            )
            self.assertEqual(
                replay_report.duration_seconds,
                poll_report.duration_seconds,
            )

    def test_zero_times_session_unchanged_between_completed(self):
        adapter, client = _adapter_for(["dropoff_normal", "pet_dropoff"])
        sessions = [CareSession() for _ in range(3)]
        finals = poll_repeatedly_into_sessions_by_times(
            adapter, sessions, [6, 0, 6]
        )
        self.assertEqual(client.calls, 12)
        self.assertEqual(
            finals,
            (
                SessionState.COMPLETED,
                SessionState.IDLE,
                SessionState.COMPLETED,
            ),
        )
        self.assertEqual(
            [len(session.history) for session in sessions], [6, 0, 6]
        )


if __name__ == "__main__":
    unittest.main()

"""poll_snapshots_by_times 짝 읽기 헬퍼 통합 QA.

118회차에 추가된 ``poll_snapshots_by_times(adapter, times_list)``는
호출 횟수·순서·타입·음수/0회/미연결만 단위 테스트됐다. 가져온
슬라이스들의 재생·재사용·읽기 전용성과 짝 직접 적용 헬퍼
``poll_repeatedly_into_sessions_by_times``와의 동등성을 검증한다.
"""

import unittest

from engine.adapters.simulator import replay, scenario_snapshots
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


class PollSnapshotsByTimesIntegrationQATest(unittest.TestCase):
    def test_paired_slices_replay_to_completed_and_exception(self):
        adapter, client = _adapter_for(
            ["dropoff_normal", "forgotten_rising_temp"]
        )
        sequences = poll_snapshots_by_times(adapter, [6, 8])
        self.assertEqual(client.calls, 14)
        self.assertEqual([len(s) for s in sequences], [6, 8])

        dropoff = CareSession()
        self.assertIs(
            replay(dropoff, sequences[0]), SessionState.COMPLETED
        )
        self.assertEqual(len(dropoff.history), 6)
        guidance = guidance_for_session(
            dropoff, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        report = report_for_session(dropoff)
        self.assertTrue(report.completed)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

        forgotten = CareSession()
        self.assertIs(
            replay(forgotten, sequences[1]), SessionState.EXCEPTION
        )
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

    def test_three_scenarios_aggregate_in_report_log(self):
        adapter, client = _adapter_for(
            ["dropoff_normal", "forgotten_rising_temp", "pet_dropoff"]
        )
        sequences = poll_snapshots_by_times(adapter, [6, 8, 6])
        self.assertEqual(client.calls, 20)

        sessions = []
        finals = []
        for sequence in sequences:
            session = CareSession()
            finals.append(replay(session, sequence))
            sessions.append(session)
        self.assertEqual(
            finals,
            [
                SessionState.COMPLETED,
                SessionState.EXCEPTION,
                SessionState.COMPLETED,
            ],
        )

        log = CareReportLog()
        log.add_sessions(sessions)
        self.assertEqual(len(log.reports), 3)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.average_duration_seconds, 280.0)

    def test_poll_snapshots_by_times_does_not_touch_existing_session(self):
        existing = CareSession()
        replay(existing, scenario_snapshots("dropoff_normal")[:1])
        before_state = existing.state
        before_history = _history_key(existing)
        before_snapshot = existing.current_snapshot

        adapter, client = _adapter_for(
            ["dropoff_normal", "forgotten_rising_temp"]
        )
        poll_snapshots_by_times(adapter, [6, 8])

        self.assertEqual(client.calls, 14)
        self.assertIs(existing.state, before_state)
        self.assertEqual(_history_key(existing), before_history)
        self.assertEqual(existing.current_snapshot, before_snapshot)

    def test_slices_are_reusable_across_sessions(self):
        adapter, _ = _adapter_for(
            ["dropoff_normal", "forgotten_rising_temp"]
        )
        sequences = poll_snapshots_by_times(adapter, [6, 8])

        for sequence, expected in zip(
            sequences, [SessionState.COMPLETED, SessionState.EXCEPTION]
        ):
            first = CareSession()
            second = CareSession()
            self.assertIs(replay(first, sequence), expected)
            self.assertIs(replay(second, sequence), expected)
            self.assertEqual(_history_key(first), _history_key(second))
            self.assertEqual(
                report_for_session(first).max_cabin_temp_c,
                report_for_session(second).max_cabin_temp_c,
            )

    def test_replay_matches_poll_repeatedly_into_sessions_by_times(self):
        adapter, _ = _adapter_for(
            ["dropoff_normal", "forgotten_rising_temp"]
        )
        sequences = poll_snapshots_by_times(adapter, [6, 8])
        via_replay = [CareSession(), CareSession()]
        replay_finals = [
            replay(session, sequence)
            for session, sequence in zip(via_replay, sequences)
        ]

        direct_adapter, direct_client = _adapter_for(
            ["dropoff_normal", "forgotten_rising_temp"]
        )
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

    def test_zero_slice_replays_to_idle_between_completed(self):
        adapter, client = _adapter_for(["dropoff_normal", "pet_dropoff"])
        sequences = poll_snapshots_by_times(adapter, [6, 0, 6])
        self.assertEqual(client.calls, 12)
        self.assertEqual([len(s) for s in sequences], [6, 0, 6])
        self.assertEqual(sequences[1], ())

        finals = []
        histories = []
        for sequence in sequences:
            session = CareSession()
            finals.append(replay(session, sequence))
            histories.append(len(session.history))
        self.assertEqual(
            finals,
            [
                SessionState.COMPLETED,
                SessionState.IDLE,
                SessionState.COMPLETED,
            ],
        )
        self.assertEqual(histories, [6, 0, 6])


if __name__ == "__main__":
    unittest.main()

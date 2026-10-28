"""poll_snapshots 읽기 전용 헬퍼 통합 QA.

82회차에 추가된 ``poll_snapshots(adapter, times)``가 고정 시나리오
3종에서 실제로 쓸 수 있는 스냅샷 시퀀스를 돌려주는지, 그 결과를
simulator ``replay``로 세션에 재생하면 ``poll_repeatedly_into``로
직접 적용한 것과 같은 결과가 되는지를 검증한다.
기존 PollSnapshotsTest는 호출 횟수·순서·타입·음수/0회/미연결만 다뤄,
가져온 스냅샷의 재생·재사용·읽기 전용성은 검증하지 않았다.
"""

import unittest

from engine.adapters.simulator import replay, scenario_snapshots
from engine.adapters.vehicle_sdk import (
    VehicleSdkAdapter,
    poll_snapshots,
    raws_from_snapshots,
)
from engine.guidance import (
    DestinationContext,
    GuidanceLevel,
    guidance_for_session,
)
from engine.report import report_for_session
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


class PollSnapshotsIntegrationQATest(unittest.TestCase):
    def test_dropoff_normal_snapshots_replay_to_completed(self):
        adapter, client = _adapter_for("dropoff_normal")
        snapshots = poll_snapshots(adapter, 6)
        self.assertEqual(client.calls, 6)

        session = CareSession()
        final = replay(session, snapshots)
        self.assertIs(final, SessionState.COMPLETED)
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

    def test_forgotten_snapshots_replay_to_exception(self):
        adapter, client = _adapter_for("forgotten_rising_temp")
        snapshots = poll_snapshots(adapter, 8)
        self.assertEqual(client.calls, 8)

        session = CareSession()
        final = replay(session, snapshots)
        self.assertIs(final, SessionState.EXCEPTION)
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

    def test_pet_snapshots_replay_to_completed(self):
        adapter, client = _adapter_for("pet_dropoff")
        snapshots = poll_snapshots(adapter, 6)
        self.assertEqual(client.calls, 6)

        session = CareSession()
        final = replay(session, snapshots)
        self.assertIs(final, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        self.assertFalse(session.passenger_present)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)

    def test_poll_snapshots_does_not_touch_existing_session(self):
        existing = CareSession()
        replay(existing, scenario_snapshots("dropoff_normal")[:1])
        before_state = existing.state
        before_history = _history_key(existing)
        before_snapshot = existing.current_snapshot

        adapter, client = _adapter_for("dropoff_normal")
        poll_snapshots(adapter, 6)

        self.assertEqual(client.calls, 6)
        self.assertIs(existing.state, before_state)
        self.assertEqual(_history_key(existing), before_history)
        self.assertEqual(existing.current_snapshot, before_snapshot)

    def test_snapshots_are_reusable_across_sessions(self):
        adapter, _ = _adapter_for("forgotten_rising_temp")
        snapshots = poll_snapshots(adapter, 8)

        first = CareSession()
        second = CareSession()
        self.assertIs(replay(first, snapshots), SessionState.EXCEPTION)
        self.assertIs(replay(second, snapshots), SessionState.EXCEPTION)
        self.assertEqual(_history_key(first), _history_key(second))
        self.assertEqual(
            report_for_session(first).max_cabin_temp_c,
            report_for_session(second).max_cabin_temp_c,
        )

    def test_replay_matches_poll_repeatedly_into_and_partial(self):
        adapter, _ = _adapter_for("dropoff_normal")
        snapshots = poll_snapshots(adapter, 6)
        via_replay = CareSession()
        replay(via_replay, snapshots)

        direct_adapter, direct_client = _adapter_for("dropoff_normal")
        via_poll = CareSession()
        final = direct_adapter.poll_repeatedly_into(via_poll, 6)
        self.assertEqual(direct_client.calls, 6)
        self.assertIs(final, SessionState.COMPLETED)
        self.assertIs(via_poll.state, via_replay.state)
        self.assertEqual(_history_key(via_poll), _history_key(via_replay))

        replay_report = report_for_session(via_replay)
        poll_report = report_for_session(via_poll)
        self.assertEqual(replay_report.final_state, poll_report.final_state)
        self.assertEqual(replay_report.completed, poll_report.completed)
        self.assertEqual(
            replay_report.transition_count, poll_report.transition_count
        )
        self.assertEqual(
            replay_report.duration_seconds, poll_report.duration_seconds
        )

        partial = CareSession()
        self.assertIs(
            replay(partial, snapshots[:3]), SessionState.DRIVING
        )
        self.assertEqual(len(partial.history), 3)


if __name__ == "__main__":
    unittest.main()

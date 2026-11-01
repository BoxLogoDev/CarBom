"""poll_snapshot 단건 읽기 헬퍼 통합 QA.

177회차에 추가된 ``poll_snapshot(adapter)``가 고정 시나리오 3종에서
실제로 쓸 수 있는 스냅샷을 1건씩 돌려주는지, 단건 읽기를 반복해
모으거나 ``apply_snapshot``으로 단계마다 적용하면 대량 경로와 같은
결과가 되는지, 읽은 스냅샷 1건을 여러 세션이 공유할 수 있는지를
검증한다.
기존 PollSnapshotTest는 호출 횟수·타입·미연결·기존 세션 불변만
다뤘고, 84회차 통합 검증은 ``poll_snapshots`` 대량 읽기 경로만
다뤄, 단건 읽기의 반복·단계 적용·공유는 검증하지 않았다.
"""

import unittest

from engine.adapters.simulator import replay, scenario_snapshots
from engine.adapters.vehicle_sdk import (
    VehicleSdkAdapter,
    poll_snapshot,
    poll_snapshots,
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
    raws = raws_from_snapshots(scenario_snapshots(name))
    client = FakeSequenceSdkClient(raws)
    return VehicleSdkAdapter(client), client


def _history_key(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


def _read_all(adapter, count):
    return tuple(poll_snapshot(adapter) for _ in range(count))


def _drive_stepwise(name, count):
    adapter, client = _adapter_for(name)
    session = CareSession()
    for _ in range(count):
        session.apply_snapshot(poll_snapshot(adapter))
    return session, client


class PollSnapshotIntegrationQATest(unittest.TestCase):
    def test_repeated_single_reads_replay_dropoff_normal(self):
        adapter, client = _adapter_for("dropoff_normal")
        snapshots = _read_all(adapter, 6)

        self.assertEqual(client.calls, 6)
        self.assertEqual(snapshots, scenario_snapshots("dropoff_normal"))

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

    def test_repeated_single_reads_replay_forgotten_exception(self):
        adapter, client = _adapter_for("forgotten_rising_temp")
        snapshots = _read_all(adapter, 8)

        self.assertEqual(client.calls, 8)
        self.assertEqual(
            snapshots, scenario_snapshots("forgotten_rising_temp")
        )

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

    def test_stepwise_single_reads_progress_through_states(self):
        adapter, client = _adapter_for("dropoff_normal")
        session = CareSession()
        states = tuple(
            session.apply_snapshot(poll_snapshot(adapter))
            for _ in range(6)
        )

        self.assertEqual(client.calls, 6)
        self.assertEqual(
            states,
            (
                SessionState.BOARDING,
                SessionState.ONBOARD,
                SessionState.DRIVING,
                SessionState.ARRIVED,
                SessionState.ALIGHTING,
                SessionState.COMPLETED,
            ),
        )

        partial_adapter, _ = _adapter_for("dropoff_normal")
        partial = CareSession()
        for _ in range(3):
            partial.apply_snapshot(poll_snapshot(partial_adapter))
        self.assertIs(partial.state, SessionState.DRIVING)
        self.assertEqual(len(partial.history), 3)

        guidance = guidance_for_session(
            partial, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "driving")

    def test_single_read_matches_bulk_head_and_poll_into(self):
        single_adapter, _ = _adapter_for("dropoff_normal")
        single = poll_snapshot(single_adapter)

        bulk_adapter, _ = _adapter_for("dropoff_normal")
        self.assertEqual(single, poll_snapshots(bulk_adapter, 1)[0])

        manual = CareSession()
        manual_state = manual.apply_snapshot(single)

        poll_adapter, _ = _adapter_for("dropoff_normal")
        via_poll = CareSession()
        poll_state = poll_adapter.poll_into(via_poll)

        self.assertIs(manual_state, poll_state)
        self.assertIs(manual.state, via_poll.state)
        self.assertEqual(_history_key(manual), _history_key(via_poll))
        self.assertEqual(
            manual.current_snapshot, via_poll.current_snapshot
        )

    def test_single_read_is_read_only_and_shareable(self):
        existing = CareSession()
        replay(existing, scenario_snapshots("dropoff_normal")[:1])
        before_state = existing.state
        before_history = _history_key(existing)
        before_snapshot = existing.current_snapshot

        adapter, client = _adapter_for("pet_dropoff")
        snapshot = poll_snapshot(adapter)

        self.assertEqual(client.calls, 1)
        self.assertIs(existing.state, before_state)
        self.assertEqual(_history_key(existing), before_history)
        self.assertEqual(existing.current_snapshot, before_snapshot)

        first = CareSession()
        second = CareSession()
        self.assertIs(
            first.apply_snapshot(snapshot), SessionState.BOARDING
        )
        self.assertIs(
            second.apply_snapshot(snapshot), SessionState.BOARDING
        )
        self.assertIs(first.current_snapshot, snapshot)
        self.assertIs(second.current_snapshot, snapshot)
        self.assertEqual(_history_key(first), _history_key(second))

    def test_stepwise_sessions_aggregate_in_report_log(self):
        sessions = (
            _drive_stepwise("dropoff_normal", 6)[0],
            _drive_stepwise("forgotten_rising_temp", 8)[0],
            _drive_stepwise("pet_dropoff", 6)[0],
        )
        self.assertEqual(
            tuple(session.state for session in sessions),
            (
                SessionState.COMPLETED,
                SessionState.EXCEPTION,
                SessionState.COMPLETED,
            ),
        )

        log = CareReportLog()
        added = log.add_sessions(sessions)

        self.assertEqual(len(log.reports), 3)
        self.assertEqual(added, log.reports)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.average_duration_seconds, 280.0)


if __name__ == "__main__":
    unittest.main()

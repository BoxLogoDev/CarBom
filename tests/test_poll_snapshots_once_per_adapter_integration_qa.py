"""poll_snapshots_once_per_adapter 다중 어댑터 단건 읽기 통합 QA.

181회차에 추가된 ``poll_snapshots_once_per_adapter(adapters)``가
고정 시나리오 3종을 어댑터별로 나눠 읽는 실제 통합 경로에서 쓸 수
있는지 검증한다. 어댑터마다 1건씩 읽은 flat 스냅샷을 세션에 단계
적용하거나, 라운드로빈으로 반복해 모아 시나리오 전체를 복원하고,
안내·리포트·누적함까지 잇는 흐름을 다룬다.
181회차 단위 테스트(PollSnapshotsOncePerAdapterTest)는 호출 횟수·
flat 순서·제너레이터 입력·미연결 전파만 다뤘고, 183회차 통합 검증은
단일 어댑터 ``poll_snapshot`` 반복 읽기만 다뤄, 어댑터 여럿을 한 번에
읽는 flat 경로의 세션·리포트 연결은 검증하지 않았다.
"""

import unittest

from engine.adapters.simulator import replay, scenario_snapshots
from engine.adapters.vehicle_sdk import (
    VehicleSdkAdapter,
    poll_snapshot,
    poll_snapshots_for_adapters,
    poll_snapshots_once_per_adapter,
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


def _adapter_for(name):
    raws = raws_from_snapshots(scenario_snapshots(name))
    client = FakeSequenceSdkClient(raws)
    return VehicleSdkAdapter(client), client


def _adapters_for(names):
    pairs = [_adapter_for(name) for name in names]
    return [a for a, _ in pairs], [c for _, c in pairs]


def _collect_round_robin():
    """어댑터 3개를 라운드로빈으로 읽어 시나리오별 스냅샷을 복원한다."""
    adapters, clients = _adapters_for(SCENARIO_NAMES_3)
    collected = {name: [] for name in SCENARIO_NAMES_3}
    for _ in range(6):
        snaps = poll_snapshots_once_per_adapter(adapters)
        for name, snap in zip(SCENARIO_NAMES_3, snaps):
            collected[name].append(snap)
    for _ in range(2):
        collected["forgotten_rising_temp"].append(
            poll_snapshot(adapters[1])
        )
    return collected, clients


class PollSnapshotsOncePerAdapterIntegrationQATest(unittest.TestCase):
    def test_first_snapshot_per_scenario_adapter(self):
        adapters, clients = _adapters_for(SCENARIO_NAMES_3)

        firsts = poll_snapshots_once_per_adapter(adapters)

        self.assertEqual(
            firsts,
            tuple(scenario_snapshots(name)[0] for name in SCENARIO_NAMES_3),
        )
        self.assertEqual([c.calls for c in clients], [1, 1, 1])
        for snap in firsts:
            session = CareSession()
            self.assertIs(
                session.apply_snapshot(snap), SessionState.BOARDING
            )
            self.assertFalse(session.passenger_present)

    def test_duplicated_adapter_advances_sequence_stepwise(self):
        adapter, client = _adapter_for("dropoff_normal")

        two = poll_snapshots_once_per_adapter([adapter, adapter])

        self.assertEqual(two, scenario_snapshots("dropoff_normal")[:2])
        self.assertEqual(client.calls, 2)

        session = CareSession()
        for snap in two:
            session.apply_snapshot(snap)
        self.assertIs(session.state, SessionState.ONBOARD)
        self.assertEqual(len(session.history), 2)

    def test_flat_matches_for_adapters_slice_heads(self):
        names = ("dropoff_normal", "pet_dropoff")
        flat_adapters, _ = _adapters_for(names)
        flat = poll_snapshots_once_per_adapter(flat_adapters)

        nested_adapters, _ = _adapters_for(names)
        nested = poll_snapshots_for_adapters(nested_adapters, 1)

        self.assertEqual([len(seq) for seq in nested], [1, 1])
        self.assertEqual(flat, tuple(seq[0] for seq in nested))

    def test_round_robin_rebuilds_scenarios_and_drives_sessions(self):
        collected, clients = _collect_round_robin()

        self.assertEqual([c.calls for c in clients], [6, 8, 6])
        for name in SCENARIO_NAMES_3:
            self.assertEqual(
                tuple(collected[name]), scenario_snapshots(name)
            )

        sessions = {}
        for name in SCENARIO_NAMES_3:
            session = CareSession()
            replay(session, collected[name])
            sessions[name] = session

        normal = sessions["dropoff_normal"]
        self.assertIs(normal.state, SessionState.COMPLETED)
        self.assertEqual(len(normal.history), 6)

        forgotten = sessions["forgotten_rising_temp"]
        self.assertIs(forgotten.state, SessionState.EXCEPTION)
        self.assertEqual(len(forgotten.history), 5)
        self.assertTrue(forgotten.passenger_present)

        guidance = guidance_for_session(
            forgotten, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)

        report = report_for_session(forgotten)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.transition_count, 5)

        pet = sessions["pet_dropoff"]
        self.assertIs(pet.state, SessionState.COMPLETED)
        self.assertEqual(len(pet.history), 6)

    def test_round_robin_sessions_aggregate_in_report_log(self):
        collected, _ = _collect_round_robin()
        sessions = []
        for name in SCENARIO_NAMES_3:
            session = CareSession()
            replay(session, collected[name])
            sessions.append(session)

        log = CareReportLog()
        log.add_sessions(sessions)

        self.assertEqual(len(log), 3)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.average_duration_seconds, 280.0)

    def test_unconnected_propagates_and_reading_is_read_only(self):
        good, good_client = _adapter_for("dropoff_normal")
        unconnected = VehicleSdkAdapter()

        existing = CareSession()
        existing.apply_snapshot(scenario_snapshots("dropoff_normal")[0])
        self.assertIs(existing.state, SessionState.BOARDING)
        history_before = list(existing.history)
        snapshot_before = existing.current_snapshot

        with self.assertRaises(NotImplementedError):
            poll_snapshots_once_per_adapter([good, unconnected])

        self.assertEqual(good_client.calls, 1)
        self.assertIs(existing.state, SessionState.BOARDING)
        self.assertEqual(list(existing.history), history_before)
        self.assertEqual(existing.current_snapshot, snapshot_before)


if __name__ == "__main__":
    unittest.main()

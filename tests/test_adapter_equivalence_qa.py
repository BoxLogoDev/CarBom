"""어댑터 동등성 QA 테스트.

핵심 원칙은 하나다: 엔진은 신호가 어디서 오는지 모른다.
시뮬레이터 스냅샷을 Vehicle SDK 변환층이 받는 원시 dict로 바꿔
VehicleSdkAdapter.poll()로 다시 읽어 세션에 적용해도, 시뮬레이터
스냅샷을 직접 replay한 결과와 상태·전이 이력·안내·리포트가
전부 같아야 한다. 고정 시나리오 3종 전부에 대해 검증한다.
"""

import unittest

from engine.adapters import (
    SCENARIO_NAMES,
    VehicleSdkAdapter,
    replay,
    scenario_snapshots,
    snapshot_from_raw,
)
from engine.guidance import DestinationContext, guidance_for_session
from engine.report import report_for_session
from engine.session import CareSession


def snapshot_to_raw(snapshot):
    """SignalSnapshot을 SDK 원시 dict 키로 되돌린다."""
    return {
        "rear_door_open": snapshot.rear_door_open,
        "rear_seat_belt_buckled": snapshot.rear_seat_belt_buckled,
        "ignition_on": snapshot.ignition_on,
        "locked": snapshot.locked,
        "hvac_on": snapshot.hvac_on,
        "cabin_temp_c": snapshot.cabin_temp_c,
        "timestamp": snapshot.timestamp,
    }


class FakeSequenceClient:
    """read_raw()가 준비된 원시 dict를 순서대로 돌려주는 가짜 클라이언트."""

    def __init__(self, raws):
        self._raws = list(raws)
        self.calls = 0

    def read_raw(self):
        self.calls += 1
        return self._raws.pop(0)


def run_via_vehicle_sdk(snapshots):
    """스냅샷 시퀀스를 원시 dict -> poll() 경로로 세션에 적용한다."""
    client = FakeSequenceClient([snapshot_to_raw(s) for s in snapshots])
    adapter = VehicleSdkAdapter(client)
    session = CareSession()
    for _ in snapshots:
        session.apply_snapshot(adapter.poll())
    return session, client


def transition_signature(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


class AdapterEquivalenceQATest(unittest.TestCase):
    def assert_scenario_equivalent(self, name):
        snapshots = scenario_snapshots(name)

        direct = CareSession()
        replay(direct, snapshots)

        via_sdk, client = run_via_vehicle_sdk(snapshots)
        self.assertEqual(client.calls, len(snapshots))

        self.assertEqual(via_sdk.state, direct.state)
        self.assertEqual(via_sdk.passenger_present, direct.passenger_present)
        self.assertEqual(
            transition_signature(via_sdk), transition_signature(direct)
        )
        self.assertEqual(via_sdk.current_snapshot, direct.current_snapshot)

        direct_guidance = guidance_for_session(
            direct, DestinationContext.DROPOFF
        )
        sdk_guidance = guidance_for_session(via_sdk, DestinationContext.DROPOFF)
        self.assertEqual(sdk_guidance.level, direct_guidance.level)
        self.assertEqual(sdk_guidance.text, direct_guidance.text)
        self.assertEqual(sdk_guidance.reason, direct_guidance.reason)

        direct_report = report_for_session(direct)
        sdk_report = report_for_session(via_sdk)
        self.assertEqual(sdk_report.final_state, direct_report.final_state)
        self.assertEqual(sdk_report.completed, direct_report.completed)
        self.assertEqual(
            sdk_report.exception_occurred, direct_report.exception_occurred
        )
        self.assertEqual(
            sdk_report.exception_count, direct_report.exception_count
        )
        self.assertEqual(
            sdk_report.transition_count, direct_report.transition_count
        )
        self.assertEqual(
            sdk_report.passenger_present, direct_report.passenger_present
        )
        self.assertEqual(
            sdk_report.max_cabin_temp_c, direct_report.max_cabin_temp_c
        )
        self.assertEqual(
            sdk_report.duration_seconds, direct_report.duration_seconds
        )
        self.assertEqual(sdk_report.summary, direct_report.summary)

    def test_dropoff_normal_equivalent(self):
        self.assert_scenario_equivalent("dropoff_normal")

    def test_forgotten_rising_temp_equivalent(self):
        self.assert_scenario_equivalent("forgotten_rising_temp")

    def test_pet_dropoff_equivalent(self):
        self.assert_scenario_equivalent("pet_dropoff")

    def test_raw_roundtrip_restores_every_snapshot(self):
        for name in SCENARIO_NAMES:
            for snapshot in scenario_snapshots(name):
                self.assertEqual(
                    snapshot_from_raw(snapshot_to_raw(snapshot)), snapshot
                )

    def test_all_scenarios_covered(self):
        self.assertEqual(
            set(SCENARIO_NAMES),
            {"dropoff_normal", "forgotten_rising_temp", "pet_dropoff"},
        )


if __name__ == "__main__":
    unittest.main()

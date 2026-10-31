"""poll_into_sessions 통합 QA.

``poll_into_sessions(adapter, sessions)``는 신호를 정확히 1회만 읽어
같은 스냅샷을 여러 세션에 적용하는 헬퍼로, 단위 테스트에서는 최종
상태·호출 횟수·빈 입력만 다뤘다. 이 파일은 여러 세션에 동시 적용한
뒤의 안내·리포트·누적함 흐름, 서로 다른 사전 상태에서 같은 스냅샷의
수렴, 수동 apply_snapshot 경로와의 동등성, 중복 세션 멱등성을
검증한다.
"""

import unittest

from engine.adapters.simulator import replay, scenario_snapshots
from engine.adapters.vehicle_sdk import (
    VehicleSdkAdapter,
    poll_into_sessions,
    raws_from_snapshots,
    snapshot_from_raw,
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


def _raw_at(scenario, index):
    return raws_from_snapshots(scenario_snapshots(scenario))[index]


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


def _driven_session(count):
    session = CareSession()
    replay(session, scenario_snapshots("dropoff_normal")[:count])
    return session


class PollIntoSessionsIntegrationQATest(unittest.TestCase):
    def test_single_poll_applies_same_snapshot_to_all_sessions(self):
        client = FakeSequenceSdkClient([_raw_at("dropoff_normal", 0)])
        adapter = VehicleSdkAdapter(client)
        sessions = [CareSession() for _ in range(3)]

        result = poll_into_sessions(adapter, sessions)

        self.assertEqual(client.calls, 1)
        self.assertEqual(result, (SessionState.BOARDING,) * 3)
        self.assertEqual(result, tuple(s.state for s in sessions))
        for session in sessions:
            self.assertEqual(len(session.history), 1)
            self.assertEqual(session.history[0].reason, "rear_door_opened")
            guidance = guidance_for_session(
                session, context=DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "boarding_dropoff")
            report = report_for_session(session)
            self.assertEqual(report.transition_count, 1)
            self.assertEqual(report.duration_seconds, 0.0)
            self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_same_exception_snapshot_converges_from_different_pre_states(self):
        # 사전 상태: IDLE(0건 재생) / ONBOARD(2건) / DRIVING(3건)
        sessions = [_driven_session(n) for n in (0, 2, 3)]
        self.assertEqual(
            [s.state for s in sessions],
            [SessionState.IDLE, SessionState.ONBOARD, SessionState.DRIVING],
        )
        client = FakeSequenceSdkClient(
            [_raw_at("forgotten_rising_temp", 4)]
        )
        adapter = VehicleSdkAdapter(client)

        result = poll_into_sessions(adapter, sessions)

        self.assertEqual(client.calls, 1)
        self.assertEqual(result, (SessionState.EXCEPTION,) * 3)
        self.assertEqual(
            [len(s.history) for s in sessions], [1, 3, 4]
        )
        for session in sessions:
            self.assertTrue(session.passenger_present)
            self.assertEqual(
                session.history[-1].reason,
                "ignition_off_locked_passenger_present",
            )
            guidance = guidance_for_session(
                session, context=DestinationContext.DROPOFF
            )
            self.assertEqual(guidance.level, GuidanceLevel.URGENT)
            self.assertEqual(guidance.reason, "passenger_left_locked")
            report = report_for_session(session)
            self.assertEqual(report.exception_count, 1)
            self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

        log = CareReportLog()
        log.add_sessions(sessions)
        self.assertEqual(len(log), 3)
        self.assertEqual(log.completed_count, 0)
        self.assertEqual(log.sessions_with_exception, 3)
        self.assertEqual(log.total_exception_count, 3)
        self.assertIsNone(log.max_cabin_temp_c)
        self.assertEqual(log.average_duration_seconds, 160.0)

    def test_matches_manual_apply_snapshot_path(self):
        raw = _raw_at("dropoff_normal", 3)
        client = FakeSequenceSdkClient([raw])
        via_poll = [_driven_session(3), _driven_session(0)]
        result = poll_into_sessions(VehicleSdkAdapter(client), via_poll)

        manual = [_driven_session(3), _driven_session(0)]
        snapshot = snapshot_from_raw(raw)
        manual_states = tuple(
            s.apply_snapshot(snapshot) for s in manual
        )

        self.assertEqual(client.calls, 1)
        self.assertEqual(result, manual_states)
        self.assertEqual(
            result, (SessionState.ARRIVED, SessionState.ONBOARD)
        )
        for polled, applied in zip(via_poll, manual):
            self.assertEqual(_history_key(polled), _history_key(applied))
            self.assertEqual(
                polled.current_snapshot, applied.current_snapshot
            )
            self.assertEqual(_report_key(polled), _report_key(applied))

    def test_empty_sessions_never_polls(self):
        client = FakeSequenceSdkClient([_raw_at("dropoff_normal", 0)])
        self.assertEqual(
            poll_into_sessions(VehicleSdkAdapter(client), []), ()
        )
        self.assertEqual(client.calls, 0)
        # 미연결 어댑터도 빈 입력이면 예외가 없다.
        self.assertEqual(poll_into_sessions(VehicleSdkAdapter(), []), ())

    def test_unconnected_adapter_leaves_all_sessions_untouched(self):
        sessions = [_driven_session(0), _driven_session(3)]
        with self.assertRaises(NotImplementedError):
            poll_into_sessions(VehicleSdkAdapter(), sessions)
        self.assertEqual(
            [s.state for s in sessions],
            [SessionState.IDLE, SessionState.DRIVING],
        )
        self.assertEqual([len(s.history) for s in sessions], [0, 3])

    def test_duplicate_session_and_generator_input(self):
        raw = _raw_at("dropoff_normal", 0)
        shared = CareSession()
        client = FakeSequenceSdkClient([raw])
        result = poll_into_sessions(
            VehicleSdkAdapter(client), [shared, shared]
        )
        # 같은 세션에 같은 스냅샷을 두 번 적용해도 전이는 1건뿐이다.
        self.assertEqual(client.calls, 1)
        self.assertEqual(result, (SessionState.BOARDING,) * 2)
        self.assertEqual(len(shared.history), 1)

        sessions = [CareSession(), CareSession()]
        gen_client = FakeSequenceSdkClient([raw])
        gen_result = poll_into_sessions(
            VehicleSdkAdapter(gen_client), (s for s in sessions)
        )
        self.assertEqual(gen_client.calls, 1)
        self.assertEqual(gen_result, (SessionState.BOARDING,) * 2)
        self.assertEqual(
            [_history_key(s) for s in sessions],
            [[(SessionState.IDLE, SessionState.BOARDING,
               "rear_door_opened", 0.0)]] * 2,
        )


if __name__ == "__main__":
    unittest.main()

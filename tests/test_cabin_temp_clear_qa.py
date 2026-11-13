"""실내 온도 소실(None) 이벤트 QA.

전제: 첨부 스냅샷 없는 SignalEvent는 현재 스냅샷을 점진적으로
바꾸며, CABIN_TEMP_CHANGED 이벤트는 cabin_temp_c 필드 값을 그대로
현재 온도에 대입한다(engine/session.py의 _snapshot_from_event).
따라서 온도 값 없는(기본값 None) 온도 변경 이벤트는 이전에 실려
있던 실내 온도를 지운다.

기존 테스트들은 CABIN_TEMP_CHANGED 이벤트에 항상 온도 값을 실어
보냈다(tests/test_session_qa.py, tests/test_event_path_qa.py,
상태별 온도 시리즈 등). 온도 소실이 안내 강도와 리포트에 미치는
영향은 검증하지 않았다. 이 파일은 그 각도를 고정한다.

관측 사항: 리포트의 max_cabin_temp_c는 전이 이력 스냅샷과 현재
스냅샷을 기준으로 계산하므로(engine/report.py), 전이를 일으키지
않은 고온이 현재 스냅샷에서 지워지면 최대값에서도 사라진다.
온도를 소실시킨 뒤의 max_cabin_temp_c가 None이 되는 것은 이
현행 규약을 그대로 고정한 것이며, 적용된 모든 스냅샷의 최대
온도를 따로 추적할지는 리포트 의미가 바뀌는 설계 판단이라
별도 제안으로 남긴다.
"""

import dataclasses
import unittest

from engine.adapters.simulator import replay_scenario, scenario_snapshots
from engine.guidance import (
    DestinationContext,
    GuidanceLevel,
    guidance_for_session,
)
from engine.report import CareReportLog, report_for_session
from engine.session import CareSession, SessionState
from engine.signals import (
    DoorState,
    IgnitionState,
    LockState,
    SignalEvent,
    SignalEventType,
)


def _exception_session():
    session = CareSession()
    replay_scenario(session, "forgotten_rising_temp")
    return session


def _temp_event(timestamp, cabin_temp_c="missing"):
    if cabin_temp_c == "missing":
        return SignalEvent(
            SignalEventType.CABIN_TEMP_CHANGED, timestamp=timestamp
        )
    return SignalEvent(
        SignalEventType.CABIN_TEMP_CHANGED,
        timestamp=timestamp,
        cabin_temp_c=cabin_temp_c,
    )


def _dropoff_guidance(session):
    return guidance_for_session(session, context=DestinationContext.DROPOFF)


def _history_keys(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


class CabinTempClearQATest(unittest.TestCase):
    def test_exception_dangerous_temp_cleared_by_none_event(self):
        session = _exception_session()
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)
        before = _dropoff_guidance(session)
        self.assertEqual(before.level, GuidanceLevel.URGENT)
        self.assertEqual(
            before.reason, "passenger_left_locked_dangerous_cabin_temp"
        )

        result = session.apply_event(_temp_event(480.0, None))

        self.assertEqual(result, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)
        self.assertTrue(session.passenger_present)
        snapshot = session.current_snapshot
        self.assertIsNone(snapshot.cabin_temp_c)
        self.assertEqual(snapshot.timestamp, 480.0)
        self.assertEqual(snapshot.rear_door, DoorState.CLOSED)
        self.assertTrue(snapshot.rear_seat_belt_buckled)
        self.assertEqual(snapshot.ignition, IgnitionState.OFF)
        self.assertEqual(snapshot.lock, LockState.LOCKED)
        self.assertFalse(snapshot.hvac_on)

        guidance = _dropoff_guidance(session)
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.reason, "passenger_left_locked")
        self.assertNotIn("35.5", guidance.text)
        self.assertNotIn("즉시", guidance.text)
        self.assertNotIn("위험", guidance.text)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertIsNone(report.max_cabin_temp_c)

    def test_exception_temp_escalation_drops_and_restores(self):
        session = _exception_session()

        session.apply_event(_temp_event(430.0, 32.0))
        guidance = _dropoff_guidance(session)
        self.assertEqual(guidance.reason, "passenger_left_locked_hot_cabin")
        self.assertEqual(report_for_session(session).max_cabin_temp_c, 32.0)

        session.apply_event(_temp_event(440.0, None))
        guidance = _dropoff_guidance(session)
        self.assertEqual(guidance.reason, "passenger_left_locked")
        self.assertIsNone(report_for_session(session).max_cabin_temp_c)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)

        session.apply_event(_temp_event(450.0, 35.5))
        guidance = _dropoff_guidance(session)
        self.assertEqual(
            guidance.reason, "passenger_left_locked_dangerous_cabin_temp"
        )
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)
        self.assertEqual(report_for_session(session).max_cabin_temp_c, 35.5)

    def test_arrived_hot_temp_cleared_by_none_event(self):
        session = CareSession()
        for snapshot in scenario_snapshots("dropoff_normal")[:4]:
            session.apply_snapshot(snapshot)
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)

        session.apply_event(_temp_event(200.0, 32.0))
        guidance = _dropoff_guidance(session)
        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(
            guidance.reason, "arrived_dropoff_check_rear_seat_hot_cabin"
        )

        session.apply_event(_temp_event(210.0, None))

        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)
        self.assertIsNone(session.current_snapshot.cabin_temp_c)
        guidance = _dropoff_guidance(session)
        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(guidance.reason, "arrived_dropoff_check_rear_seat")
        self.assertNotIn("32도", guidance.text)
        report = report_for_session(session)
        self.assertIsNone(report.max_cabin_temp_c)
        self.assertEqual(report.duration_seconds, 180.0)

    def test_exception_recovery_after_temp_cleared(self):
        session = _exception_session()
        session.apply_event(_temp_event(480.0, None))
        self.assertEqual(session.state, SessionState.EXCEPTION)

        result = session.apply_event(
            SignalEvent(SignalEventType.REAR_DOOR_OPENED, timestamp=540.0)
        )
        self.assertEqual(result, SessionState.ALIGHTING)
        self.assertEqual(
            session.history[-1].reason, "rear_door_opened_after_exception"
        )

        session.apply_event(
            SignalEvent(SignalEventType.REAR_BELT_UNBUCKLED, timestamp=600.0)
        )
        self.assertFalse(session.passenger_present)
        self.assertEqual(session.state, SessionState.ALIGHTING)

        result = session.apply_event(
            SignalEvent(SignalEventType.REAR_DOOR_CLOSED, timestamp=660.0)
        )
        self.assertEqual(result, SessionState.COMPLETED)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 7)
        self.assertEqual(report.duration_seconds, 660.0)
        self.assertIsNone(report.max_cabin_temp_c)
        self.assertEqual(report.summary, "예외 발생 후 하차 확인 완료")

    def test_default_argument_and_snapshot_path_match_none_event(self):
        explicit = _exception_session()
        explicit.apply_event(_temp_event(480.0, None))

        defaulted = _exception_session()
        defaulted.apply_event(_temp_event(480.0))

        self.assertEqual(defaulted.state, explicit.state)
        self.assertEqual(defaulted.current_snapshot, explicit.current_snapshot)
        self.assertEqual(len(defaulted.history), len(explicit.history))
        self.assertEqual(_history_keys(defaulted), _history_keys(explicit))

        via_snapshot = _exception_session()
        cleared = dataclasses.replace(
            via_snapshot.current_snapshot, cabin_temp_c=None, timestamp=480.0
        )
        via_snapshot.apply_snapshot(cleared)

        self.assertEqual(via_snapshot.current_snapshot, explicit.current_snapshot)
        self.assertEqual(via_snapshot.state, explicit.state)
        self.assertEqual(
            _dropoff_guidance(via_snapshot).reason,
            _dropoff_guidance(explicit).reason,
        )
        self.assertIsNone(report_for_session(via_snapshot).max_cabin_temp_c)
        self.assertEqual(
            report_for_session(via_snapshot).max_cabin_temp_c,
            report_for_session(explicit).max_cabin_temp_c,
        )

    def test_bulk_apply_and_report_log_after_temp_cleared(self):
        events = [
            _temp_event(430.0, 32.0),
            _temp_event(440.0, None),
            _temp_event(450.0, 35.5),
        ]

        bulk = _exception_session()
        bulk.apply_events(iter(events))

        stepwise = _exception_session()
        for event in events:
            stepwise.apply_event(event)

        self.assertEqual(bulk.state, stepwise.state)
        self.assertEqual(bulk.current_snapshot, stepwise.current_snapshot)
        self.assertEqual(_history_keys(bulk), _history_keys(stepwise))
        self.assertEqual(report_for_session(bulk), report_for_session(stepwise))
        self.assertEqual(
            _dropoff_guidance(bulk).reason,
            "passenger_left_locked_dangerous_cabin_temp",
        )

        cleared = _exception_session()
        cleared.apply_event(_temp_event(480.0, None))
        normal = CareSession()
        replay_scenario(normal, "dropoff_normal")

        log = CareReportLog()
        log.add_session(cleared)
        log.add_session(normal)

        self.assertEqual(len(log.reports), 2)
        self.assertEqual(log.completed_count, 1)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.total_exception_count, 1)
        self.assertIsNone(log.max_cabin_temp_c)
        self.assertEqual(log.average_duration_seconds, 270.0)


if __name__ == "__main__":
    unittest.main()

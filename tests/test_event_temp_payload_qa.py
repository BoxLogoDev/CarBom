"""첨부 없는 비온도 이벤트의 실내 온도 탑재 QA.

전제: 첨부 스냅샷이 없는 SignalEvent(snapshot=None)는 현재
스냅샷을 점진적으로 바꾼다. engine/session.py의
_snapshot_from_event는 CABIN_TEMP_CHANGED일 때만 cabin_temp_c를
changes에 넣는다. 따라서 그 외 이벤트 타입이 cabin_temp_c 값을
실어 보내도 그 값은 무시되고 현재 실내 온도는 유지된다.

기존 tests/test_event_snapshot_precedence_qa.py는 첨부 스냅샷이
있는 경우만 다뤘다. 첨부 스냅샷이 있을 때는 이벤트 타입과 온도
필드 자체를 보지 않는다. 이 파일은 첨부가 없는 경우를 다룬다.
첨부 없는 비온도 이벤트의 온도 탑재가 현재 온도와 안내와
리포트에 닿지 않음을 고정한다.
"""

import unittest

from engine.adapters.simulator import replay_scenario, scenario_snapshots
from engine.guidance import (
    DestinationContext,
    GuidanceLevel,
    guidance_for_session,
)
from engine.report import CareReportLog, report_for_session
from engine.session import CareSession, SessionState
from engine.signals import LockState, SignalEvent, SignalEventType


def _event(type, timestamp, cabin_temp_c="missing"):
    if cabin_temp_c == "missing":
        return SignalEvent(type, timestamp=timestamp)
    return SignalEvent(
        type, timestamp=timestamp, cabin_temp_c=cabin_temp_c
    )


def _exception_session():
    session = CareSession()
    replay_scenario(session, "forgotten_rising_temp")
    return session


def _arrived_session():
    session = CareSession()
    for snapshot in scenario_snapshots("dropoff_normal")[:4]:
        session.apply_snapshot(snapshot)
    return session


def _dropoff_guidance(session):
    return guidance_for_session(session, context=DestinationContext.DROPOFF)


def _history_keys(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


_NORMAL_FLOW = (
    (SignalEventType.REAR_DOOR_OPENED, 0.0),
    (SignalEventType.REAR_BELT_BUCKLED, 60.0),
    (SignalEventType.REAR_DOOR_CLOSED, 120.0),
    (SignalEventType.IGNITION_ON, 180.0),
    (SignalEventType.IGNITION_OFF, 240.0),
    (SignalEventType.REAR_DOOR_OPENED, 300.0),
    (SignalEventType.REAR_BELT_UNBUCKLED, 360.0),
    (SignalEventType.REAR_DOOR_CLOSED, 420.0),
)


def _normal_flow_session(cabin_temp_c="missing"):
    session = CareSession()
    for event_type, timestamp in _NORMAL_FLOW:
        session.apply_event(_event(event_type, timestamp, cabin_temp_c))
    return session


class EventTempPayloadQATest(unittest.TestCase):
    def test_exception_stray_temp_on_locked_and_hvac_events_ignored(self):
        session = _exception_session()
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)
        before = _dropoff_guidance(session)
        self.assertEqual(before.level, GuidanceLevel.URGENT)
        self.assertEqual(
            before.reason, "passenger_left_locked_dangerous_cabin_temp"
        )

        result = session.apply_event(
            _event(SignalEventType.LOCKED, 480.0, 99.0)
        )

        self.assertEqual(result, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)
        self.assertTrue(session.passenger_present)
        snapshot = session.current_snapshot
        self.assertEqual(snapshot.cabin_temp_c, 35.5)
        self.assertEqual(snapshot.timestamp, 480.0)
        self.assertEqual(snapshot.lock, LockState.LOCKED)

        guidance = _dropoff_guidance(session)
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason,
            "passenger_left_locked_dangerous_cabin_temp",
        )
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

        result = session.apply_event(
            _event(SignalEventType.HVAC_ON, 490.0, 99.0)
        )

        self.assertEqual(result, SessionState.EXCEPTION)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)
        snapshot = session.current_snapshot
        self.assertTrue(snapshot.hvac_on)
        self.assertEqual(snapshot.cabin_temp_c, 35.5)
        self.assertEqual(snapshot.timestamp, 490.0)
        self.assertEqual(snapshot.lock, LockState.LOCKED)
        self.assertEqual(_dropoff_guidance(session), guidance)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_arrived_stray_temp_ignored_then_real_temp_event_applies(self):
        session = _arrived_session()
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)
        self.assertIsNone(session.current_snapshot.cabin_temp_c)
        before = _dropoff_guidance(session)
        self.assertEqual(before.level, GuidanceLevel.REMIND)
        self.assertEqual(before.reason, "arrived_dropoff_check_rear_seat")

        result = session.apply_event(
            _event(SignalEventType.HVAC_ON, 200.0, 99.0)
        )

        self.assertEqual(result, SessionState.ARRIVED)
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)
        snapshot = session.current_snapshot
        self.assertTrue(snapshot.hvac_on)
        self.assertIsNone(snapshot.cabin_temp_c)
        self.assertEqual(snapshot.timestamp, 200.0)
        self.assertEqual(_dropoff_guidance(session), before)

        report = report_for_session(session)
        self.assertIsNone(report.max_cabin_temp_c)
        self.assertEqual(report.duration_seconds, 180.0)

        result = session.apply_event(
            _event(SignalEventType.CABIN_TEMP_CHANGED, 210.0, 32.0)
        )

        self.assertEqual(result, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 32.0)
        guidance = _dropoff_guidance(session)
        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(
            guidance.reason, "arrived_dropoff_check_rear_seat_hot_cabin"
        )
        self.assertIn("32도", guidance.text)
        self.assertEqual(report_for_session(session).max_cabin_temp_c, 32.0)

    def test_normal_event_flow_with_stray_temps_matches_clean_flow(self):
        stray = _normal_flow_session(99.0)
        clean = _normal_flow_session()

        self.assertEqual(stray.state, SessionState.COMPLETED)
        self.assertEqual(clean.state, SessionState.COMPLETED)
        self.assertEqual(len(stray.history), 6)
        self.assertEqual(len(clean.history), 6)
        self.assertEqual(_history_keys(stray), _history_keys(clean))
        self.assertEqual(stray.current_snapshot, clean.current_snapshot)
        self.assertIsNone(stray.current_snapshot.cabin_temp_c)
        self.assertEqual(stray.current_snapshot.timestamp, 420.0)
        self.assertFalse(stray.passenger_present)
        self.assertFalse(clean.passenger_present)

        stray_report = report_for_session(stray)
        clean_report = report_for_session(clean)
        self.assertEqual(stray_report, clean_report)
        self.assertTrue(stray_report.completed)
        self.assertEqual(stray_report.duration_seconds, 420.0)
        self.assertIsNone(stray_report.max_cabin_temp_c)
        self.assertEqual(stray_report.summary, "하차 확인 완료 · 예외 없음")

    def test_only_temp_changed_event_sets_cabin_temp_in_idle(self):
        stray = CareSession()
        result = stray.apply_event(
            _event(SignalEventType.REAR_DOOR_OPENED, 10.0, 32.0)
        )

        self.assertEqual(result, SessionState.BOARDING)
        self.assertEqual(stray.state, SessionState.BOARDING)
        self.assertEqual(len(stray.history), 1)
        self.assertIsNone(stray.current_snapshot.cabin_temp_c)
        self.assertEqual(stray.current_snapshot.timestamp, 10.0)

        temp_only = CareSession()
        result = temp_only.apply_event(
            _event(SignalEventType.CABIN_TEMP_CHANGED, 10.0, 32.0)
        )

        self.assertEqual(result, SessionState.IDLE)
        self.assertEqual(temp_only.state, SessionState.IDLE)
        self.assertEqual(len(temp_only.history), 0)
        self.assertEqual(temp_only.current_snapshot.cabin_temp_c, 32.0)
        self.assertEqual(temp_only.current_snapshot.timestamp, 10.0)

    def test_boarding_stray_temps_do_not_set_temp(self):
        session = CareSession()

        result = session.apply_event(
            _event(SignalEventType.REAR_DOOR_OPENED, 0.0, 50.0)
        )
        self.assertEqual(result, SessionState.BOARDING)
        self.assertIsNone(session.current_snapshot.cabin_temp_c)

        result = session.apply_event(
            _event(SignalEventType.REAR_BELT_BUCKLED, 60.0, 50.0)
        )
        self.assertEqual(result, SessionState.BOARDING)
        self.assertTrue(session.passenger_present)
        self.assertTrue(session.current_snapshot.rear_door_open)
        self.assertIsNone(session.current_snapshot.cabin_temp_c)

        result = session.apply_event(
            _event(SignalEventType.REAR_DOOR_CLOSED, 120.0, -5.0)
        )
        self.assertEqual(result, SessionState.ONBOARD)
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertIsNone(session.current_snapshot.cabin_temp_c)
        self.assertEqual(
            _history_keys(session),
            [
                (
                    SessionState.IDLE,
                    SessionState.BOARDING,
                    "rear_door_opened",
                    0.0,
                ),
                (
                    SessionState.BOARDING,
                    SessionState.ONBOARD,
                    "passenger_onboard",
                    120.0,
                ),
            ],
        )

    def test_bulk_apply_with_stray_temps_and_report_log(self):
        stray_events = [
            _event(SignalEventType.REAR_DOOR_OPENED, 0.0, 10.0),
            _event(SignalEventType.REAR_BELT_BUCKLED, 60.0, 20.0),
            _event(SignalEventType.REAR_DOOR_CLOSED, 120.0, 30.0),
            _event(SignalEventType.IGNITION_ON, 180.0, 40.0),
        ]
        bulk = CareSession()
        result = bulk.apply_events(event for event in stray_events)

        clean = CareSession()
        for event_type, timestamp in (
            (SignalEventType.REAR_DOOR_OPENED, 0.0),
            (SignalEventType.REAR_BELT_BUCKLED, 60.0),
            (SignalEventType.REAR_DOOR_CLOSED, 120.0),
            (SignalEventType.IGNITION_ON, 180.0),
        ):
            clean.apply_event(_event(event_type, timestamp))

        self.assertEqual(result, SessionState.DRIVING)
        self.assertEqual(bulk.state, SessionState.DRIVING)
        self.assertEqual(clean.state, SessionState.DRIVING)
        self.assertEqual(len(bulk.history), 3)
        self.assertEqual(_history_keys(bulk), _history_keys(clean))
        self.assertEqual(bulk.current_snapshot, clean.current_snapshot)
        self.assertIsNone(bulk.current_snapshot.cabin_temp_c)

        bulk_report = report_for_session(bulk)
        self.assertEqual(bulk_report, report_for_session(clean))
        self.assertEqual(bulk_report.duration_seconds, 180.0)
        self.assertIsNone(bulk_report.max_cabin_temp_c)

        log = CareReportLog()
        log.add_session(_normal_flow_session(99.0))
        log.add_session(_normal_flow_session())

        self.assertEqual(len(log.reports), 2)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 0)
        self.assertEqual(log.total_exception_count, 0)
        self.assertIsNone(log.max_cabin_temp_c)
        self.assertEqual(log.average_duration_seconds, 420.0)


if __name__ == "__main__":
    unittest.main()

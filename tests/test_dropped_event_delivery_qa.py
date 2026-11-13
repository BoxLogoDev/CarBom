"""QA: 이벤트 1건 누락 배달(lossy event delivery) 전 흐름 거동.

전제: 첨부 스냅샷 없는 SignalEvent는 증분 입력이라, 전체 상태
스냅샷과 달리 중간 누락이 뒤 입력에 흡수되지 않는 경우가 많다.
기존 tests/test_dropped_snapshot_delivery_qa.py는 스냅샷 1건 누락을,
tests/test_duplicate_event_delivery_qa.py는 이벤트 중복 배달을
다뤘다. 이 파일은 이벤트 시퀀스에서 인덱스 1건만 빠진 채 배달될 때
최종 상태·전이 이력·동승자 판정·안내·리포트가 어떻게 달라지는지를
고정한다. 결함 판정이 아니라 현행 거동의 고정이다.
"""

import unittest

from engine import (
    CareSession,
    SessionState,
    SignalEvent,
    SignalEventType,
)
from engine.guidance import (
    DestinationContext,
    GuidanceLevel,
    guidance_for_session,
)
from engine.report import report_for_session


def _event(event_type, timestamp, cabin_temp_c=None):
    return SignalEvent(
        event_type, timestamp=timestamp, cabin_temp_c=cabin_temp_c
    )


def _normal_events():
    return [
        _event(SignalEventType.REAR_DOOR_OPENED, 0.0),
        _event(SignalEventType.REAR_BELT_BUCKLED, 60.0),
        _event(SignalEventType.REAR_DOOR_CLOSED, 120.0),
        _event(SignalEventType.IGNITION_ON, 180.0),
        _event(SignalEventType.IGNITION_OFF, 240.0),
        _event(SignalEventType.REAR_DOOR_OPENED, 300.0),
        _event(SignalEventType.REAR_BELT_UNBUCKLED, 360.0),
        _event(SignalEventType.REAR_DOOR_CLOSED, 420.0),
    ]


def _forgotten_events():
    return [
        _event(SignalEventType.REAR_DOOR_OPENED, 0.0),
        _event(SignalEventType.REAR_BELT_BUCKLED, 60.0),
        _event(SignalEventType.REAR_DOOR_CLOSED, 120.0),
        _event(SignalEventType.IGNITION_ON, 180.0),
        _event(SignalEventType.IGNITION_OFF, 240.0),
        _event(SignalEventType.LOCKED, 300.0),
        _event(SignalEventType.CABIN_TEMP_CHANGED, 360.0, 32.0),
        _event(SignalEventType.CABIN_TEMP_CHANGED, 420.0, 35.5),
    ]


def _run(events):
    session = CareSession()
    for event in events:
        session.apply_event(event)
    return session


def _run_dropped(events, drop_index):
    return _run(
        [event for index, event in enumerate(events) if index != drop_index]
    )


def _history(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


class DroppedEventDeliveryQATest(unittest.TestCase):
    def test_baseline_flows_complete(self):
        normal = _run(_normal_events())
        self.assertEqual(normal.state, SessionState.COMPLETED)
        self.assertEqual(len(normal.history), 6)
        report = report_for_session(normal)
        self.assertEqual(report.duration_seconds, 420.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

        forgotten = _run(_forgotten_events())
        self.assertEqual(forgotten.state, SessionState.EXCEPTION)
        self.assertEqual(len(forgotten.history), 5)
        report = report_for_session(forgotten)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        guidance = guidance_for_session(
            forgotten, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason, "passenger_left_locked_dangerous_cabin_temp"
        )

    def test_normal_belt_buckled_dropped_never_latches_passenger(self):
        session = _run_dropped(_normal_events(), 1)
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertFalse(session.passenger_present)
        self.assertEqual(
            _history(session),
            [
                (
                    SessionState.IDLE,
                    SessionState.BOARDING,
                    "rear_door_opened",
                    0.0,
                ),
                (
                    SessionState.BOARDING,
                    SessionState.IDLE,
                    "boarding_without_passenger",
                    120.0,
                ),
                (
                    SessionState.IDLE,
                    SessionState.BOARDING,
                    "rear_door_opened",
                    300.0,
                ),
                (
                    SessionState.BOARDING,
                    SessionState.IDLE,
                    "boarding_without_passenger",
                    420.0,
                ),
            ],
        )
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.NONE)
        self.assertEqual(guidance.reason, "idle")
        self.assertEqual(guidance.text, "")
        report = report_for_session(session)
        self.assertEqual(report.duration_seconds, 420.0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_normal_arrival_door_open_dropped_stays_arrived(self):
        session = _run_dropped(_normal_events(), 5)
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 4)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(guidance.reason, "arrived_dropoff_check_rear_seat")
        report = report_for_session(session)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_normal_unbuckle_vs_final_door_close_dropped(self):
        unbuckle_dropped = _run_dropped(_normal_events(), 6)
        self.assertEqual(unbuckle_dropped.state, SessionState.ALIGHTING)
        self.assertEqual(len(unbuckle_dropped.history), 5)
        self.assertTrue(unbuckle_dropped.passenger_present)
        guidance = guidance_for_session(
            unbuckle_dropped, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "alighting")
        self.assertEqual(
            report_for_session(unbuckle_dropped).duration_seconds, 300.0
        )

        close_dropped = _run_dropped(_normal_events(), 7)
        self.assertEqual(close_dropped.state, SessionState.ALIGHTING)
        self.assertEqual(len(close_dropped.history), 5)
        self.assertFalse(close_dropped.passenger_present)
        guidance = guidance_for_session(
            close_dropped, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "alighting")

    def test_forgotten_belt_buckled_dropped_no_exception(self):
        session = _run_dropped(_forgotten_events(), 1)
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertEqual(len(session.history), 2)
        self.assertFalse(session.passenger_present)
        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.NONE)
        self.assertEqual(guidance.reason, "idle")

    def test_forgotten_locked_dropped_stays_arrived_with_hot_guidance(self):
        session = _run_dropped(_forgotten_events(), 5)
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)
        self.assertTrue(session.passenger_present)
        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(
            guidance.reason,
            "arrived_dropoff_check_rear_seat_dangerous_cabin_temp",
        )
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)

    def test_forgotten_last_temp_dropped_and_apply_events_equivalence(self):
        session = _run_dropped(_forgotten_events(), 7)
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)
        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.max_cabin_temp_c, 32.0)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.reason, "passenger_left_locked_hot_cabin")
        self.assertIn("32도", guidance.text)
        self.assertNotIn("35.5도", guidance.text)

        dropped = [
            event
            for index, event in enumerate(_forgotten_events())
            if index != 7
        ]
        bulk = CareSession()
        bulk.apply_events(iter(dropped))
        self.assertEqual(bulk.state, session.state)
        self.assertEqual(_history(bulk), _history(session))
        self.assertEqual(bulk.current_snapshot, session.current_snapshot)
        self.assertEqual(report_for_session(bulk), report)


if __name__ == "__main__":
    unittest.main()

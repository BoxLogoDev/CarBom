"""QA: 중복 이벤트 배달(at-least-once delivery) 전 흐름 멱등성.

전제: 첨부 스냅샷 없는 SignalEvent가 같은 type·timestamp·cabin_temp_c로
2회 배달돼도(중복 배달) 세션 결과는 1회 배달과 완전히 같아야 한다.
기존 테스트는 같은 스냅샷 반복(상태별 단일 입력)과 대량 헬퍼의 중복
원소 보존을 다뤘으나, 이벤트 전 흐름을 통째로 중복 배달했을 때 전이
이력·예외 횟수·안내·리포트가 중복으로 부풀지 않는지는 검증하지
않았다. 특히 EXCEPTION 진입 이벤트가 중복 배달되면 exception_count가
2로 부풀 위험이 있어, 그 값을 명시적으로 고정한다.
"""

import unittest

from engine import (
    CareSession,
    SessionState,
    SignalEvent,
    SignalEventType,
)
from engine.guidance import DestinationContext, GuidanceLevel, guidance_for_session
from engine.report import CareReportLog, report_for_session


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


def _exception_events():
    return _normal_events()[:5] + [
        _event(SignalEventType.LOCKED, 300.0),
        _event(SignalEventType.CABIN_TEMP_CHANGED, 360.0, 32.0),
        _event(SignalEventType.CABIN_TEMP_CHANGED, 420.0, 35.5),
    ]


def _recovery_events():
    return _exception_events() + [
        _event(SignalEventType.REAR_DOOR_OPENED, 540.0),
        _event(SignalEventType.REAR_BELT_UNBUCKLED, 600.0),
        _event(SignalEventType.REAR_DOOR_CLOSED, 660.0),
    ]


def _run_single(events):
    session = CareSession()
    for event in events:
        session.apply_event(event)
    return session


def _run_duplicated(events, times=2):
    session = CareSession()
    for event in events:
        for _ in range(times):
            session.apply_event(event)
    return session


def _history_keys(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


def _surfaces(session):
    guidance = guidance_for_session(session, context=DestinationContext.DROPOFF)
    report = report_for_session(session)
    return (
        session.state,
        session.passenger_present,
        _history_keys(session),
        session.current_snapshot,
        (guidance.level, guidance.text, guidance.reason),
        (
            report.completed,
            report.exception_count,
            report.transition_count,
            report.duration_seconds,
            report.max_cabin_temp_c,
            report.summary,
        ),
    )


class DuplicateEventDeliveryQATest(unittest.TestCase):
    def test_normal_flow_duplicated_matches_single(self):
        single = _run_single(_normal_events())
        duplicated = _run_duplicated(_normal_events())

        self.assertEqual(_surfaces(duplicated), _surfaces(single))
        self.assertIs(duplicated.state, SessionState.COMPLETED)
        self.assertFalse(duplicated.passenger_present)
        self.assertEqual(
            _history_keys(duplicated),
            [
                (SessionState.IDLE, SessionState.BOARDING, "rear_door_opened", 0.0),
                (
                    SessionState.BOARDING,
                    SessionState.ONBOARD,
                    "passenger_onboard",
                    120.0,
                ),
                (SessionState.ONBOARD, SessionState.DRIVING, "ignition_on", 180.0),
                (SessionState.DRIVING, SessionState.ARRIVED, "ignition_off", 240.0),
                (
                    SessionState.ARRIVED,
                    SessionState.ALIGHTING,
                    "alighting_started",
                    300.0,
                ),
                (
                    SessionState.ALIGHTING,
                    SessionState.COMPLETED,
                    "alighting_confirmed",
                    420.0,
                ),
            ],
        )
        guidance = guidance_for_session(
            duplicated, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        report = report_for_session(duplicated)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 420.0)
        self.assertIsNone(report.max_cabin_temp_c)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_exception_flow_duplicated_does_not_double_count(self):
        single = _run_single(_exception_events())
        duplicated = _run_duplicated(_exception_events())

        self.assertEqual(_surfaces(duplicated), _surfaces(single))
        self.assertIs(duplicated.state, SessionState.EXCEPTION)
        self.assertTrue(duplicated.passenger_present)
        self.assertEqual(len(duplicated.history), 5)
        self.assertEqual(
            _history_keys(duplicated)[-1],
            (
                SessionState.ARRIVED,
                SessionState.EXCEPTION,
                "ignition_off_locked_passenger_present",
                300.0,
            ),
        )
        guidance = guidance_for_session(
            duplicated, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason, "passenger_left_locked_dangerous_cabin_temp"
        )
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)
        report = report_for_session(duplicated)
        self.assertFalse(report.completed)
        # 중복 배달이 예외 횟수를 부풀리지 않는다.
        self.assertEqual(report.exception_count, 1)
        self.assertNotEqual(report.exception_count, 2)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_recovery_flow_duplicated_matches_single(self):
        single = _run_single(_recovery_events())
        duplicated = _run_duplicated(_recovery_events())

        self.assertEqual(_surfaces(duplicated), _surfaces(single))
        self.assertIs(duplicated.state, SessionState.COMPLETED)
        self.assertEqual(len(duplicated.history), 7)
        self.assertEqual(
            _history_keys(duplicated)[5],
            (
                SessionState.EXCEPTION,
                SessionState.ALIGHTING,
                "rear_door_opened_after_exception",
                540.0,
            ),
        )
        report = report_for_session(duplicated)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 7)
        self.assertEqual(report.duration_seconds, 660.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.summary, "예외 발생 후 하차 확인 완료")

    def test_bulk_apply_events_with_duplicated_generator(self):
        events = _normal_events()
        duplicated = [event for event in events for _ in range(2)]

        bulk = CareSession()
        result = bulk.apply_events(event for event in duplicated)
        self.assertIs(result, SessionState.COMPLETED)
        self.assertEqual(_surfaces(bulk), _surfaces(_run_duplicated(events)))
        self.assertEqual(_surfaces(bulk), _surfaces(_run_single(events)))

        tripled = _run_duplicated(events, times=3)
        self.assertEqual(_surfaces(tripled), _surfaces(_run_single(events)))

    def test_non_transition_duplicates_and_post_completion_duplicate(self):
        # (a) IDLE에서 전이를 일으키지 않는 이벤트의 반복 적용.
        single = CareSession()
        single.apply_event(_event(SignalEventType.LOCKED, 10.0))
        single.apply_event(_event(SignalEventType.HVAC_ON, 20.0))

        repeated = CareSession()
        for _ in range(3):
            repeated.apply_event(_event(SignalEventType.LOCKED, 10.0))
        for _ in range(3):
            repeated.apply_event(_event(SignalEventType.HVAC_ON, 20.0))

        self.assertIs(repeated.state, SessionState.IDLE)
        self.assertEqual(len(repeated.history), 0)
        self.assertEqual(repeated.current_snapshot, single.current_snapshot)
        self.assertTrue(repeated.current_snapshot.locked)
        self.assertTrue(repeated.current_snapshot.hvac_on)

        # (b) COMPLETED 뒤 마지막 이벤트를 한 번 더 배달해도 불변.
        completed = _run_single(_normal_events())
        before = _surfaces(completed)
        completed.apply_event(_event(SignalEventType.REAR_DOOR_CLOSED, 420.0))
        self.assertEqual(_surfaces(completed), before)

    def test_report_log_aggregates_duplicated_sessions_like_single(self):
        duplicated_log = CareReportLog()
        duplicated_log.add_sessions(
            [
                _run_duplicated(_normal_events()),
                _run_duplicated(_exception_events()),
            ]
        )
        single_log = CareReportLog()
        single_log.add_sessions(
            [_run_single(_normal_events()), _run_single(_exception_events())]
        )

        self.assertEqual(duplicated_log.reports, single_log.reports)
        self.assertEqual(len(duplicated_log.reports), 2)
        self.assertEqual(duplicated_log.completed_count, 1)
        self.assertEqual(duplicated_log.sessions_with_exception, 1)
        self.assertEqual(duplicated_log.total_exception_count, 1)
        self.assertEqual(duplicated_log.max_cabin_temp_c, 35.5)
        self.assertEqual(duplicated_log.average_duration_seconds, 360.0)


if __name__ == "__main__":
    unittest.main()

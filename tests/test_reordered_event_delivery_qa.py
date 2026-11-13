"""QA: 순서 바뀐 이벤트 배달(reordered event delivery) 전 흐름 거동.

전제: 순서 변경은 이벤트 타입과 그 timestamp(및 cabin_temp_c)가
함께 이동한다. 즉 교환·역순은 배달 순서만 바꾸고, 각 이벤트가
들고 있는 시각과 온도 값은 바꾸지 않는다. 기존
tests/test_reordered_snapshot_delivery_qa.py는 스냅샷 순서만,
tests/test_duplicate_event_delivery_qa.py는 이벤트 중복 배달을,
tests/test_dropped_event_delivery_qa.py는 이벤트 1건 누락 배달을
다뤘다. 이 파일은 고정 시나리오 SignalEvent 시퀀스에서 인접한
두 건의 배달 순서를 교환하거나 전체를 역순으로 배달할 때 최종
상태와 전이 이력과 안내와 리포트가 어떻게 달라지는지를 고정한다.
결함 판정이 아니라 현행 거동의 고정이다. 안내 맥락은 DROPOFF로
고정한다.
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


def _run_swapped(events, first, second):
    swapped = list(events)
    swapped[first], swapped[second] = swapped[second], swapped[first]
    return _run(swapped)


def _run_reversed(events):
    return _run(list(reversed(events)))


def _history_keys(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


def _report_key(report):
    return (
        report.final_state,
        report.completed,
        report.exception_count,
        report.transition_count,
        report.passenger_present,
        report.duration_seconds,
        report.max_cabin_temp_c,
        report.summary,
    )


def _surfaces(session):
    guidance = guidance_for_session(
        session, context=DestinationContext.DROPOFF
    )
    return (
        session.state,
        session.passenger_present,
        _history_keys(session),
        session.current_snapshot,
        (guidance.level, guidance.text, guidance.reason),
        _report_key(report_for_session(session)),
    )


class ReorderedEventDeliveryQATest(unittest.TestCase):
    def test_normal_swap_first_two_collapses_transitions_but_completes(
        self,
    ):
        session = _run_swapped(_normal_events(), 0, 1)

        self.assertIs(session.state, SessionState.COMPLETED)
        self.assertEqual(
            _history_keys(session),
            [
                (
                    SessionState.IDLE,
                    SessionState.ONBOARD,
                    "passenger_onboard",
                    60.0,
                ),
                (
                    SessionState.ONBOARD,
                    SessionState.DRIVING,
                    "ignition_on",
                    180.0,
                ),
                (
                    SessionState.DRIVING,
                    SessionState.ARRIVED,
                    "ignition_off",
                    240.0,
                ),
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
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.duration_seconds, 360.0)
        self.assertIsNone(report.max_cabin_temp_c)

    def test_normal_swap_belt_and_door_close_adds_detour_transitions(
        self,
    ):
        session = _run_swapped(_normal_events(), 1, 2)

        self.assertIs(session.state, SessionState.COMPLETED)
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
                    SessionState.IDLE,
                    "boarding_without_passenger",
                    120.0,
                ),
                (
                    SessionState.IDLE,
                    SessionState.ONBOARD,
                    "passenger_onboard",
                    60.0,
                ),
                (
                    SessionState.ONBOARD,
                    SessionState.DRIVING,
                    "ignition_on",
                    180.0,
                ),
                (
                    SessionState.DRIVING,
                    SessionState.ARRIVED,
                    "ignition_off",
                    240.0,
                ),
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
        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.transition_count, 7)
        self.assertEqual(report.duration_seconds, 420.0)

    def test_normal_swap_ignition_off_before_on_stuck_in_driving(self):
        session = _run_swapped(_normal_events(), 3, 4)

        self.assertIs(session.state, SessionState.DRIVING)
        self.assertFalse(session.passenger_present)
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
                (
                    SessionState.ONBOARD,
                    SessionState.DRIVING,
                    "ignition_on",
                    180.0,
                ),
            ],
        )
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.NONE)
        self.assertEqual(guidance.reason, "no_passenger")
        self.assertEqual(guidance.text, "")
        report = report_for_session(session)
        self.assertFalse(report.completed)
        self.assertEqual(report.transition_count, 3)
        self.assertEqual(report.duration_seconds, 180.0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_forgotten_swap_lock_before_ignition_off_to_exception(
        self,
    ):
        session = _run_swapped(_forgotten_events(), 4, 5)

        self.assertIs(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 4)
        self.assertEqual(
            _history_keys(session)[-1],
            (
                SessionState.DRIVING,
                SessionState.EXCEPTION,
                "ignition_off_locked_passenger_present",
                240.0,
            ),
        )
        self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason,
            "passenger_left_locked_dangerous_cabin_temp",
        )
        report = report_for_session(session)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 4)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_forgotten_swap_last_two_temps_lowers_guidance_and_max(
        self,
    ):
        single = _run(_forgotten_events())
        session = _run_swapped(_forgotten_events(), 6, 7)

        self.assertIs(session.state, SessionState.EXCEPTION)
        self.assertEqual(
            _history_keys(session), _history_keys(single)
        )
        self.assertEqual(len(session.history), 5)
        self.assertEqual(
            _history_keys(session)[-1],
            (
                SessionState.ARRIVED,
                SessionState.EXCEPTION,
                "ignition_off_locked_passenger_present",
                300.0,
            ),
        )
        self.assertEqual(session.current_snapshot.cabin_temp_c, 32.0)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason, "passenger_left_locked_hot_cabin"
        )
        self.assertIn("32도", guidance.text)
        self.assertNotIn("즉시", guidance.text)
        report = report_for_session(session)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.max_cabin_temp_c, 32.0)

        with self.subTest(swap=(5, 6)):
            absorbed = _run_swapped(_forgotten_events(), 5, 6)
            self.assertEqual(_surfaces(absorbed), _surfaces(single))
            absorbed_report = report_for_session(absorbed)
            self.assertEqual(absorbed_report.transition_count, 5)
            self.assertEqual(absorbed_report.duration_seconds, 300.0)
            self.assertEqual(absorbed_report.max_cabin_temp_c, 35.5)
            absorbed_guidance = guidance_for_session(
                absorbed, context=DestinationContext.DROPOFF
            )
            self.assertEqual(
                absorbed_guidance.level, GuidanceLevel.URGENT
            )
            self.assertEqual(
                absorbed_guidance.reason,
                "passenger_left_locked_dangerous_cabin_temp",
            )

    def test_reversed_delivery_and_report_log_aggregates(self):
        normal = _run_reversed(_normal_events())

        self.assertIs(normal.state, SessionState.DRIVING)
        self.assertTrue(normal.passenger_present)
        self.assertEqual(
            _history_keys(normal),
            [
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
                    120.0,
                ),
                (
                    SessionState.IDLE,
                    SessionState.ONBOARD,
                    "passenger_onboard",
                    60.0,
                ),
                (
                    SessionState.ONBOARD,
                    SessionState.DRIVING,
                    "ignition_on",
                    60.0,
                ),
            ],
        )
        normal_guidance = guidance_for_session(
            normal, context=DestinationContext.DROPOFF
        )
        self.assertEqual(normal_guidance.level, GuidanceLevel.INFO)
        self.assertEqual(normal_guidance.reason, "driving")
        normal_report = report_for_session(normal)
        self.assertFalse(normal_report.completed)
        self.assertEqual(normal_report.transition_count, 4)
        self.assertEqual(normal_report.duration_seconds, -240.0)

        forgotten = _run_reversed(_forgotten_events())

        self.assertIs(forgotten.state, SessionState.DRIVING)
        self.assertEqual(len(forgotten.history), 2)
        self.assertEqual(
            forgotten.current_snapshot.cabin_temp_c, 32.0
        )
        forgotten_report = report_for_session(forgotten)
        self.assertEqual(forgotten_report.transition_count, 2)
        self.assertEqual(forgotten_report.duration_seconds, 0.0)
        self.assertEqual(forgotten_report.max_cabin_temp_c, 32.0)

        log = CareReportLog()
        log.add_sessions(
            [
                _run_swapped(_normal_events(), 0, 1),
                _run_swapped(_forgotten_events(), 6, 7),
                _run_reversed(_normal_events()),
            ]
        )
        self.assertEqual(len(log), 3)
        self.assertEqual(len(log.reports), 3)
        self.assertEqual(log.completed_count, 1)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(log.max_cabin_temp_c, 32.0)
        self.assertEqual(log.average_duration_seconds, 140.0)


if __name__ == "__main__":
    unittest.main()

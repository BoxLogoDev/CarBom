"""QA: 절단 이벤트 배달(truncated event delivery) 전 흐름 거동.

전제: 고정 시나리오의 SignalEvent 시퀀스를 앞에서부터 cut개만
배달하고 나머지는 아예 오지 않는다. 기존
tests/test_duplicate_event_delivery_qa.py는 각 이벤트가 중복
배달되는 경우를, tests/test_dropped_event_delivery_qa.py는 중간
1건만 빠지고 뒤 이벤트는 도착하는 경우를,
tests/test_reordered_event_delivery_qa.py는 전부 도착하되 순서가
바뀌는 경우를, tests/test_truncated_snapshot_delivery_qa.py는
스냅샷 시퀀스의 절단을 다뤘다. 이 파일은 그들과 중복되지 않게,
이벤트 시퀀스의 뒤쪽이 전혀 도착하지 않는 접두사만으로 세션이
어디까지 진행되고 전이 이력·소요 시간·안내·리포트가 어떻게
멈추는지를 고정한다. 결함 판정이 아니라 현행 거동의 고정이다.

이벤트 특유의 지점: 벨트 체결 이벤트만으로는 BOARDING에서
ONBOARD로 전이하지 않고(문이 닫혀야 전이), HVAC_ON 이벤트는
전이를 만들지 않으며, 절단된 접두사의 전이 이력은 전체 배달
전이 이력의 앞부분과 정확히 일치한다.
"""

import unittest

from engine import CareSession, SessionState, SignalEvent, SignalEventType
from engine.guidance import (
    DestinationContext,
    GuidanceLevel,
    guidance_for_session,
)
from engine.report import CareReportLog, report_for_session

_IN_PROGRESS = "진행 중 · 하차 미확인"
_COMPLETED = "하차 확인 완료 · 예외 없음"
_EXCEPTION = "예외 발생 · 하차 미확인"


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


def _pet_events():
    return [
        _event(SignalEventType.REAR_DOOR_OPENED, 0.0),
        _event(SignalEventType.REAR_BELT_BUCKLED, 60.0),
        _event(SignalEventType.REAR_DOOR_CLOSED, 120.0),
        _event(SignalEventType.HVAC_ON, 150.0),
        _event(SignalEventType.IGNITION_ON, 180.0),
        _event(SignalEventType.IGNITION_OFF, 240.0),
        _event(SignalEventType.REAR_DOOR_OPENED, 300.0),
        _event(SignalEventType.REAR_BELT_UNBUCKLED, 360.0),
        _event(SignalEventType.REAR_DOOR_CLOSED, 420.0),
    ]


_EVENTS = {
    "normal": _normal_events,
    "forgotten": _forgotten_events,
    "pet": _pet_events,
}

# cut, state, passenger, history 건수, duration, 안내 수준, 안내 이유, summary
_NORMAL_PROGRESSION = (
    (0, SessionState.IDLE, False, 0, None, GuidanceLevel.NONE, "idle", _IN_PROGRESS),
    (1, SessionState.BOARDING, False, 1, 0.0, GuidanceLevel.INFO, "boarding_dropoff", _IN_PROGRESS),
    (2, SessionState.BOARDING, True, 1, 0.0, GuidanceLevel.INFO, "boarding_dropoff", _IN_PROGRESS),
    (3, SessionState.ONBOARD, True, 2, 120.0, GuidanceLevel.INFO, "passenger_onboard", _IN_PROGRESS),
    (4, SessionState.DRIVING, True, 3, 180.0, GuidanceLevel.INFO, "driving", _IN_PROGRESS),
    (5, SessionState.ARRIVED, True, 4, 240.0, GuidanceLevel.REMIND, "arrived_dropoff_check_rear_seat", _IN_PROGRESS),
    (6, SessionState.ALIGHTING, True, 5, 300.0, GuidanceLevel.INFO, "alighting", _IN_PROGRESS),
    (7, SessionState.ALIGHTING, False, 5, 300.0, GuidanceLevel.INFO, "alighting", _IN_PROGRESS),
    (8, SessionState.COMPLETED, False, 6, 420.0, GuidanceLevel.INFO, "completed", _COMPLETED),
)

_PET_PROGRESSION = (
    (0, SessionState.IDLE, False, 0, None, GuidanceLevel.NONE, "idle", _IN_PROGRESS),
    (1, SessionState.BOARDING, False, 1, 0.0, GuidanceLevel.INFO, "boarding_dropoff", _IN_PROGRESS),
    (2, SessionState.BOARDING, True, 1, 0.0, GuidanceLevel.INFO, "boarding_dropoff", _IN_PROGRESS),
    (3, SessionState.ONBOARD, True, 2, 120.0, GuidanceLevel.INFO, "passenger_onboard", _IN_PROGRESS),
    (4, SessionState.ONBOARD, True, 2, 120.0, GuidanceLevel.INFO, "passenger_onboard", _IN_PROGRESS),
    (5, SessionState.DRIVING, True, 3, 180.0, GuidanceLevel.INFO, "driving", _IN_PROGRESS),
    (6, SessionState.ARRIVED, True, 4, 240.0, GuidanceLevel.REMIND, "arrived_dropoff_check_rear_seat", _IN_PROGRESS),
    (7, SessionState.ALIGHTING, True, 5, 300.0, GuidanceLevel.INFO, "alighting", _IN_PROGRESS),
    (8, SessionState.ALIGHTING, False, 5, 300.0, GuidanceLevel.INFO, "alighting", _IN_PROGRESS),
    (9, SessionState.COMPLETED, False, 6, 420.0, GuidanceLevel.INFO, "completed", _COMPLETED),
)


def _run(name, cut):
    session = CareSession()
    for event in _EVENTS[name]()[:cut]:
        session.apply_event(event)
    return session


def _history_keys(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


def _full_history_keys(name):
    return _history_keys(_run(name, len(_EVENTS[name]())))


def _assert_progression_row(test_case, session, row):
    cut, state, passenger, history_count, duration, level, reason, summary = row
    test_case.assertIs(session.state, state)
    test_case.assertEqual(session.passenger_present, passenger)
    test_case.assertEqual(len(session.history), history_count)
    guidance = guidance_for_session(session, context=DestinationContext.DROPOFF)
    test_case.assertEqual(guidance.level, level)
    test_case.assertEqual(guidance.reason, reason)
    report = report_for_session(session)
    test_case.assertIs(report.final_state, state)
    test_case.assertEqual(report.passenger_present, passenger)
    test_case.assertEqual(report.transition_count, history_count)
    test_case.assertEqual(report.duration_seconds, duration)
    test_case.assertEqual(report.summary, summary)


class TruncatedEventDeliveryQATest(unittest.TestCase):
    def test_normal_all_prefixes_progression(self):
        full_keys = _full_history_keys("normal")
        self.assertEqual(len(full_keys), 6)
        for row in _NORMAL_PROGRESSION:
            cut = row[0]
            with self.subTest(scenario="normal", cut=cut):
                session = _run("normal", cut)
                _assert_progression_row(self, session, row)
                self.assertIsNone(session.current_snapshot.cabin_temp_c)
                self.assertFalse(session.current_snapshot.hvac_on)
                report = report_for_session(session)
                self.assertIsNone(report.max_cabin_temp_c)
                self.assertEqual(report.exception_count, 0)
                self.assertEqual(report.completed, cut == 8)
                self.assertEqual(_history_keys(session), full_keys[: len(session.history)])

    def test_forgotten_cut0_to_5_progression(self):
        full_keys = _full_history_keys("forgotten")
        for row in _NORMAL_PROGRESSION[:6]:
            cut = row[0]
            with self.subTest(scenario="forgotten", cut=cut):
                session = _run("forgotten", cut)
                _assert_progression_row(self, session, row)
                report = report_for_session(session)
                self.assertIsNone(report.max_cabin_temp_c)
                self.assertEqual(report.exception_count, 0)
                self.assertFalse(report.completed)
                self.assertEqual(_history_keys(session), full_keys[: len(session.history)])

    def test_forgotten_cut6_to_8_fixed_history_but_temp_advances(self):
        expected = (
            (6, None, None, "passenger_left_locked"),
            (7, 32.0, 32.0, "passenger_left_locked_hot_cabin"),
            (8, 35.5, 35.5, "passenger_left_locked_dangerous_cabin_temp"),
        )
        fixed_keys = _history_keys(_run("forgotten", 6))
        self.assertEqual(len(fixed_keys), 5)
        for cut, current_temp, max_temp, reason in expected:
            with self.subTest(scenario="forgotten", cut=cut):
                session = _run("forgotten", cut)
                self.assertIs(session.state, SessionState.EXCEPTION)
                self.assertTrue(session.passenger_present)
                self.assertEqual(len(session.history), 5)
                self.assertEqual(_history_keys(session), fixed_keys)
                self.assertEqual(session.current_snapshot.cabin_temp_c, current_temp)
                guidance = guidance_for_session(
                    session, context=DestinationContext.DROPOFF
                )
                self.assertEqual(guidance.level, GuidanceLevel.URGENT)
                self.assertEqual(guidance.reason, reason)
                if cut == 8:
                    self.assertIn("35.5도", guidance.text)
                    self.assertIn("즉시", guidance.text)
                report = report_for_session(session)
                self.assertFalse(report.completed)
                self.assertEqual(report.exception_count, 1)
                self.assertEqual(report.transition_count, 5)
                self.assertEqual(report.duration_seconds, 300.0)
                self.assertEqual(report.max_cabin_temp_c, max_temp)
                self.assertEqual(report.summary, _EXCEPTION)

    def test_pet_all_prefixes_progression_and_hvac(self):
        full_keys = _full_history_keys("pet")
        self.assertEqual(len(full_keys), 6)
        for row in _PET_PROGRESSION:
            cut = row[0]
            with self.subTest(scenario="pet", cut=cut):
                session = _run("pet", cut)
                _assert_progression_row(self, session, row)
                report = report_for_session(session)
                self.assertIsNone(report.max_cabin_temp_c)
                self.assertEqual(report.exception_count, 0)
                self.assertEqual(report.completed, cut == 9)
                self.assertEqual(_history_keys(session), full_keys[: len(session.history)])
                # HVAC_ON은 cut=4부터 도착하며 전이를 만들지 않는다.
                self.assertEqual(session.current_snapshot.hvac_on, cut >= 4)

    def test_all_prefixes_report_log_aggregates(self):
        sessions = [
            _run(name, cut)
            for name in ("normal", "forgotten", "pet")
            for cut in range(len(_EVENTS[name]()) + 1)
        ]
        self.assertEqual(len(sessions), 28)
        log = CareReportLog()
        added = log.add_sessions(sessions)
        self.assertEqual(len(added), 28)
        self.assertEqual(len(log), 28)
        self.assertEqual(len(log.reports), 28)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 3)
        self.assertEqual(log.total_exception_count, 3)
        self.assertEqual(log.total_transition_count, 82)
        self.assertEqual(sum(r.transition_count for r in log.reports), 82)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.average_duration_seconds, 187.2)

    def test_truncated_event_invariants_and_apply_events_equivalence(self):
        for name in ("normal", "forgotten", "pet"):
            events = _EVENTS[name]()
            full_count = len(events)
            full_keys = _full_history_keys(name)
            full_transition_count = len(full_keys)
            for cut in range(full_count + 1):
                with self.subTest(scenario=name, cut=cut):
                    session = _run(name, cut)
                    report = report_for_session(session)
                    self.assertEqual(_history_keys(session), full_keys[: len(session.history)])
                    self.assertLessEqual(report.transition_count, full_transition_count)
                    is_full_completed = (
                        name in ("normal", "pet") and cut == full_count
                    )
                    self.assertEqual(report.completed, is_full_completed)
                    if not is_full_completed:
                        self.assertFalse(report.completed)
                        self.assertIsNot(session.state, SessionState.COMPLETED)
                    # apply_events(제너레이터) 경로는 per-event와 동일하다.
                    bulk = CareSession()
                    bulk.apply_events(iter(events[:cut]))
                    self.assertIs(bulk.state, session.state)
                    self.assertEqual(_history_keys(bulk), _history_keys(session))
                    self.assertEqual(bulk.current_snapshot, session.current_snapshot)
                    self.assertEqual(report_for_session(bulk), report)


if __name__ == "__main__":
    unittest.main()

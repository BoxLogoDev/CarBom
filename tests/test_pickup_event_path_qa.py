"""하원(PICKUP) 맥락 고정 시나리오의 이벤트 전용 경로 QA.

전제: 안내 문구의 목적지 맥락은 BOARDING·ARRIVED 표현만 바꾸고
세션 상태머신·전이·케어 리포트에는 영향을 주지 않으며, EXCEPTION
안내는 맥락과 무관하다(engine/guidance.py).

기존 tests/test_pickup_flow_qa.py는 스냅샷 시퀀스 경로로 PICKUP
맥락을 관통 검증했고, 기존 tests/test_pet_event_path_qa.py와
tests/test_elder_event_path_qa.py는 동승자 변형의 이벤트 전용
경로만 다뤘다. 그래서 하원 흐름을 첨부 스냅샷 없는 SignalEvent
입력만으로 구동하면서 모든 안내를 PICKUP 맥락으로 조회하는
조합은 미검증이었다. 이 파일이 그 조합을 검증한다.
"""

import unittest

from engine.guidance import (
    DestinationContext,
    GuidanceLevel,
    guidance_for_session,
)
from engine.report import report_for_session
from engine.session import CareSession, SessionState
from engine.signals import SignalEvent, SignalEventType
from engine.adapters.simulator import replay_scenario

_NORMAL_HISTORY = (
    (SessionState.IDLE, SessionState.BOARDING, "rear_door_opened"),
    (SessionState.BOARDING, SessionState.ONBOARD, "passenger_onboard"),
    (SessionState.ONBOARD, SessionState.DRIVING, "ignition_on"),
    (SessionState.DRIVING, SessionState.ARRIVED, "ignition_off"),
    (SessionState.ARRIVED, SessionState.ALIGHTING, "alighting_started"),
    (
        SessionState.ALIGHTING,
        SessionState.COMPLETED,
        "alighting_confirmed",
    ),
)


def _events_to_arrived():
    return (
        SignalEvent(SignalEventType.REAR_DOOR_OPENED, timestamp=0.0),
        SignalEvent(SignalEventType.REAR_BELT_BUCKLED, timestamp=60.0),
        SignalEvent(SignalEventType.REAR_DOOR_CLOSED, timestamp=120.0),
        SignalEvent(SignalEventType.HVAC_ON, timestamp=150.0),
        SignalEvent(SignalEventType.IGNITION_ON, timestamp=180.0),
        SignalEvent(SignalEventType.IGNITION_OFF, timestamp=240.0),
    )


def _normal_events():
    return _events_to_arrived() + (
        SignalEvent(SignalEventType.REAR_DOOR_OPENED, timestamp=300.0),
        SignalEvent(
            SignalEventType.REAR_BELT_UNBUCKLED, timestamp=360.0
        ),
        SignalEvent(SignalEventType.REAR_DOOR_CLOSED, timestamp=420.0),
    )


def _exception_events():
    return _events_to_arrived() + (
        SignalEvent(SignalEventType.HVAC_OFF, timestamp=250.0),
        SignalEvent(SignalEventType.LOCKED, timestamp=300.0),
        SignalEvent(
            SignalEventType.CABIN_TEMP_CHANGED,
            timestamp=360.0,
            cabin_temp_c=28.0,
        ),
        SignalEvent(
            SignalEventType.CABIN_TEMP_CHANGED,
            timestamp=420.0,
            cabin_temp_c=32.0,
        ),
        SignalEvent(
            SignalEventType.CABIN_TEMP_CHANGED,
            timestamp=480.0,
            cabin_temp_c=35.5,
        ),
    )


def _history_signature(session):
    return tuple(
        (t.from_state, t.to_state, t.reason) for t in session.history
    )


def _history_full(session):
    return tuple(
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    )


class PickupEventPathQATest(unittest.TestCase):
    def test_normal_flow_until_arrived_and_pickup_guidance(self):
        session = CareSession()
        events = _events_to_arrived()

        state = session.apply_event(events[0])
        self.assertEqual(state, SessionState.BOARDING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 1)
        boarding = guidance_for_session(
            session, DestinationContext.PICKUP
        )
        self.assertEqual(boarding.level, GuidanceLevel.INFO)
        self.assertEqual(boarding.reason, "boarding_pickup")
        self.assertIn("하원", boarding.text)

        state = session.apply_event(events[1])
        self.assertEqual(state, SessionState.BOARDING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 1)

        state = session.apply_event(events[2])
        self.assertEqual(state, SessionState.ONBOARD)
        self.assertEqual(len(session.history), 2)
        self.assertEqual(
            session.history[-1].reason, "passenger_onboard"
        )

        state = session.apply_event(events[3])
        self.assertEqual(state, SessionState.ONBOARD)
        self.assertEqual(len(session.history), 2)
        self.assertTrue(session.current_snapshot.hvac_on)

        state = session.apply_event(events[4])
        self.assertEqual(state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)

        state = session.apply_event(events[5])
        self.assertEqual(state, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)
        self.assertTrue(session.passenger_present)
        arrived = guidance_for_session(
            session, DestinationContext.PICKUP
        )
        self.assertEqual(arrived.level, GuidanceLevel.REMIND)
        self.assertEqual(
            arrived.reason, "arrived_pickup_check_rear_seat"
        )
        self.assertIn("하원", arrived.text)
        self.assertIn("뒷좌석", arrived.text)

    def test_normal_flow_alighting_history_report_and_guidance(self):
        session = CareSession()
        for event in _events_to_arrived():
            session.apply_event(event)

        events = _normal_events()[len(_events_to_arrived()):]
        state = session.apply_event(events[0])
        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 5)
        self.assertEqual(
            session.history[-1].reason, "alighting_started"
        )

        state = session.apply_event(events[1])
        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 5)

        state = session.apply_event(events[2])
        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(_history_signature(session), _NORMAL_HISTORY)

        report = report_for_session(session)
        self.assertEqual(report.final_state, SessionState.COMPLETED)
        self.assertTrue(report.completed)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 420.0)
        self.assertIsNone(report.max_cabin_temp_c)
        self.assertFalse(report.passenger_present)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

        pickup = guidance_for_session(
            session, DestinationContext.PICKUP
        )
        dropoff = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(pickup.level, GuidanceLevel.INFO)
        self.assertEqual(pickup.reason, "completed")
        self.assertEqual(pickup.text, "하차 확인이 완료되었습니다.")
        self.assertEqual(
            (pickup.level, pickup.text, pickup.reason),
            (dropoff.level, dropoff.text, dropoff.reason),
        )

    def test_exception_flow_temp_escalation_context_independent(self):
        session = CareSession()
        for event in _events_to_arrived():
            session.apply_event(event)
        self.assertEqual(session.state, SessionState.ARRIVED)

        events = _exception_events()[len(_events_to_arrived()):]
        state = session.apply_event(events[0])
        self.assertEqual(state, SessionState.ARRIVED)
        self.assertFalse(session.current_snapshot.hvac_on)
        self.assertEqual(len(session.history), 4)

        state = session.apply_event(events[1])
        self.assertEqual(state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 5)
        self.assertEqual(
            session.history[-1].reason,
            "ignition_off_locked_passenger_present",
        )

        expected = (
            ("passenger_left_locked", None),
            ("passenger_left_locked_hot_cabin", "32도"),
            (
                "passenger_left_locked_dangerous_cabin_temp",
                "35.5도",
            ),
        )
        for event, (reason, temp_text) in zip(events[2:], expected):
            session.apply_event(event)
            self.assertEqual(session.state, SessionState.EXCEPTION)
            self.assertEqual(len(session.history), 5)
            pickup = guidance_for_session(
                session, DestinationContext.PICKUP
            )
            dropoff = guidance_for_session(
                session, DestinationContext.DROPOFF
            )
            self.assertEqual(pickup.level, GuidanceLevel.URGENT)
            self.assertEqual(pickup.reason, reason)
            self.assertEqual(
                (pickup.level, pickup.text, pickup.reason),
                (dropoff.level, dropoff.text, dropoff.reason),
            )
            if temp_text is None:
                self.assertNotIn("도입니다", pickup.text)
            else:
                self.assertIn(temp_text, pickup.text)
        self.assertIn("즉시", pickup.text)

        report = report_for_session(session)
        self.assertEqual(report.final_state, SessionState.EXCEPTION)
        self.assertFalse(report.completed)
        self.assertTrue(report.exception_occurred)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_exception_recovery_completes_and_report(self):
        session = CareSession()
        for event in _exception_events():
            session.apply_event(event)
        self.assertEqual(session.state, SessionState.EXCEPTION)

        state = session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_OPENED, timestamp=540.0
            )
        )
        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertEqual(len(session.history), 6)
        self.assertEqual(
            session.history[-1].reason,
            "rear_door_opened_after_exception",
        )
        self.assertTrue(session.passenger_present)

        state = session.apply_event(
            SignalEvent(
                SignalEventType.REAR_BELT_UNBUCKLED, timestamp=600.0
            )
        )
        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 6)

        state = session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_CLOSED, timestamp=660.0
            )
        )
        self.assertEqual(state, SessionState.COMPLETED)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertTrue(report.exception_occurred)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 7)
        self.assertEqual(report.duration_seconds, 660.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(
            report.summary, "예외 발생 후 하차 확인 완료"
        )

    def test_event_path_matches_snapshot_path_history(self):
        event_session = CareSession()
        for event in _normal_events():
            event_session.apply_event(event)

        snapshot_session = CareSession()
        final = replay_scenario(snapshot_session, "dropoff_normal")

        self.assertEqual(final, SessionState.COMPLETED)
        self.assertEqual(event_session.state, snapshot_session.state)
        self.assertEqual(
            event_session.passenger_present,
            snapshot_session.passenger_present,
        )
        self.assertEqual(
            _history_signature(event_session),
            _history_signature(snapshot_session),
        )
        self.assertEqual(
            _history_signature(event_session), _NORMAL_HISTORY
        )
        event_guide = guidance_for_session(
            event_session, DestinationContext.PICKUP
        )
        snapshot_guide = guidance_for_session(
            snapshot_session, DestinationContext.PICKUP
        )
        self.assertEqual(
            (
                event_guide.level,
                event_guide.text,
                event_guide.reason,
            ),
            (
                snapshot_guide.level,
                snapshot_guide.text,
                snapshot_guide.reason,
            ),
        )

    def test_apply_events_generator_matches_per_event(self):
        per_event = CareSession()
        for event in _normal_events():
            per_event.apply_event(event)

        bulk = CareSession()
        result = bulk.apply_events(
            event for event in _normal_events()
        )

        self.assertEqual(result, per_event.state)
        self.assertEqual(bulk.state, per_event.state)
        self.assertEqual(
            bulk.passenger_present, per_event.passenger_present
        )
        self.assertEqual(
            _history_full(bulk), _history_full(per_event)
        )
        self.assertEqual(
            bulk.current_snapshot, per_event.current_snapshot
        )
        self.assertEqual(
            report_for_session(bulk), report_for_session(per_event)
        )


if __name__ == "__main__":
    unittest.main()

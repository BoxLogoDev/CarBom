"""부모님 변형 고정 시나리오의 이벤트 전용 경로 QA.

전제: 부모님이 후석 안전벨트를 체결한 경우를 현행 동승자 판정
(후석 벨트 체결 시 동승자 있음)으로 모델링한다. 부모님(ELDER)
프로필은 벨트를 체결하지 않아도 수동 탑승 확인을 요구하지 않으며
수동 확인을 요구하는 것은 반려동물(PET)뿐이다. 반대로 벨트를
체결하지 않은 동승자는 현행 벨트 기반 판정으로는 세션이 감지할
수 없다는 한계도 함께 고정한다.

기존 tests/test_elder_variant_qa.py는 스냅샷 경로만 다뤘고
기존 tests/test_pet_event_path_qa.py는 반려동물 이벤트 경로만,
기존 tests/test_event_path_qa.py는 아이 흐름 이벤트 경로만 다뤘다.
그래서 부모님을 첨부 스냅샷 없는 SignalEvent 입력만으로 구동하는
조합은 미검증이었다. 이 파일이 그 조합을 검증한다.
"""

import unittest

from engine import (
    PassengerKind,
    needs_manual_confirmation,
    profile_for,
)
from engine.guidance import (
    DestinationContext,
    GuidanceLevel,
    guidance_for_session,
)
from engine.report import report_for_session
from engine.session import CareSession, SessionState
from engine.signals import SignalEvent, SignalEventType

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


def _drive(events):
    session = CareSession()
    for event in events:
        session.apply_event(event)
    return session


def _history(session):
    return tuple(
        (t.from_state, t.to_state, t.reason) for t in session.history
    )


def _history_with_timestamps(session):
    return tuple(
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    )


class ElderEventPathQATest(unittest.TestCase):
    def test_normal_flow_until_arrived_and_dropoff_guidance(self):
        elder = profile_for(PassengerKind.ELDER)
        pet = profile_for(PassengerKind.PET)
        session = CareSession()

        session.apply_event(
            SignalEvent(SignalEventType.REAR_DOOR_OPENED, timestamp=0.0)
        )
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertFalse(session.passenger_present)
        belt = session.current_snapshot.rear_seat_belt_buckled
        self.assertFalse(belt)
        self.assertFalse(
            needs_manual_confirmation(elder, belt_buckled=belt)
        )
        # 대조: 벨트 체결 전에는 PET만 수동 확인을 요구한다.
        self.assertTrue(needs_manual_confirmation(pet, belt_buckled=belt))

        session.apply_event(
            SignalEvent(
                SignalEventType.REAR_BELT_BUCKLED, timestamp=60.0
            )
        )
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertTrue(session.passenger_present)
        belt = session.current_snapshot.rear_seat_belt_buckled
        self.assertTrue(belt)
        self.assertFalse(
            needs_manual_confirmation(elder, belt_buckled=belt)
        )
        self.assertFalse(
            needs_manual_confirmation(pet, belt_buckled=belt)
        )

        session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_CLOSED, timestamp=120.0
            )
        )
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertTrue(session.passenger_present)

        session.apply_event(
            SignalEvent(SignalEventType.HVAC_ON, timestamp=150.0)
        )
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertTrue(session.current_snapshot.hvac_on)

        session.apply_event(
            SignalEvent(SignalEventType.IGNITION_ON, timestamp=180.0)
        )
        self.assertEqual(session.state, SessionState.DRIVING)
        belt = session.current_snapshot.rear_seat_belt_buckled
        self.assertFalse(
            needs_manual_confirmation(elder, belt_buckled=belt)
        )

        session.apply_event(
            SignalEvent(SignalEventType.IGNITION_OFF, timestamp=240.0)
        )
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertTrue(session.passenger_present)

        guidance = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(
            guidance.reason, "arrived_dropoff_check_rear_seat"
        )
        self.assertIn("뒷좌석", guidance.text)
        self.assertIs(guidance.state, SessionState.ARRIVED)

    def test_normal_flow_alighting_history_report_and_guidance(self):
        session = _drive(_events_to_arrived())
        self.assertEqual(session.state, SessionState.ARRIVED)

        session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_OPENED, timestamp=300.0
            )
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertTrue(session.passenger_present)

        session.apply_event(
            SignalEvent(
                SignalEventType.REAR_BELT_UNBUCKLED, timestamp=360.0
            )
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)

        session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_CLOSED, timestamp=420.0
            )
        )
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)

        self.assertEqual(_history(session), _NORMAL_HISTORY)

        report = report_for_session(session)
        self.assertIs(report.final_state, SessionState.COMPLETED)
        self.assertTrue(report.completed)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertFalse(report.passenger_present)
        self.assertEqual(report.started_at, 0.0)
        self.assertEqual(report.ended_at, 420.0)
        self.assertEqual(report.duration_seconds, 420.0)
        self.assertIsNone(report.max_cabin_temp_c)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

        guidance = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")

    def test_exception_flow_temp_escalation_and_report(self):
        session = _drive(_events_to_arrived())
        self.assertEqual(session.state, SessionState.ARRIVED)

        session.apply_event(
            SignalEvent(SignalEventType.HVAC_OFF, timestamp=250.0)
        )
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertFalse(session.current_snapshot.hvac_on)

        session.apply_event(
            SignalEvent(SignalEventType.LOCKED, timestamp=300.0)
        )
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertTrue(session.current_snapshot.locked)
        self.assertEqual(len(session.history), 5)
        last = session.history[-1]
        self.assertEqual(
            (last.from_state, last.to_state, last.reason),
            (
                SessionState.ARRIVED,
                SessionState.EXCEPTION,
                "ignition_off_locked_passenger_present",
            ),
        )

        session.apply_event(
            SignalEvent(
                SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=360.0,
                cabin_temp_c=28.0,
            )
        )
        self.assertEqual(session.state, SessionState.EXCEPTION)
        guidance = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.reason, "passenger_left_locked")
        self.assertNotIn("28", guidance.text)

        session.apply_event(
            SignalEvent(
                SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=420.0,
                cabin_temp_c=32.0,
            )
        )
        self.assertEqual(session.state, SessionState.EXCEPTION)
        guidance = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason, "passenger_left_locked_hot_cabin"
        )
        self.assertIn("32도", guidance.text)

        session.apply_event(
            SignalEvent(
                SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=480.0,
                cabin_temp_c=35.5,
            )
        )
        self.assertEqual(session.state, SessionState.EXCEPTION)
        guidance = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason,
            "passenger_left_locked_dangerous_cabin_temp",
        )
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)

        report = report_for_session(session)
        self.assertIs(report.final_state, SessionState.EXCEPTION)
        self.assertFalse(report.completed)
        self.assertTrue(report.exception_occurred)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 5)
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.started_at, 0.0)
        self.assertEqual(report.ended_at, 300.0)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

    def test_exception_recovery_completes_and_report(self):
        session = _drive(_exception_events())
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)

        session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_OPENED, timestamp=540.0
            )
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        last = session.history[-1]
        self.assertEqual(
            (last.from_state, last.to_state, last.reason),
            (
                SessionState.EXCEPTION,
                SessionState.ALIGHTING,
                "rear_door_opened_after_exception",
            ),
        )

        session.apply_event(
            SignalEvent(
                SignalEventType.REAR_BELT_UNBUCKLED, timestamp=600.0
            )
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)

        session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_CLOSED, timestamp=660.0
            )
        )
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)

        report = report_for_session(session)
        self.assertIs(report.final_state, SessionState.COMPLETED)
        self.assertTrue(report.completed)
        self.assertTrue(report.exception_occurred)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 7)
        self.assertFalse(report.passenger_present)
        self.assertEqual(report.started_at, 0.0)
        self.assertEqual(report.ended_at, 660.0)
        self.assertEqual(report.duration_seconds, 660.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(
            report.summary, "예외 발생 후 하차 확인 완료"
        )

    def test_unbelted_elder_is_not_detected_by_belt_based_engine(self):
        elder = profile_for(PassengerKind.ELDER)
        pet = profile_for(PassengerKind.PET)
        # ELDER는 벨트 미체결이어도 수동 확인을 요구하지 않는다.
        self.assertFalse(
            needs_manual_confirmation(elder, belt_buckled=False)
        )
        self.assertTrue(
            needs_manual_confirmation(pet, belt_buckled=False)
        )

        session = CareSession()
        session.apply_event(
            SignalEvent(SignalEventType.REAR_DOOR_OPENED, timestamp=0.0)
        )
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertFalse(session.passenger_present)

        session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_CLOSED, timestamp=60.0
            )
        )
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertFalse(session.passenger_present)
        last = session.history[-1]
        self.assertEqual(last.reason, "boarding_without_passenger")

        session.apply_event(
            SignalEvent(SignalEventType.IGNITION_ON, timestamp=120.0)
        )
        self.assertEqual(session.state, SessionState.IDLE)
        session.apply_event(
            SignalEvent(SignalEventType.IGNITION_OFF, timestamp=180.0)
        )
        self.assertEqual(session.state, SessionState.IDLE)
        session.apply_event(
            SignalEvent(SignalEventType.LOCKED, timestamp=240.0)
        )
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 2)

        report = report_for_session(session)
        self.assertIs(report.final_state, SessionState.IDLE)
        self.assertFalse(report.completed)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 2)
        self.assertFalse(report.passenger_present)
        self.assertEqual(report.started_at, 0.0)
        self.assertEqual(report.ended_at, 60.0)
        self.assertEqual(report.duration_seconds, 60.0)
        self.assertIsNone(report.max_cabin_temp_c)

    def test_apply_events_generator_matches_per_event(self):
        events = _normal_events()
        for event in events:
            self.assertIsNone(event.snapshot)

        per_event = _drive(events)

        bulk = CareSession()
        final = bulk.apply_events(
            event for event in _normal_events()
        )

        self.assertIs(final, SessionState.COMPLETED)
        self.assertIs(bulk.state, per_event.state)
        self.assertEqual(
            _history_with_timestamps(bulk),
            _history_with_timestamps(per_event),
        )
        self.assertEqual(
            bulk.passenger_present, per_event.passenger_present
        )
        self.assertEqual(
            bulk.current_snapshot, per_event.current_snapshot
        )

        bulk_report = report_for_session(bulk)
        per_event_report = report_for_session(per_event)
        self.assertEqual(bulk_report, per_event_report)
        self.assertIs(
            bulk_report.final_state, per_event_report.final_state
        )
        self.assertEqual(
            bulk_report.completed, per_event_report.completed
        )
        self.assertEqual(
            bulk_report.exception_occurred,
            per_event_report.exception_occurred,
        )
        self.assertEqual(
            bulk_report.exception_count,
            per_event_report.exception_count,
        )
        self.assertEqual(
            bulk_report.transition_count,
            per_event_report.transition_count,
        )
        self.assertEqual(
            bulk_report.passenger_present,
            per_event_report.passenger_present,
        )
        self.assertEqual(
            bulk_report.started_at, per_event_report.started_at
        )
        self.assertEqual(
            bulk_report.ended_at, per_event_report.ended_at
        )
        self.assertEqual(
            bulk_report.duration_seconds,
            per_event_report.duration_seconds,
        )
        self.assertEqual(
            bulk_report.max_cabin_temp_c,
            per_event_report.max_cabin_temp_c,
        )
        self.assertEqual(
            bulk_report.transitions, per_event_report.transitions
        )
        self.assertEqual(
            bulk_report.summary, per_event_report.summary
        )


if __name__ == "__main__":
    unittest.main()

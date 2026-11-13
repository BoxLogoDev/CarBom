"""성인 변형 x 하원(PICKUP) 맥락의 이벤트 전용 경로 QA.

전제: 성인이 후석 안전벨트를 체결한 경우를 현행 동승자 판정
(벨트 체결 시 동승자 있음)으로 모델링한다. 동승 프로필 ADULT는
표시명 '성인', belt_detectable True, reminder_note
'안전벨트를 확인해 주세요.'이다. 벨트 체결 여부와 무관하게
수동 탑승 확인(needs_manual_confirmation)은 False이며,
요구하는 것은 PET뿐이다.

기존 tests/test_adult_event_path_qa.py는 DROPOFF 맥락의 성인
이벤트 경로를 다뤘고, 기존 tests/test_pickup_event_path_qa.py는
일반 PICKUP 이벤트 경로를 다뤘으며, 기존
tests/test_pet_pickup_event_path_qa.py와
tests/test_elder_pickup_event_path_qa.py와
tests/test_child_pickup_event_path_qa.py는 각각 PET x PICKUP와
ELDER x PICKUP와 CHILD x PICKUP만 다뤘다. 그래서 성인을 첨부
스냅샷 없는 SignalEvent 입력만으로 구동하면서 모든 안내를
PICKUP 맥락으로 조회하고 ADULT 수동 확인 판정까지 교차하는
ADULT x PICKUP 조합은 미검증이었다. 이 파일이 그 교차 조합을
검증하며, 동승자 변형 4종 x PICKUP 이벤트 경로는 이 파일로
전수된다.
"""

import unittest

from engine.adapters.simulator import replay_scenario
from engine.guidance import (
    DestinationContext,
    GuidanceLevel,
    guidance_for_session,
)
from engine.profiles import (
    PassengerKind,
    needs_manual_confirmation,
    profile_for,
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


def _adult_manual(session):
    return needs_manual_confirmation(
        profile_for(PassengerKind.ADULT),
        belt_buckled=session.current_snapshot.rear_seat_belt_buckled,
    )


class AdultPickupEventPathQATest(unittest.TestCase):
    def test_normal_flow_until_arrived_and_pickup_guidance(self):
        session = CareSession()
        adult = profile_for(PassengerKind.ADULT)
        self.assertEqual(adult.label, "성인")
        self.assertTrue(adult.belt_detectable)
        self.assertFalse(
            adult.requires_manual_confirmation_when_unbelted
        )
        self.assertEqual(
            adult.reminder_note, "안전벨트를 확인해 주세요."
        )
        # 수동 확인 행렬: 미체결에서는 PET만 True, ADULT는 항상 False.
        for kind in PassengerKind:
            profile = profile_for(kind)
            self.assertEqual(
                needs_manual_confirmation(
                    profile, belt_buckled=False
                ),
                kind is PassengerKind.PET,
            )
            self.assertFalse(
                needs_manual_confirmation(
                    profile, belt_buckled=True
                )
            )

        session.apply_event(
            SignalEvent(SignalEventType.REAR_DOOR_OPENED, timestamp=0.0)
        )
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertFalse(session.passenger_present)
        self.assertFalse(_adult_manual(session))
        boarding = guidance_for_session(
            session, DestinationContext.PICKUP
        )
        self.assertEqual(boarding.level, GuidanceLevel.INFO)
        self.assertEqual(boarding.reason, "boarding_pickup")
        self.assertIn("하원", boarding.text)

        session.apply_event(
            SignalEvent(
                SignalEventType.REAR_BELT_BUCKLED, timestamp=60.0
            )
        )
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 1)
        self.assertFalse(_adult_manual(session))

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
        self.assertFalse(_adult_manual(session))

        session.apply_event(
            SignalEvent(SignalEventType.IGNITION_OFF, timestamp=240.0)
        )
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertTrue(session.passenger_present)

        pickup = guidance_for_session(
            session, DestinationContext.PICKUP
        )
        self.assertEqual(pickup.level, GuidanceLevel.REMIND)
        self.assertEqual(
            pickup.reason, "arrived_pickup_check_rear_seat"
        )
        self.assertIn("하원", pickup.text)
        self.assertIn("뒷좌석", pickup.text)
        dropoff = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(
            dropoff.reason, "arrived_dropoff_check_rear_seat"
        )
        self.assertNotEqual(pickup.reason, dropoff.reason)

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
        self.assertEqual(report.duration_seconds, 420.0)
        self.assertIsNone(report.max_cabin_temp_c)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

        pickup = guidance_for_session(
            session, DestinationContext.PICKUP
        )
        dropoff = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(pickup.level, GuidanceLevel.INFO)
        self.assertEqual(pickup.reason, "completed")
        self.assertEqual(
            (pickup.level, pickup.text, pickup.reason),
            (dropoff.level, dropoff.text, dropoff.reason),
        )

    def test_exception_flow_temp_escalation_context_independent(self):
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
        temp_events = _exception_events()[len(_events_to_arrived()) + 2:]
        for event, (reason, temp_text) in zip(temp_events, expected):
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
                self.assertNotIn("28", pickup.text)
            else:
                self.assertIn(temp_text, pickup.text)
        self.assertIn("즉시", pickup.text)

        report = report_for_session(session)
        self.assertIs(report.final_state, SessionState.EXCEPTION)
        self.assertFalse(report.completed)
        self.assertTrue(report.exception_occurred)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 5)
        self.assertTrue(report.passenger_present)
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
        self.assertEqual(
            session.history[-1].reason,
            "rear_door_opened_after_exception",
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
        self.assertEqual(report.duration_seconds, 660.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(
            report.summary, "예외 발생 후 하차 확인 완료"
        )

    def test_unbelted_adult_limit_and_pickup_guidance(self):
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
        self.assertEqual(len(session.history), 2)
        self.assertEqual(
            session.history[-1].reason, "boarding_without_passenger"
        )

        guidance = guidance_for_session(
            session, DestinationContext.PICKUP
        )
        self.assertEqual(guidance.level, GuidanceLevel.NONE)
        self.assertEqual(guidance.reason, "idle")
        self.assertEqual(guidance.text, "")

        # ADULT는 벨트 미체결이어도 수동 확인을 요구하지 않는다.
        self.assertFalse(
            needs_manual_confirmation(
                profile_for(PassengerKind.ADULT), belt_buckled=False
            )
        )
        self.assertTrue(
            needs_manual_confirmation(
                profile_for(PassengerKind.PET), belt_buckled=False
            )
        )
        self.assertFalse(_adult_manual(session))

        report = report_for_session(session)
        self.assertIs(report.final_state, SessionState.IDLE)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 2)
        self.assertEqual(report.duration_seconds, 60.0)
        self.assertIsNone(report.max_cabin_temp_c)

    def test_event_only_matches_snapshot_replay_and_bulk(self):
        events = _normal_events()
        for event in events:
            self.assertIsNone(event.snapshot)

        event_session = _drive(events)

        snapshot_session = CareSession()
        final = replay_scenario(snapshot_session, "dropoff_normal")

        self.assertIs(final, SessionState.COMPLETED)
        self.assertEqual(_history(event_session), _NORMAL_HISTORY)
        self.assertEqual(
            _history(event_session), _history(snapshot_session)
        )
        self.assertIs(event_session.state, snapshot_session.state)
        self.assertEqual(
            event_session.passenger_present,
            snapshot_session.passenger_present,
        )

        per_event = _drive(events)
        bulk = CareSession()
        bulk_final = bulk.apply_events(event for event in events)

        self.assertIs(bulk_final, SessionState.COMPLETED)
        self.assertEqual(
            _history_with_timestamps(bulk),
            _history_with_timestamps(per_event),
        )
        self.assertEqual(
            bulk.current_snapshot, per_event.current_snapshot
        )
        self.assertEqual(
            report_for_session(bulk), report_for_session(per_event)
        )


if __name__ == "__main__":
    unittest.main()

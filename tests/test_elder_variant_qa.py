"""QA scenario for an elder (부모님) passenger in the rear seat.

전제: 부모님이 후석 안전벨트를 체결한 경우를 현행 엔진의 동승자
판정(후석 벨트 체결 시 동승자 있음)으로 모델링한다. 반려동물 변형과
달리 부모님 프로필은 벨트 미체결이어도 수동 탑승 확인을 요구하지
않는다(engine/profiles.py: PET만 requires_manual_confirmation_when_unbelted).
벨트를 체결하지 않은 동승자는 현행 벨트 기반 판정으로는 세션이
감지할 수 없다는 한계도 함께 고정한다.
"""

import unittest

from engine import (
    CareSession,
    DoorState,
    GuidanceLevel,
    IgnitionState,
    LockState,
    PassengerKind,
    SessionState,
    SignalSnapshot,
    guidance_for_session,
    needs_manual_confirmation,
    profile_for,
    report_for_session,
)


def snapshot(**overrides):
    values = {
        "rear_door": DoorState.CLOSED,
        "rear_seat_belt_buckled": False,
        "ignition": IgnitionState.OFF,
        "hvac_on": False,
        "cabin_temp_c": None,
        "lock": LockState.UNLOCKED,
        "timestamp": None,
    }
    values.update(overrides)
    return SignalSnapshot(**values)


def board_drive_and_arrive(session):
    session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
    session.apply_snapshot(snapshot(rear_seat_belt_buckled=True))
    session.apply_snapshot(
        snapshot(rear_seat_belt_buckled=True, ignition=IgnitionState.ON)
    )
    session.apply_snapshot(snapshot(rear_seat_belt_buckled=True))


def enter_exception(session):
    board_drive_and_arrive(session)
    session.apply_snapshot(
        snapshot(rear_seat_belt_buckled=True, lock=LockState.LOCKED)
    )


class ElderProfileTest(unittest.TestCase):
    def test_elder_profile_identity_and_parsing(self):
        elder = profile_for(PassengerKind.ELDER)

        self.assertIs(elder.kind, PassengerKind.ELDER)
        self.assertEqual(elder.label, "부모님")
        self.assertTrue(elder.belt_detectable)
        self.assertTrue(elder.reminder_note)
        self.assertEqual(profile_for(" elder "), elder)
        self.assertEqual(profile_for("ELDER"), elder)

    def test_elder_never_needs_manual_confirmation_unlike_pet(self):
        elder = profile_for(PassengerKind.ELDER)
        pet = profile_for(PassengerKind.PET)

        self.assertFalse(needs_manual_confirmation(elder, belt_buckled=True))
        self.assertFalse(needs_manual_confirmation(elder, belt_buckled=False))
        # 대조: 벨트 미체결에서 수동 확인을 요구하는 것은 PET뿐이다.
        self.assertTrue(needs_manual_confirmation(pet, belt_buckled=False))
        self.assertFalse(needs_manual_confirmation(pet, belt_buckled=True))


class ElderBeltedFlowTest(unittest.TestCase):
    def test_normal_flow_completes_after_alighting(self):
        session = CareSession()

        session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
        self.assertEqual(session.state, SessionState.BOARDING)

        session.apply_snapshot(snapshot(rear_seat_belt_buckled=True))
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertTrue(session.passenger_present)

        session.apply_snapshot(
            snapshot(rear_seat_belt_buckled=True, ignition=IgnitionState.ON)
        )
        self.assertEqual(session.state, SessionState.DRIVING)

        session.apply_snapshot(snapshot(rear_seat_belt_buckled=True))
        self.assertEqual(session.state, SessionState.ARRIVED)

        guidance = guidance_for_session(session)
        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertIn("뒷좌석", guidance.text)
        self.assertIn("확인", guidance.text)

        session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)

        session.apply_snapshot(snapshot())
        self.assertEqual(session.state, SessionState.COMPLETED)

    def test_forgotten_alighting_locked_is_urgent_exception(self):
        session = CareSession()
        enter_exception(session)

        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)

        guidance = guidance_for_session(session)
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)

    def test_exception_recovers_and_completes_with_report(self):
        session = CareSession()
        enter_exception(session)
        self.assertEqual(session.state, SessionState.EXCEPTION)

        session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
        self.assertEqual(session.state, SessionState.ALIGHTING)

        session.apply_snapshot(snapshot())
        self.assertEqual(session.state, SessionState.COMPLETED)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertTrue(report.exception_occurred)
        self.assertEqual(report.exception_count, 1)

    def test_unbelted_elder_is_not_detected_by_belt_based_session(self):
        # 한계 고정: 벨트 미체결 동승자는 현행 판정으로 감지할 수 없고,
        # ELDER 프로필은 PET와 달리 수동 확인 보조 판정도 요구하지 않는다.
        session = CareSession()

        session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
        self.assertEqual(session.state, SessionState.BOARDING)

        session.apply_snapshot(snapshot())
        self.assertEqual(session.state, SessionState.IDLE)
        self.assertFalse(session.passenger_present)

        elder = profile_for(PassengerKind.ELDER)
        self.assertFalse(
            needs_manual_confirmation(elder, belt_buckled=False)
        )


if __name__ == "__main__":
    unittest.main()

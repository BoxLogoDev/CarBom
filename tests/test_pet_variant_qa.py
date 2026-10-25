"""QA scenario for a pet carrier belted to the rear seat.

전제: 반려동물 이동장이 후석 안전벨트로 고정된 경우를 현행 엔진의
동승자 판정(후석 벨트 체결 시 동승자 있음)으로 모델링한다.
"""

import unittest

from engine import (
    CareSession,
    DoorState,
    GuidanceLevel,
    IgnitionState,
    LockState,
    SessionState,
    SignalSnapshot,
    guidance_for_session,
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
        snapshot(
            rear_seat_belt_buckled=True,
            cabin_temp_c=34.0,
            lock=LockState.LOCKED,
        )
    )


class PetCarrierBeltedTest(unittest.TestCase):
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

    def test_forgotten_alighting_hot_locked_is_urgent_exception(self):
        session = CareSession()
        enter_exception(session)

        self.assertEqual(session.state, SessionState.EXCEPTION)

        guidance = guidance_for_session(session)
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertIn("34", guidance.text)

    def test_exception_recovers_and_completes(self):
        session = CareSession()
        enter_exception(session)
        self.assertEqual(session.state, SessionState.EXCEPTION)

        session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
        self.assertEqual(session.state, SessionState.ALIGHTING)

        session.apply_snapshot(snapshot())
        self.assertEqual(session.state, SessionState.COMPLETED)

        completed = [
            transition
            for transition in session.history
            if transition.to_state is SessionState.COMPLETED
        ]
        self.assertTrue(completed)


if __name__ == "__main__":
    unittest.main()

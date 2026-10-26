"""안내 문구 직접 API(guidance_for) 경계 조건 QA 테스트."""

import unittest
from dataclasses import FrozenInstanceError

from engine import (
    CareSession,
    DestinationContext,
    DoorState,
    Guidance,
    GuidanceLevel,
    IgnitionState,
    LockState,
    SessionState,
    SignalSnapshot,
    guidance_for,
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


class NoneSnapshotTest(unittest.TestCase):
    def test_none_snapshot_arrived_is_remind_without_temperature(self):
        guidance = guidance_for(
            SessionState.ARRIVED, None, passenger_present=True
        )

        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertIn("뒷좌석", guidance.text)
        self.assertNotIn("실내 온도", guidance.text)

    def test_none_snapshot_exception_is_urgent_without_temperature(self):
        guidance = guidance_for(
            SessionState.EXCEPTION, None, passenger_present=True
        )

        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertIn("뒷좌석", guidance.text)
        self.assertNotIn("실내 온도", guidance.text)
        self.assertFalse(any(ch.isdigit() for ch in guidance.text))

    def test_none_snapshot_driving_is_info(self):
        guidance = guidance_for(
            SessionState.DRIVING, None, passenger_present=True
        )

        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertIn("안전 운전", guidance.text)


class NoPassengerGateMatrixTest(unittest.TestCase):
    def test_no_passenger_gate_for_all_states(self):
        # (state, expected level, expected reason)
        cases = [
            (SessionState.IDLE, GuidanceLevel.NONE, "idle"),
            (SessionState.BOARDING, GuidanceLevel.INFO, "boarding"),
            (SessionState.ONBOARD, GuidanceLevel.NONE, "no_passenger"),
            (SessionState.DRIVING, GuidanceLevel.NONE, "no_passenger"),
            (SessionState.ARRIVED, GuidanceLevel.NONE, "no_passenger"),
            (SessionState.ALIGHTING, GuidanceLevel.INFO, "alighting"),
            (SessionState.COMPLETED, GuidanceLevel.INFO, "completed"),
            (SessionState.EXCEPTION, GuidanceLevel.NONE, "no_passenger"),
        ]
        for state, level, reason in cases:
            with self.subTest(state=state):
                guidance = guidance_for(
                    state, snapshot(), passenger_present=False
                )
                self.assertEqual(guidance.level, level)
                self.assertEqual(guidance.reason, reason)
                if level is GuidanceLevel.NONE:
                    self.assertEqual(guidance.text, "")
                else:
                    self.assertNotEqual(guidance.text, "")


class GuidanceImmutabilityTest(unittest.TestCase):
    def test_guidance_is_frozen(self):
        guidance = Guidance(
            level=GuidanceLevel.INFO,
            state=SessionState.DRIVING,
            text="안전 운전 중입니다.",
            reason="driving",
        )

        with self.assertRaises(FrozenInstanceError):
            guidance.level = GuidanceLevel.URGENT


class GuidanceForSessionEquivalenceTest(unittest.TestCase):
    def test_session_guidance_matches_direct_guidance(self):
        session = CareSession()
        session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
        session.apply_snapshot(snapshot(rear_seat_belt_buckled=True))
        session.apply_snapshot(
            snapshot(rear_seat_belt_buckled=True, ignition=IgnitionState.ON)
        )
        session.apply_snapshot(snapshot(rear_seat_belt_buckled=True))
        self.assertEqual(session.state, SessionState.ARRIVED)

        via_session = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        direct = guidance_for(
            session.state,
            session.current_snapshot,
            passenger_present=session.passenger_present,
            context=DestinationContext.DROPOFF,
        )

        self.assertEqual(via_session.level, direct.level)
        self.assertEqual(via_session.state, direct.state)
        self.assertEqual(via_session.text, direct.text)
        self.assertEqual(via_session.reason, direct.reason)


class IntegerTemperatureFormatTest(unittest.TestCase):
    def test_integer_temperature_has_no_decimal_point(self):
        guidance = guidance_for(
            SessionState.EXCEPTION,
            snapshot(
                rear_seat_belt_buckled=True,
                lock=LockState.LOCKED,
                cabin_temp_c=32.0,
            ),
            passenger_present=True,
        )

        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertIn("32도", guidance.text)
        self.assertNotIn("32.0도", guidance.text)
        self.assertEqual(
            guidance.reason, "passenger_left_locked_hot_cabin"
        )


if __name__ == "__main__":
    unittest.main()

"""안내 문구 엔진의 단위 테스트."""

import unittest

from engine import (
    CareSession,
    DestinationContext,
    DoorState,
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


def board_drive_and_arrive(session):
    session.apply_snapshot(snapshot(rear_door=DoorState.OPEN))
    session.apply_snapshot(snapshot(rear_seat_belt_buckled=True))
    session.apply_snapshot(
        snapshot(rear_seat_belt_buckled=True, ignition=IgnitionState.ON)
    )
    session.apply_snapshot(snapshot(rear_seat_belt_buckled=True))


class GuidanceForTest(unittest.TestCase):
    def test_arrived_dropoff_reminds_rear_seat_check(self):
        guidance = guidance_for(
            SessionState.ARRIVED,
            snapshot(rear_seat_belt_buckled=True),
            passenger_present=True,
            context=DestinationContext.DROPOFF,
        )

        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(guidance.state, SessionState.ARRIVED)
        self.assertIn("뒷좌석", guidance.text)
        self.assertIn("확인", guidance.text)
        self.assertIn("등원", guidance.text)
        self.assertIn("하차", guidance.text)

    def test_driving_is_info_without_encouraging_operation(self):
        guidance = guidance_for(
            SessionState.DRIVING,
            snapshot(rear_seat_belt_buckled=True, ignition=IgnitionState.ON),
            passenger_present=True,
        )

        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertIn("안전", guidance.text)
        self.assertIn("운전 중", guidance.text)
        self.assertIn("조작하지", guidance.text)

    def test_completed_is_info_completion_message(self):
        guidance = guidance_for(
            SessionState.COMPLETED,
            snapshot(),
            passenger_present=False,
        )

        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertIn("완료", guidance.text)

    def test_exception_is_urgent(self):
        guidance = guidance_for(
            SessionState.EXCEPTION,
            snapshot(rear_seat_belt_buckled=True, lock=LockState.LOCKED),
            passenger_present=True,
        )

        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertIn("뒷좌석", guidance.text)
        self.assertIn("확인", guidance.text)
        self.assertTrue(guidance.reason)

    def test_exception_at_32_includes_cabin_temperature(self):
        guidance = guidance_for(
            SessionState.EXCEPTION,
            snapshot(
                rear_seat_belt_buckled=True,
                lock=LockState.LOCKED,
                cabin_temp_c=33.5,
            ),
            passenger_present=True,
        )

        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertIn("33.5", guidance.text)

    def test_exception_at_35_escalates_wording_and_reason(self):
        warm = guidance_for(
            SessionState.EXCEPTION,
            snapshot(
                rear_seat_belt_buckled=True,
                lock=LockState.LOCKED,
                cabin_temp_c=33.0,
            ),
            passenger_present=True,
        )
        hot = guidance_for(
            SessionState.EXCEPTION,
            snapshot(
                rear_seat_belt_buckled=True,
                lock=LockState.LOCKED,
                cabin_temp_c=36.0,
            ),
            passenger_present=True,
        )

        self.assertEqual(hot.level, GuidanceLevel.URGENT)
        self.assertIn("36", hot.text)
        self.assertTrue("즉시" in hot.text or "위험" in hot.text)
        self.assertNotEqual(hot.reason, warm.reason)
        self.assertNotEqual(hot.text, warm.text)

    def test_idle_and_no_passenger_are_none_with_empty_text(self):
        idle = guidance_for(
            SessionState.IDLE, snapshot(), passenger_present=False
        )
        no_passenger = guidance_for(
            SessionState.DRIVING,
            snapshot(ignition=IgnitionState.ON),
            passenger_present=False,
        )

        self.assertEqual(idle.level, GuidanceLevel.NONE)
        self.assertEqual(idle.text, "")
        self.assertEqual(no_passenger.level, GuidanceLevel.NONE)
        self.assertEqual(no_passenger.text, "")

    def test_boarding_dropoff_mentions_school_preparation(self):
        guidance = guidance_for(
            SessionState.BOARDING,
            snapshot(rear_door=DoorState.OPEN),
            passenger_present=False,
            context=DestinationContext.DROPOFF,
        )

        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertIn("승차", guidance.text)
        self.assertIn("등원", guidance.text)

    def test_level_strength_is_ordered(self):
        self.assertLess(GuidanceLevel.NONE, GuidanceLevel.INFO)
        self.assertLess(GuidanceLevel.INFO, GuidanceLevel.REMIND)
        self.assertLess(GuidanceLevel.REMIND, GuidanceLevel.URGENT)


class GuidanceForSessionTest(unittest.TestCase):
    def test_session_arrived_in_dropoff_flow(self):
        session = CareSession()
        board_drive_and_arrive(session)
        self.assertEqual(session.state, SessionState.ARRIVED)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )

        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(guidance.state, SessionState.ARRIVED)
        self.assertIn("등원", guidance.text)

    def test_session_exception_uses_current_snapshot_temperature(self):
        session = CareSession()
        board_drive_and_arrive(session)
        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                lock=LockState.LOCKED,
                cabin_temp_c=36.5,
            )
        )
        self.assertEqual(session.state, SessionState.EXCEPTION)

        guidance = guidance_for_session(session)

        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertIn("36.5", guidance.text)


if __name__ == "__main__":
    unittest.main()

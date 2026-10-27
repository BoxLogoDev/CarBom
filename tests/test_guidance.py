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
    guidances_for_sessions,
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


class GuidancesForSessionsTest(unittest.TestCase):
    def _arrived_session(self):
        session = CareSession()
        board_drive_and_arrive(session)
        self.assertEqual(session.state, SessionState.ARRIVED)
        return session

    def test_empty_input_returns_empty_tuple(self):
        self.assertEqual(guidances_for_sessions([]), ())
        self.assertEqual(guidances_for_sessions(iter(())), ())

    def test_order_preserved_and_matches_individual_calls(self):
        idle = CareSession()
        arrived = self._arrived_session()

        result = guidances_for_sessions([arrived, idle])

        self.assertEqual(len(result), 2)
        for actual, session in zip(result, [arrived, idle]):
            expected = guidance_for_session(session)
            self.assertEqual(actual.level, expected.level)
            self.assertEqual(actual.state, expected.state)
            self.assertEqual(actual.text, expected.text)
            self.assertEqual(actual.reason, expected.reason)
        self.assertEqual(result[0].state, SessionState.ARRIVED)
        self.assertEqual(result[0].level, GuidanceLevel.REMIND)
        self.assertEqual(result[1].state, SessionState.IDLE)
        self.assertEqual(result[1].level, GuidanceLevel.NONE)

    def test_sessions_are_not_mutated(self):
        arrived = self._arrived_session()
        before = (
            arrived.state,
            len(arrived.history),
            arrived.current_snapshot,
            arrived.passenger_present,
        )

        guidances_for_sessions([arrived])

        after = (
            arrived.state,
            len(arrived.history),
            arrived.current_snapshot,
            arrived.passenger_present,
        )
        self.assertEqual(after, before)

    def test_generator_input_matches_list_input(self):
        sessions = [CareSession(), self._arrived_session()]

        from_list = guidances_for_sessions(sessions)
        from_generator = guidances_for_sessions(s for s in sessions)

        self.assertEqual(from_generator, from_list)

    def test_context_is_propagated_to_each_session(self):
        arrived = self._arrived_session()

        default = guidances_for_sessions([arrived])
        dropoff = guidances_for_sessions(
            [arrived], context=DestinationContext.DROPOFF
        )

        self.assertIn("등원", dropoff[0].text)
        self.assertNotEqual(dropoff[0].text, default[0].text)
        self.assertEqual(
            dropoff[0],
            guidance_for_session(
                arrived, context=DestinationContext.DROPOFF
            ),
        )

    def test_string_context_matches_enum_context(self):
        arrived = self._arrived_session()

        from_string = guidances_for_sessions([arrived], context="dropoff")
        from_enum = guidances_for_sessions(
            [arrived], context=DestinationContext.DROPOFF
        )

        self.assertEqual(from_string, from_enum)


if __name__ == "__main__":
    unittest.main()

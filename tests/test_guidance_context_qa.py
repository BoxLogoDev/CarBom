"""목적지 맥락이 안내 문구를 바꾸는 범위를 검증하는 QA 테스트.

목적지 맥락은 BOARDING과 ARRIVED의 표현만 바꾼다.
ONBOARD와 DRIVING과 ALIGHTING과 COMPLETED와 EXCEPTION은 맥락과 무관하다.
이 파일은 guidance_for 직접 호출과 실세션 경유 호출로 그 경계를 전수 검증한다.
"""

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
from engine.adapters.simulator import dropoff_normal_snapshots, replay

_CONTEXTS = (
    DestinationContext.GENERAL,
    DestinationContext.DROPOFF,
    DestinationContext.PICKUP,
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


def fields(guidance):
    return (guidance.level, guidance.text, guidance.reason, guidance.state)


def by_context(state, snap):
    return {
        context: guidance_for(
            state, snap, passenger_present=True, context=context
        )
        for context in _CONTEXTS
    }


class GuidanceContextQaTest(unittest.TestCase):
    def test_boarding_text_and_reason_differ_by_context(self):
        results = by_context(
            SessionState.BOARDING, snapshot(rear_door=DoorState.OPEN)
        )
        general = results[DestinationContext.GENERAL]
        dropoff = results[DestinationContext.DROPOFF]
        pickup = results[DestinationContext.PICKUP]

        self.assertEqual(dropoff.reason, "boarding_dropoff")
        self.assertEqual(pickup.reason, "boarding_pickup")
        self.assertEqual(general.reason, "boarding")
        self.assertIn("등원", dropoff.text)
        self.assertIn("하원", pickup.text)
        self.assertNotIn("등원", general.text)
        self.assertNotIn("하원", general.text)
        texts = {guidance.text for guidance in results.values()}
        reasons = {guidance.reason for guidance in results.values()}
        self.assertEqual(len(texts), 3)
        self.assertEqual(len(reasons), 3)
        for guidance in results.values():
            self.assertEqual(guidance.state, SessionState.BOARDING)

    def test_arrived_text_and_reason_differ_by_context_and_level_is_remind(
        self,
    ):
        results = by_context(
            SessionState.ARRIVED, snapshot(rear_seat_belt_buckled=True)
        )
        general = results[DestinationContext.GENERAL]
        dropoff = results[DestinationContext.DROPOFF]
        pickup = results[DestinationContext.PICKUP]

        self.assertEqual(dropoff.reason, "arrived_dropoff_check_rear_seat")
        self.assertEqual(pickup.reason, "arrived_pickup_check_rear_seat")
        self.assertEqual(general.reason, "arrived_check_rear_seat")
        texts = {guidance.text for guidance in results.values()}
        reasons = {guidance.reason for guidance in results.values()}
        self.assertEqual(len(texts), 3)
        self.assertEqual(len(reasons), 3)
        for guidance in results.values():
            self.assertEqual(guidance.level, GuidanceLevel.REMIND)
            self.assertEqual(guidance.state, SessionState.ARRIVED)

    def test_onboard_is_identical_across_contexts(self):
        results = by_context(
            SessionState.ONBOARD, snapshot(rear_seat_belt_buckled=True)
        )

        distinct = {fields(guidance) for guidance in results.values()}
        self.assertEqual(len(distinct), 1)

    def test_driving_is_identical_across_contexts(self):
        results = by_context(
            SessionState.DRIVING,
            snapshot(rear_seat_belt_buckled=True, ignition=IgnitionState.ON),
        )

        distinct = {fields(guidance) for guidance in results.values()}
        self.assertEqual(len(distinct), 1)

    def test_alighting_is_identical_across_contexts(self):
        results = by_context(
            SessionState.ALIGHTING, snapshot(rear_door=DoorState.OPEN)
        )

        distinct = {fields(guidance) for guidance in results.values()}
        self.assertEqual(len(distinct), 1)

    def test_completed_and_exception_are_identical_across_contexts(self):
        completed = by_context(SessionState.COMPLETED, snapshot())
        distinct_completed = {
            fields(guidance) for guidance in completed.values()
        }
        self.assertEqual(len(distinct_completed), 1)

        exception_snaps = (
            snapshot(rear_seat_belt_buckled=True, lock=LockState.LOCKED),
            snapshot(
                rear_seat_belt_buckled=True,
                lock=LockState.LOCKED,
                cabin_temp_c=35.5,
            ),
        )
        for snap in exception_snaps:
            with self.subTest(cabin_temp_c=snap.cabin_temp_c):
                results = by_context(SessionState.EXCEPTION, snap)
                distinct = {fields(guidance) for guidance in results.values()}
                self.assertEqual(len(distinct), 1)
                for guidance in results.values():
                    self.assertEqual(guidance.level, GuidanceLevel.URGENT)

    def test_session_context_only_changes_arrived_not_driving(self):
        snapshots = dropoff_normal_snapshots()

        driving_session = CareSession()
        replay(driving_session, snapshots[:3])
        self.assertEqual(driving_session.state, SessionState.DRIVING)
        driving_dropoff = guidance_for_session(
            driving_session, context=DestinationContext.DROPOFF
        )
        driving_pickup = guidance_for_session(
            driving_session, context=DestinationContext.PICKUP
        )
        self.assertEqual(fields(driving_dropoff), fields(driving_pickup))

        arrived_session = CareSession()
        replay(arrived_session, snapshots[:4])
        self.assertEqual(arrived_session.state, SessionState.ARRIVED)
        arrived_dropoff = guidance_for_session(
            arrived_session, context=DestinationContext.DROPOFF
        )
        arrived_pickup = guidance_for_session(
            arrived_session, context=DestinationContext.PICKUP
        )
        self.assertNotEqual(arrived_dropoff.text, arrived_pickup.text)
        self.assertNotEqual(arrived_dropoff.reason, arrived_pickup.reason)


if __name__ == "__main__":
    unittest.main()

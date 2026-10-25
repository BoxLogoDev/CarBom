"""안내 문구 엔진의 경계 조건 QA 테스트.

온도 경계(32.0도·35.0도 정확히), PICKUP 맥락, 문자열 맥락 정규화를 고정한다.
기존 tests/test_guidance.py는 33.5도·36도 구간 안쪽 값만 검증하므로,
경계값이 바뀌면 조용히 어긋날 수 있어 이 파일에서 경계를 따로 고정한다.
"""

import unittest

from engine import (
    DestinationContext,
    DoorState,
    GuidanceLevel,
    IgnitionState,
    LockState,
    SessionState,
    SignalSnapshot,
    guidance_for,
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


def arrived_guidance(cabin_temp_c):
    return guidance_for(
        SessionState.ARRIVED,
        snapshot(rear_seat_belt_buckled=True, cabin_temp_c=cabin_temp_c),
        passenger_present=True,
        context=DestinationContext.GENERAL,
    )


def exception_guidance(cabin_temp_c):
    return guidance_for(
        SessionState.EXCEPTION,
        snapshot(
            rear_seat_belt_buckled=True,
            lock=LockState.LOCKED,
            cabin_temp_c=cabin_temp_c,
        ),
        passenger_present=True,
    )


class ArrivedTempBoundaryTest(unittest.TestCase):
    def test_31_9_has_no_temperature_wording(self):
        guidance = arrived_guidance(31.9)

        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertNotIn("31.9", guidance.text)
        self.assertNotIn("실내 온도", guidance.text)
        self.assertNotIn("hot", guidance.reason)
        self.assertNotIn("dangerous", guidance.reason)

    def test_32_0_exactly_is_hot_not_dangerous(self):
        guidance = arrived_guidance(32.0)

        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertIn("32", guidance.text)
        self.assertIn("실내 온도", guidance.text)
        self.assertIn("hot", guidance.reason)
        self.assertNotIn("dangerous", guidance.reason)
        self.assertNotIn("즉시", guidance.text)

    def test_34_9_is_still_hot_not_dangerous(self):
        guidance = arrived_guidance(34.9)

        self.assertIn("34.9", guidance.text)
        self.assertIn("hot", guidance.reason)
        self.assertNotIn("dangerous", guidance.reason)

    def test_35_0_exactly_is_dangerous(self):
        guidance = arrived_guidance(35.0)

        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertIn("35", guidance.text)
        self.assertIn("즉시", guidance.text)
        self.assertIn("dangerous", guidance.reason)


class ExceptionTempBoundaryTest(unittest.TestCase):
    def test_32_0_exactly_is_hot_not_dangerous(self):
        guidance = exception_guidance(32.0)

        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertIn("32", guidance.text)
        self.assertIn("hot", guidance.reason)
        self.assertNotIn("dangerous", guidance.reason)
        self.assertNotIn("위험합니다", guidance.text)

    def test_34_9_is_still_hot_not_dangerous(self):
        guidance = exception_guidance(34.9)

        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertIn("34.9", guidance.text)
        self.assertIn("hot", guidance.reason)
        self.assertNotIn("dangerous", guidance.reason)

    def test_35_0_exactly_is_dangerous(self):
        guidance = exception_guidance(35.0)

        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertIn("35", guidance.text)
        self.assertIn("위험", guidance.text)
        self.assertIn("즉시", guidance.text)
        self.assertIn("dangerous", guidance.reason)


class PickupContextTest(unittest.TestCase):
    def test_boarding_pickup_mentions_pickup(self):
        guidance = guidance_for(
            SessionState.BOARDING,
            snapshot(rear_door=DoorState.OPEN),
            passenger_present=False,
            context=DestinationContext.PICKUP,
        )

        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertIn("하원", guidance.text)
        self.assertIn("승차", guidance.text)

    def test_arrived_pickup_reminds_rear_seat_check(self):
        guidance = guidance_for(
            SessionState.ARRIVED,
            snapshot(rear_seat_belt_buckled=True),
            passenger_present=True,
            context=DestinationContext.PICKUP,
        )

        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertIn("하원", guidance.text)
        self.assertIn("뒷좌석", guidance.text)


class StringContextNormalizationTest(unittest.TestCase):
    def boarding(self, context):
        return guidance_for(
            SessionState.BOARDING,
            snapshot(rear_door=DoorState.OPEN),
            passenger_present=False,
            context=context,
        )

    def test_lowercase_string_matches_enum(self):
        by_string = self.boarding("dropoff")
        by_enum = self.boarding(DestinationContext.DROPOFF)

        self.assertEqual(by_string.text, by_enum.text)
        self.assertEqual(by_string.reason, by_enum.reason)
        self.assertIn("등원", by_string.text)

    def test_padded_uppercase_string_matches_enum(self):
        by_string = self.boarding(" DROPOFF ")
        by_enum = self.boarding(DestinationContext.DROPOFF)

        self.assertEqual(by_string.text, by_enum.text)
        self.assertEqual(by_string.reason, by_enum.reason)

    def test_unknown_string_falls_back_to_general(self):
        by_string = self.boarding("unknown")
        by_enum = self.boarding(DestinationContext.GENERAL)

        self.assertEqual(by_string.text, by_enum.text)
        self.assertEqual(by_string.reason, by_enum.reason)

    def test_none_falls_back_to_general(self):
        by_none = self.boarding(None)
        by_enum = self.boarding(DestinationContext.GENERAL)

        self.assertEqual(by_none.text, by_enum.text)
        self.assertEqual(by_none.reason, by_enum.reason)


if __name__ == "__main__":
    unittest.main()

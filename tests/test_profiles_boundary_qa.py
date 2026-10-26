"""동승 프로필 경계 조건 QA 테스트."""

import dataclasses
import unittest

from engine import PassengerKind, needs_manual_confirmation, profile_for
from engine.profiles import all_profiles


class TestProfileForFallback(unittest.TestCase):
    def test_none_falls_back_to_adult(self):
        profile = profile_for(None)
        self.assertEqual(profile.kind, PassengerKind.ADULT)
        self.assertEqual(profile.label, "성인")

    def test_empty_and_whitespace_strings_fall_back_to_adult(self):
        for value in ("", "   "):
            with self.subTest(value=repr(value)):
                profile = profile_for(value)
                self.assertEqual(profile.kind, PassengerKind.ADULT)
                self.assertEqual(profile.label, "성인")

    def test_unknown_strings_fall_back_to_adult(self):
        for value in ("unknown", " driver ", "아이", "child1"):
            with self.subTest(value=value):
                profile = profile_for(value)
                self.assertEqual(profile.kind, PassengerKind.ADULT)
                self.assertEqual(profile.label, "성인")

    def test_non_string_values_fall_back_to_adult(self):
        for value in (123, 0, 3.14):
            with self.subTest(value=value):
                profile = profile_for(value)  # type: ignore[arg-type]
                self.assertEqual(profile.kind, PassengerKind.ADULT)
                self.assertEqual(profile.label, "성인")


class TestProfileForParsing(unittest.TestCase):
    def test_all_kinds_parse_with_case_and_whitespace(self):
        cases = (
            (" CHILD ", PassengerKind.CHILD, "아이"),
            ("Pet", PassengerKind.PET, "반려동물"),
            ("ELDER", PassengerKind.ELDER, "부모님"),
            (" adult ", PassengerKind.ADULT, "성인"),
        )
        for value, expected_kind, expected_label in cases:
            with self.subTest(value=value):
                profile = profile_for(value)
                self.assertEqual(profile.kind, expected_kind)
                self.assertEqual(profile.label, expected_label)


class TestNeedsManualConfirmationMatrix(unittest.TestCase):
    def test_full_matrix_true_only_for_unbelted_pet(self):
        combinations = [
            (profile, belt_buckled)
            for profile in all_profiles()
            for belt_buckled in (True, False)
        ]
        self.assertEqual(len(combinations), 8)

        true_count = 0
        for profile, belt_buckled in combinations:
            expected = (
                profile.kind is PassengerKind.PET and not belt_buckled
            )
            with self.subTest(
                kind=profile.kind, belt_buckled=belt_buckled
            ):
                result = needs_manual_confirmation(
                    profile, belt_buckled=belt_buckled
                )
                self.assertIs(result, expected)
            true_count += needs_manual_confirmation(
                profile, belt_buckled=belt_buckled
            )
        self.assertEqual(true_count, 1)


class TestAllProfilesCompleteness(unittest.TestCase):
    def test_all_profiles_completeness(self):
        profiles = all_profiles()

        self.assertEqual(len(profiles), 4)
        self.assertEqual(
            [profile.kind for profile in profiles],
            [
                PassengerKind.CHILD,
                PassengerKind.PET,
                PassengerKind.ELDER,
                PassengerKind.ADULT,
            ],
        )

        labels = [profile.label for profile in profiles]
        self.assertEqual(len(set(labels)), 4)
        for profile in profiles:
            with self.subTest(kind=profile.kind):
                self.assertTrue(profile.label.strip())
                self.assertTrue(profile.reminder_note.strip())
                self.assertTrue(profile.belt_detectable)
                self.assertIs(
                    profile.requires_manual_confirmation_when_unbelted,
                    profile.kind is PassengerKind.PET,
                )

    def test_all_profiles_returns_tuple(self):
        self.assertIsInstance(all_profiles(), tuple)


class TestPassengerProfileFrozen(unittest.TestCase):
    def test_label_assignment_raises_frozen_instance_error(self):
        profile = profile_for(PassengerKind.CHILD)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            profile.label = "변경"  # type: ignore[misc]
        self.assertEqual(profile.label, "아이")


if __name__ == "__main__":
    unittest.main()

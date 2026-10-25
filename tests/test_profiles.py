"""동승 프로필 단위 테스트."""

import unittest

from engine import (
    PassengerKind,
    PassengerProfile,
    needs_manual_confirmation,
    profile_for,
)
from engine.profiles import all_profiles


class TestProfileFor(unittest.TestCase):
    def test_child_profile_fields(self):
        profile = profile_for(PassengerKind.CHILD)
        self.assertIsInstance(profile, PassengerProfile)
        self.assertEqual(profile.kind, PassengerKind.CHILD)
        self.assertEqual(profile.label, "아이")
        self.assertTrue(profile.belt_detectable)
        self.assertFalse(profile.requires_manual_confirmation_when_unbelted)

    def test_pet_profile_from_string(self):
        profile = profile_for("pet")
        self.assertEqual(profile.kind, PassengerKind.PET)
        self.assertEqual(profile.label, "반려동물")
        self.assertTrue(profile.belt_detectable)
        self.assertTrue(profile.requires_manual_confirmation_when_unbelted)

    def test_unknown_string_falls_back_to_adult(self):
        profile = profile_for(" unknown ")
        self.assertEqual(profile.kind, PassengerKind.ADULT)
        self.assertEqual(profile.label, "성인")

    def test_string_parsing_ignores_case_and_spaces(self):
        self.assertEqual(profile_for(" ELDER ").kind, PassengerKind.ELDER)
        self.assertEqual(profile_for("Child").kind, PassengerKind.CHILD)


class TestNeedsManualConfirmation(unittest.TestCase):
    def test_pet_unbelted_needs_manual_confirmation(self):
        profile = profile_for(PassengerKind.PET)
        self.assertTrue(needs_manual_confirmation(profile, belt_buckled=False))

    def test_pet_belted_needs_no_manual_confirmation(self):
        profile = profile_for(PassengerKind.PET)
        self.assertFalse(needs_manual_confirmation(profile, belt_buckled=True))

    def test_child_unbelted_needs_no_manual_confirmation(self):
        profile = profile_for(PassengerKind.CHILD)
        self.assertFalse(needs_manual_confirmation(profile, belt_buckled=False))


class TestAllProfiles(unittest.TestCase):
    def test_all_profiles_order_and_count(self):
        profiles = all_profiles()
        self.assertEqual(len(profiles), 4)
        self.assertEqual(
            [p.kind for p in profiles],
            [
                PassengerKind.CHILD,
                PassengerKind.PET,
                PassengerKind.ELDER,
                PassengerKind.ADULT,
            ],
        )


class TestEngineExports(unittest.TestCase):
    def test_engine_package_exports_profiles(self):
        import engine

        self.assertIs(engine.PassengerKind, PassengerKind)
        self.assertIs(engine.PassengerProfile, PassengerProfile)
        self.assertIs(engine.profile_for, profile_for)
        self.assertIs(engine.needs_manual_confirmation, needs_manual_confirmation)
        self.assertIn("PassengerKind", engine.__all__)
        self.assertIn("profile_for", engine.__all__)


if __name__ == "__main__":
    unittest.main()

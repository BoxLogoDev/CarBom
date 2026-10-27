"""동승 프로필 단위 테스트."""

import unittest

from engine import (
    PassengerKind,
    PassengerProfile,
    needs_manual_confirmation,
    profile_for,
    profiles_for,
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


class ProfilesForTest(unittest.TestCase):
    def test_empty_input_returns_empty_tuple(self):
        self.assertEqual(profiles_for([]), ())
        self.assertEqual(profiles_for(iter(())), ())

    def test_enum_list_preserves_order_and_matches_profile_for(self):
        kinds = [PassengerKind.PET, PassengerKind.CHILD, PassengerKind.ADULT]
        result = profiles_for(kinds)
        self.assertEqual(result, tuple(profile_for(kind) for kind in kinds))
        self.assertEqual(
            [p.kind for p in result],
            [PassengerKind.PET, PassengerKind.CHILD, PassengerKind.ADULT],
        )

    def test_mixed_string_none_and_unknown_inputs_match_profile_for(self):
        kinds = ["pet", None, " unknown ", " ELDER "]
        result = profiles_for(kinds)
        self.assertEqual(result, tuple(profile_for(kind) for kind in kinds))
        self.assertEqual(
            [p.kind for p in result],
            [
                PassengerKind.PET,
                PassengerKind.ADULT,
                PassengerKind.ADULT,
                PassengerKind.ELDER,
            ],
        )

    def test_generator_input_matches_list_input(self):
        kinds = [PassengerKind.CHILD, "pet", None]
        from_list = profiles_for(kinds)
        from_generator = profiles_for(kind for kind in kinds)
        self.assertEqual(from_generator, from_list)
        self.assertEqual(len(from_generator), 3)

    def test_duplicate_inputs_are_kept(self):
        result = profiles_for([PassengerKind.PET, PassengerKind.PET])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], profile_for(PassengerKind.PET))
        self.assertEqual(result[1], profile_for(PassengerKind.PET))

    def test_result_is_tuple_of_passenger_profiles(self):
        result = profiles_for([PassengerKind.CHILD, "adult"])
        self.assertIsInstance(result, tuple)
        for profile in result:
            self.assertIsInstance(profile, PassengerProfile)


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

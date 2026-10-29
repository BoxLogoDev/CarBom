"""패키지 공개 API re-export QA 테스트.

통합자는 engine 패키지와 engine.adapters 패키지에서 공개 이름을 가져온다.
패키지가 다시 내보낸 이름은 원본 서브모듈의 객체와 같은 객체여야 한다.
복사본이나 래퍼가 끼면 통합자의 동일성 검사와 타입 검사가 깨진다.
이 파일은 두 패키지의 __all__ 전체를 원본과 전수 대조한다.
"""

import unittest

import engine
import engine.adapters as adapters
import engine.guidance as guidance
import engine.profiles as profiles
import engine.report as report
import engine.session as session
import engine.signals as signals
from engine.adapters import simulator, vehicle_sdk

ENGINE_SOURCES = {
    "DestinationContext": guidance,
    "Guidance": guidance,
    "GuidanceLevel": guidance,
    "guidance_for": guidance,
    "guidance_for_session": guidance,
    "guidances_for_sessions": guidance,
    "guidances_for_sessions_by_context": guidance,
    "PassengerKind": profiles,
    "PassengerProfile": profiles,
    "all_profiles": profiles,
    "needs_manual_confirmation": profiles,
    "needs_manual_confirmations": profiles,
    "needs_manual_confirmations_by_belt": profiles,
    "needs_manual_confirmations_for_kinds": profiles,
    "needs_manual_confirmations_for_kinds_by_belt": profiles,
    "profile_for": profiles,
    "profiles_for": profiles,
    "CareReport": report,
    "CareReportLog": report,
    "report_for_session": report,
    "reports_for_sessions": report,
    "CareSession": session,
    "SessionState": session,
    "StateTransition": session,
    "DoorState": signals,
    "IgnitionState": signals,
    "LockState": signals,
    "SignalEvent": signals,
    "SignalEventType": signals,
    "SignalSnapshot": signals,
}

ADAPTER_SOURCES = {
    "SCENARIO_NAMES": simulator,
    "dropoff_normal_snapshots": simulator,
    "forgotten_rising_temp_snapshots": simulator,
    "pet_dropoff_snapshots": simulator,
    "replay": simulator,
    "replay_scenario": simulator,
    "replay_scenarios": simulator,
    "replay_scenarios_by_name": simulator,
    "replay_scenarios_by_name_and_start": simulator,
    "replay_snapshot_sequences_for_sessions": simulator,
    "scenario_snapshots": simulator,
    "snapshots_for_scenarios": simulator,
    "snapshots_for_scenarios_by_start": simulator,
    "VehicleSdkAdapter": vehicle_sdk,
    "apply_raw": vehicle_sdk,
    "apply_raws": vehicle_sdk,
    "apply_raws_for_sessions": vehicle_sdk,
    "apply_raw_sequences_for_sessions": vehicle_sdk,
    "poll_into_sessions": vehicle_sdk,
    "poll_repeatedly_into_sessions": vehicle_sdk,
    "poll_snapshots": vehicle_sdk,
    "raw_from_snapshot": vehicle_sdk,
    "raws_from_snapshots": vehicle_sdk,
    "snapshot_from_raw": vehicle_sdk,
    "snapshots_from_raws": vehicle_sdk,
}


class TestEnginePackageExports(unittest.TestCase):
    def test_engine_all_names_exist_and_are_identical_to_sources(self):
        self.assertEqual(set(ENGINE_SOURCES), set(engine.__all__))
        for name in engine.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(engine, name))
                self.assertIs(
                    getattr(engine, name),
                    getattr(ENGINE_SOURCES[name], name),
                )

    def test_engine_all_has_no_duplicates_and_covers_submodule_alls(self):
        self.assertEqual(len(engine.__all__), len(set(engine.__all__)))
        for module in (guidance, profiles, report):
            with self.subTest(module=module.__name__):
                self.assertLessEqual(set(module.__all__), set(engine.__all__))
                for name in module.__all__:
                    self.assertIn(name, engine.__all__)


class TestAdaptersPackageExports(unittest.TestCase):
    def test_adapters_all_names_exist_and_are_identical_to_sources(self):
        self.assertEqual(set(ADAPTER_SOURCES), set(adapters.__all__))
        for name in adapters.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(adapters, name))
                self.assertIs(
                    getattr(adapters, name),
                    getattr(ADAPTER_SOURCES[name], name),
                )

    def test_adapters_all_is_exact_union_without_duplicates(self):
        self.assertEqual(
            set(adapters.__all__),
            set(simulator.__all__) | set(vehicle_sdk.__all__),
        )
        self.assertEqual(len(adapters.__all__), len(set(adapters.__all__)))

    def test_adapters_scenario_names_is_simulator_object_with_value(self):
        self.assertIs(adapters.SCENARIO_NAMES, simulator.SCENARIO_NAMES)
        self.assertEqual(
            adapters.SCENARIO_NAMES,
            ("dropoff_normal", "forgotten_rising_temp", "pet_dropoff"),
        )


class TestBulkHelperExports(unittest.TestCase):
    def test_bulk_helpers_are_exposed_on_package_surface(self):
        self.assertIn("guidances_for_sessions", engine.__all__)
        self.assertIs(
            engine.guidances_for_sessions, guidance.guidances_for_sessions
        )
        self.assertIn("guidances_for_sessions_by_context", engine.__all__)
        self.assertIs(
            engine.guidances_for_sessions_by_context,
            guidance.guidances_for_sessions_by_context,
        )
        self.assertIn("profiles_for", engine.__all__)
        self.assertIs(engine.profiles_for, profiles.profiles_for)
        self.assertIn("needs_manual_confirmations", engine.__all__)
        self.assertIs(
            engine.needs_manual_confirmations,
            profiles.needs_manual_confirmations,
        )
        self.assertIn("needs_manual_confirmations_by_belt", engine.__all__)
        self.assertIs(
            engine.needs_manual_confirmations_by_belt,
            profiles.needs_manual_confirmations_by_belt,
        )
        self.assertIn("needs_manual_confirmations_for_kinds", engine.__all__)
        self.assertIs(
            engine.needs_manual_confirmations_for_kinds,
            profiles.needs_manual_confirmations_for_kinds,
        )
        self.assertIn(
            "needs_manual_confirmations_for_kinds_by_belt", engine.__all__
        )
        self.assertIs(
            engine.needs_manual_confirmations_for_kinds_by_belt,
            profiles.needs_manual_confirmations_for_kinds_by_belt,
        )
        self.assertIn("reports_for_sessions", engine.__all__)
        self.assertIs(
            engine.reports_for_sessions, report.reports_for_sessions
        )
        self.assertIn("replay_scenarios", adapters.__all__)
        self.assertIs(adapters.replay_scenarios, simulator.replay_scenarios)
        self.assertIn("replay_scenarios_by_name", adapters.__all__)
        self.assertIs(
            adapters.replay_scenarios_by_name,
            simulator.replay_scenarios_by_name,
        )
        self.assertIn(
            "replay_scenarios_by_name_and_start", adapters.__all__
        )
        self.assertIs(
            adapters.replay_scenarios_by_name_and_start,
            simulator.replay_scenarios_by_name_and_start,
        )
        self.assertIn(
            "replay_snapshot_sequences_for_sessions", adapters.__all__
        )
        self.assertIs(
            adapters.replay_snapshot_sequences_for_sessions,
            simulator.replay_snapshot_sequences_for_sessions,
        )
        self.assertIn("apply_raws_for_sessions", adapters.__all__)
        self.assertIs(
            adapters.apply_raws_for_sessions,
            vehicle_sdk.apply_raws_for_sessions,
        )
        self.assertIn("apply_raw_sequences_for_sessions", adapters.__all__)
        self.assertIs(
            adapters.apply_raw_sequences_for_sessions,
            vehicle_sdk.apply_raw_sequences_for_sessions,
        )
        self.assertIn("snapshots_for_scenarios", adapters.__all__)
        self.assertIs(
            adapters.snapshots_for_scenarios,
            simulator.snapshots_for_scenarios,
        )
        self.assertIn("snapshots_for_scenarios_by_start", adapters.__all__)
        self.assertIs(
            adapters.snapshots_for_scenarios_by_start,
            simulator.snapshots_for_scenarios_by_start,
        )
        self.assertIn("poll_repeatedly_into_sessions", adapters.__all__)
        self.assertIs(
            adapters.poll_repeatedly_into_sessions,
            vehicle_sdk.poll_repeatedly_into_sessions,
        )
        self.assertIn("poll_snapshots", adapters.__all__)
        self.assertIs(adapters.poll_snapshots, vehicle_sdk.poll_snapshots)


if __name__ == "__main__":
    unittest.main()

"""교대 구동 세션 독립성 QA.

여러 CareSession을 스냅샷 단위로 번갈아 적용해도 각 세션의 결과가
순차 구동과 완전히 같음을 검증한다. 세션은 서로 상태를 공유하지
않으며, 한 세션의 예외·리셋·진행이 다른 세션에 새지 않는다.
기존 테스트는 세션을 하나씩 끝까지 구동하는 경우만 다뤘다.
"""

import unittest

from engine.adapters.simulator import SCENARIO_NAMES, scenario_snapshots
from engine.guidance import guidance_for_session
from engine.report import report_for_session
from engine.session import CareSession, SessionState
from engine.signals import SignalSnapshot


def _sequential(name, start=0.0):
    session = CareSession()
    for snapshot in scenario_snapshots(name, start=start):
        session.apply_snapshot(snapshot)
    return session


def _surfaces(session):
    return (
        session.state,
        session.passenger_present,
        [
            (t.from_state, t.to_state, t.reason, t.timestamp)
            for t in session.history
        ],
        session.current_snapshot,
        guidance_for_session(session, context="dropoff"),
        report_for_session(session),
    )


def _interleave(sessions_and_snapshots):
    max_len = max(len(snaps) for _, snaps in sessions_and_snapshots)
    for index in range(max_len):
        for session, snaps in sessions_and_snapshots:
            if index < len(snaps):
                session.apply_snapshot(snaps[index])


class InterleavedThreeScenariosQaTest(unittest.TestCase):
    def test_interleaved_three_scenarios_match_sequential(self):
        sessions = {name: CareSession() for name in SCENARIO_NAMES}
        _interleave(
            [
                (sessions[name], scenario_snapshots(name))
                for name in SCENARIO_NAMES
            ]
        )
        for name in SCENARIO_NAMES:
            self.assertEqual(
                _surfaces(sessions[name]), _surfaces(_sequential(name))
            )
        self.assertEqual(
            sessions["dropoff_normal"].state, SessionState.COMPLETED
        )
        self.assertEqual(len(sessions["dropoff_normal"].history), 6)
        self.assertEqual(
            sessions["forgotten_rising_temp"].state,
            SessionState.EXCEPTION,
        )
        self.assertEqual(len(sessions["forgotten_rising_temp"].history), 5)
        report = report_for_session(sessions["forgotten_rising_temp"])
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(
            sessions["pet_dropoff"].state, SessionState.COMPLETED
        )

    def test_interleaved_same_scenario_different_starts(self):
        early, late = CareSession(), CareSession()
        _interleave(
            [
                (early, scenario_snapshots("dropoff_normal", start=0.0)),
                (
                    late,
                    scenario_snapshots("dropoff_normal", start=1000.0),
                ),
            ]
        )
        self.assertEqual(early.state, SessionState.COMPLETED)
        self.assertEqual(late.state, SessionState.COMPLETED)
        shape = [
            (t.from_state, t.to_state, t.reason) for t in early.history
        ]
        self.assertEqual(
            shape,
            [(t.from_state, t.to_state, t.reason) for t in late.history],
        )
        early_report = report_for_session(early)
        late_report = report_for_session(late)
        self.assertEqual(
            (early_report.started_at, early_report.ended_at), (0.0, 300.0)
        )
        self.assertEqual(
            (late_report.started_at, late_report.ended_at),
            (1000.0, 1300.0),
        )
        self.assertEqual(early_report.duration_seconds, 300.0)
        self.assertEqual(late_report.duration_seconds, 300.0)


class SessionIndependenceQaTest(unittest.TestCase):
    def test_untouched_session_stays_idle_while_others_progress(self):
        first, second = CareSession(), CareSession()
        self.assertIsNot(first.history, second.history)
        untouched = CareSession()
        _interleave(
            [
                (first, scenario_snapshots("dropoff_normal")),
                (second, scenario_snapshots("pet_dropoff")),
            ]
        )
        self.assertEqual(first.state, SessionState.COMPLETED)
        self.assertEqual(second.state, SessionState.COMPLETED)
        self.assertEqual(untouched.state, SessionState.IDLE)
        self.assertFalse(untouched.passenger_present)
        self.assertEqual(untouched.history, [])
        self.assertEqual(untouched.current_snapshot, SignalSnapshot())

    def test_exception_in_one_session_does_not_leak_to_other(self):
        forgotten, dropoff = CareSession(), CareSession()
        _interleave(
            [
                (forgotten, scenario_snapshots("forgotten_rising_temp")),
                (dropoff, scenario_snapshots("dropoff_normal")),
            ]
        )
        self.assertEqual(forgotten.state, SessionState.EXCEPTION)
        self.assertEqual(
            guidance_for_session(forgotten, context="dropoff").level.name,
            "URGENT",
        )
        self.assertEqual(dropoff.state, SessionState.COMPLETED)
        report = report_for_session(dropoff)
        self.assertEqual(report.exception_count, 0)
        self.assertFalse(report.exception_occurred)
        self.assertNotEqual(
            guidance_for_session(dropoff, context="dropoff").level.name,
            "URGENT",
        )

    def test_reset_of_one_session_does_not_affect_other(self):
        reset_target, steady = CareSession(), CareSession()
        dropoff_snaps = scenario_snapshots("dropoff_normal")
        pet_snaps = scenario_snapshots("pet_dropoff")
        for index in range(3):
            reset_target.apply_snapshot(dropoff_snaps[index])
            steady.apply_snapshot(pet_snaps[index])
        reset_target.reset()
        self.assertEqual(reset_target.state, SessionState.IDLE)
        self.assertEqual(reset_target.history, [])
        for index in range(3, len(pet_snaps)):
            steady.apply_snapshot(pet_snaps[index])
        self.assertEqual(_surfaces(steady), _surfaces(_sequential("pet_dropoff")))
        for snapshot in dropoff_snaps:
            reset_target.apply_snapshot(snapshot)
        self.assertEqual(
            _surfaces(reset_target),
            _surfaces(_sequential("dropoff_normal")),
        )

    def test_mid_interleave_report_stays_isolated(self):
        first, second = CareSession(), CareSession()
        dropoff_snaps = scenario_snapshots("dropoff_normal")
        pet_snaps = scenario_snapshots("pet_dropoff")
        first.apply_snapshot(dropoff_snaps[0])
        second.apply_snapshot(pet_snaps[0])
        mid_report = report_for_session(first)
        self.assertEqual(mid_report.final_state, SessionState.BOARDING)
        _interleave(
            [(first, dropoff_snaps[1:]), (second, pet_snaps[1:])]
        )
        self.assertEqual(first.state, SessionState.COMPLETED)
        self.assertEqual(second.state, SessionState.COMPLETED)
        self.assertEqual(mid_report.final_state, SessionState.BOARDING)
        self.assertEqual(mid_report.transition_count, 1)
        self.assertEqual(len(mid_report.transitions), 1)
        self.assertEqual(mid_report.summary, "진행 중 · 하차 미확인")


if __name__ == "__main__":
    unittest.main()

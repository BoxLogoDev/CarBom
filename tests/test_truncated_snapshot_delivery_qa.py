"""QA: 절단 배달(truncated delivery) 전 흐름 거동.

전제: 고정 시나리오의 SignalSnapshot 시퀀스를 앞에서부터 cut개만
배달하고 나머지는 아예 오지 않는다. 기존
tests/test_duplicate_snapshot_delivery_qa.py는 각 스냅샷이 같은
값으로 중복 배달되는 경우를, tests/test_dropped_snapshot_delivery_qa.py는
중간 1건만 빠지고 뒤 스냅샷은 도착하는 경우를,
tests/test_reordered_snapshot_delivery_qa.py는 전부 도착하되 순서가
바뀌는 경우를 다뤘다. 이 파일은 그들과 중복되지 않게, 뒤 스냅샷이
전혀 도착하지 않는 접두사만으로 세션이 어디까지 진행되고 전이
이력·소요 시간·안내·리포트가 어떻게 멈추는지를 고정한다.
"""

import unittest

from engine import CareSession, SessionState
from engine.adapters.simulator import scenario_snapshots
from engine.guidance import (
    DestinationContext,
    GuidanceLevel,
    guidance_for_session,
)
from engine.report import CareReportLog, report_for_session

_IN_PROGRESS = "진행 중 · 하차 미확인"
_COMPLETED = "하차 확인 완료 · 예외 없음"
_EXCEPTION = "예외 발생 · 하차 미확인"

# cut, state, passenger, history 건수, duration, 안내 수준, 안내 이유, summary
_DROPOFF_PROGRESSION = (
    (0, SessionState.IDLE, False, 0, None, GuidanceLevel.NONE, "idle", _IN_PROGRESS),
    (
        1,
        SessionState.BOARDING,
        False,
        1,
        0.0,
        GuidanceLevel.INFO,
        "boarding_dropoff",
        _IN_PROGRESS,
    ),
    (
        2,
        SessionState.ONBOARD,
        True,
        2,
        60.0,
        GuidanceLevel.INFO,
        "passenger_onboard",
        _IN_PROGRESS,
    ),
    (
        3,
        SessionState.DRIVING,
        True,
        3,
        120.0,
        GuidanceLevel.INFO,
        "driving",
        _IN_PROGRESS,
    ),
    (
        4,
        SessionState.ARRIVED,
        True,
        4,
        180.0,
        GuidanceLevel.REMIND,
        "arrived_dropoff_check_rear_seat",
        _IN_PROGRESS,
    ),
    (
        5,
        SessionState.ALIGHTING,
        False,
        5,
        240.0,
        GuidanceLevel.INFO,
        "alighting",
        _IN_PROGRESS,
    ),
    (
        6,
        SessionState.COMPLETED,
        False,
        6,
        300.0,
        GuidanceLevel.INFO,
        "completed",
        _COMPLETED,
    ),
)


def _run(name, cut):
    session = CareSession()
    for snapshot in scenario_snapshots(name)[:cut]:
        session.apply_snapshot(snapshot)
    return session


def _history_keys(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


def _full_history_keys(name):
    return _history_keys(_run(name, len(scenario_snapshots(name))))


def _assert_progression_row(test_case, session, row):
    cut, state, passenger, history_count, duration, level, reason, summary = row
    test_case.assertIs(session.state, state)
    test_case.assertEqual(session.passenger_present, passenger)
    test_case.assertEqual(len(session.history), history_count)
    guidance = guidance_for_session(
        session, context=DestinationContext.DROPOFF
    )
    test_case.assertEqual(guidance.level, level)
    test_case.assertEqual(guidance.reason, reason)
    report = report_for_session(session)
    test_case.assertIs(report.final_state, state)
    test_case.assertEqual(report.passenger_present, passenger)
    test_case.assertEqual(report.transition_count, history_count)
    test_case.assertEqual(report.duration_seconds, duration)
    test_case.assertIsNone(report.max_cabin_temp_c)
    test_case.assertEqual(report.summary, summary)


class TruncatedSnapshotDeliveryQATest(unittest.TestCase):
    def test_dropoff_normal_all_prefixes_progression(self):
        full_keys = _full_history_keys("dropoff_normal")
        self.assertEqual(len(full_keys), 6)
        for row in _DROPOFF_PROGRESSION:
            cut = row[0]
            with self.subTest(scenario="dropoff_normal", cut=cut):
                session = _run("dropoff_normal", cut)
                _assert_progression_row(self, session, row)
                self.assertIsNone(session.current_snapshot.cabin_temp_c)
                report = report_for_session(session)
                self.assertEqual(report.exception_count, 0)
                self.assertEqual(report.completed, cut == 6)
                self.assertEqual(_history_keys(session), full_keys[:cut])

    def test_forgotten_cut0_to_4_progression(self):
        full_keys = _full_history_keys("forgotten_rising_temp")
        for row in _DROPOFF_PROGRESSION[:5]:
            cut = row[0]
            with self.subTest(scenario="forgotten_rising_temp", cut=cut):
                session = _run("forgotten_rising_temp", cut)
                _assert_progression_row(self, session, row)
                report = report_for_session(session)
                self.assertEqual(report.exception_count, 0)
                self.assertFalse(report.completed)
                self.assertEqual(_history_keys(session), full_keys[:cut])

    def test_forgotten_cut5_to_8_fixed_history_but_temp_advances(self):
        expected = (
            (5, None, None, "passenger_left_locked"),
            (6, 28.0, 28.0, "passenger_left_locked"),
            (7, 32.0, 32.0, "passenger_left_locked_hot_cabin"),
            (
                8,
                35.5,
                35.5,
                "passenger_left_locked_dangerous_cabin_temp",
            ),
        )
        fixed_keys = _history_keys(_run("forgotten_rising_temp", 5))
        self.assertEqual(len(fixed_keys), 5)
        for cut, current_temp, max_temp, reason in expected:
            with self.subTest(scenario="forgotten_rising_temp", cut=cut):
                session = _run("forgotten_rising_temp", cut)
                self.assertIs(session.state, SessionState.EXCEPTION)
                self.assertTrue(session.passenger_present)
                self.assertEqual(len(session.history), 5)
                self.assertEqual(_history_keys(session), fixed_keys)
                self.assertEqual(
                    session.current_snapshot.cabin_temp_c, current_temp
                )
                guidance = guidance_for_session(
                    session, context=DestinationContext.DROPOFF
                )
                self.assertEqual(guidance.level, GuidanceLevel.URGENT)
                self.assertEqual(guidance.reason, reason)
                if cut == 8:
                    self.assertIn("35.5도", guidance.text)
                    self.assertIn("즉시", guidance.text)
                report = report_for_session(session)
                self.assertFalse(report.completed)
                self.assertEqual(report.exception_count, 1)
                self.assertEqual(report.transition_count, 5)
                self.assertEqual(report.duration_seconds, 240.0)
                self.assertEqual(report.max_cabin_temp_c, max_temp)
                self.assertEqual(report.summary, _EXCEPTION)

    def test_pet_prefixes_match_dropoff_except_hvac_at_cut3(self):
        for row in _DROPOFF_PROGRESSION:
            cut = row[0]
            with self.subTest(scenario="pet_dropoff", cut=cut):
                pet = _run("pet_dropoff", cut)
                dropoff = _run("dropoff_normal", cut)
                _assert_progression_row(self, pet, row)
                self.assertIs(pet.state, dropoff.state)
                self.assertEqual(
                    pet.passenger_present, dropoff.passenger_present
                )
                self.assertEqual(
                    _history_keys(pet), _history_keys(dropoff)
                )
                pet_guidance = guidance_for_session(
                    pet, context=DestinationContext.DROPOFF
                )
                dropoff_guidance = guidance_for_session(
                    dropoff, context=DestinationContext.DROPOFF
                )
                self.assertEqual(
                    (
                        pet_guidance.level,
                        pet_guidance.text,
                        pet_guidance.reason,
                    ),
                    (
                        dropoff_guidance.level,
                        dropoff_guidance.text,
                        dropoff_guidance.reason,
                    ),
                )
                pet_report = report_for_session(pet)
                dropoff_report = report_for_session(dropoff)
                self.assertEqual(
                    (
                        pet_report.duration_seconds,
                        pet_report.max_cabin_temp_c,
                        pet_report.summary,
                        pet_report.transition_count,
                        pet_report.completed,
                    ),
                    (
                        dropoff_report.duration_seconds,
                        dropoff_report.max_cabin_temp_c,
                        dropoff_report.summary,
                        dropoff_report.transition_count,
                        dropoff_report.completed,
                    ),
                )
                if cut == 3:
                    self.assertTrue(pet.current_snapshot.hvac_on)
                    self.assertFalse(dropoff.current_snapshot.hvac_on)
                else:
                    self.assertEqual(
                        pet.current_snapshot.hvac_on,
                        dropoff.current_snapshot.hvac_on,
                    )
                    self.assertEqual(
                        pet.current_snapshot, dropoff.current_snapshot
                    )

    def test_all_prefixes_report_log_aggregates(self):
        sessions = [
            _run(name, cut)
            for name in (
                "dropoff_normal",
                "forgotten_rising_temp",
                "pet_dropoff",
            )
            for cut in range(len(scenario_snapshots(name)) + 1)
        ]
        self.assertEqual(len(sessions), 23)
        log = CareReportLog()
        added = log.add_sessions(sessions)
        self.assertEqual(len(added), 23)
        self.assertEqual(len(log), 23)
        self.assertEqual(len(log.reports), 23)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 4)
        self.assertEqual(log.total_exception_count, 4)
        self.assertEqual(log.total_transition_count, 72)
        self.assertEqual(
            sum(r.transition_count for r in log.reports), 72
        )
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.average_duration_seconds, 156.0)

    def test_truncated_delivery_invariants(self):
        for name in (
            "dropoff_normal",
            "forgotten_rising_temp",
            "pet_dropoff",
        ):
            full_count = len(scenario_snapshots(name))
            full_keys = _full_history_keys(name)
            full_transition_count = len(full_keys)
            for cut in range(full_count + 1):
                with self.subTest(scenario=name, cut=cut):
                    session = _run(name, cut)
                    report = report_for_session(session)
                    expected_count = (
                        5
                        if name == "forgotten_rising_temp" and cut >= 5
                        else cut
                    )
                    self.assertEqual(
                        report.transition_count, expected_count
                    )
                    self.assertEqual(len(session.history), expected_count)
                    self.assertEqual(
                        _history_keys(session),
                        full_keys[:expected_count],
                    )
                    self.assertLessEqual(
                        report.transition_count, full_transition_count
                    )
                    is_full_completed = (
                        name in ("dropoff_normal", "pet_dropoff")
                        and cut == 6
                    )
                    self.assertEqual(report.completed, is_full_completed)
                    if not is_full_completed:
                        self.assertFalse(report.completed)
                        self.assertIsNot(
                            session.state, SessionState.COMPLETED
                        )
        cut5 = _run("dropoff_normal", 5)
        self.assertIs(cut5.state, SessionState.ALIGHTING)
        self.assertFalse(report_for_session(cut5).completed)
        self.assertEqual(
            _history_keys(cut5),
            _full_history_keys("dropoff_normal")[:5],
        )


if __name__ == "__main__":
    unittest.main()

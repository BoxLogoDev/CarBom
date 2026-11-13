"""QA: 스냅샷 1건 누락 배달(lossy delivery) 전 흐름 거동.

전제: 스냅샷은 전체 상태 스냅샷이라 중간 누락은 뒤 스냅샷이 흡수하는
경우가 많지만, 전이 이력·소요 시간·최종 온도 안내에는 흔적이 남고,
하차 시작·최종 닫힘 스냅샷 누락은 완료를 막는다. 기존
tests/test_duplicate_snapshot_delivery_qa.py는 각 스냅샷이 중복
배달되는 경우를 다뤘다. 이 파일은 고정 시나리오 스냅샷 시퀀스에서
인덱스 1건만 빠진 채 배달될 때 최종 상태와 전이 이력과 안내와
리포트가 어떻게 달라지는지를 고정한다.
"""

import unittest

from engine import CareSession, SessionState
from engine.adapters.simulator import scenario_snapshots
from engine.guidance import (
    DestinationContext,
    GuidanceLevel,
    guidance_for_session,
)
from engine.report import report_for_session


def _run_single(name):
    session = CareSession()
    for snapshot in scenario_snapshots(name):
        session.apply_snapshot(snapshot)
    return session


def _run_dropped(name, drop_index):
    snapshots = scenario_snapshots(name)
    session = CareSession()
    for index, snapshot in enumerate(snapshots):
        if index == drop_index:
            continue
        session.apply_snapshot(snapshot)
    return session


def _history_keys(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


def _report_key(report):
    return (
        report.final_state,
        report.completed,
        report.exception_count,
        report.transition_count,
        report.passenger_present,
        report.duration_seconds,
        report.max_cabin_temp_c,
        report.summary,
    )


def _surfaces(session):
    guidance = guidance_for_session(
        session, context=DestinationContext.DROPOFF
    )
    return (
        session.state,
        session.passenger_present,
        _history_keys(session),
        session.current_snapshot,
        (guidance.level, guidance.text, guidance.reason),
        _report_key(report_for_session(session)),
    )


class DroppedSnapshotDeliveryQATest(unittest.TestCase):
    def test_dropoff_normal_drop_first_snapshot_still_completes(self):
        session = _run_dropped("dropoff_normal", 0)

        self.assertIs(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 5)
        self.assertEqual(
            _history_keys(session)[0],
            (
                SessionState.IDLE,
                SessionState.ONBOARD,
                "passenger_onboard",
                60.0,
            ),
        )
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_dropoff_normal_drop_ignition_on_skips_driving(self):
        session = _run_dropped("dropoff_normal", 2)

        self.assertIs(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 4)
        history = _history_keys(session)
        to_states = [key[1] for key in history]
        self.assertNotIn(SessionState.DRIVING, to_states)
        self.assertNotIn(SessionState.ARRIVED, to_states)
        self.assertIn(
            (
                SessionState.ONBOARD,
                SessionState.ALIGHTING,
                "passenger_alighting",
                240.0,
            ),
            history,
        )
        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.transition_count, 4)
        self.assertEqual(report.duration_seconds, 300.0)

    def test_dropoff_normal_drop_alighting_snapshots_blocks_completion(
        self,
    ):
        dropped_start = _run_dropped("dropoff_normal", 4)

        self.assertIs(dropped_start.state, SessionState.ARRIVED)
        self.assertTrue(dropped_start.passenger_present)
        self.assertEqual(len(dropped_start.history), 4)
        guidance = guidance_for_session(
            dropped_start, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(
            guidance.reason, "arrived_dropoff_check_rear_seat"
        )
        self.assertIn("뒷좌석", guidance.text)
        report = report_for_session(dropped_start)
        self.assertFalse(report.completed)
        self.assertEqual(report.transition_count, 4)
        self.assertEqual(report.duration_seconds, 180.0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

        dropped_close = _run_dropped("dropoff_normal", 5)

        self.assertIs(dropped_close.state, SessionState.ALIGHTING)
        self.assertEqual(len(dropped_close.history), 5)
        close_guidance = guidance_for_session(
            dropped_close, context=DestinationContext.DROPOFF
        )
        self.assertEqual(close_guidance.level, GuidanceLevel.INFO)
        self.assertEqual(close_guidance.reason, "alighting")
        close_report = report_for_session(dropped_close)
        self.assertFalse(close_report.completed)
        self.assertEqual(close_report.transition_count, 5)
        self.assertEqual(close_report.duration_seconds, 240.0)

    def test_forgotten_drop_lock_delays_exception_transition(self):
        session = _run_dropped("forgotten_rising_temp", 4)

        self.assertIs(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)
        self.assertEqual(
            _history_keys(session)[-1],
            (
                SessionState.ARRIVED,
                SessionState.EXCEPTION,
                "ignition_off_locked_passenger_present",
                300.0,
            ),
        )
        report = report_for_session(session)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_forgotten_drop_middle_temp_matches_single_delivery(self):
        single = _run_single("forgotten_rising_temp")

        for drop_index in (5, 6):
            with self.subTest(drop_index=drop_index):
                session = _run_dropped(
                    "forgotten_rising_temp", drop_index
                )

                self.assertEqual(_surfaces(session), _surfaces(single))
                self.assertIs(session.state, SessionState.EXCEPTION)
                self.assertEqual(len(session.history), 5)
                guidance = guidance_for_session(
                    session, context=DestinationContext.DROPOFF
                )
                self.assertEqual(guidance.level, GuidanceLevel.URGENT)
                self.assertEqual(
                    guidance.reason,
                    "passenger_left_locked_dangerous_cabin_temp",
                )
                report = report_for_session(session)
                self.assertEqual(report.transition_count, 5)
                self.assertEqual(report.duration_seconds, 240.0)
                self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_forgotten_drop_final_temp_lowers_guidance_and_max(self):
        session = _run_dropped("forgotten_rising_temp", 7)

        self.assertIs(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 32.0)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason, "passenger_left_locked_hot_cabin"
        )
        self.assertIn("32도", guidance.text)
        self.assertNotIn("즉시", guidance.text)
        report = report_for_session(session)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.max_cabin_temp_c, 32.0)

        with self.subTest(scenario="pet_dropoff", drop_index=4):
            pet = _run_dropped("pet_dropoff", 4)
            self.assertIs(pet.state, SessionState.ARRIVED)
            self.assertTrue(pet.passenger_present)


if __name__ == "__main__":
    unittest.main()

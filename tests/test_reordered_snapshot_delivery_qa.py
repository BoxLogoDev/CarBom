"""QA: 순서 바뀐 스냅샷 배달(reordered delivery) 전 흐름 거동.

전제: 스냅샷은 자기 timestamp를 그대로 들고 이동하므로, 배달 순서가
바뀌면 전이 판정은 새 순서의 신호 값으로 이뤄지고 전이 이력의 시각도
바뀐 순서를 따른다. 기존 tests/test_duplicate_snapshot_delivery_qa.py는
각 스냅샷이 중복 배달되는 경우, tests/test_dropped_snapshot_delivery_qa.py는
인덱스 1건이 누락 배달되는 경우,
tests/test_out_of_order_timestamp_qa.py는 배달 순서는 같고 timestamp
값만 비단조인 경우를 다뤘다. 이 파일은 고정 시나리오 스냅샷 시퀀스에서
인접한 두 건의 배달 순서를 교환하거나 전체를 역순으로 배달할 때 최종
상태와 전이 이력과 안내와 리포트가 어떻게 달라지는지를 고정한다.
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
from engine.signals import DoorState


def _run_single(name):
    session = CareSession()
    for snapshot in scenario_snapshots(name):
        session.apply_snapshot(snapshot)
    return session


def _run_swapped(name, first, second):
    snapshots = list(scenario_snapshots(name))
    snapshots[first], snapshots[second] = (
        snapshots[second],
        snapshots[first],
    )
    session = CareSession()
    for snapshot in snapshots:
        session.apply_snapshot(snapshot)
    return session


def _run_reversed(name):
    session = CareSession()
    for snapshot in reversed(list(scenario_snapshots(name))):
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


class ReorderedSnapshotDeliveryQATest(unittest.TestCase):
    def test_dropoff_swap_belt_and_ignition_absorbed_except_history_timestamps(
        self,
    ):
        single = _run_single("dropoff_normal")
        session = _run_swapped("dropoff_normal", 1, 2)

        self.assertIs(session.state, SessionState.COMPLETED)
        single_surfaces = _surfaces(single)
        surfaces = _surfaces(session)
        # 상태·동승자·현재 스냅샷·안내·리포트는 1회 배달과 동일하다.
        self.assertEqual(surfaces[0], single_surfaces[0])
        self.assertEqual(surfaces[1], single_surfaces[1])
        self.assertEqual(surfaces[3], single_surfaces[3])
        self.assertEqual(surfaces[4], single_surfaces[4])
        self.assertEqual(surfaces[5], single_surfaces[5])
        # 전이의 (from, to, reason) 순서도 동일하고 시각만 바뀐다.
        self.assertEqual(
            [key[:3] for key in surfaces[2]],
            [key[:3] for key in single_surfaces[2]],
        )
        self.assertEqual(
            [key[3] for key in surfaces[2]],
            [0.0, 120.0, 120.0, 60.0, 240.0, 300.0],
        )
        report = report_for_session(session)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)

    def test_dropoff_swap_first_two_collapses_transitions_but_completes(
        self,
    ):
        single = _run_single("dropoff_normal")
        session = _run_swapped("dropoff_normal", 0, 1)

        self.assertIs(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)
        self.assertEqual(
            _history_keys(session),
            [
                (
                    SessionState.IDLE,
                    SessionState.ONBOARD,
                    "passenger_onboard",
                    60.0,
                ),
                (
                    SessionState.ONBOARD,
                    SessionState.ALIGHTING,
                    "passenger_alighting",
                    0.0,
                ),
                (
                    SessionState.ALIGHTING,
                    SessionState.COMPLETED,
                    "alighting_confirmed",
                    300.0,
                ),
            ],
        )
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")
        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.transition_count, 3)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")
        self.assertEqual(
            session.current_snapshot, single.current_snapshot
        )

    def test_dropoff_late_swaps_block_completion_differently(self):
        swapped_open = _run_swapped("dropoff_normal", 3, 4)

        self.assertIs(swapped_open.state, SessionState.ALIGHTING)
        self.assertTrue(swapped_open.passenger_present)
        self.assertEqual(len(swapped_open.history), 5)
        self.assertEqual(
            swapped_open.current_snapshot.timestamp, 300.0
        )
        self.assertIs(
            swapped_open.current_snapshot.rear_door, DoorState.CLOSED
        )
        guidance = guidance_for_session(
            swapped_open, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "alighting")
        report = report_for_session(swapped_open)
        self.assertFalse(report.completed)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

        swapped_close = _run_swapped("dropoff_normal", 4, 5)

        self.assertIs(swapped_close.state, SessionState.ALIGHTING)
        self.assertFalse(swapped_close.passenger_present)
        self.assertEqual(len(swapped_close.history), 5)
        self.assertEqual(
            swapped_close.current_snapshot.timestamp, 240.0
        )
        self.assertIs(
            swapped_close.current_snapshot.rear_door, DoorState.OPEN
        )
        close_guidance = guidance_for_session(
            swapped_close, context=DestinationContext.DROPOFF
        )
        self.assertEqual(close_guidance.level, GuidanceLevel.INFO)
        self.assertEqual(close_guidance.reason, "alighting")
        close_report = report_for_session(swapped_close)
        self.assertFalse(close_report.completed)
        self.assertEqual(close_report.transition_count, 5)
        self.assertEqual(close_report.duration_seconds, 240.0)

    def test_forgotten_swap_lock_and_first_temp_delays_exception(self):
        session = _run_swapped("forgotten_rising_temp", 4, 5)

        self.assertIs(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
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
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason,
            "passenger_left_locked_dangerous_cabin_temp",
        )
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)
        report = report_for_session(session)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_forgotten_swap_last_two_temps_lowers_final_guidance_and_max(
        self,
    ):
        single = _run_single("forgotten_rising_temp")
        session = _run_swapped("forgotten_rising_temp", 6, 7)

        self.assertIs(session.state, SessionState.EXCEPTION)
        self.assertEqual(
            _history_keys(session), _history_keys(single)
        )
        self.assertEqual(session.current_snapshot.cabin_temp_c, 32.0)
        self.assertEqual(session.current_snapshot.timestamp, 360.0)
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
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.max_cabin_temp_c, 32.0)
        self.assertEqual(report.duration_seconds, 240.0)

        with self.subTest(swap=(5, 6)):
            absorbed = _run_swapped("forgotten_rising_temp", 5, 6)
            self.assertEqual(_surfaces(absorbed), _surfaces(single))

    def test_reversed_delivery_and_report_log_aggregates(self):
        dropoff = _run_reversed("dropoff_normal")

        self.assertIs(dropoff.state, SessionState.ALIGHTING)
        self.assertFalse(dropoff.passenger_present)
        self.assertEqual(len(dropoff.history), 5)
        self.assertEqual(
            [key[3] for key in _history_keys(dropoff)],
            [240.0, 180.0, 120.0, 60.0, 0.0],
        )
        dropoff_report = report_for_session(dropoff)
        self.assertFalse(dropoff_report.completed)
        self.assertEqual(dropoff_report.duration_seconds, -240.0)
        self.assertEqual(
            dropoff_report.summary, "진행 중 · 하차 미확인"
        )

        forgotten = _run_reversed("forgotten_rising_temp")

        self.assertIs(forgotten.state, SessionState.ALIGHTING)
        self.assertFalse(forgotten.passenger_present)
        self.assertEqual(len(forgotten.history), 5)
        forgotten_report = report_for_session(forgotten)
        self.assertEqual(forgotten_report.exception_count, 1)
        self.assertEqual(forgotten_report.duration_seconds, -420.0)
        self.assertEqual(forgotten_report.max_cabin_temp_c, 35.5)
        forgotten_guidance = guidance_for_session(
            forgotten, context=DestinationContext.DROPOFF
        )
        self.assertEqual(forgotten_guidance.level, GuidanceLevel.INFO)
        self.assertEqual(forgotten_guidance.reason, "alighting")

        log = CareReportLog()
        added = log.add_sessions(
            [
                _run_swapped("dropoff_normal", 1, 2),
                _run_swapped("forgotten_rising_temp", 4, 5),
                _run_swapped("pet_dropoff", 0, 1),
            ]
        )
        self.assertEqual(len(added), 3)
        self.assertEqual(len(log.reports), 3)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.average_duration_seconds, 280.0)


if __name__ == "__main__":
    unittest.main()

"""시뮬레이터 단일 스냅샷 대량 헬퍼의 QA 통합 테스트.

replay_snapshot_for_sessions(같은 스냅샷 1건을 여러 세션에 적용)와
replay_snapshots_for_sessions(세션마다 다른 스냅샷 1건을 짝지어 적용)를
안내(guidance_for_session/guidances_for_sessions, DROPOFF 맥락),
케어 리포트(report_for_session/reports_for_sessions), 누적함(CareReportLog)까지
이어 검증한다. 기존 tests/test_simulator.py의 단위 테스트는 최종 상태와
동승자와 온도만 다루므로, 이 파일은 그 표면과 겹치지 않게 안내와 리포트와
누적함 단언을 중심에 둔다.
"""

import unittest

from engine import (
    CareReportLog,
    CareSession,
    DestinationContext,
    DoorState,
    GuidanceLevel,
    LockState,
    SessionState,
    SignalSnapshot,
    guidance_for_session,
    guidances_for_sessions,
    report_for_session,
    reports_for_sessions,
)
from engine.adapters import (
    dropoff_normal_snapshots,
    replay,
    replay_snapshot_for_sessions,
    replay_snapshots_for_sessions,
)

DROPOFF = DestinationContext.DROPOFF


def _history_sequence(session):
    return tuple(
        (
            transition.from_state,
            transition.to_state,
            transition.reason,
            transition.timestamp,
        )
        for transition in session.history
    )


def _arrived_session():
    session = CareSession()
    replay(session, dropoff_normal_snapshots()[:4])
    return session


def _paired_snapshots():
    return [
        SignalSnapshot(rear_door=DoorState.OPEN, timestamp=10.0),
        SignalSnapshot(
            rear_door=DoorState.OPEN,
            rear_seat_belt_buckled=True,
            timestamp=300.0,
        ),
    ]


class ReplaySnapshotBulkIntegrationQaTest(unittest.TestCase):
    def test_stepwise_same_snapshot_completes_with_guidance_reports_and_log(
        self,
    ):
        sessions = [CareSession(), CareSession()]

        result = ()
        for snapshot in dropoff_normal_snapshots():
            result = replay_snapshot_for_sessions(sessions, snapshot)
            self.assertEqual(
                result, (sessions[0].state, sessions[1].state)
            )

        self.assertEqual(
            result, (SessionState.COMPLETED, SessionState.COMPLETED)
        )
        sequences = [_history_sequence(session) for session in sessions]
        self.assertEqual(sequences[0], sequences[1])
        for sequence in sequences:
            self.assertEqual(len(sequence), 6)

        guidances = guidances_for_sessions(sessions, context=DROPOFF)
        self.assertEqual(len(guidances), 2)
        for guidance in guidances:
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "completed")

        reports = reports_for_sessions(sessions)
        self.assertEqual(
            reports,
            tuple(report_for_session(session) for session in sessions),
        )
        for report in reports:
            self.assertTrue(report.completed)
            self.assertEqual(report.transition_count, 6)
            self.assertEqual(report.duration_seconds, 300.0)
            self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

        log = CareReportLog()
        log.add_sessions(sessions)
        self.assertEqual(len(log), 2)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 0)
        self.assertEqual(log.average_duration_seconds, 300.0)

    def test_same_locked_snapshot_raises_urgent_guidance_and_log_counts(
        self,
    ):
        sessions = [_arrived_session(), _arrived_session()]

        result = replay_snapshot_for_sessions(
            sessions,
            SignalSnapshot(
                rear_seat_belt_buckled=True,
                lock=LockState.LOCKED,
                cabin_temp_c=35.5,
                timestamp=240.0,
            ),
        )

        self.assertEqual(
            result, (SessionState.EXCEPTION, SessionState.EXCEPTION)
        )
        for session in sessions:
            self.assertTrue(session.passenger_present)
            self.assertEqual(len(session.history), 5)

        guidances = guidances_for_sessions(sessions, context=DROPOFF)
        for guidance in guidances:
            self.assertEqual(guidance.level, GuidanceLevel.URGENT)
            self.assertEqual(
                guidance.reason,
                "passenger_left_locked_dangerous_cabin_temp",
            )
            self.assertIn("35.5도", guidance.text)
            self.assertIn("즉시", guidance.text)

        reports = reports_for_sessions(sessions)
        for report in reports:
            self.assertEqual(report.exception_count, 1)
            self.assertEqual(report.duration_seconds, 240.0)
            self.assertEqual(report.max_cabin_temp_c, 35.5)
            self.assertEqual(report.summary, "예외 발생 · 하차 미확인")

        log = CareReportLog()
        log.add_sessions(sessions)
        self.assertEqual(log.sessions_with_exception, 2)
        self.assertEqual(log.total_exception_count, 2)
        self.assertEqual(log.max_cabin_temp_c, 35.5)

    def test_paired_snapshots_split_boarding_and_alighting(self):
        session_a = CareSession()
        session_b = _arrived_session()
        sessions = [session_a, session_b]

        result = replay_snapshots_for_sessions(
            sessions, _paired_snapshots()
        )

        self.assertEqual(
            result, (SessionState.BOARDING, SessionState.ALIGHTING)
        )
        guidances = guidances_for_sessions(sessions, context=DROPOFF)
        self.assertEqual(guidances[0].level, GuidanceLevel.INFO)
        self.assertEqual(guidances[0].reason, "boarding_dropoff")
        self.assertEqual(guidances[1].level, GuidanceLevel.INFO)
        self.assertEqual(guidances[1].reason, "alighting")

        reports = reports_for_sessions(sessions)
        self.assertEqual(reports[0].transition_count, 1)
        self.assertEqual(reports[0].duration_seconds, 0.0)
        self.assertEqual(reports[1].transition_count, 5)
        self.assertEqual(reports[1].duration_seconds, 300.0)

        log = CareReportLog()
        log.add_sessions(sessions)
        self.assertEqual(len(log), 2)
        self.assertEqual(log.completed_count, 0)
        self.assertEqual(log.incomplete_count, 2)

    def test_length_mismatch_leaves_sessions_unchanged(self):
        session_a = CareSession()
        replay(session_a, dropoff_normal_snapshots()[:2])
        session_b = CareSession()
        snapshot = SignalSnapshot(
            rear_door=DoorState.OPEN, timestamp=120.0
        )

        with self.assertRaises(ValueError):
            replay_snapshots_for_sessions(
                [session_a, session_b], [snapshot]
            )
        with self.assertRaises(ValueError):
            replay_snapshots_for_sessions(
                [session_a], [snapshot, snapshot]
            )

        self.assertEqual(session_a.state, SessionState.ONBOARD)
        self.assertEqual(len(session_a.history), 2)
        self.assertEqual(session_a.current_snapshot.timestamp, 60.0)
        self.assertEqual(
            guidance_for_session(session_a, context=DROPOFF).reason,
            "passenger_onboard",
        )
        self.assertEqual(report_for_session(session_a).transition_count, 2)
        self.assertEqual(session_b.state, SessionState.IDLE)
        self.assertEqual(session_b.history, [])

    def test_same_snapshot_on_idle_and_completed_sessions(self):
        session_a = CareSession()
        session_c = CareSession()
        replay(session_c, dropoff_normal_snapshots())
        summary_before = report_for_session(session_c).summary

        result = replay_snapshot_for_sessions(
            [session_a, session_c],
            SignalSnapshot(
                rear_seat_belt_buckled=True,
                lock=LockState.LOCKED,
                cabin_temp_c=35.5,
                timestamp=999.0,
            ),
        )

        self.assertEqual(
            result, (SessionState.EXCEPTION, SessionState.COMPLETED)
        )
        report_a = report_for_session(session_a)
        self.assertEqual(len(session_a.history), 1)
        self.assertEqual(report_a.exception_count, 1)
        self.assertEqual(report_a.duration_seconds, 0.0)

        report_c = report_for_session(session_c)
        self.assertEqual(len(session_c.history), 6)
        self.assertTrue(report_c.completed)
        self.assertEqual(report_c.exception_count, 0)
        self.assertEqual(report_c.duration_seconds, 300.0)
        self.assertEqual(report_c.summary, summary_before)
        self.assertEqual(session_c.current_snapshot.cabin_temp_c, 35.5)
        self.assertEqual(report_c.max_cabin_temp_c, 35.5)
        guidance_c = guidance_for_session(session_c, context=DROPOFF)
        self.assertEqual(guidance_c.level, GuidanceLevel.INFO)
        self.assertEqual(guidance_c.reason, "completed")

    def test_generator_paired_inputs_match_list_inputs(self):
        list_sessions = [CareSession(), _arrived_session()]
        generator_sessions = [CareSession(), _arrived_session()]
        snapshots = _paired_snapshots()

        list_result = replay_snapshots_for_sessions(
            list_sessions, snapshots
        )
        generator_result = replay_snapshots_for_sessions(
            (session for session in generator_sessions),
            (snapshot for snapshot in snapshots),
        )

        self.assertEqual(generator_result, list_result)
        self.assertEqual(
            [session.state for session in generator_sessions],
            [session.state for session in list_sessions],
        )
        self.assertEqual(
            [_history_sequence(session) for session in generator_sessions],
            [_history_sequence(session) for session in list_sessions],
        )
        self.assertEqual(
            [session.current_snapshot for session in generator_sessions],
            [session.current_snapshot for session in list_sessions],
        )
        self.assertEqual(
            guidances_for_sessions(generator_sessions, context=DROPOFF),
            guidances_for_sessions(list_sessions, context=DROPOFF),
        )
        self.assertEqual(
            reports_for_sessions(generator_sessions),
            reports_for_sessions(list_sessions),
        )


if __name__ == "__main__":
    unittest.main()

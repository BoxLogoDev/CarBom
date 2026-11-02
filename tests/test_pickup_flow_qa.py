"""QA scenario for the pickup (하원) context across a whole session.

전제: 안내 문구의 목적지 맥락은 BOARDING·ARRIVED 표현만 바꾸고
세션 상태머신·전이·케어 리포트에는 영향을 주지 않는다
(engine/guidance.py: 맥락은 _boarding·_arrived에서만 쓰이고
_exception은 맥락과 무관하다). 기존 테스트는 PICKUP 맥락을 안내
단위 수준(문구·reason)에서만 다뤄, 세션을 처음부터 끝까지 관통하며
단계별 안내와 리포트를 함께 확인하는 각도는 없었다. 이 파일은
고정 시나리오 스냅샷 시퀀스를 그대로 쓰되 모든 안내를 PICKUP
맥락으로 조회해 그 관통 동작을 고정한다.
"""

import unittest

from engine import (
    CareReportLog,
    CareSession,
    DestinationContext,
    DoorState,
    GuidanceLevel,
    SessionState,
    SignalSnapshot,
    guidance_for_session,
    report_for_session,
)
from engine.adapters.simulator import (
    dropoff_normal_snapshots,
    forgotten_rising_temp_snapshots,
)


def drive(session, snapshots):
    for snapshot in snapshots:
        session.apply_snapshot(snapshot)
    return session


class PickupNormalFlowTest(unittest.TestCase):
    def test_pickup_normal_flow_guidance_and_report(self):
        session = CareSession()
        snapshots = dropoff_normal_snapshots()

        session.apply_snapshot(snapshots[0])
        self.assertEqual(session.state, SessionState.BOARDING)
        boarding = guidance_for_session(session, DestinationContext.PICKUP)
        self.assertEqual(boarding.level, GuidanceLevel.INFO)
        self.assertEqual(boarding.state, SessionState.BOARDING)
        self.assertEqual(boarding.reason, "boarding_pickup")
        self.assertIn("하원", boarding.text)
        self.assertIn("안전벨트", boarding.text)

        drive(session, snapshots[1:4])
        self.assertEqual(session.state, SessionState.ARRIVED)
        arrived = guidance_for_session(session, DestinationContext.PICKUP)
        self.assertEqual(arrived.level, GuidanceLevel.REMIND)
        self.assertEqual(arrived.state, SessionState.ARRIVED)
        self.assertEqual(arrived.reason, "arrived_pickup_check_rear_seat")
        self.assertIn("하원", arrived.text)
        self.assertIn("뒷좌석", arrived.text)

        drive(session, snapshots[4:])
        self.assertEqual(session.state, SessionState.COMPLETED)
        completed = guidance_for_session(session, DestinationContext.PICKUP)
        self.assertEqual(completed.level, GuidanceLevel.INFO)
        self.assertEqual(completed.state, SessionState.COMPLETED)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)


class PickupForgottenFlowTest(unittest.TestCase):
    def test_pickup_forgotten_exception_guidance_is_urgent(self):
        session = drive(CareSession(), forgotten_rising_temp_snapshots())

        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        guidance = guidance_for_session(session, DestinationContext.PICKUP)
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.state, SessionState.EXCEPTION)
        self.assertEqual(
            guidance.reason, "passenger_left_locked_dangerous_cabin_temp"
        )
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)

        report = report_for_session(session)
        self.assertFalse(report.completed)
        self.assertTrue(report.exception_occurred)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_pickup_exception_recovers_to_completed(self):
        session = drive(CareSession(), forgotten_rising_temp_snapshots())
        self.assertEqual(session.state, SessionState.EXCEPTION)

        session.apply_snapshot(
            SignalSnapshot(rear_door=DoorState.OPEN, timestamp=480.0)
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        session.apply_snapshot(SignalSnapshot(timestamp=540.0))
        self.assertEqual(session.state, SessionState.COMPLETED)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertTrue(report.exception_occurred)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.summary, "예외 발생 후 하차 확인 완료")


class PickupContextScopeTest(unittest.TestCase):
    def test_context_changes_only_boarding_and_arrived_wording(self):
        session = CareSession()
        snapshots = dropoff_normal_snapshots()

        session.apply_snapshot(snapshots[0])
        self.assertEqual(session.state, SessionState.BOARDING)
        boarding_drop = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        boarding_pick = guidance_for_session(
            session, DestinationContext.PICKUP
        )
        self.assertEqual(boarding_drop.level, boarding_pick.level)
        self.assertNotEqual(boarding_drop.text, boarding_pick.text)
        self.assertNotEqual(boarding_drop.reason, boarding_pick.reason)

        session.apply_snapshot(snapshots[1])
        session.apply_snapshot(snapshots[2])
        self.assertEqual(session.state, SessionState.DRIVING)
        driving_drop = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        driving_pick = guidance_for_session(
            session, DestinationContext.PICKUP
        )
        self.assertEqual(driving_drop, driving_pick)

        session.apply_snapshot(snapshots[3])
        self.assertEqual(session.state, SessionState.ARRIVED)
        arrived_drop = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        arrived_pick = guidance_for_session(
            session, DestinationContext.PICKUP
        )
        self.assertEqual(arrived_drop.level, arrived_pick.level)
        self.assertNotEqual(arrived_drop.text, arrived_pick.text)
        self.assertNotEqual(arrived_drop.reason, arrived_pick.reason)

    def test_exception_guidance_is_context_independent_via_session(self):
        session = drive(CareSession(), forgotten_rising_temp_snapshots())

        drop = guidance_for_session(session, DestinationContext.DROPOFF)
        pick = guidance_for_session(session, DestinationContext.PICKUP)
        general = guidance_for_session(session, DestinationContext.GENERAL)
        self.assertEqual(drop, pick)
        self.assertEqual(drop, general)
        self.assertEqual(drop.level, GuidanceLevel.URGENT)

    def test_guidance_queries_do_not_mutate_session(self):
        first = drive(CareSession(), dropoff_normal_snapshots())
        second = drive(CareSession(), dropoff_normal_snapshots())

        for context in DestinationContext:
            guidance_for_session(first, context)

        self.assertEqual(first.state, second.state)
        self.assertEqual(first.history, second.history)
        self.assertEqual(
            report_for_session(first), report_for_session(second)
        )


class PickupReportLogTest(unittest.TestCase):
    def test_log_accumulates_pickup_sessions(self):
        normal = drive(CareSession(), dropoff_normal_snapshots())
        forgotten = drive(CareSession(), forgotten_rising_temp_snapshots())
        # 두 세션 모두 PICKUP 맥락으로 안내를 조회한 뒤 누적한다.
        guidance_for_session(normal, DestinationContext.PICKUP)
        guidance_for_session(forgotten, DestinationContext.PICKUP)

        log = CareReportLog()
        added = log.add_sessions((normal, forgotten))

        self.assertEqual(len(added), 2)
        self.assertEqual(len(log), 2)
        self.assertEqual(log.completed_count, 1)
        self.assertEqual(log.sessions_with_exception, 1)
        self.assertEqual(log.total_exception_count, 1)
        self.assertEqual(log.max_cabin_temp_c, 35.5)


if __name__ == "__main__":
    unittest.main()

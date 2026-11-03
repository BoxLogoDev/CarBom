"""QA scenarios for out-of-order signals after arrival.

기존 테스트는 도착(ARRIVED) 뒤 곧바로 하차하는 흐름만 다뤘다.
이 파일은 순서 밖 신호를 고정한다: 도착 후 하차 없이 다시 시동을
걸어도(재출발 시도) 세션은 ARRIVED에 머물고 전이 이력은 늘지 않으며,
주행(DRIVING) 중 뒷문이 열리는 스냅샷도 상태를 바꾸지 않는다.
재출발을 시도한 뒤에도 뒷문 열림부터의 정상 하차 완료는 그대로
동작하고, 이벤트 경로(IGNITION_ON)도 스냅샷 경로와 동일하게
전이는 없이 신호만 현재 스냅샷에 반영된다.
"""

import unittest

from engine import (
    CareSession,
    DoorState,
    GuidanceLevel,
    IgnitionState,
    SessionState,
    SignalEvent,
    SignalEventType,
    SignalSnapshot,
)
from engine.adapters.simulator import dropoff_normal_snapshots
from engine.guidance import DestinationContext, guidance_for_session
from engine.report import report_for_session


def arrived_session():
    session = CareSession()
    for snapshot in dropoff_normal_snapshots()[:4]:
        session.apply_snapshot(snapshot)
    return session


def reignition_snapshot(timestamp):
    return SignalSnapshot(
        rear_door=DoorState.CLOSED,
        rear_seat_belt_buckled=True,
        ignition=IgnitionState.ON,
        hvac_on=True,
        cabin_temp_c=24.0,
        timestamp=timestamp,
    )


def history_signature(session):
    return tuple(
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    )


class ReignitionAfterArrivalQATest(unittest.TestCase):
    def test_reignition_keeps_arrived_and_history(self):
        session = arrived_session()
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)
        self.assertTrue(session.passenger_present)

        for timestamp in (200.0, 220.0):
            result = session.apply_snapshot(reignition_snapshot(timestamp))
            self.assertEqual(result, SessionState.ARRIVED)
            self.assertEqual(session.state, SessionState.ARRIVED)
            self.assertEqual(len(session.history), 4)
            self.assertTrue(session.passenger_present)

    def test_redeparture_then_normal_completion(self):
        session = arrived_session()
        snapshots = dropoff_normal_snapshots()

        session.apply_snapshot(reignition_snapshot(200.0))
        result = session.apply_snapshot(
            SignalSnapshot(
                rear_door=DoorState.CLOSED,
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.OFF,
                cabin_temp_c=24.0,
                timestamp=230.0,
            )
        )
        self.assertEqual(result, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)

        self.assertEqual(
            session.apply_snapshot(snapshots[4]), SessionState.ALIGHTING
        )
        self.assertEqual(
            session.apply_snapshot(snapshots[5]), SessionState.COMPLETED
        )

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_guidance_stays_remind_after_reignition(self):
        session = arrived_session()
        before = guidance_for_session(session, DestinationContext.DROPOFF)
        self.assertEqual(before.level, GuidanceLevel.REMIND)
        self.assertEqual(before.reason, "arrived_dropoff_check_rear_seat")
        self.assertEqual(
            before.text, "도착했습니다. 등원 하차 전 뒷좌석을 확인해 주세요."
        )

        session.apply_snapshot(reignition_snapshot(200.0))

        after = guidance_for_session(session, DestinationContext.DROPOFF)
        self.assertEqual(after.level, before.level)
        self.assertEqual(after.reason, before.reason)
        self.assertEqual(after.text, before.text)
        self.assertEqual(after.state, SessionState.ARRIVED)

    def test_repeated_reignition_is_idempotent(self):
        session = arrived_session()
        for timestamp in (200.0, 210.0, 220.0):
            session.apply_snapshot(reignition_snapshot(timestamp))

        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)

        report = report_for_session(session)
        self.assertEqual(report.final_state, SessionState.ARRIVED)
        self.assertFalse(report.completed)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.transition_count, 4)


class OutOfOrderSignalQATest(unittest.TestCase):
    def test_door_open_while_driving_is_ignored(self):
        session = CareSession()
        snapshots = dropoff_normal_snapshots()
        for snapshot in snapshots[:3]:
            session.apply_snapshot(snapshot)
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)

        result = session.apply_snapshot(
            SignalSnapshot(
                rear_door=DoorState.OPEN,
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                timestamp=150.0,
            )
        )
        self.assertEqual(result, SessionState.DRIVING)
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertEqual(len(session.history), 3)
        self.assertTrue(session.passenger_present)

        self.assertEqual(
            session.apply_snapshot(snapshots[3]), SessionState.ARRIVED
        )

    def test_event_reignition_at_arrived_matches_snapshot_path(self):
        snapshot_session = arrived_session()
        snapshot_session.apply_snapshot(reignition_snapshot(200.0))

        event_session = arrived_session()
        result = event_session.apply_event(
            SignalEvent(SignalEventType.IGNITION_ON, timestamp=200.0)
        )

        self.assertEqual(result, SessionState.ARRIVED)
        self.assertEqual(event_session.state, SessionState.ARRIVED)
        self.assertEqual(len(event_session.history), 4)
        self.assertEqual(
            event_session.current_snapshot.ignition, IgnitionState.ON
        )
        self.assertEqual(
            history_signature(event_session),
            history_signature(snapshot_session),
        )


if __name__ == "__main__":
    unittest.main()

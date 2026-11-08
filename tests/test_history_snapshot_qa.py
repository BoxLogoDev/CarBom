"""QA: 전이 이력(StateTransition)에 기록된 스냅샷의 보존·공유 검증.

전제: CareSession._advance는 전이 시점에 세션의 현재 스냅샷
(self._snapshot)을 StateTransition.snapshot으로 그대로 기록한다
(engine/session.py). 기존 테스트는 전이의 from/to/reason/timestamp
열만 다뤄, 이력에 남은 스냅샷 객체 자체가 입력 스냅샷과 같은지,
전이를 일으키지 않은 뒤쪽 스냅샷이 이력 스냅샷을 덮지 않는지,
한 건의 스냅샷이 일으킨 다단계 전이가 스냅샷을 공유하는지는
검증하지 않았다. 이 파일은 그 각도를 고정한다.
"""

import unittest
from dataclasses import FrozenInstanceError

from engine import (
    CareSession,
    DoorState,
    IgnitionState,
    SessionState,
    SignalEvent,
    SignalEventType,
    SignalSnapshot,
)
from engine.adapters.simulator import (
    dropoff_normal_snapshots,
    forgotten_rising_temp_snapshots,
    replay,
)


class HistorySnapshotPreservationQATest(unittest.TestCase):
    def test_dropoff_history_snapshots_are_input_snapshots(self):
        session = CareSession()
        snapshots = dropoff_normal_snapshots()

        replay(session, snapshots)

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        for transition, snapshot in zip(session.history, snapshots):
            self.assertIs(transition.snapshot, snapshot)
            self.assertEqual(transition.timestamp, snapshot.timestamp)

    def test_forgotten_history_snapshots_not_overwritten_by_later_temps(self):
        session = CareSession()
        snapshots = forgotten_rising_temp_snapshots()

        replay(session, snapshots)

        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)
        for transition, snapshot in zip(session.history, snapshots[:5]):
            self.assertIs(transition.snapshot, snapshot)
        # 전이를 일으킨 마지막 스냅샷(240.0)에는 온도가 없고,
        # 뒤쪽 고온 스냅샷은 이력에 남지 않는다.
        self.assertIsNone(session.history[-1].snapshot.cabin_temp_c)
        # 현재 스냅샷만 마지막 입력(420.0, 35.5도)으로 갱신된다.
        self.assertIs(session.current_snapshot, snapshots[-1])
        self.assertEqual(session.current_snapshot.timestamp, 420.0)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 35.5)

    def test_multistep_transitions_share_one_snapshot(self):
        session = CareSession()
        snapshot = SignalSnapshot(
            rear_seat_belt_buckled=True,
            ignition=IgnitionState.ON,
            timestamp=10.0,
        )

        result = session.apply_snapshot(snapshot)

        self.assertEqual(result, SessionState.DRIVING)
        self.assertEqual(len(session.history), 2)
        self.assertEqual(
            [t.reason for t in session.history],
            ["passenger_onboard", "ignition_on"],
        )
        for transition in session.history:
            self.assertIs(transition.snapshot, snapshot)
            self.assertEqual(transition.timestamp, 10.0)

    def test_no_transition_snapshots_preserve_existing_history_snapshots(self):
        session = CareSession()
        snapshots = forgotten_rising_temp_snapshots()
        replay(session, snapshots[:5])
        self.assertEqual(session.state, SessionState.EXCEPTION)
        history_snapshots_before = [t.snapshot for t in session.history]

        for extra in snapshots[5:]:
            session.apply_snapshot(extra)

        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)
        for transition, before in zip(session.history, history_snapshots_before):
            self.assertIs(transition.snapshot, before)
        self.assertIs(session.current_snapshot, snapshots[-1])

    def test_event_attached_snapshot_timestamp_fallback_and_preservation(self):
        # (a) 스냅샷 시각이 없으면 이벤트 시각으로 폴백한 복사본이 기록되고
        # 원본 스냅샷은 그대로다.
        session = CareSession()
        original = SignalSnapshot(rear_door=DoorState.OPEN)
        session.apply_event(
            SignalEvent(
                type=SignalEventType.IGNITION_ON,
                timestamp=123.0,
                snapshot=original,
            )
        )
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(len(session.history), 1)
        recorded = session.history[0].snapshot
        self.assertIsNot(recorded, original)
        self.assertEqual(recorded.timestamp, 123.0)
        self.assertEqual(session.history[0].timestamp, 123.0)
        self.assertIsNone(original.timestamp)
        self.assertTrue(recorded.rear_door_open)

        # (b) 스냅샷 자체 시각이 있으면 이벤트 시각으로 덮지 않고
        # 원본 객체가 그대로 기록된다.
        session2 = CareSession()
        original2 = SignalSnapshot(rear_door=DoorState.OPEN, timestamp=50.0)
        session2.apply_event(
            SignalEvent(
                type=SignalEventType.LOCKED,
                timestamp=999.0,
                snapshot=original2,
            )
        )
        self.assertEqual(len(session2.history), 1)
        self.assertIs(session2.history[0].snapshot, original2)
        self.assertEqual(session2.history[0].timestamp, 50.0)

    def test_transition_and_its_snapshot_are_frozen(self):
        session = CareSession()
        replay(session, dropoff_normal_snapshots())
        transition = session.history[0]

        with self.assertRaises(FrozenInstanceError):
            transition.snapshot = SignalSnapshot()
        with self.assertRaises(FrozenInstanceError):
            transition.snapshot.timestamp = 999.0


if __name__ == "__main__":
    unittest.main()

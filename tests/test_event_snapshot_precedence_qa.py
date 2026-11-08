"""첨부 스냅샷 이벤트 우선순위 QA.

CareSession.apply_event는 SignalEvent에 snapshot이 첨부돼 있으면
이벤트 type과 cabin_temp_c 필드를 보지 않고 첨부 스냅샷을 그대로
적용한다(단, 스냅샷 timestamp가 None이면 이벤트 timestamp로 폴백).
기존 tests/test_event_path_qa.py는 type과 스냅샷 내용이 일치하는
경우와 timestamp 폴백만 검증했으므로, type·온도 필드가 첨부
스냅샷과 어긋나는 경우와 첨부 스냅샷이 현재 스냅샷을 통째로
교체한다는 점은 미검증이었다. 이 파일은 그 우선순위를 어긋난
입력, 다단계 전이, 통째 교체, 전 흐름 동등성으로 검증한다.
"""

import unittest

from engine import (
    CareSession,
    DoorState,
    IgnitionState,
    LockState,
    SessionState,
    SignalEvent,
    SignalEventType,
    SignalSnapshot,
)
from engine.adapters.simulator import replay, scenario_snapshots
from engine.guidance import DestinationContext, guidance_for_session
from engine.report import report_for_session


def snapshot(**overrides):
    values = {
        "rear_door": DoorState.CLOSED,
        "rear_seat_belt_buckled": False,
        "ignition": IgnitionState.OFF,
        "hvac_on": False,
        "cabin_temp_c": None,
        "lock": LockState.UNLOCKED,
        "timestamp": None,
    }
    values.update(overrides)
    return SignalSnapshot(**values)


def transition_keys(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


class EventSnapshotPrecedenceQATest(unittest.TestCase):
    def test_event_type_ignored_when_snapshot_attached_ignition_vs_door(
        self,
    ):
        session = CareSession()

        result = session.apply_event(
            SignalEvent(
                SignalEventType.IGNITION_ON,
                timestamp=99.0,
                snapshot=snapshot(
                    rear_door=DoorState.OPEN, timestamp=10.0
                ),
            )
        )

        # 이벤트 type(시동 ON)이 아니라 첨부 스냅샷(뒷문 열림)이 적용된다.
        self.assertIs(result, SessionState.BOARDING)
        self.assertIs(session.state, SessionState.BOARDING)
        self.assertFalse(session.current_snapshot.ignition_on)
        self.assertTrue(session.current_snapshot.rear_door_open)
        # 스냅샷 자체 timestamp(10.0)가 있고 이벤트 timestamp(99.0)는
        # 전이 이력에 쓰이지 않는다.
        self.assertEqual(
            transition_keys(session),
            [
                (
                    SessionState.IDLE,
                    SessionState.BOARDING,
                    "rear_door_opened",
                    10.0,
                )
            ],
        )

    def test_event_type_ignored_multistep_from_snapshot(self):
        session = CareSession()

        result = session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_CLOSED,
                snapshot=snapshot(
                    rear_seat_belt_buckled=True,
                    ignition=IgnitionState.ON,
                    timestamp=5.0,
                ),
            )
        )

        # 첨부 스냅샷 한 건이 ONBOARD를 거쳐 DRIVING까지 2단계 전이한다.
        self.assertIs(result, SessionState.DRIVING)
        self.assertIs(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(
            [(t.from_state, t.to_state, t.reason) for t in session.history],
            [
                (
                    SessionState.IDLE,
                    SessionState.ONBOARD,
                    "passenger_onboard",
                ),
                (
                    SessionState.ONBOARD,
                    SessionState.DRIVING,
                    "ignition_on",
                ),
            ],
        )

    def test_event_cabin_temp_ignored_when_snapshot_attached(self):
        session = CareSession()
        session.apply_event(
            SignalEvent(
                SignalEventType.CABIN_TEMP_CHANGED,
                cabin_temp_c=40.0,
                timestamp=2.0,
                snapshot=snapshot(cabin_temp_c=24.0, timestamp=1.0),
            )
        )
        self.assertEqual(session.current_snapshot.cabin_temp_c, 24.0)
        self.assertIs(session.state, SessionState.IDLE)

        # 스냅샷 온도가 None이면 이벤트 온도가 병합되지 않고 None 그대로다.
        other = CareSession()
        other.apply_event(
            SignalEvent(
                SignalEventType.CABIN_TEMP_CHANGED,
                cabin_temp_c=40.0,
                timestamp=2.0,
                snapshot=snapshot(cabin_temp_c=None, timestamp=1.0),
            )
        )
        self.assertIsNone(other.current_snapshot.cabin_temp_c)

    def test_attached_snapshot_replaces_current_wholesale(self):
        session = CareSession()
        session.apply_event(SignalEvent(SignalEventType.REAR_DOOR_OPENED))
        session.apply_event(SignalEvent(SignalEventType.REAR_BELT_BUCKLED))
        session.apply_event(SignalEvent(SignalEventType.REAR_DOOR_CLOSED))
        session.apply_event(SignalEvent(SignalEventType.HVAC_ON))
        self.assertIs(session.state, SessionState.ONBOARD)
        self.assertTrue(session.current_snapshot.hvac_on)
        self.assertTrue(session.passenger_present)

        result = session.apply_event(
            SignalEvent(
                SignalEventType.HVAC_OFF,
                timestamp=40.0,
                snapshot=snapshot(hvac_on=True, timestamp=40.0),
            )
        )

        # HVAC_OFF 이벤트가 아니라 첨부 스냅샷(hvac_on=True)이 기준이다.
        self.assertIs(result, SessionState.ONBOARD)
        self.assertTrue(session.current_snapshot.hvac_on)
        # 첨부 스냅샷은 현재 스냅샷과 병합되지 않고 통째로 교체되므로
        # 이전에 체결돼 있던 벨트 플래그가 현재 스냅샷에서 사라진다.
        self.assertFalse(session.current_snapshot.rear_seat_belt_buckled)
        # 다만 동승자 래치는 문이 닫힌 동안 해제되지 않는다.
        self.assertTrue(session.passenger_present)

        # 뒷문이 열리면 래치가 풀리며 ALIGHTING으로 전이한다.
        result = session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=50.0)
        )
        self.assertIs(result, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)

    def test_scrambled_event_types_full_flow_equivalence(self):
        event_types = list(SignalEventType)
        for name, expected_state in (
            ("dropoff_normal", SessionState.COMPLETED),
            ("forgotten_rising_temp", SessionState.EXCEPTION),
        ):
            with self.subTest(scenario=name):
                snapshots = scenario_snapshots(name)

                via_events = CareSession()
                for index, snap in enumerate(snapshots):
                    via_events.apply_event(
                        SignalEvent(
                            event_types[
                                (index * 3 + 1) % len(event_types)
                            ],
                            timestamp=9999.0,
                            cabin_temp_c=99.0,
                            snapshot=snap,
                        )
                    )

                reference = CareSession()
                replay(reference, snapshots)

                self.assertIs(via_events.state, expected_state)
                self.assertEqual(
                    transition_keys(via_events),
                    transition_keys(reference),
                )
                self.assertEqual(
                    via_events.current_snapshot,
                    reference.current_snapshot,
                )
                self.assertEqual(
                    guidance_for_session(
                        via_events, context=DestinationContext.DROPOFF
                    ),
                    guidance_for_session(
                        reference, context=DestinationContext.DROPOFF
                    ),
                )
                self.assertEqual(
                    report_for_session(via_events),
                    report_for_session(reference),
                )

    def test_apply_events_bulk_with_attached_snapshots(self):
        session = CareSession()
        events = [
            SignalEvent(SignalEventType.LOCKED, snapshot=snap)
            for snap in scenario_snapshots("pet_dropoff")
        ]

        result = session.apply_events(events)

        self.assertIs(result, SessionState.COMPLETED)
        self.assertIs(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)

        # 스냅샷 timestamp와 이벤트 timestamp가 모두 None이면
        # 전이 이력의 timestamp도 None이다.
        timeless = CareSession()
        timeless.apply_event(
            SignalEvent(
                SignalEventType.IGNITION_ON,
                snapshot=snapshot(rear_door=DoorState.OPEN),
            )
        )
        self.assertIs(timeless.state, SessionState.BOARDING)
        self.assertIsNone(timeless.current_snapshot.timestamp)
        self.assertEqual(
            [t.timestamp for t in timeless.history], [None]
        )


if __name__ == "__main__":
    unittest.main()

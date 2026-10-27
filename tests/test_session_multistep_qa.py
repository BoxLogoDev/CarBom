"""세션 다단 전이와 입력 경로 동등성에 대한 QA 단위 테스트.

기존 tests/test_session.py 는 단계마다 스냅샷 한 건씩 넣는 정상 흐름을 다룬다.
이 파일은 스냅샷 한 건이 여러 상태를 건너뛰는 경우를 다룬다.
이 파일은 update 와 apply_snapshot 과 apply_event 의 결과 동등성을 다룬다.
이 파일은 전이 기록이 얼어 있는지도 다룬다.
"""

import dataclasses
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


def history_tuples(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


def drive(session):
    session.apply_snapshot(
        SignalSnapshot(rear_door=DoorState.OPEN, timestamp=0.0)
    )
    session.apply_snapshot(
        SignalSnapshot(rear_seat_belt_buckled=True, timestamp=60.0)
    )
    session.apply_snapshot(
        SignalSnapshot(
            rear_seat_belt_buckled=True,
            ignition=IgnitionState.ON,
            timestamp=120.0,
        )
    )


class SessionMultistepQaTest(unittest.TestCase):
    def test_single_snapshot_skips_to_driving(self):
        session = CareSession()

        session.apply_snapshot(
            SignalSnapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                timestamp=10.0,
            )
        )

        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(
            history_tuples(session),
            [
                (
                    SessionState.IDLE,
                    SessionState.ONBOARD,
                    "passenger_onboard",
                    10.0,
                ),
                (
                    SessionState.ONBOARD,
                    SessionState.DRIVING,
                    "ignition_on",
                    10.0,
                ),
            ],
        )

    def test_single_snapshot_goes_straight_to_exception(self):
        session = CareSession()

        session.apply_snapshot(
            SignalSnapshot(
                rear_seat_belt_buckled=True,
                lock=LockState.LOCKED,
                timestamp=30.0,
            )
        )

        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(
            [
                (t.from_state, t.to_state, t.reason)
                for t in session.history
            ],
            [
                (
                    SessionState.IDLE,
                    SessionState.EXCEPTION,
                    "ignition_off_locked_passenger_present",
                )
            ],
        )

    def test_single_snapshot_passes_arrived_then_completes(self):
        session = CareSession()
        drive(session)
        self.assertEqual(session.state, SessionState.DRIVING)

        session.apply_snapshot(
            SignalSnapshot(rear_door=DoorState.OPEN, timestamp=180.0)
        )

        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        self.assertIn(
            (SessionState.DRIVING, SessionState.ARRIVED),
            [(t.from_state, t.to_state) for t in session.history],
        )

        session.apply_snapshot(SignalSnapshot(timestamp=240.0))

        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)

    def test_update_matches_apply_on_mixed_input(self):
        signals = [
            SignalSnapshot(rear_door=DoorState.OPEN, timestamp=0.0),
            SignalEvent(
                SignalEventType.REAR_BELT_BUCKLED, timestamp=60.0
            ),
            SignalEvent(
                SignalEventType.REAR_DOOR_CLOSED, timestamp=61.0
            ),
            SignalSnapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                timestamp=120.0,
            ),
            SignalSnapshot(
                rear_seat_belt_buckled=True, timestamp=180.0
            ),
            SignalEvent(
                SignalEventType.REAR_DOOR_OPENED, timestamp=240.0
            ),
            SignalEvent(
                SignalEventType.REAR_BELT_UNBUCKLED, timestamp=241.0
            ),
            SignalEvent(
                SignalEventType.REAR_DOOR_CLOSED, timestamp=242.0
            ),
        ]
        via_update = CareSession()
        via_apply = CareSession()

        for signal in signals:
            via_update.update(signal)
        for signal in signals:
            if isinstance(signal, SignalEvent):
                via_apply.apply_event(signal)
            else:
                via_apply.apply_snapshot(signal)

        self.assertEqual(via_update.state, SessionState.COMPLETED)
        self.assertEqual(via_apply.state, SessionState.COMPLETED)
        self.assertEqual(
            via_update.passenger_present, via_apply.passenger_present
        )
        self.assertEqual(
            history_tuples(via_update), history_tuples(via_apply)
        )

    def test_update_returns_same_state_as_apply(self):
        via_update = CareSession()
        via_apply = CareSession()
        signals = [
            SignalSnapshot(rear_door=DoorState.OPEN, timestamp=0.0),
            SignalEvent(
                SignalEventType.REAR_BELT_BUCKLED, timestamp=60.0
            ),
            SignalEvent(
                SignalEventType.REAR_DOOR_CLOSED, timestamp=61.0
            ),
        ]

        for signal in signals:
            returned = via_update.update(signal)
            if isinstance(signal, SignalEvent):
                expected = via_apply.apply_event(signal)
            else:
                expected = via_apply.apply_snapshot(signal)
            self.assertEqual(returned, expected)

        self.assertEqual(via_update.state, SessionState.ONBOARD)

    def test_transition_is_frozen_and_keeps_snapshot(self):
        session = CareSession()
        applied = SignalSnapshot(
            rear_door=DoorState.OPEN, timestamp=5.0
        )

        session.apply_snapshot(applied)

        transition = session.history[0]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            transition.reason = "changed"
        self.assertEqual(transition.snapshot, applied)
        self.assertEqual(transition.timestamp, applied.timestamp)


if __name__ == "__main__":
    unittest.main()

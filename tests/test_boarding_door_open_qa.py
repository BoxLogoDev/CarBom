"""QA scenarios for boarding with the rear door still open.

Boarding only completes once the rear door closes with a passenger
on board. While the door stays open the session must hold in
BOARDING: buckling the belt does not finish boarding, and turning
the ignition on does not depart. Closing the door with the ignition
already on then walks BOARDING -> ONBOARD -> DRIVING in a single
snapshot. A passenger who unbuckles and gets out while the door is
still open is cleared during BOARDING, and closing the door after
that returns the session to IDLE instead of departing. The
scenarios cover both the snapshot path and the event path, plus
the guidance and report views of the held boarding state.
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
from engine.guidance import DestinationContext, GuidanceLevel, guidance_for_session
from engine.report import report_for_session


def snapshot(timestamp, *, door_open=False, belt=False, ignition=False,
             locked=False, hvac_on=False, cabin_temp_c=None):
    return SignalSnapshot(
        rear_door=DoorState.OPEN if door_open else DoorState.CLOSED,
        rear_seat_belt_buckled=belt,
        ignition=IgnitionState.ON if ignition else IgnitionState.OFF,
        lock=LockState.LOCKED if locked else LockState.UNLOCKED,
        hvac_on=hvac_on,
        cabin_temp_c=cabin_temp_c,
        timestamp=timestamp,
    )


def history_of(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


def door_open_boarding_session():
    session = CareSession()
    session.apply_snapshot(snapshot(0.0, door_open=True))
    session.apply_snapshot(snapshot(60.0, door_open=True, belt=True))
    return session


class BoardingDoorOpenQATest(unittest.TestCase):
    def test_boarding_holds_while_door_open_with_belt(self):
        session = door_open_boarding_session()
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(
            history_of(session),
            [
                (
                    SessionState.IDLE,
                    SessionState.BOARDING,
                    "rear_door_opened",
                    0.0,
                )
            ],
        )
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "boarding_dropoff")

    def test_ignition_on_with_door_open_does_not_depart(self):
        session = door_open_boarding_session()
        for timestamp in (120.0, 180.0):
            state = session.apply_snapshot(
                snapshot(
                    timestamp, door_open=True, belt=True, ignition=True
                )
            )
            self.assertEqual(state, SessionState.BOARDING)
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 1)

    def test_closing_door_with_ignition_on_goes_driving_then_completes(self):
        session = door_open_boarding_session()
        session.apply_snapshot(
            snapshot(120.0, door_open=True, belt=True, ignition=True)
        )
        state = session.apply_snapshot(
            snapshot(240.0, belt=True, ignition=True)
        )
        self.assertEqual(state, SessionState.DRIVING)
        self.assertEqual(
            history_of(session)[-2:],
            [
                (
                    SessionState.BOARDING,
                    SessionState.ONBOARD,
                    "passenger_onboard",
                    240.0,
                ),
                (
                    SessionState.ONBOARD,
                    SessionState.DRIVING,
                    "ignition_on",
                    240.0,
                ),
            ],
        )
        session.apply_snapshot(snapshot(300.0, belt=True))
        self.assertEqual(session.state, SessionState.ARRIVED)
        session.apply_snapshot(snapshot(360.0, door_open=True, belt=True))
        self.assertEqual(session.state, SessionState.ALIGHTING)
        session.apply_snapshot(snapshot(420.0, door_open=True))
        self.assertEqual(session.state, SessionState.ALIGHTING)
        state = session.apply_snapshot(snapshot(480.0))
        self.assertEqual(state, SessionState.COMPLETED)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 480.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_passenger_leaving_during_boarding_returns_to_idle_on_door_close(self):
        session = door_open_boarding_session()
        state = session.apply_snapshot(snapshot(120.0, door_open=True))
        self.assertEqual(state, SessionState.BOARDING)
        self.assertFalse(session.passenger_present)
        self.assertEqual(len(session.history), 1)

        state = session.apply_snapshot(snapshot(180.0))
        self.assertEqual(state, SessionState.IDLE)
        self.assertEqual(
            history_of(session)[-1],
            (
                SessionState.BOARDING,
                SessionState.IDLE,
                "boarding_without_passenger",
                180.0,
            ),
        )

        report = report_for_session(session)
        self.assertEqual(report.final_state, SessionState.IDLE)
        self.assertFalse(report.completed)
        self.assertEqual(report.transition_count, 2)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

        guidance = guidance_for_session(session)
        self.assertEqual(guidance.level, GuidanceLevel.NONE)
        self.assertEqual(guidance.text, "")

    def test_event_path_matches_snapshot_path_for_door_open_boarding(self):
        via_events = CareSession()
        via_events.apply_event(
            SignalEvent(
                type=SignalEventType.REAR_DOOR_OPENED, timestamp=0.0
            )
        )
        via_events.apply_event(
            SignalEvent(
                type=SignalEventType.REAR_BELT_BUCKLED, timestamp=60.0
            )
        )
        via_events.apply_event(
            SignalEvent(type=SignalEventType.IGNITION_ON, timestamp=120.0)
        )
        self.assertEqual(via_events.state, SessionState.BOARDING)
        self.assertTrue(via_events.passenger_present)
        self.assertEqual(len(via_events.history), 1)
        via_events.apply_event(
            SignalEvent(
                type=SignalEventType.REAR_DOOR_CLOSED, timestamp=240.0
            )
        )

        via_snapshots = door_open_boarding_session()
        via_snapshots.apply_snapshot(
            snapshot(120.0, door_open=True, belt=True, ignition=True)
        )
        via_snapshots.apply_snapshot(snapshot(240.0, belt=True, ignition=True))

        self.assertEqual(via_events.state, SessionState.DRIVING)
        self.assertEqual(via_events.state, via_snapshots.state)
        self.assertEqual(history_of(via_events), history_of(via_snapshots))

    def test_boarding_guidance_general_context(self):
        session = CareSession()
        session.apply_snapshot(snapshot(0.0, door_open=True, belt=True))
        self.assertEqual(session.state, SessionState.BOARDING)
        guidance = guidance_for_session(session)
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "boarding")


if __name__ == "__main__":
    unittest.main()

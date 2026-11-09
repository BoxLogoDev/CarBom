"""QA scenarios for opening the rear door alone while ARRIVED.

Arrived is the one state where opening the rear door is itself the
normal start of alighting. No dedicated file isolates that single
input. The arrived lock file enters EXCEPTION on lock alone, and
the arrived HVAC file stays in ARRIVED while the door stays shut.
Neither pins what door opening alone does: it must move ARRIVED to
ALIGHTING with reason alighting_started, keep the passenger inside
until the belt is released with the door open, stay idempotent when
repeated or closed again while belted, match between the snapshot
and event paths, not escalate on a hot cabin (the open door blocks
the exception condition), and complete once the passenger leaves
and the door closes.
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


def arrived_session():
    """ARRIVED reached by boarding, belting, driving, ignition off."""
    session = CareSession()
    session.apply_snapshot(snapshot(0.0, door_open=True))
    session.apply_snapshot(snapshot(60.0, belt=True))
    session.apply_snapshot(snapshot(120.0, belt=True, ignition=True))
    session.apply_snapshot(snapshot(180.0, belt=True))
    return session


def history_signature(session):
    return [
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    ]


class ArrivedDoorOpenQATest(unittest.TestCase):
    def test_door_open_in_arrived_starts_alighting(self):
        session = arrived_session()
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 4)
        base_guidance = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(base_guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(
            base_guidance.reason, "arrived_dropoff_check_rear_seat"
        )

        state = session.apply_snapshot(
            snapshot(240.0, door_open=True, belt=True)
        )

        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertEqual(len(session.history), 5)
        self.assertEqual(session.history[-1].from_state, SessionState.ARRIVED)
        self.assertEqual(session.history[-1].to_state, SessionState.ALIGHTING)
        self.assertEqual(session.history[-1].reason, "alighting_started")
        self.assertEqual(session.history[-1].timestamp, 240.0)
        self.assertTrue(session.passenger_present)
        guidance = guidance_for_session(session, DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "alighting")
        self.assertEqual(
            guidance.text, "하차 중입니다. 뒷좌석이 비었는지 확인해 주세요."
        )
        report = report_for_session(session)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertIsNone(report.max_cabin_temp_c)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_door_open_repeated_and_close_while_belted_stay_alighting(self):
        session = arrived_session()
        session.apply_snapshot(snapshot(240.0, door_open=True, belt=True))
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertEqual(len(session.history), 5)

        state = session.apply_snapshot(
            snapshot(300.0, door_open=True, belt=True)
        )
        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertEqual(len(session.history), 5)
        self.assertEqual(session.current_snapshot.timestamp, 300.0)

        # Closing the door while the passenger is still belted does
        # not confirm alighting, so the session stays in ALIGHTING.
        state = session.apply_snapshot(snapshot(360.0, belt=True))
        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 5)

    def test_door_open_event_in_arrived_matches_snapshot_path(self):
        session = arrived_session()
        state = session.apply_event(
            SignalEvent(type=SignalEventType.REAR_DOOR_OPENED, timestamp=240.0)
        )
        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertEqual(session.current_snapshot.rear_door, DoorState.OPEN)

        snapshot_session = arrived_session()
        snapshot_session.apply_snapshot(
            snapshot(240.0, door_open=True, belt=True)
        )
        self.assertEqual(
            history_signature(session), history_signature(snapshot_session)
        )
        self.assertEqual(session.state, snapshot_session.state)
        self.assertEqual(
            session.current_snapshot.rear_door,
            snapshot_session.current_snapshot.rear_door,
        )

    def test_door_open_in_arrived_hot_cabin_no_exception(self):
        session = arrived_session()
        state = session.apply_snapshot(
            snapshot(240.0, door_open=True, belt=True, cabin_temp_c=35.5)
        )
        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertNotEqual(state, SessionState.EXCEPTION)
        guidance = guidance_for_session(session, DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "alighting")
        self.assertNotIn("35.5도", guidance.text)
        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_alighting_after_door_open_guidance_same_all_contexts(self):
        session = arrived_session()
        session.apply_snapshot(snapshot(240.0, door_open=True, belt=True))
        self.assertEqual(session.state, SessionState.ALIGHTING)

        guidances = [
            guidance_for_session(session, context)
            for context in (
                DestinationContext.GENERAL,
                DestinationContext.DROPOFF,
                DestinationContext.PICKUP,
            )
        ]
        for guidance in guidances:
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "alighting")
        self.assertEqual(guidances[0].text, guidances[1].text)
        self.assertEqual(guidances[1].text, guidances[2].text)

    def test_door_open_then_unbuckle_and_close_completes(self):
        session = arrived_session()
        state = session.apply_snapshot(
            snapshot(240.0, door_open=True, belt=True)
        )
        self.assertEqual(state, SessionState.ALIGHTING)

        state = session.apply_snapshot(snapshot(300.0, door_open=True))
        self.assertEqual(state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)

        state = session.apply_snapshot(snapshot(360.0))
        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        self.assertEqual(session.history[-1].reason, "alighting_confirmed")
        self.assertEqual(session.history[-1].timestamp, 360.0)
        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 360.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")
        guidance = guidance_for_session(session, DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")


if __name__ == "__main__":
    unittest.main()

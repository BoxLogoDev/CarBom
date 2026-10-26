"""QA scenarios for the event-only input path of CareSession."""

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


def board_via_events(session):
    session.apply_event(SignalEvent(SignalEventType.REAR_DOOR_OPENED))
    session.apply_event(SignalEvent(SignalEventType.REAR_BELT_BUCKLED))
    session.apply_event(SignalEvent(SignalEventType.REAR_DOOR_CLOSED))


def enter_exception_via_events(session):
    board_via_events(session)
    session.apply_event(SignalEvent(SignalEventType.IGNITION_ON))
    session.apply_event(SignalEvent(SignalEventType.IGNITION_OFF))
    session.apply_event(SignalEvent(SignalEventType.LOCKED))


class EventPathQATest(unittest.TestCase):
    def test_locked_event_drives_exception(self):
        session = CareSession()

        session.apply_event(SignalEvent(SignalEventType.REAR_DOOR_OPENED))
        self.assertEqual(session.state, SessionState.BOARDING)

        session.apply_event(SignalEvent(SignalEventType.REAR_BELT_BUCKLED))
        session.apply_event(SignalEvent(SignalEventType.REAR_DOOR_CLOSED))
        self.assertEqual(session.state, SessionState.ONBOARD)

        session.apply_event(SignalEvent(SignalEventType.IGNITION_ON))
        self.assertEqual(session.state, SessionState.DRIVING)

        session.apply_event(SignalEvent(SignalEventType.IGNITION_OFF))
        self.assertEqual(session.state, SessionState.ARRIVED)

        session.apply_event(SignalEvent(SignalEventType.LOCKED))
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        self.assertTrue(session.current_snapshot.locked)

    def test_exception_recovers_via_unlock_and_ignition_events(self):
        session = CareSession()
        enter_exception_via_events(session)
        self.assertEqual(session.state, SessionState.EXCEPTION)

        session.apply_event(
            SignalEvent(
                SignalEventType.CABIN_TEMP_CHANGED, cabin_temp_c=34.0
            )
        )
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 34.0)

        session.apply_event(SignalEvent(SignalEventType.UNLOCKED))
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertFalse(session.current_snapshot.locked)
        self.assertFalse(session.current_snapshot.ignition_on)

        session.apply_event(SignalEvent(SignalEventType.IGNITION_ON))
        self.assertEqual(session.state, SessionState.DRIVING)

        recovery = [
            transition
            for transition in session.history
            if transition.from_state is SessionState.EXCEPTION
            and transition.to_state is SessionState.ONBOARD
        ]
        self.assertEqual(len(recovery), 1)
        self.assertEqual(
            recovery[0].reason,
            "unlocked_and_ignition_on_after_exception",
        )

    def test_hvac_events_update_snapshot_without_state_change(self):
        session = CareSession()
        board_via_events(session)
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertFalse(session.current_snapshot.hvac_on)

        session.apply_event(SignalEvent(SignalEventType.HVAC_ON))
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertTrue(session.current_snapshot.hvac_on)

        session.apply_event(SignalEvent(SignalEventType.HVAC_OFF))
        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertFalse(session.current_snapshot.hvac_on)

    def test_event_with_attached_snapshot_and_timestamp_fallback(self):
        session = CareSession()

        session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_OPENED,
                timestamp=123.0,
                snapshot=snapshot(rear_door=DoorState.OPEN),
            )
        )
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertEqual(session.current_snapshot.timestamp, 123.0)
        self.assertEqual(session.history[-1].timestamp, 123.0)

        other = CareSession()
        other.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_OPENED,
                timestamp=999.0,
                snapshot=snapshot(
                    rear_door=DoorState.OPEN, timestamp=50.0
                ),
            )
        )
        self.assertEqual(other.state, SessionState.BOARDING)
        self.assertEqual(other.current_snapshot.timestamp, 50.0)


if __name__ == "__main__":
    unittest.main()

"""QA scenarios for rear belt buckled input alone while IDLE."""

import unittest

from engine import (
    CareSession,
    DestinationContext,
    DoorState,
    GuidanceLevel,
    IgnitionState,
    LockState,
    SessionState,
    SignalEvent,
    SignalEventType,
    SignalSnapshot,
    guidance_for_session,
    report_for_session,
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


class IdleBeltQATest(unittest.TestCase):
    def test_idle_belt_buckled_alone_enters_onboard(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                cabin_temp_c=24.0,
                timestamp=10.0,
            )
        )

        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 1)
        self.assertEqual(session.history[0].from_state, SessionState.IDLE)
        self.assertEqual(
            session.history[0].to_state, SessionState.ONBOARD
        )
        self.assertEqual(session.history[0].reason, "passenger_onboard")
        self.assertEqual(session.history[0].timestamp, 10.0)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "passenger_onboard")
        self.assertEqual(
            guidance.text,
            "뒷좌석 승차가 확인되었습니다. "
            "출발 전 안전벨트를 확인해 주세요.",
        )

        report = report_for_session(session)
        self.assertFalse(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 1)
        self.assertEqual(report.duration_seconds, 0.0)
        self.assertEqual(report.max_cabin_temp_c, 24.0)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_idle_belt_buckled_repeated_is_idempotent(self):
        session = CareSession()

        for timestamp in (10.0, 20.0):
            session.apply_snapshot(
                snapshot(
                    rear_seat_belt_buckled=True,
                    cabin_temp_c=24.0,
                    timestamp=timestamp,
                )
            )
            self.assertEqual(session.state, SessionState.ONBOARD)
            self.assertTrue(session.passenger_present)
            self.assertEqual(len(session.history), 1)

    def test_idle_belt_event_alone_matches_snapshot_path(self):
        snapshot_session = CareSession()
        snapshot_session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                cabin_temp_c=24.0,
                timestamp=10.0,
            )
        )

        event_session = CareSession()
        event_session.apply_event(
            SignalEvent(
                SignalEventType.REAR_BELT_BUCKLED, timestamp=10.0
            )
        )

        self.assertEqual(event_session.state, SessionState.ONBOARD)
        self.assertTrue(event_session.passenger_present)
        self.assertEqual(len(event_session.history), 1)
        self.assertEqual(
            [
                (
                    transition.from_state,
                    transition.to_state,
                    transition.reason,
                    transition.timestamp,
                )
                for transition in event_session.history
            ],
            [
                (
                    transition.from_state,
                    transition.to_state,
                    transition.reason,
                    transition.timestamp,
                )
                for transition in snapshot_session.history
            ],
        )

    def test_idle_belt_buckled_hot_alone_stays_onboard(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                cabin_temp_c=35.5,
                timestamp=10.0,
            )
        )

        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertTrue(session.passenger_present)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "passenger_onboard")
        self.assertEqual(
            guidance.text,
            "뒷좌석 승차가 확인되었습니다. "
            "출발 전 안전벨트를 확인해 주세요.",
        )

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_onboard_unbuckle_closed_door_keeps_passenger_latch(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(rear_seat_belt_buckled=True, timestamp=0.0)
        )
        self.assertEqual(session.state, SessionState.ONBOARD)

        session.apply_snapshot(snapshot(timestamp=60.0))

        self.assertEqual(session.state, SessionState.ONBOARD)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 1)

    def test_belt_first_full_journey_completes_without_boarding(self):
        session = CareSession()

        session.apply_snapshot(
            snapshot(rear_seat_belt_buckled=True, timestamp=0.0)
        )
        self.assertEqual(session.state, SessionState.ONBOARD)

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                timestamp=60.0,
            )
        )
        self.assertEqual(session.state, SessionState.DRIVING)

        session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=True,
                ignition=IgnitionState.ON,
                timestamp=120.0,
            )
        )
        self.assertEqual(session.state, SessionState.DRIVING)

        session.apply_snapshot(
            snapshot(rear_seat_belt_buckled=True, timestamp=180.0)
        )
        self.assertEqual(session.state, SessionState.ARRIVED)

        session.apply_snapshot(
            snapshot(rear_door=DoorState.OPEN, timestamp=240.0)
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)

        session.apply_snapshot(snapshot(timestamp=300.0))
        self.assertEqual(session.state, SessionState.COMPLETED)

        self.assertEqual(
            [
                (
                    transition.from_state,
                    transition.to_state,
                    transition.reason,
                )
                for transition in session.history
            ],
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
                (
                    SessionState.DRIVING,
                    SessionState.ARRIVED,
                    "ignition_off",
                ),
                (
                    SessionState.ARRIVED,
                    SessionState.ALIGHTING,
                    "alighting_started",
                ),
                (
                    SessionState.ALIGHTING,
                    SessionState.COMPLETED,
                    "alighting_confirmed",
                ),
            ],
        )
        self.assertNotIn(
            SessionState.BOARDING,
            [transition.to_state for transition in session.history],
        )
        self.assertNotIn(
            SessionState.BOARDING,
            [transition.from_state for transition in session.history],
        )

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 5)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")


if __name__ == "__main__":
    unittest.main()

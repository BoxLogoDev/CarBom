"""QA scenarios for inputs that arrive after a session is COMPLETED.

COMPLETED is the terminal state: the state machine never leaves it
and the transition history never grows again. The existing edge QA
only checked that a few later snapshots keep the state and the
history length. These scenarios pin the wider surface after
completion: an exception-shaped snapshot (belt buckled, locked,
dangerous cabin temperature) must not re-enter EXCEPTION, the event
path and bulk apply helpers must not revive the session, replaying a
whole scenario must keep the original history, and guidance stays
INFO/completed in every destination context.

One current-snapshot effect is characterized rather than hidden: the
passenger latch is recomputed from every incoming snapshot even in
COMPLETED, so a post-completion belt signal turns passenger_present
back on, and a report built afterwards reflects that latch and the
current snapshot temperature in max_cabin_temp_c — while its
completed flag, exception counts, transition count, duration and
summary stay exactly as they were at completion.
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
from engine.adapters.simulator import replay_scenario, scenario_snapshots
from engine.guidance import DestinationContext, GuidanceLevel, guidance_for_session
from engine.report import CareReportLog, report_for_session


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


def completed_session():
    """A session driven to COMPLETED by the normal dropoff scenario."""
    session = CareSession()
    replay_scenario(session, "dropoff_normal")
    return session


def history_signature(session):
    return [
        (transition.from_state, transition.to_state,
         transition.reason, transition.timestamp)
        for transition in session.history
    ]


class CompletedTerminalQATest(unittest.TestCase):
    def test_exception_trigger_after_completed_does_not_reenter_exception(self):
        session = completed_session()
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        before = history_signature(session)
        self.assertEqual(
            [reason for _, _, reason, _ in before],
            ["rear_door_opened", "passenger_onboard", "ignition_on",
             "ignition_off", "alighting_started", "alighting_confirmed"],
        )

        state = session.apply_snapshot(
            snapshot(500, belt=True, locked=True, cabin_temp_c=35.5)
        )

        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(history_signature(session), before)
        for context in (DestinationContext.GENERAL,
                        DestinationContext.DROPOFF,
                        DestinationContext.PICKUP):
            guidance = guidance_for_session(session, context)
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "completed")
            self.assertEqual(guidance.text, "하차 확인이 완료되었습니다.")
        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.started_at, 0.0)
        self.assertEqual(report.ended_at, 300.0)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")
        # Characterized current-snapshot effect: the latch is recomputed
        # from the incoming snapshot even in the terminal state, and the
        # report reads passenger presence and max temperature from it.
        self.assertTrue(session.passenger_present)
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.max_cabin_temp_c, 35.5)

    def test_door_open_and_ignition_after_completed_keep_terminal(self):
        session = completed_session()
        before = history_signature(session)

        session.apply_snapshot(snapshot(400, door_open=True))
        state = session.apply_snapshot(snapshot(460, ignition=True))

        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(history_signature(session), before)

    def test_events_after_completed_keep_terminal_but_update_snapshot(self):
        session = completed_session()
        before = history_signature(session)

        for event in (
            SignalEvent(type=SignalEventType.REAR_DOOR_OPENED, timestamp=700),
            SignalEvent(type=SignalEventType.REAR_BELT_BUCKLED, timestamp=710),
            SignalEvent(type=SignalEventType.LOCKED, timestamp=720),
            SignalEvent(type=SignalEventType.IGNITION_ON, timestamp=730),
        ):
            state = session.apply_event(event)
            self.assertEqual(state, SessionState.COMPLETED)

        self.assertEqual(history_signature(session), before)
        current = session.current_snapshot
        self.assertEqual(current.rear_door, DoorState.OPEN)
        self.assertTrue(current.rear_seat_belt_buckled)
        self.assertEqual(current.lock, LockState.LOCKED)
        self.assertEqual(current.ignition, IgnitionState.ON)
        self.assertEqual(current.timestamp, 730.0)
        guidance = guidance_for_session(session, DestinationContext.DROPOFF)
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")

    def test_replay_again_after_completed_keeps_original_history(self):
        session = completed_session()
        before = history_signature(session)

        state = replay_scenario(session, "dropoff_normal", start=1000.0)

        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(history_signature(session), before)
        self.assertEqual(session.history[0].timestamp, 0.0)
        self.assertEqual(session.history[-1].timestamp, 300.0)
        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)

    def test_bulk_apply_after_completed_keeps_terminal(self):
        session = completed_session()
        before = history_signature(session)

        state = session.apply_snapshots(
            scenario_snapshots("forgotten_rising_temp")
        )

        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(history_signature(session), before)

        other = completed_session()
        other_before = history_signature(other)
        state = other.apply_updates(
            [snapshot(800, belt=True, locked=True, cabin_temp_c=35.5)]
        )
        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(history_signature(other), other_before)

    def test_report_log_after_post_completion_trigger(self):
        untouched = completed_session()
        triggered = completed_session()
        triggered.apply_snapshot(
            snapshot(500, belt=True, locked=True, cabin_temp_c=35.5)
        )

        log = CareReportLog()
        returned = log.add_sessions([untouched, triggered])

        self.assertEqual(len(log.reports), 2)
        self.assertEqual(returned, log.reports)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 0)
        self.assertEqual(log.total_exception_count, 0)
        # The post-completion temperature reaches the log only through
        # the report's current-snapshot max temperature.
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.sessions_with_passenger, 1)
        self.assertEqual(log.sessions_without_passenger, 1)


if __name__ == "__main__":
    unittest.main()

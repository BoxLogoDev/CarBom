"""QA scenarios for HVAC input alone after a session is COMPLETED.

COMPLETED is the terminal state, so an HVAC snapshot or event that
arrives after completion must not revive the session. It only toggles
hvac_on on the current snapshot. These scenarios pin that angle
without repeating the wider terminal-state QA: guidance stays
INFO/completed in every destination context, a high cabin
temperature does not escalate the way it can while ARRIVED, and the
completed report keeps its completion verdict, exception counts,
transition count, and transition-based duration. The only report
field a post-completion HVAC snapshot can still reach is
max_cabin_temp_c, through the current snapshot temperature. An HVAC
event carries no temperature, so the event path leaves that field
empty while matching the snapshot path on state and history.
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
from engine.adapters.simulator import replay_scenario
from engine.guidance import DestinationContext, GuidanceLevel, guidance_for_session
from engine.report import CareReportLog, report_for_session


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


def completed_session():
    session = CareSession()
    replay_scenario(session, "dropoff_normal")
    return session


def history_signature(session):
    return [
        (transition.from_state, transition.to_state,
         transition.reason, transition.timestamp)
        for transition in session.history
    ]


class CompletedHvacQATest(unittest.TestCase):
    def test_completed_hvac_on_alone_stays_completed(self):
        session = completed_session()
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        before = history_signature(session)
        self.assertEqual(
            [reason for _, _, reason, _ in before],
            ["rear_door_opened", "passenger_onboard", "ignition_on",
             "ignition_off", "alighting_started", "alighting_confirmed"],
        )
        self.assertEqual(
            [timestamp for _, _, _, timestamp in before],
            [0.0, 60.0, 120.0, 180.0, 240.0, 300.0],
        )
        self.assertFalse(session.passenger_present)
        self.assertFalse(session.current_snapshot.hvac_on)
        self.assertIsNone(session.current_snapshot.cabin_temp_c)

        state = session.apply_snapshot(
            snapshot(hvac_on=True, cabin_temp_c=24.0, timestamp=360.0)
        )

        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        self.assertEqual(history_signature(session), before)
        self.assertFalse(session.passenger_present)
        self.assertTrue(session.current_snapshot.hvac_on)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
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
        self.assertEqual(report.max_cabin_temp_c, 24.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_completed_hvac_repeated_is_idempotent_and_toggles_off(self):
        session = completed_session()

        for timestamp in (360.0, 420.0):
            state = session.apply_snapshot(
                snapshot(hvac_on=True, timestamp=timestamp)
            )
            self.assertEqual(state, SessionState.COMPLETED)
            self.assertEqual(session.state, SessionState.COMPLETED)
            self.assertEqual(len(session.history), 6)
            self.assertTrue(session.current_snapshot.hvac_on)

        state = session.apply_snapshot(
            snapshot(hvac_on=False, timestamp=480.0)
        )
        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        self.assertFalse(session.current_snapshot.hvac_on)

    def test_completed_hvac_on_high_temp_no_escalation(self):
        session = completed_session()

        state = session.apply_snapshot(
            snapshot(
                rear_seat_belt_buckled=False,
                hvac_on=True,
                cabin_temp_c=35.5,
                lock=LockState.UNLOCKED,
                timestamp=360.0,
            )
        )

        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertNotEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertNotEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(guidance.reason, "completed")
        self.assertEqual(guidance.text, "하차 확인이 완료되었습니다.")
        self.assertNotIn("35.5도", guidance.text)
        self.assertNotIn("즉시", guidance.text)

        report = report_for_session(session)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

    def test_completed_hvac_event_path_matches_snapshot_path(self):
        snapshot_session = completed_session()
        state = snapshot_session.apply_snapshot(
            snapshot(hvac_on=True, timestamp=360.0)
        )
        self.assertEqual(state, SessionState.COMPLETED)
        self.assertTrue(snapshot_session.current_snapshot.hvac_on)
        state = snapshot_session.apply_snapshot(
            snapshot(hvac_on=False, timestamp=420.0)
        )
        self.assertEqual(state, SessionState.COMPLETED)

        event_session = completed_session()
        state = event_session.apply_event(
            SignalEvent(type=SignalEventType.HVAC_ON, timestamp=360.0)
        )
        self.assertEqual(state, SessionState.COMPLETED)
        self.assertTrue(event_session.current_snapshot.hvac_on)
        state = event_session.apply_event(
            SignalEvent(type=SignalEventType.HVAC_OFF, timestamp=420.0)
        )
        self.assertEqual(state, SessionState.COMPLETED)

        self.assertEqual(snapshot_session.state, SessionState.COMPLETED)
        self.assertEqual(event_session.state, SessionState.COMPLETED)
        self.assertEqual(len(snapshot_session.history), 6)
        self.assertEqual(len(event_session.history), 6)
        self.assertEqual(
            history_signature(snapshot_session),
            history_signature(event_session),
        )
        self.assertFalse(snapshot_session.current_snapshot.hvac_on)
        self.assertFalse(event_session.current_snapshot.hvac_on)

        report = report_for_session(event_session)
        self.assertIsNone(report.max_cabin_temp_c)

    def test_completed_hvac_guidance_same_in_all_contexts(self):
        session = completed_session()
        session.apply_snapshot(
            snapshot(hvac_on=True, cabin_temp_c=24.0, timestamp=360.0)
        )

        for context in (DestinationContext.GENERAL,
                        DestinationContext.DROPOFF,
                        DestinationContext.PICKUP):
            guidance = guidance_for_session(session, context=context)
            self.assertEqual(guidance.level, GuidanceLevel.INFO)
            self.assertEqual(guidance.reason, "completed")
            self.assertEqual(guidance.text, "하차 확인이 완료되었습니다.")

    def test_completed_hvac_bulk_and_report_log(self):
        session = completed_session()

        state = session.apply_snapshots(
            [
                snapshot(
                    hvac_on=True, cabin_temp_c=24.0, timestamp=360.0
                ),
                snapshot(
                    hvac_on=False, cabin_temp_c=24.0, timestamp=420.0
                ),
            ]
        )

        self.assertEqual(state, SessionState.COMPLETED)
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(len(session.history), 6)
        self.assertFalse(session.current_snapshot.hvac_on)

        report = report_for_session(session)
        self.assertEqual(report.max_cabin_temp_c, 24.0)
        self.assertEqual(report.duration_seconds, 300.0)

        untouched = completed_session()
        heated = completed_session()
        heated.apply_snapshot(
            snapshot(hvac_on=True, cabin_temp_c=35.5, timestamp=360.0)
        )

        log = CareReportLog()
        log.add_sessions([untouched, heated])

        self.assertEqual(len(log), 2)
        self.assertEqual(len(log.reports), 2)
        self.assertEqual(log.completed_count, 2)
        self.assertEqual(log.sessions_with_exception, 0)
        self.assertEqual(log.total_exception_count, 0)
        self.assertEqual(log.total_transition_count, 12)
        self.assertEqual(log.max_cabin_temp_c, 35.5)
        self.assertEqual(log.average_duration_seconds, 300.0)


if __name__ == "__main__":
    unittest.main()

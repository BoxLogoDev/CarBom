"""QA scenarios for cabin temperature rising while dwelling at ARRIVED.

Reaching ARRIVED is covered elsewhere, and so is EXCEPTION entry. This
file covers the unlocked dwell in between: the driver has arrived but
has not locked the car yet, so rising cabin temperature must keep the
session in ARRIVED (EXCEPTION requires the locked signal), the guidance
must escalate only up to REMIND wording, and normal alighting must
still complete the session afterwards.
"""

import unittest

from engine import CareSession, DoorState, SessionState, SignalSnapshot
from engine.adapters.simulator import dropoff_normal_snapshots, replay
from engine.guidance import DestinationContext, guidance_for_session
from engine.report import report_for_session


def arrived_session():
    session = CareSession()
    replay(session, dropoff_normal_snapshots()[:4])
    return session


def dwell_snapshot(cabin_temp_c, timestamp):
    return SignalSnapshot(
        rear_seat_belt_buckled=True,
        hvac_on=False,
        cabin_temp_c=cabin_temp_c,
        timestamp=timestamp,
    )


class ArrivedDwellTempQATest(unittest.TestCase):
    def test_hot_dwell_keeps_arrived_state_and_history(self):
        session = arrived_session()
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertEqual(len(session.history), 4)

        result = session.apply_snapshot(dwell_snapshot(32.0, 240.0))

        self.assertEqual(result, SessionState.ARRIVED)
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertTrue(session.passenger_present)
        self.assertEqual(len(session.history), 4)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 32.0)

    def test_hot_dwell_guidance_is_remind_with_temperature(self):
        session = arrived_session()
        session.apply_snapshot(dwell_snapshot(32.0, 240.0))

        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level.name, "REMIND")
        self.assertEqual(
            guidance.reason,
            "arrived_dropoff_check_rear_seat_hot_cabin",
        )
        self.assertIn("32도", guidance.text)
        self.assertNotIn("즉시", guidance.text)

    def test_dangerous_dwell_guidance_stays_remind_not_urgent(self):
        session = arrived_session()
        session.apply_snapshot(dwell_snapshot(32.0, 240.0))
        session.apply_snapshot(dwell_snapshot(35.5, 300.0))

        self.assertEqual(session.state, SessionState.ARRIVED)
        guidance = guidance_for_session(
            session, context=DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level.name, "REMIND")
        self.assertNotEqual(guidance.level.name, "URGENT")
        self.assertEqual(
            guidance.reason,
            "arrived_dropoff_check_rear_seat_dangerous_cabin_temp",
        )
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)

    def test_repeated_dangerous_dwell_is_idempotent(self):
        session = arrived_session()
        session.apply_snapshot(dwell_snapshot(35.5, 300.0))

        for timestamp in (360.0, 420.0):
            result = session.apply_snapshot(
                dwell_snapshot(35.5, timestamp)
            )
            self.assertEqual(result, SessionState.ARRIVED)
            self.assertEqual(len(session.history), 4)
            self.assertTrue(session.passenger_present)

    def test_report_during_dwell_has_no_exception(self):
        session = arrived_session()
        session.apply_snapshot(dwell_snapshot(32.0, 240.0))
        session.apply_snapshot(dwell_snapshot(35.5, 300.0))

        report = report_for_session(session)
        self.assertEqual(report.final_state, SessionState.ARRIVED)
        self.assertFalse(report.completed)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 4)
        self.assertEqual(report.duration_seconds, 180.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.summary, "진행 중 · 하차 미확인")

    def test_alighting_after_dwell_completes_without_exception(self):
        session = arrived_session()
        session.apply_snapshot(dwell_snapshot(35.5, 300.0))

        result = session.apply_snapshot(
            SignalSnapshot(rear_door=DoorState.OPEN, timestamp=420.0)
        )
        self.assertEqual(result, SessionState.ALIGHTING)

        result = session.apply_snapshot(SignalSnapshot(timestamp=480.0))
        self.assertEqual(result, SessionState.COMPLETED)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 480.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")


if __name__ == "__main__":
    unittest.main()

"""이벤트·스냅샷 혼합 경로 QA.

전제: SignalSnapshot은 세션의 현재 스냅샷을 통째로 교체하고,
첨부 스냅샷 없는 SignalEvent는 현재 스냅샷을 점진적으로 바꾼다
(예: IGNITION_OFF 이벤트는 hvac_on을 건드리지 않는다).

기존 tests/test_pet_event_path_qa.py는 첨부 없는 이벤트만으로
구동하는 경로, tests/test_event_path_qa.py는 아이 흐름의 이벤트
경로, tests/test_session_multistep_qa.py는 update() 디스패치의
일부 동등성, tests/test_event_snapshot_precedence_qa.py는 첨부
스냅샷의 우선순위만 다뤘다. 한 세션 안에서 두 입력 방식을 번갈아
적용하는 혼합 순서 자체와, 그 결과가 순수 스냅샷 재생
(replay_scenario)과 전이 이력·최종 스냅샷·안내·리포트까지
일치하는지는 미검증이었다. 이 파일이 그 조합을 검증한다.
"""

import dataclasses
import unittest

from engine.adapters.simulator import replay_scenario, scenario_snapshots
from engine.guidance import (
    DestinationContext,
    GuidanceLevel,
    guidance_for_session,
)
from engine.report import report_for_session
from engine.session import CareSession, SessionState
from engine.signals import SignalEvent, SignalEventType


def _history(session):
    return tuple(
        (t.from_state, t.to_state, t.reason, t.timestamp)
        for t in session.history
    )


def _pure(name):
    session = CareSession()
    replay_scenario(session, name)
    return session


def _mixed_dropoff_steps():
    snaps = scenario_snapshots("dropoff_normal")
    return [
        ("snapshot", snaps[0]),
        (
            "event",
            SignalEvent(
                SignalEventType.REAR_BELT_BUCKLED, timestamp=60.0
            ),
        ),
        (
            "event",
            SignalEvent(
                SignalEventType.REAR_DOOR_CLOSED, timestamp=60.0
            ),
        ),
        ("snapshot", snaps[2]),
        (
            "event",
            SignalEvent(
                SignalEventType.IGNITION_OFF, timestamp=180.0
            ),
        ),
        ("snapshot", snaps[4]),
        (
            "event",
            SignalEvent(
                SignalEventType.REAR_DOOR_CLOSED, timestamp=300.0
            ),
        ),
    ]


def _apply_steps(session, steps):
    for kind, item in steps:
        if kind == "snapshot":
            session.apply_snapshot(item)
        else:
            session.apply_event(item)
    return session


def _mixed_forgotten_to_exception(session):
    snaps = scenario_snapshots("forgotten_rising_temp")
    session.apply_snapshot(snaps[0])
    session.apply_event(
        SignalEvent(SignalEventType.REAR_BELT_BUCKLED, timestamp=60.0)
    )
    session.apply_event(
        SignalEvent(SignalEventType.REAR_DOOR_CLOSED, timestamp=60.0)
    )
    session.apply_snapshot(snaps[2])
    session.apply_event(
        SignalEvent(SignalEventType.IGNITION_OFF, timestamp=180.0)
    )
    session.apply_event(
        SignalEvent(SignalEventType.LOCKED, timestamp=240.0)
    )
    return session, snaps


class MixedDropoffQATest(unittest.TestCase):
    def test_mixed_normal_completes_and_matches_pure_replay(self):
        session = CareSession()
        steps = _mixed_dropoff_steps()

        _apply_steps(session, steps[:1])
        self.assertEqual(session.state, SessionState.BOARDING)

        _apply_steps(session, steps[1:2])
        self.assertEqual(session.state, SessionState.BOARDING)
        self.assertTrue(session.passenger_present)

        _apply_steps(session, steps[2:3])
        self.assertEqual(session.state, SessionState.ONBOARD)

        _apply_steps(session, steps[3:4])
        self.assertEqual(session.state, SessionState.DRIVING)

        _apply_steps(session, steps[4:5])
        self.assertEqual(session.state, SessionState.ARRIVED)

        _apply_steps(session, steps[5:6])
        self.assertEqual(session.state, SessionState.ALIGHTING)

        _apply_steps(session, steps[6:])
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.passenger_present)

        pure = _pure("dropoff_normal")
        self.assertEqual(_history(session), _history(pure))
        self.assertEqual(session.current_snapshot, pure.current_snapshot)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertFalse(report.exception_occurred)
        self.assertEqual(report.exception_count, 0)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertIsNone(report.max_cabin_temp_c)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")
        self.assertEqual(report, report_for_session(pure))

        guidance = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")

    def test_mixed_arrived_guidance(self):
        session = _apply_steps(
            CareSession(), _mixed_dropoff_steps()[:5]
        )
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertTrue(session.passenger_present)

        guidance = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.REMIND)
        self.assertEqual(
            guidance.reason, "arrived_dropoff_check_rear_seat"
        )
        self.assertEqual(
            guidance.text,
            "도착했습니다. 등원 하차 전 뒷좌석을 확인해 주세요.",
        )


class MixedForgottenQATest(unittest.TestCase):
    def test_mixed_exception_temp_escalation_and_report(self):
        session, snaps = _mixed_forgotten_to_exception(CareSession())
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertTrue(session.passenger_present)
        last = session.history[-1]
        self.assertEqual(
            (last.from_state, last.to_state, last.reason),
            (
                SessionState.ARRIVED,
                SessionState.EXCEPTION,
                "ignition_off_locked_passenger_present",
            ),
        )

        session.apply_event(
            SignalEvent(
                SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=300.0,
                cabin_temp_c=28.0,
            )
        )
        self.assertEqual(session.state, SessionState.EXCEPTION)
        guidance = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(guidance.reason, "passenger_left_locked")
        self.assertNotIn("28", guidance.text)

        session.apply_snapshot(snaps[6])
        self.assertEqual(session.state, SessionState.EXCEPTION)
        self.assertEqual(session.current_snapshot.cabin_temp_c, 32.0)
        guidance = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason, "passenger_left_locked_hot_cabin"
        )
        self.assertIn("32도", guidance.text)

        session.apply_event(
            SignalEvent(
                SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=420.0,
                cabin_temp_c=35.5,
            )
        )
        self.assertEqual(session.state, SessionState.EXCEPTION)
        guidance = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.URGENT)
        self.assertEqual(
            guidance.reason,
            "passenger_left_locked_dangerous_cabin_temp",
        )
        self.assertIn("35.5도", guidance.text)
        self.assertIn("즉시", guidance.text)

        pure = _pure("forgotten_rising_temp")
        self.assertEqual(_history(session), _history(pure))
        self.assertEqual(session.current_snapshot, pure.current_snapshot)

        report = report_for_session(session)
        self.assertFalse(report.completed)
        self.assertTrue(report.exception_occurred)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 5)
        self.assertTrue(report.passenger_present)
        self.assertEqual(report.duration_seconds, 240.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")
        self.assertEqual(report, report_for_session(pure))

    def test_mixed_exception_recovery_completes(self):
        session, snaps = _mixed_forgotten_to_exception(CareSession())
        session.apply_event(
            SignalEvent(
                SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=300.0,
                cabin_temp_c=28.0,
            )
        )
        session.apply_snapshot(snaps[6])
        session.apply_event(
            SignalEvent(
                SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=420.0,
                cabin_temp_c=35.5,
            )
        )
        self.assertEqual(session.state, SessionState.EXCEPTION)

        session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_OPENED, timestamp=480.0
            )
        )
        self.assertEqual(session.state, SessionState.ALIGHTING)
        last = session.history[-1]
        self.assertEqual(
            (last.from_state, last.to_state, last.reason),
            (
                SessionState.EXCEPTION,
                SessionState.ALIGHTING,
                "rear_door_opened_after_exception",
            ),
        )

        recovery = dataclasses.replace(
            scenario_snapshots("dropoff_normal")[4], timestamp=540.0
        )
        session.apply_snapshot(recovery)
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)

        session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_CLOSED, timestamp=600.0
            )
        )
        self.assertEqual(session.state, SessionState.COMPLETED)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertTrue(report.exception_occurred)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.transition_count, 7)
        self.assertEqual(report.duration_seconds, 600.0)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(
            report.summary, "예외 발생 후 하차 확인 완료"
        )

        guidance = guidance_for_session(
            session, DestinationContext.DROPOFF
        )
        self.assertEqual(guidance.level, GuidanceLevel.INFO)
        self.assertEqual(guidance.reason, "completed")


class MixedPetQATest(unittest.TestCase):
    def test_mixed_pet_hvac_event_preserves_snapshot_replaces(self):
        snaps = scenario_snapshots("pet_dropoff")
        session = CareSession()

        session.apply_snapshot(snaps[0])
        session.apply_event(
            SignalEvent(
                SignalEventType.REAR_BELT_BUCKLED, timestamp=60.0
            )
        )
        session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_CLOSED, timestamp=60.0
            )
        )
        self.assertEqual(session.state, SessionState.ONBOARD)

        session.apply_snapshot(snaps[2])
        self.assertEqual(session.state, SessionState.DRIVING)
        self.assertTrue(session.current_snapshot.hvac_on)

        # 이벤트는 점진적이라 IGNITION_OFF가 hvac_on을 끄지 않는다.
        # 순수 재생의 snaps[3]은 hvac_on=False인 것과 다른 지점이다.
        session.apply_event(
            SignalEvent(SignalEventType.IGNITION_OFF, timestamp=180.0)
        )
        self.assertEqual(session.state, SessionState.ARRIVED)
        self.assertTrue(session.current_snapshot.hvac_on)
        self.assertFalse(snaps[3].hvac_on)

        # 스냅샷은 통째 교체라 hvac_on이 다시 False가 된다.
        session.apply_snapshot(snaps[4])
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.current_snapshot.hvac_on)

        session.apply_event(
            SignalEvent(
                SignalEventType.REAR_DOOR_CLOSED, timestamp=300.0
            )
        )
        self.assertEqual(session.state, SessionState.COMPLETED)

        pure = _pure("pet_dropoff")
        self.assertEqual(_history(session), _history(pure))
        self.assertEqual(session.current_snapshot, pure.current_snapshot)

        report = report_for_session(session)
        self.assertTrue(report.completed)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")


class MixedBulkDispatchQATest(unittest.TestCase):
    def test_apply_updates_mixed_matches_per_call_and_pure(self):
        snaps = scenario_snapshots("forgotten_rising_temp")
        items = [
            snaps[0],
            SignalEvent(
                SignalEventType.REAR_BELT_BUCKLED, timestamp=60.0
            ),
            SignalEvent(
                SignalEventType.REAR_DOOR_CLOSED, timestamp=60.0
            ),
            snaps[2],
            SignalEvent(
                SignalEventType.IGNITION_OFF, timestamp=180.0
            ),
            SignalEvent(SignalEventType.LOCKED, timestamp=240.0),
            snaps[5],
            SignalEvent(
                SignalEventType.CABIN_TEMP_CHANGED,
                timestamp=360.0,
                cabin_temp_c=32.0,
            ),
            snaps[7],
        ]

        bulk = CareSession()
        final = bulk.apply_updates(item for item in items)
        self.assertIs(final, SessionState.EXCEPTION)
        self.assertIs(final, bulk.state)

        per_call = CareSession()
        for item in items:
            per_call.update(item)

        pure = _pure("forgotten_rising_temp")
        self.assertEqual(_history(bulk), _history(per_call))
        self.assertEqual(_history(bulk), _history(pure))
        self.assertEqual(bulk.current_snapshot, per_call.current_snapshot)
        self.assertEqual(bulk.current_snapshot, pure.current_snapshot)
        self.assertEqual(
            report_for_session(bulk), report_for_session(per_call)
        )
        self.assertEqual(
            report_for_session(bulk), report_for_session(pure)
        )

    def test_update_returns_mixed_dropoff_sequence(self):
        session = CareSession()
        returns = [
            session.update(item)
            for _kind, item in _mixed_dropoff_steps()
        ]
        self.assertEqual(
            returns,
            [
                SessionState.BOARDING,
                SessionState.BOARDING,
                SessionState.ONBOARD,
                SessionState.DRIVING,
                SessionState.ARRIVED,
                SessionState.ALIGHTING,
                SessionState.COMPLETED,
            ],
        )
        self.assertIs(session.state, SessionState.COMPLETED)
        self.assertEqual(
            _history(session), _history(_pure("dropoff_normal"))
        )


if __name__ == "__main__":
    unittest.main()

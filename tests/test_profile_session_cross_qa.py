"""동승 프로필 × 세션 실제 벨트 상태 교차 QA.

전제: 수동 탑승 확인 판정(engine/profiles.py)은 벨트 상태만 본다.
세션 상태나 동승자 래치는 모른다. 반대로 CareSession은 프로필을
받지 않으므로 같은 신호를 넣으면 프로필 의도와 무관하게 같은
판정을 낸다. 기존 테스트는 프로필 판정 단독(test_profiles.py,
test_profiles_boundary_qa.py)과 종류별 시나리오(pet·elder 변형)를
각각 다뤘으나, 세션이 실제로 보고하는 벨트값을 단계마다 판정에
먹이는 교차 각도는 없었다. 이 파일이 그 교차를 고정한다.

특성화해 두는 동작 두 가지:
- EXCEPTION에서도 벨트가 체결된 채면 수동 확인은 전부 False다.
  수동 확인은 승차 시점의 벨트 판정일 뿐 예외 탐지가 아니다.
- ALIGHTING·COMPLETED에서는 래치가 풀렸어도 벨트가 풀려 있으면
  PET 판정이 다시 True가 된다. 판정이 벨트 전용이기 때문이다.
"""

import unittest

from engine import (
    CareSession,
    PassengerKind,
    SessionState,
    all_profiles,
    needs_manual_confirmation,
    needs_manual_confirmations,
    needs_manual_confirmations_for_kinds,
    profile_for,
    report_for_session,
)
from engine.adapters.simulator import replay_scenario, scenario_snapshots
from engine.guidance import DestinationContext, guidance_for_session


class ProfileSessionCrossQATest(unittest.TestCase):
    def test_belt_driven_manual_confirmation_per_step(self):
        session = CareSession()
        expected_states = [
            SessionState.BOARDING,
            SessionState.ONBOARD,
            SessionState.DRIVING,
            SessionState.ARRIVED,
            SessionState.ALIGHTING,
            SessionState.COMPLETED,
        ]
        expected_belts = [False, True, True, True, False, False]
        snapshots = scenario_snapshots("dropoff_normal")
        self.assertEqual(len(snapshots), 6)
        for snapshot, state, belt in zip(
            snapshots, expected_states, expected_belts
        ):
            self.assertEqual(session.apply_snapshot(snapshot), state)
            live_belt = session.current_snapshot.rear_seat_belt_buckled
            self.assertEqual(live_belt, belt)
            self.assertEqual(
                needs_manual_confirmations(
                    all_profiles(), belt_buckled=live_belt
                ),
                (False, True, False, False) if not belt else (False,) * 4,
            )

    def test_boarding_stage_kinds_with_fallback(self):
        session = CareSession()
        first = scenario_snapshots("dropoff_normal")[0]
        self.assertEqual(session.apply_snapshot(first), SessionState.BOARDING)
        self.assertFalse(session.current_snapshot.rear_seat_belt_buckled)
        self.assertEqual(
            needs_manual_confirmations_for_kinds(
                ["child", "pet", "elder", "adult", None, "unknown"],
                belt_buckled=session.current_snapshot.rear_seat_belt_buckled,
            ),
            (False, True, False, False, False, False),
        )

    def test_exception_stage_belt_still_buckled_all_false(self):
        session = CareSession()
        self.assertEqual(
            replay_scenario(session, "forgotten_rising_temp"),
            SessionState.EXCEPTION,
        )
        self.assertTrue(session.passenger_present)
        self.assertTrue(session.current_snapshot.rear_seat_belt_buckled)
        self.assertEqual(
            needs_manual_confirmations(
                all_profiles(),
                belt_buckled=session.current_snapshot.rear_seat_belt_buckled,
            ),
            (False, False, False, False),
        )
        self.assertFalse(
            needs_manual_confirmation(
                profile_for(PassengerKind.PET),
                belt_buckled=session.current_snapshot.rear_seat_belt_buckled,
            )
        )

    def test_alighting_and_completed_pet_true_again(self):
        session = CareSession()
        snapshots = scenario_snapshots("dropoff_normal")
        for snapshot in snapshots[:5]:
            session.apply_snapshot(snapshot)
        self.assertEqual(session.state, SessionState.ALIGHTING)
        self.assertFalse(session.passenger_present)
        pet = profile_for(PassengerKind.PET)
        self.assertTrue(
            needs_manual_confirmation(
                pet,
                belt_buckled=session.current_snapshot.rear_seat_belt_buckled,
            )
        )
        session.apply_snapshot(snapshots[5])
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertTrue(
            needs_manual_confirmation(
                pet,
                belt_buckled=session.current_snapshot.rear_seat_belt_buckled,
            )
        )

    def test_session_is_profile_agnostic(self):
        sessions = []
        for _kind in PassengerKind:
            session = CareSession()
            replay_scenario(session, "dropoff_normal")
            sessions.append(session)
        base = sessions[0]
        base_history = [
            (t.from_state, t.to_state, t.reason, t.timestamp)
            for t in base.history
        ]
        for other in sessions[1:]:
            self.assertEqual(other.state, base.state)
            self.assertEqual(
                [
                    (t.from_state, t.to_state, t.reason, t.timestamp)
                    for t in other.history
                ],
                base_history,
            )
            self.assertEqual(
                report_for_session(other), report_for_session(base)
            )
            self.assertEqual(
                guidance_for_session(other, context=DestinationContext.DROPOFF),
                guidance_for_session(base, context=DestinationContext.DROPOFF),
            )

    def test_cross_reports(self):
        done = CareSession()
        replay_scenario(done, "dropoff_normal")
        report = report_for_session(done)
        self.assertTrue(report.completed)
        self.assertEqual(report.transition_count, 6)
        self.assertEqual(report.duration_seconds, 300.0)
        self.assertEqual(report.summary, "하차 확인 완료 · 예외 없음")

        stuck = CareSession()
        replay_scenario(stuck, "forgotten_rising_temp")
        report = report_for_session(stuck)
        self.assertEqual(report.exception_count, 1)
        self.assertEqual(report.max_cabin_temp_c, 35.5)
        self.assertEqual(report.summary, "예외 발생 · 하차 미확인")


if __name__ == "__main__":
    unittest.main()

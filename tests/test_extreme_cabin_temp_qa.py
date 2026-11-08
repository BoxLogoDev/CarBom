"""극단·소수 실내 온도의 안내 표기·판정 QA.

기존 안내 경계 테스트(test_guidance_boundary_qa)는 31.9/32.0/34.9/35.0
정수 경계만 다뤘다. 이 파일은 그 밖의 각도를 고정한다: 소수 온도
(32.5·34.999)의 :g 표기, 극단 고온(50·100도)에서도 dangerous 유지,
저온·영하에서는 온도 문구 없음, 온도를 보지 않는 상태
(DRIVING·ONBOARD·BOARDING·ALIGHTING·COMPLETED)의 온도 무관성,
공조(hvac) 여부와 무관한 온도 판정, 그리고 전이 스냅샷에 실린
온도는 이후 스냅샷이 식어도 리포트 최대값에 남는다는 이력성.
기대값은 작성 전 감독자 실측으로 전수 확인했다.

관측 사항: 전이를 일으키지 않은 스냅샷의 온도는 전이 이력에 남지
않아, 현재 스냅샷이 그보다 낮은 온도로 바뀌면 리포트 최대값에서
사라진다(현행 report 정의는 전이 이력 스냅샷+현재 스냅샷 기준).
이 값의 보존 여부는 리포트 의미가 바뀌는 설계 판단이라 이 파일에
기대값으로 고정하지 않고 DEVELOPMENT 제안으로 분리했다.
"""

import dataclasses
import unittest

from engine.adapters.simulator import replay, scenario_snapshots
from engine.guidance import GuidanceLevel, guidance_for, guidance_for_session
from engine.report import report_for_session
from engine.session import CareSession, SessionState
from engine.signals import SignalSnapshot


def snap(cabin_temp_c, hvac_on=False):
    return SignalSnapshot(
        rear_seat_belt_buckled=True,
        hvac_on=hvac_on,
        cabin_temp_c=cabin_temp_c,
    )


class ExtremeCabinTempQATest(unittest.TestCase):
    def test_fractional_temperatures_use_g_format_and_hot_band(self):
        arrived = guidance_for(
            SessionState.ARRIVED, snap(32.5), passenger_present=True
        )
        self.assertEqual(arrived.level, GuidanceLevel.REMIND)
        self.assertEqual(arrived.reason, "arrived_check_rear_seat_hot_cabin")
        self.assertIn("실내 온도 32.5도입니다.", arrived.text)

        arrived_edge = guidance_for(
            SessionState.ARRIVED, snap(34.999), passenger_present=True
        )
        self.assertEqual(
            arrived_edge.reason, "arrived_check_rear_seat_hot_cabin"
        )
        self.assertIn("34.999도", arrived_edge.text)

        exception = guidance_for(
            SessionState.EXCEPTION, snap(32.5), passenger_present=True
        )
        self.assertEqual(exception.level, GuidanceLevel.URGENT)
        self.assertEqual(
            exception.reason, "passenger_left_locked_hot_cabin"
        )
        self.assertIn("실내 온도 32.5도입니다.", exception.text)

    def test_extreme_high_temperatures_stay_dangerous(self):
        arrived = guidance_for(
            SessionState.ARRIVED, snap(50.0), passenger_present=True
        )
        self.assertEqual(arrived.level, GuidanceLevel.REMIND)
        self.assertEqual(
            arrived.reason, "arrived_check_rear_seat_dangerous_cabin_temp"
        )
        self.assertIn("실내 온도 50도로 높습니다.", arrived.text)
        self.assertNotIn("50.0도", arrived.text)
        self.assertIn("즉시", arrived.text)

        exception = guidance_for(
            SessionState.EXCEPTION, snap(100.0), passenger_present=True
        )
        self.assertEqual(exception.level, GuidanceLevel.URGENT)
        self.assertEqual(
            exception.reason,
            "passenger_left_locked_dangerous_cabin_temp",
        )
        self.assertIn("100도", exception.text)
        self.assertIn("위험합니다", exception.text)

    def test_cold_temperatures_have_no_temperature_wording(self):
        for temp in (-10.0, 0.0):
            with self.subTest(cabin_temp_c=temp):
                arrived = guidance_for(
                    SessionState.ARRIVED, snap(temp), passenger_present=True
                )
                self.assertEqual(arrived.reason, "arrived_check_rear_seat")
                self.assertNotIn("도입니다", arrived.text)

                exception = guidance_for(
                    SessionState.EXCEPTION,
                    snap(temp),
                    passenger_present=True,
                )
                self.assertEqual(
                    exception.reason, "passenger_left_locked"
                )
                self.assertNotIn("도입니다", exception.text)

    def test_non_temperature_states_ignore_extreme_temperature(self):
        expected = {
            SessionState.DRIVING: "driving",
            SessionState.ONBOARD: "passenger_onboard",
            SessionState.BOARDING: "boarding",
            SessionState.ALIGHTING: "alighting",
            SessionState.COMPLETED: "completed",
        }
        for state, reason in expected.items():
            with self.subTest(state=state):
                guidance = guidance_for(
                    state, snap(50.0), passenger_present=True
                )
                self.assertEqual(guidance.level, GuidanceLevel.INFO)
                self.assertEqual(guidance.reason, reason)
                self.assertNotIn("50", guidance.text)

    def test_hvac_does_not_change_temperature_judgement(self):
        for hvac_on in (True, False):
            with self.subTest(hvac_on=hvac_on):
                arrived = guidance_for(
                    SessionState.ARRIVED,
                    snap(50.0, hvac_on=hvac_on),
                    passenger_present=True,
                )
                self.assertEqual(
                    arrived.reason,
                    "arrived_check_rear_seat_dangerous_cabin_temp",
                )
                exception = guidance_for(
                    SessionState.EXCEPTION,
                    snap(50.0, hvac_on=hvac_on),
                    passenger_present=True,
                )
                self.assertEqual(
                    exception.reason,
                    "passenger_left_locked_dangerous_cabin_temp",
                )

    def test_report_max_temperature_survives_cooling_after_transition(self):
        session = CareSession()
        replay(session, scenario_snapshots("forgotten_rising_temp"))
        self.assertIs(session.state, SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)

        # 전이 없는 고온 스냅샷은 현재 스냅샷으로 최대값에 반영된다.
        hot = dataclasses.replace(
            session.current_snapshot, cabin_temp_c=50.0, timestamp=999.0
        )
        self.assertIs(session.apply_snapshot(hot), SessionState.EXCEPTION)
        self.assertEqual(len(session.history), 5)
        self.assertEqual(report_for_session(session).max_cabin_temp_c, 50.0)
        self.assertEqual(
            guidance_for_session(session).reason,
            "passenger_left_locked_dangerous_cabin_temp",
        )

        # 뒷문을 여는 전이에 실린 50.0도는 전이 이력에 남는다.
        from engine.signals import DoorState

        opened = dataclasses.replace(
            hot, rear_door=DoorState.OPEN, timestamp=1000.0
        )
        self.assertIs(session.apply_snapshot(opened), SessionState.ALIGHTING)

        # 이후 -10.0도로 식고 하차가 끝나도 최대값은 50.0으로 유지된다.
        cooled = dataclasses.replace(
            opened, rear_seat_belt_buckled=False, cabin_temp_c=-10.0,
            timestamp=1060.0,
        )
        self.assertIs(session.apply_snapshot(cooled), SessionState.ALIGHTING)
        closed = dataclasses.replace(
            cooled, rear_door=DoorState.CLOSED, timestamp=1120.0
        )
        self.assertIs(session.apply_snapshot(closed), SessionState.COMPLETED)
        report = report_for_session(session)
        self.assertEqual(report.transition_count, 7)
        self.assertEqual(report.max_cabin_temp_c, 50.0)
        self.assertEqual(report.summary, "예외 발생 후 하차 확인 완료")


if __name__ == "__main__":
    unittest.main()

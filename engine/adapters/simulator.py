"""시뮬레이션 신호 어댑터.

엔진은 신호가 어디서 오는지 모른다.
이 어댑터는 고정 시나리오의 SignalSnapshot 시퀀스를 제공한다.
호출자는 시퀀스를 순서대로 CareSession에 적용해 시나리오를 재현한다.
실 SDK 어댑터로 바꿔도 세션 로직은 그대로 간다.
"""

from __future__ import annotations

from collections.abc import Iterable

from engine.session import CareSession, SessionState
from engine.signals import DoorState, IgnitionState, LockState, SignalSnapshot

SCENARIO_NAMES: tuple[str, ...] = (
    "dropoff_normal",
    "forgotten_rising_temp",
    "pet_dropoff",
)

__all__ = [
    "SCENARIO_NAMES",
    "dropoff_normal_snapshots",
    "forgotten_rising_temp_snapshots",
    "pet_dropoff_snapshots",
    "replay",
    "replay_scenario",
    "scenario_snapshots",
]


def dropoff_normal_snapshots(
    start: float = 0.0,
) -> tuple[SignalSnapshot, ...]:
    """등원 정상 흐름 6단계 스냅샷을 돌려준다.

    순서대로 적용하면 IDLE에서 BOARDING, ONBOARD, DRIVING, ARRIVED,
    ALIGHTING을 거쳐 COMPLETED가 된다.
    타임스탬프는 start부터 60초 간격으로 증가한다.
    """
    return (
        SignalSnapshot(rear_door=DoorState.OPEN, timestamp=start),
        SignalSnapshot(rear_seat_belt_buckled=True, timestamp=start + 60.0),
        SignalSnapshot(
            rear_seat_belt_buckled=True,
            ignition=IgnitionState.ON,
            timestamp=start + 120.0,
        ),
        SignalSnapshot(rear_seat_belt_buckled=True, timestamp=start + 180.0),
        SignalSnapshot(rear_door=DoorState.OPEN, timestamp=start + 240.0),
        SignalSnapshot(timestamp=start + 300.0),
    )


def forgotten_rising_temp_snapshots(
    start: float = 0.0,
) -> tuple[SignalSnapshot, ...]:
    """하차 깜빡 예외 흐름 스냅샷을 돌려준다.

    승차와 주행과 도착까지는 정상 흐름 앞부분과 같다.
    그 뒤 벨트 체결+잠금으로 EXCEPTION에 진입한다.
    이어서 공조 OFF 상태로 실내 온도가 28.0, 32.0, 35.5도로 오른다.
    적용 후 최종 상태는 EXCEPTION이고 동승자는 남아 있다.
    타임스탬프는 start부터 60초 간격으로 증가한다.
    """
    prefix = dropoff_normal_snapshots(start)[:4]
    return prefix + (
        SignalSnapshot(
            rear_seat_belt_buckled=True,
            lock=LockState.LOCKED,
            timestamp=start + 240.0,
        ),
        SignalSnapshot(
            rear_seat_belt_buckled=True,
            lock=LockState.LOCKED,
            hvac_on=False,
            cabin_temp_c=28.0,
            timestamp=start + 300.0,
        ),
        SignalSnapshot(
            rear_seat_belt_buckled=True,
            lock=LockState.LOCKED,
            hvac_on=False,
            cabin_temp_c=32.0,
            timestamp=start + 360.0,
        ),
        SignalSnapshot(
            rear_seat_belt_buckled=True,
            lock=LockState.LOCKED,
            hvac_on=False,
            cabin_temp_c=35.5,
            timestamp=start + 420.0,
        ),
    )


def pet_dropoff_snapshots(
    start: float = 0.0,
) -> tuple[SignalSnapshot, ...]:
    """반려동물 변형 정상 흐름 스냅샷을 돌려준다.

    전제: 반려동물 이동장이 후석 안전벨트로 고정된 경우를 현행 동승자
    판정(벨트 체결 시 동승자 있음)으로 모델링한다.
    주행 중에는 동승 중인 반려동물을 위해 공조를 켠 상태를 유지한다.
    순서대로 적용하면 IDLE에서 BOARDING, ONBOARD, DRIVING, ARRIVED,
    ALIGHTING을 거쳐 COMPLETED가 된다.
    타임스탬프는 start부터 60초 간격으로 증가한다.
    """
    return (
        SignalSnapshot(rear_door=DoorState.OPEN, timestamp=start),
        SignalSnapshot(rear_seat_belt_buckled=True, timestamp=start + 60.0),
        SignalSnapshot(
            rear_seat_belt_buckled=True,
            ignition=IgnitionState.ON,
            hvac_on=True,
            timestamp=start + 120.0,
        ),
        SignalSnapshot(rear_seat_belt_buckled=True, timestamp=start + 180.0),
        SignalSnapshot(rear_door=DoorState.OPEN, timestamp=start + 240.0),
        SignalSnapshot(timestamp=start + 300.0),
    )


def scenario_snapshots(
    name: str, start: float = 0.0
) -> tuple[SignalSnapshot, ...]:
    """이름으로 시나리오 스냅샷 시퀀스를 돌려준다.

    Raises:
        ValueError: 알 수 없는 시나리오 이름이면 낸다.
    """
    if name == "dropoff_normal":
        return dropoff_normal_snapshots(start)
    if name == "forgotten_rising_temp":
        return forgotten_rising_temp_snapshots(start)
    if name == "pet_dropoff":
        return pet_dropoff_snapshots(start)
    raise ValueError(f"알 수 없는 시나리오 이름이다: {name}")


def replay(
    session: CareSession, snapshots: Iterable[SignalSnapshot]
) -> SessionState:
    """스냅샷을 순서대로 적용하고 최종 상태를 돌려준다."""
    state = session.state
    for snapshot in snapshots:
        state = session.apply_snapshot(snapshot)
    return state


def replay_scenario(
    session: CareSession, name: str, start: float = 0.0
) -> SessionState:
    """이름으로 시나리오를 조회해 세션에 재생하고 최종 상태를 돌려준다.

    VehicleSdkAdapter.poll_into와 짝을 이루는 시뮬레이터 쪽 편의 경로로,
    scenario_snapshots(name, start)를 replay(session, ...)에 넘긴 것과 같다.

    Raises:
        ValueError: 알 수 없는 시나리오 이름이면 낸다.
            조회가 먼저 실패하므로 세션은 변경되지 않는다.
    """
    return replay(session, scenario_snapshots(name, start))

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
    "replay_scenarios",
    "replay_scenarios_by_name",
    "replay_scenarios_by_start",
    "replay_scenarios_by_name_and_start",
    "replay_snapshot_sequences_for_sessions",
    "scenario_snapshots",
    "snapshots_for_scenarios",
    "snapshots_for_scenarios_by_start",
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


def snapshots_for_scenarios(
    names: Iterable[str], start: float = 0.0
) -> tuple[tuple[SignalSnapshot, ...], ...]:
    """여러 시나리오의 스냅샷 시퀀스를 입력 순서대로 돌려준다.

    names의 각 이름에 scenario_snapshots(name, start)를 적용한 결과들을
    하나의 tuple로 묶는다. start는 모든 시나리오에 동일하게 전달된다.
    빈 입력이면 빈 tuple을 돌려준다. 중복 이름은 중복 그대로 유지한다.

    Raises:
        ValueError: 알 수 없는 시나리오 이름이 있으면 낸다.
            부분 결과는 돌려주지 않는다.
    """
    return tuple(scenario_snapshots(name, start) for name in names)


def snapshots_for_scenarios_by_start(
    names: Iterable[str], starts: Iterable[float]
) -> tuple[tuple[SignalSnapshot, ...], ...]:
    """여러 시나리오의 스냅샷 시퀀스를 시나리오마다 다른 시작 시각으로 돌려준다.

    names와 starts를 입력 순서대로 짝지어, 각 이름에 대응하는 시작 시각으로
    scenario_snapshots(name, start)를 적용한 결과들을 하나의 tuple로 묶는다.
    빈 입력(둘 다 빈 경우)이면 빈 tuple이다. 중복은 중복 그대로 유지한다.
    snapshots_for_scenarios(같은 start를 모든 시나리오에 전달)와 짝을 이루는,
    시나리오마다 다른 시작 시각을 전달하는 경로다.

    Raises:
        ValueError: names와 starts의 길이가 다르면 낸다.
            부분 결과는 돌려주지 않는다.
        ValueError: 알 수 없는 시나리오 이름이 있으면 낸다.
            부분 결과는 돌려주지 않는다.
    """
    names_tuple = tuple(names)
    starts_tuple = tuple(starts)
    if len(names_tuple) != len(starts_tuple):
        raise ValueError(
            "시나리오 이름 수와 시작 시각 수가 다릅니다: "
            f"{len(names_tuple)} != {len(starts_tuple)}"
        )
    return tuple(
        scenario_snapshots(name, start)
        for name, start in zip(names_tuple, starts_tuple)
    )


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


def replay_scenarios(
    sessions: Iterable[CareSession], name: str, start: float = 0.0
) -> tuple[SessionState, ...]:
    """여러 세션에 같은 시나리오를 재생하고 최종 상태들을 돌려준다.

    sessions를 입력 순서대로 읽어 각 세션에 scenario_snapshots(name, start)를
    재생하고 최종 상태들을 tuple로 묶는다. 빈 입력이면 빈 tuple이다.

    Raises:
        ValueError: 알 수 없는 시나리오 이름이면 낸다.
            조회가 먼저 실패하므로 어떤 세션도 변경되지 않는다.
    """
    snapshots = scenario_snapshots(name, start)
    return tuple(replay(session, snapshots) for session in sessions)


def replay_scenarios_by_start(
    sessions: Iterable[CareSession],
    name: str,
    starts: Iterable[float],
) -> tuple[SessionState, ...]:
    """여러 세션에 같은 시나리오를 세션마다 다른 시작 시각으로 재생한다.

    sessions와 starts를 입력 순서대로 짝지어, 이름이 하나인 시나리오를
    각 세션에 대응하는 시작 시각으로 재생하고 최종 상태들을 tuple로
    묶는다. 빈 입력(둘 다 빈 경우)이면 빈 tuple이다. 중복은 중복
    그대로 유지한다. replay_scenarios(같은 start를 모든 세션에 전달)의
    짝 시작시각 버전으로, replay_scenarios_by_name_and_start(세션마다
    다른 이름과 다른 start)와 달리 이름은 하나를 공유한다.

    Raises:
        ValueError: sessions와 starts의 길이가 다르면 낸다.
            어떤 세션도 변경되지 않는다.
        ValueError: 알 수 없는 시나리오 이름이면 낸다.
            모든 스냅샷을 적용 전에 먼저 조회하므로 어떤 세션도
            변경되지 않는다.
    """
    sessions_tuple = tuple(sessions)
    starts_tuple = tuple(starts)
    if len(sessions_tuple) != len(starts_tuple):
        raise ValueError(
            "세션 수와 시작 시각 수가 다릅니다: "
            f"{len(sessions_tuple)} != {len(starts_tuple)}"
        )
    snapshots_list = snapshots_for_scenarios_by_start(
        (name,) * len(sessions_tuple), starts_tuple
    )
    return tuple(
        replay(session, snapshots)
        for session, snapshots in zip(sessions_tuple, snapshots_list)
    )


def replay_scenarios_by_name(
    sessions: Iterable[CareSession],
    names: Iterable[str],
    start: float = 0.0,
) -> tuple[SessionState, ...]:
    """세션마다 다른 시나리오를 짝지어 재생하고 최종 상태들을 돌려준다.

    sessions와 names를 입력 순서대로 짝지어, 각 세션에 대응하는 이름의
    시나리오를 재생하고 최종 상태들을 tuple로 묶는다. 빈 입력(둘 다 빈
    경우)이면 빈 tuple이다. 중복은 중복 그대로 유지하고, start는 모든
    시나리오에 동일하게 전달된다. replay_scenarios(같은 시나리오를 여러
    세션에 재생)와 짝을 이루는, 세션마다 다른 시나리오를 재생하는 경로다.

    Raises:
        ValueError: sessions와 names의 길이가 다르면 낸다.
            어떤 세션도 변경되지 않는다.
        ValueError: 알 수 없는 시나리오 이름이 있으면 낸다.
            모든 스냅샷을 적용 전에 먼저 조회하므로 어떤 세션도
            변경되지 않는다.
    """
    sessions_tuple = tuple(sessions)
    names_tuple = tuple(names)
    if len(sessions_tuple) != len(names_tuple):
        raise ValueError(
            "세션 수와 시나리오 이름 수가 다릅니다: "
            f"{len(sessions_tuple)} != {len(names_tuple)}"
        )
    snapshots_list = snapshots_for_scenarios(names_tuple, start)
    return tuple(
        replay(session, snapshots)
        for session, snapshots in zip(sessions_tuple, snapshots_list)
    )


def replay_scenarios_by_name_and_start(
    sessions: Iterable[CareSession],
    names: Iterable[str],
    starts: Iterable[float],
) -> tuple[SessionState, ...]:
    """세션마다 다른 시나리오를 다른 시작 시각으로 짝지어 재생한다.

    sessions와 names와 starts를 입력 순서대로 짝지어, 각 세션에 대응하는
    이름의 시나리오를 대응하는 시작 시각으로 재생하고 최종 상태들을
    tuple로 묶는다. 빈 입력(셋 다 빈 경우)이면 빈 tuple이다. 중복은
    중복 그대로 유지한다. replay_scenarios_by_name(같은 start를 모든
    시나리오에 전달)의 짝 시작시각 버전으로, 시나리오마다 다른 시작
    시각을 전달하는 경로다.

    Raises:
        ValueError: sessions와 names와 starts의 길이가 다르면 낸다.
            어떤 세션도 변경되지 않는다.
        ValueError: 알 수 없는 시나리오 이름이 있으면 낸다.
            모든 스냅샷을 적용 전에 먼저 조회하므로 어떤 세션도
            변경되지 않는다.
    """
    sessions_tuple = tuple(sessions)
    names_tuple = tuple(names)
    starts_tuple = tuple(starts)
    if not (len(sessions_tuple) == len(names_tuple) == len(starts_tuple)):
        raise ValueError(
            "세션 수와 시나리오 이름 수와 시작 시각 수가 다릅니다: "
            f"{len(sessions_tuple)} != {len(names_tuple)} != "
            f"{len(starts_tuple)}"
        )
    snapshots_list = snapshots_for_scenarios_by_start(
        names_tuple, starts_tuple
    )
    return tuple(
        replay(session, snapshots)
        for session, snapshots in zip(sessions_tuple, snapshots_list)
    )


def replay_snapshot_sequences_for_sessions(
    sessions: Iterable[CareSession],
    snapshot_sequences: Iterable[Iterable[SignalSnapshot]],
) -> tuple[SessionState, ...]:
    """세션마다 다른 스냅샷 시퀀스를 짝지어 재생하고 최종 상태들을 돌려준다.

    sessions와 snapshot_sequences를 입력 순서대로 짝지어, 각 세션에
    대응하는 시퀀스를 replay로 적용하고 최종 상태들을 tuple로 묶는다.
    Vehicle SDK 쪽 apply_raw_sequences_for_sessions(세션마다 다른 raw
    시퀀스를 짝지어 적용)와 짝을 이루는 시뮬레이터 쪽 경로이며,
    replay_scenarios_by_name(이름으로 조회한 시나리오를 짝지어 재생)과
    달리 스냅샷 시퀀스를 직접 짝지어 재생한다.
    sessions와 snapshot_sequences를 먼저 각각 tuple로 구체화하고, 각
    내부 시퀀스도 적용 전에 tuple로 구체화한다. 그래서 제너레이터
    입력도 리스트 입력과 같게 동작한다.
    빈 입력(둘 다 빈 경우)이면 빈 tuple이다. 내부 시퀀스가 빈 세션은
    변경하지 않고 현재 상태를 돌려준다. 중복은 중복 그대로 유지한다.

    Raises:
        ValueError: sessions와 snapshot_sequences의 길이가 다르면 낸다.
            길이 검사와 구체화가 모든 적용보다 먼저 끝나므로
            어떤 세션도 변경되지 않는다.
    """
    sessions_tuple = tuple(sessions)
    sequences_tuple = tuple(
        tuple(sequence) for sequence in snapshot_sequences
    )
    if len(sessions_tuple) != len(sequences_tuple):
        raise ValueError(
            "세션 수와 스냅샷 시퀀스 수가 다릅니다: "
            f"{len(sessions_tuple)} != {len(sequences_tuple)}"
        )
    return tuple(
        replay(session, snapshots)
        for session, snapshots in zip(sessions_tuple, sequences_tuple)
    )

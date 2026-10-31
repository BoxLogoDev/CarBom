"""Pleos Vehicle SDK 어댑터의 인터페이스와 변환층.

아직 실제 Pleos Vehicle SDK는 이 환경에 연동되지 않았다.
이 모듈은 실 SDK가 붙을 자리를 미리 정해 두는 인터페이스와,
SDK 쪽 원시 신호(dict)를 엔진의 SignalSnapshot으로 바꾸는 변환층만
제공한다. 실차량 연결을 주장하지 않는다.

호출자는 read_raw() 메서드를 가진 SDK 클라이언트 객체를 주입한다.
클라이언트가 없으면 poll()은 NotImplementedError를 내며,
엔진은 그 전까지 시뮬레이션 어댑터(simulator.py)의 신호를 쓴다.
실 SDK 어댑터로 바꿔도 세션 로직은 그대로 간다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from engine.signals import DoorState, IgnitionState, LockState, SignalSnapshot

if TYPE_CHECKING:
    from engine.session import CareSession, SessionState

__all__ = [
    "VehicleSdkAdapter",
    "apply_raw",
    "apply_raw_for_sessions",
    "apply_raws",
    "apply_raws_paired_for_sessions",
    "apply_raws_for_sessions",
    "apply_raw_sequences_for_sessions",
    "poll_into_sessions",
    "poll_paired_into_sessions",
    "poll_repeatedly_into_sessions",
    "poll_repeatedly_into_sessions_by_times",
    "poll_repeatedly_paired_into_sessions",
    "poll_snapshots",
    "poll_snapshots_by_times",
    "poll_snapshots_paired",
    "raw_from_snapshot",
    "raws_from_snapshots",
    "snapshot_from_raw",
    "snapshots_from_raws",
]


def snapshot_from_raw(raw: Mapping[str, Any]) -> SignalSnapshot:
    """원시 신호 dict를 SignalSnapshot으로 바꾼다.

    모든 키는 선택이며, 없는 키는 SignalSnapshot 기본값을 쓴다.
    모르는 키는 무시한다.

    Keys:
        rear_door_open: 뒷문이 열렸으면 True.
        rear_seat_belt_buckled: 후석 벨트가 체결됐으면 True.
        ignition_on: 시동이 켜졌으면 True.
        locked: 차량이 잠겼으면 True.
        hvac_on: 공조가 켜졌으면 True.
        cabin_temp_c: 실내 온도(섭씨). 모르면 None.
        timestamp: 신호 시각(epoch 초). 모르면 None.
    """
    return SignalSnapshot(
        rear_door=(
            DoorState.OPEN if raw.get("rear_door_open") else DoorState.CLOSED
        ),
        rear_seat_belt_buckled=bool(raw.get("rear_seat_belt_buckled", False)),
        ignition=(
            IgnitionState.ON if raw.get("ignition_on") else IgnitionState.OFF
        ),
        hvac_on=bool(raw.get("hvac_on", False)),
        cabin_temp_c=raw.get("cabin_temp_c"),
        lock=LockState.LOCKED if raw.get("locked") else LockState.UNLOCKED,
        timestamp=raw.get("timestamp"),
    )


def raw_from_snapshot(snapshot: SignalSnapshot) -> dict:
    """SignalSnapshot을 원시 신호 dict로 바꾼다.

    snapshot_from_raw의 정확한 역변환이다.
    7개 키를 항상 모두 포함한다.
    """
    return {
        "rear_door_open": bool(snapshot.rear_door_open),
        "rear_seat_belt_buckled": bool(snapshot.rear_seat_belt_buckled),
        "ignition_on": bool(snapshot.ignition_on),
        "locked": bool(snapshot.locked),
        "hvac_on": bool(snapshot.hvac_on),
        "cabin_temp_c": snapshot.cabin_temp_c,
        "timestamp": snapshot.timestamp,
    }


def snapshots_from_raws(
    raws: Iterable[Mapping[str, Any]],
) -> tuple[SignalSnapshot, ...]:
    """원시 신호 dict 시퀀스를 SignalSnapshot tuple로 바꾼다.

    snapshot_from_raw의 대량 변환이다.
    입력 순서를 그대로 유지하고, 빈 입력이면 빈 tuple을 돌려준다.
    """
    return tuple(snapshot_from_raw(raw) for raw in raws)


def raws_from_snapshots(
    snapshots: Iterable[SignalSnapshot],
) -> tuple[dict, ...]:
    """SignalSnapshot 시퀀스를 원시 신호 dict tuple로 바꾼다.

    raw_from_snapshot의 대량 변환이며 snapshots_from_raws의 역변환이다.
    입력 순서를 그대로 유지하고, 빈 입력이면 빈 tuple을 돌려준다.
    """
    return tuple(raw_from_snapshot(snapshot) for snapshot in snapshots)


def apply_raw(
    session: CareSession, raw: Mapping[str, Any]
) -> SessionState:
    """원시 신호 dict를 스냅샷으로 바꿔 세션에 적용하고 세션 상태를 돌려준다.

    snapshot_from_raw(raw)를 session.apply_snapshot(...)에 넘긴 것과 같다.
    SDK 클라이언트 없이도 raw를 세션에 바로 넣을 수 있는 직접 경로이다.
    """
    return session.apply_snapshot(snapshot_from_raw(raw))


def apply_raw_for_sessions(
    sessions: Iterable[CareSession], raw: Mapping[str, Any]
) -> tuple[SessionState, ...]:
    """원시 신호 dict 하나를 여러 세션에 적용하고 상태들을 돌려준다.

    apply_raw의 다중 세션 버전이다.
    poll_into_sessions(신호를 한 번 읽어 여러 세션에 같은 스냅샷을
    적용)의 raw 쪽 짝이다.
    raw를 snapshot_from_raw로 딱 한 번만 변환하고, 그 같은
    SignalSnapshot을 각 세션에 입력 순서대로 적용한다.
    sessions를 입력 순서대로 읽고 반환된 상태들을 입력 순서대로 묶는다.
    빈 sessions이면 빈 tuple을 돌려준다.
    """
    snapshot = snapshot_from_raw(raw)
    return tuple(session.apply_snapshot(snapshot) for session in sessions)


def apply_raws(
    session: CareSession, raws: Iterable[Mapping[str, Any]]
) -> SessionState:
    """원시 신호 dict를 순서대로 세션에 적용하고 최종 상태를 돌려준다.

    apply_raw의 대량 적용이다.
    빈 입력이면 세션을 변경하지 않고 현재 상태를 그대로 돌려준다.
    """
    state = session.state
    for raw in raws:
        state = apply_raw(session, raw)
    return state


def apply_raws_paired_for_sessions(
    sessions: Iterable[CareSession],
    raws: Iterable[Mapping[str, Any]],
) -> tuple[SessionState, ...]:
    """세션마다 다른 원시 신호 dict 1건을 짝지어 적용하고 상태들을 돌려준다.

    sessions와 raws를 입력 순서대로 짝지어, 각 세션에 대응하는 raw 1건을
    apply_raw로 적용하고 반환된 SessionState들을 tuple로 묶는다.
    apply_raw_for_sessions(같은 raw 1건을 모든 세션에 적용)의 짝 버전으로,
    세션마다 다른 raw를 적용하는 경로이며, simulator의
    replay_snapshots_for_sessions(세션마다 다른 스냅샷 1건을 적용)와
    짝을 이룬다.
    sessions와 raws를 먼저 각각 tuple로 구체화하므로 제너레이터 입력도
    리스트 입력과 같게 동작한다.
    빈 입력(둘 다 빈 경우)이면 빈 tuple이다. 중복은 중복 그대로 유지한다.

    Raises:
        ValueError: sessions와 raws의 길이가 다르면 낸다.
            길이 검사가 모든 적용보다 먼저 끝나므로
            어떤 세션도 변경되지 않는다.
    """
    sessions_tuple = tuple(sessions)
    raws_tuple = tuple(raws)
    if len(sessions_tuple) != len(raws_tuple):
        raise ValueError(
            "세션 수와 원시 신호 수가 다릅니다: "
            f"{len(sessions_tuple)} != {len(raws_tuple)}"
        )
    return tuple(
        apply_raw(session, raw)
        for session, raw in zip(sessions_tuple, raws_tuple)
    )


def apply_raws_for_sessions(
    sessions: Iterable[CareSession],
    raws: Iterable[Mapping[str, Any]],
) -> tuple[SessionState, ...]:
    """여러 세션에 같은 원시 신호 시퀀스를 적용하고 최종 상태들을 돌려준다.

    apply_raws의 다중 세션 버전이다.
    simulator.replay_scenarios와 짝을 이루는 SDK 쪽 편의 경로이다.
    raws를 함수 시작 시 한 번만 tuple로 구체화한다.
    그래서 제너레이터 raws도 모든 세션에 같은 시퀀스로 재사용된다.
    sessions를 입력 순서대로 읽고 최종 상태들을 입력 순서대로 묶는다.
    빈 sessions이면 빈 tuple을 돌려준다.
    빈 raws이면 각 세션을 변경하지 않고 현재 상태들을 돌려준다.
    """
    materialized = tuple(raws)
    return tuple(apply_raws(session, materialized) for session in sessions)


def apply_raw_sequences_for_sessions(
    sessions: Iterable[CareSession],
    raw_sequences: Iterable[Iterable[Mapping[str, Any]]],
) -> tuple[SessionState, ...]:
    """세션마다 다른 원시 신호 시퀀스를 짝지어 적용하고 최종 상태들을 돌려준다.

    sessions와 raw_sequences를 입력 순서대로 짝지어, 각 세션에 대응하는
    시퀀스를 apply_raws로 적용하고 최종 상태들을 tuple로 묶는다.
    apply_raws_for_sessions(같은 시퀀스를 모든 세션에 적용)와 짝을 이루는,
    세션마다 다른 시퀀스를 적용하는 경로이며, simulator의
    replay_scenarios_by_name과 짝을 이룬다.
    sessions와 raw_sequences를 먼저 각각 tuple로 구체화하고, 각 내부
    시퀀스도 적용 전에 tuple로 구체화한다. 그래서 제너레이터 입력도
    리스트 입력과 같게 동작한다.
    빈 입력(둘 다 빈 경우)이면 빈 tuple을 돌려준다.
    내부 시퀀스가 빈 세션은 변경하지 않고 현재 상태를 돌려준다.
    중복은 중복 그대로 유지한다.

    Raises:
        ValueError: sessions와 raw_sequences의 길이가 다르면 낸다.
            길이 검사와 구체화가 모든 적용보다 먼저 끝나므로
            어떤 세션도 변경되지 않는다.
    """
    sessions_tuple = tuple(sessions)
    sequences_tuple = tuple(tuple(sequence) for sequence in raw_sequences)
    if len(sessions_tuple) != len(sequences_tuple):
        raise ValueError(
            "세션 수와 원시 신호 시퀀스 수가 다릅니다: "
            f"{len(sessions_tuple)} != {len(sequences_tuple)}"
        )
    return tuple(
        apply_raws(session, sequence)
        for session, sequence in zip(sessions_tuple, sequences_tuple)
    )


class VehicleSdkAdapter:
    """주입된 SDK 클라이언트에서 신호를 읽어 스냅샷으로 돌려주는 어댑터.

    클라이언트는 read_raw() -> Mapping 메서드를 가진 객체로 가정한다.
    클라이언트가 주입되지 않은 상태는 아직 실 SDK가 연결되지 않은
    상태이며, 이때 poll()은 변환을 시도하지 않고 명시적으로 실패한다.
    """

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    @property
    def is_connected(self) -> bool:
        """SDK 클라이언트가 주입됐으면 True를 돌려준다."""
        return self._client is not None

    def poll(self) -> SignalSnapshot:
        """현재 차량 신호를 한 번 읽어 스냅샷으로 돌려준다.

        Raises:
            NotImplementedError: SDK 클라이언트가 연결되지 않았으면 낸다.
        """
        if self._client is None:
            raise NotImplementedError(
                "실 SDK 클라이언트가 연결되지 않았습니다. "
                "Pleos Vehicle SDK 연동은 아직 구현되지 않았으며, "
                "지금은 시뮬레이션 어댑터를 사용하십시오."
            )
        return snapshot_from_raw(self._client.read_raw())

    def poll_into(self, session: CareSession) -> SessionState:
        """현재 차량 신호를 한 번 읽어 세션에 적용하고 세션 상태를 돌려준다.

        Raises:
            NotImplementedError: SDK 클라이언트가 연결되지 않았으면 낸다.
                이때 poll()이 먼저 실패하므로 세션은 변경되지 않는다.
        """
        return session.apply_snapshot(self.poll())

    def poll_repeatedly_into(
        self, session: CareSession, times: int
    ) -> SessionState:
        """현재 차량 신호를 times번 반복해서 읽어 세션에 적용하고 최종 상태를 돌려준다.

        poll_into의 반복 적용이다.
        simulator의 replay, raw 쪽 apply_raws와 짝을 이루는 poll 쪽
        반복 적용 경로이다.
        times가 0이면 poll()을 한 번도 호출하지 않고 현재 상태를
        그대로 돌려주므로, 클라이언트 미연결 어댑터에서도 예외가 나지
        않는다.

        Raises:
            ValueError: times가 음수이면 낸다.
                poll()을 호출하지 않고 세션도 변경하지 않는다.
            NotImplementedError: SDK 클라이언트가 연결되지 않았고
                times가 양수이면 첫 poll()에서 낸다.
                이때 세션은 변경되지 않는다.
        """
        if times < 0:
            raise ValueError(f"times는 0 이상이어야 한다: {times}")
        state = session.state
        for _ in range(times):
            state = self.poll_into(session)
        return state


def poll_into_sessions(
    adapter: VehicleSdkAdapter,
    sessions: Iterable[CareSession],
) -> tuple[SessionState, ...]:
    """신호를 한 번 읽어 여러 세션에 같은 스냅샷을 적용하고 상태들을 돌려준다.

    VehicleSdkAdapter.poll_into의 다중 세션 버전이다.
    sessions를 먼저 tuple로 구체화한다.
    빈 sessions이면 poll()을 호출하지 않고 빈 tuple을 돌려준다.
    비어 있지 않으면 adapter.poll()을 정확히 1회만 호출해 스냅샷 1건을
    얻고, 그 스냅샷을 각 세션에 입력 순서대로 적용한다.
    미연결 어댑터이면 poll()의 NotImplementedError가 먼저 전파되므로
    어떤 세션도 변경되지 않는다.
    """
    materialized = tuple(sessions)
    if not materialized:
        return ()
    snapshot = adapter.poll()
    return tuple(session.apply_snapshot(snapshot) for session in materialized)


def poll_paired_into_sessions(
    adapters: Iterable[VehicleSdkAdapter],
    sessions: Iterable[CareSession],
) -> tuple[SessionState, ...]:
    """어댑터마다 한 번씩 읽어 짝지어진 세션에 적용하고 상태들을 돌려준다.

    adapters와 sessions를 입력 순서대로 짝지어, 각 어댑터의
    poll_into를 대응하는 세션에 적용하고 반환된 SessionState들을
    tuple로 묶는다.
    apply_raws_paired_for_sessions(세션마다 다른 raw 1건을 적용)의
    poll 쪽 짝으로, 세션마다 다른 어댑터(다른 차량 신호원)를 읽는
    경로이며, poll_into_sessions(한 어댑터의 스냅샷 1건을 모든
    세션에 적용)와 달리 어댑터마다 poll이 따로 일어난다.
    adapters와 sessions를 먼저 각각 tuple로 구체화하므로
    제너레이터 입력도 리스트 입력과 같게 동작한다.
    빈 입력(둘 다 빈 경우)이면 poll을 한 번도 호출하지 않고
    빈 tuple이다. 중복은 중복 그대로 유지한다.

    Raises:
        ValueError: adapters와 sessions의 길이가 다르면 낸다.
            길이 검사가 모든 poll보다 먼저 끝나므로 어떤 어댑터의
            poll도 호출되지 않고 어떤 세션도 변경되지 않는다.
    """
    adapters_tuple = tuple(adapters)
    sessions_tuple = tuple(sessions)
    if len(adapters_tuple) != len(sessions_tuple):
        raise ValueError(
            "어댑터 수와 세션 수가 다릅니다: "
            f"{len(adapters_tuple)} != {len(sessions_tuple)}"
        )
    return tuple(
        adapter.poll_into(session)
        for adapter, session in zip(adapters_tuple, sessions_tuple)
    )


def poll_repeatedly_into_sessions(
    adapter: VehicleSdkAdapter,
    sessions: Iterable[CareSession],
    times: int,
) -> tuple[SessionState, ...]:
    """신호를 times번 읽어 그 시퀀스를 여러 세션 각각에 적용하고 상태들을 돌려준다.

    VehicleSdkAdapter.poll_repeatedly_into의 다중 세션 버전이며
    poll_into_sessions의 반복 버전이다.
    apply_raws_for_sessions와 짝을 이루는 poll 쪽 다중 세션 반복 경로이다.
    sessions를 먼저 tuple로 구체화한다.
    세션이 비어 있거나 times가 0이면 poll()을 한 번도 호출하지 않고
    각 세션의 현재 상태들을 입력 순서대로 돌려주므로, 클라이언트
    미연결 어댑터에서도 예외가 나지 않는다(빈 sessions이면 빈 tuple).
    비어 있지 않고 times가 양수이면 adapter.poll()을 정확히 times번만
    호출해 스냅샷 시퀀스를 먼저 모두 모은 뒤, 그 시퀀스를 각 세션에
    순서대로 적용한다. 따라서 모든 세션이 같은 스냅샷 시퀀스를 받고,
    poll 횟수는 세션 수가 아니라 times와 같다.

    Raises:
        ValueError: times가 음수이면 낸다. 빈 sessions인 경우에도
            이 검사가 먼저 적용되며, poll()을 호출하지 않고
            어떤 세션도 변경하지 않는다.
        NotImplementedError: SDK 클라이언트가 연결되지 않았고
            times가 양수이며 sessions가 비어 있지 않으면 첫 poll()에서
            낸다. 스냅샷을 모두 모은 뒤에 적용하므로 어떤 세션도
            변경되지 않는다.
    """
    if times < 0:
        raise ValueError(f"times는 0 이상이어야 한다: {times}")
    materialized = tuple(sessions)
    if not materialized or times == 0:
        return tuple(session.state for session in materialized)
    snapshots = tuple(adapter.poll() for _ in range(times))
    states: list[SessionState] = []
    for session in materialized:
        state = session.state
        for snapshot in snapshots:
            state = session.apply_snapshot(snapshot)
        states.append(state)
    return tuple(states)


def poll_repeatedly_into_sessions_by_times(
    adapter: VehicleSdkAdapter,
    sessions: Iterable[CareSession],
    times_list: Iterable[int],
) -> tuple[SessionState, ...]:
    """신호를 세션마다 다른 횟수만큼 읽어 각 세션에 적용하고 상태들을 돌려준다.

    poll_repeatedly_into_sessions의 짝 버전이다. sessions와 times_list를
    먼저 각각 tuple로 구체화하고, 입력 순서대로 짝지어 각 세션에
    자기 몫의 횟수만큼 poll한 스냅샷들을 적용한다.
    스냅샷은 적용 전에 poll()을 총합(sum(times_list))번 호출해 짝 순서대로
    모두 먼저 모으므로, 모든 세션이 연속된 poll 스트림에서 자기 몫의
    슬라이스를 순서대로 받고, poll 횟수는 세션 수가 아니라 횟수의
    총합과 같다.
    times가 0인 세션은 변경하지 않고 현재 상태를 돌려준다. sessions가
    비어 있거나 모든 times가 0이면 poll()을 한 번도 호출하지 않으므로,
    클라이언트 미연결 어댑터에서도 예외가 나지 않는다(빈 sessions이면
    빈 tuple).

    Raises:
        ValueError: sessions와 times_list의 길이가 다르면 낸다.
            poll()을 호출하지 않고 어떤 세션도 변경하지 않는다.
        ValueError: 어느 times라도 음수이면 낸다. 길이 검사가 먼저
            적용되고, poll()을 호출하지 않고 어떤 세션도 변경하지
            않는다.
        NotImplementedError: SDK 클라이언트가 연결되지 않았고 양수인
            times가 있으면 첫 poll()에서 낸다. 스냅샷을 모두 모은 뒤에
            적용하므로 어떤 세션도 변경되지 않는다.
    """
    materialized_sessions = tuple(sessions)
    materialized_times = tuple(times_list)
    if len(materialized_sessions) != len(materialized_times):
        raise ValueError(
            "세션 수와 반복 횟수 수가 다릅니다: "
            f"{len(materialized_sessions)} != {len(materialized_times)}"
        )
    for times in materialized_times:
        if times < 0:
            raise ValueError(f"times는 0 이상이어야 한다: {times}")
    total = sum(materialized_times)
    if total == 0:
        return tuple(session.state for session in materialized_sessions)
    snapshots = tuple(adapter.poll() for _ in range(total))
    states: list[SessionState] = []
    offset = 0
    for session, times in zip(materialized_sessions, materialized_times):
        state = session.state
        for snapshot in snapshots[offset : offset + times]:
            state = session.apply_snapshot(snapshot)
        states.append(state)
        offset += times
    return tuple(states)


def poll_repeatedly_paired_into_sessions(
    adapters: Iterable[VehicleSdkAdapter],
    sessions: Iterable[CareSession],
    times_list: Iterable[int],
) -> tuple[SessionState, ...]:
    """어댑터마다 다른 횟수만큼 읽어 짝지어진 세션에 적용하고 상태들을 돌려준다.

    poll_paired_into_sessions(어댑터마다 1회 poll)의 반복 버전이며
    poll_repeatedly_into_sessions_by_times(단일 어댑터, 짝 times)의
    어댑터 짝 버전이다. adapters·sessions·times_list를 입력 순서대로
    짝지어, 각 어댑터를 자기 times만큼 poll한 스냅샷들을 대응 세션에
    적용한다.
    세 입력은 먼저 각각 tuple로 구체화하므로 제너레이터 입력도
    리스트 입력과 같게 동작한다. 중복은 중복 그대로 유지하고,
    중복된 어댑터는 등장할 때마다 따로 poll한다.
    스냅샷은 적용 전에 어댑터 순서대로 모두 먼저 모으므로, 수집 중
    어느 poll이라도 실패하면 어떤 세션도 변경되지 않는다.
    times가 0인 세션은 변경하지 않고 현재 상태를 돌려준다. 모든
    times 합이 0이면 poll()을 한 번도 호출하지 않으므로, 클라이언트
    미연결 어댑터에서도 예외가 나지 않는다(빈 입력이면 빈 tuple).

    Raises:
        ValueError: adapters·sessions·times_list의 길이가 모두
            같지 않으면 낸다. 길이 검사가 모든 poll보다 먼저
            끝나므로 어떤 어댑터의 poll도 호출되지 않고 어떤
            세션도 변경되지 않는다.
        ValueError: 어느 times라도 음수이면 낸다. 길이 검사가 먼저
            적용되고, poll()을 호출하지 않고 어떤 세션도 변경하지
            않는다.
        NotImplementedError: 어느 어댑터라도 연결되지 않았고 그
            어댑터의 times가 양수이면 수집 단계의 poll()에서 낸다.
            스냅샷을 모두 모은 뒤에 적용하므로 어떤 세션도
            변경되지 않는다.
    """
    adapters_tuple = tuple(adapters)
    sessions_tuple = tuple(sessions)
    times_tuple = tuple(times_list)
    if not (
        len(adapters_tuple) == len(sessions_tuple) == len(times_tuple)
    ):
        raise ValueError(
            "어댑터 수·세션 수·반복 횟수 수가 다릅니다: "
            f"{len(adapters_tuple)} != {len(sessions_tuple)} "
            f"!= {len(times_tuple)}"
        )
    for times in times_tuple:
        if times < 0:
            raise ValueError(f"times는 0 이상이어야 한다: {times}")
    if sum(times_tuple) == 0:
        return tuple(session.state for session in sessions_tuple)
    slices = tuple(
        tuple(adapter.poll() for _ in range(times))
        for adapter, times in zip(adapters_tuple, times_tuple)
    )
    states: list[SessionState] = []
    for session, slice_snapshots in zip(sessions_tuple, slices):
        state = session.state
        for snapshot in slice_snapshots:
            state = session.apply_snapshot(snapshot)
        states.append(state)
    return tuple(states)


def poll_snapshots(
    adapter: VehicleSdkAdapter, times: int
) -> tuple[SignalSnapshot, ...]:
    """신호를 times번 읽어 스냅샷 시퀀스만 돌려준다(세션에 적용하지 않는다).

    poll_repeatedly_into·poll_repeatedly_into_sessions가 내부에서 먼저
    모으는 스냅샷 시퀀스를 읽기 전용으로 분리한 헬퍼이다.
    adapter.poll()을 정확히 times번 호출하고, 얻은 스냅샷들을 호출
    순서 그대로 tuple로 묶는다.
    times가 0이면 poll()을 한 번도 호출하지 않고 빈 tuple을 돌려주므로,
    클라이언트 미연결 어댑터에서도 예외가 나지 않는다.

    Raises:
        ValueError: times가 음수이면 낸다. 이 검사가 먼저 적용되므로
            poll()을 호출하지 않는다.
        NotImplementedError: SDK 클라이언트가 연결되지 않았고
            times가 양수이면 첫 poll()에서 낸다.
    """
    if times < 0:
        raise ValueError(f"times는 0 이상이어야 한다: {times}")
    return tuple(adapter.poll() for _ in range(times))


def poll_snapshots_by_times(
    adapter: VehicleSdkAdapter, times_list: Iterable[int]
) -> tuple[tuple[SignalSnapshot, ...], ...]:
    """신호를 항목마다 다른 횟수만큼 읽어 스냅샷 시퀀스들을 돌려준다.

    poll_snapshots의 짝 버전이며 poll_repeatedly_into_sessions_by_times가
    내부에서 먼저 모으는 스냅샷 슬라이스를 읽기 전용으로 분리한 헬퍼이다.
    세션에는 전혀 관여하지 않는다.
    times_list를 먼저 tuple로 구체화한다. 어느 times라도 음수이면
    poll()을 한 번도 호출하지 않고 ValueError를 내며, 이 검사는 미연결
    어댑터에서도 먼저 적용된다. 빈 입력이면 빈 tuple을 돌려주고 poll()을
    호출하지 않으며, 모든 times가 0이면 poll()을 호출하지 않고 0인
    개수만큼 빈 tuple들을 돌려주므로, 클라이언트 미연결 어댑터에서도
    예외가 나지 않는다. 그 외에는 adapter.poll()을 정확히
    sum(times_list)번만 호출해 모든 스냅샷을 먼저 모은 뒤, 짝 순서대로
    각 times 몫의 슬라이스를 tuple로 묶어 돌려준다. times가 0인 항목은
    빈 tuple이다.

    Raises:
        ValueError: 어느 times라도 음수이면 낸다. poll()을 호출하지
            않는다.
        NotImplementedError: SDK 클라이언트가 연결되지 않았고 양수인
            times가 있으면 첫 poll()에서 낸다.
    """
    materialized_times = tuple(times_list)
    for times in materialized_times:
        if times < 0:
            raise ValueError(f"times는 0 이상이어야 한다: {times}")
    total = sum(materialized_times)
    if total == 0:
        return tuple(() for _ in materialized_times)
    snapshots = tuple(adapter.poll() for _ in range(total))
    sequences: list[tuple[SignalSnapshot, ...]] = []
    offset = 0
    for times in materialized_times:
        sequences.append(snapshots[offset : offset + times])
        offset += times
    return tuple(sequences)


def poll_snapshots_paired(
    adapters: Iterable[VehicleSdkAdapter],
    times_list: Iterable[int],
) -> tuple[tuple[SignalSnapshot, ...], ...]:
    """어댑터마다 다른 횟수만큼 읽어 스냅샷 시퀀스들을 돌려준다.

    poll_snapshots_by_times(단일 어댑터, 짝 times)의 어댑터 짝 버전이며
    poll_repeatedly_paired_into_sessions가 내부에서 모으는 어댑터별
    스냅샷 슬라이스를 읽기 전용으로 분리한 헬퍼이다.
    세션에는 전혀 관여하지 않는다.
    adapters와 times_list를 먼저 각각 tuple로 구체화하므로
    제너레이터 입력도 리스트 입력과 같게 동작한다. 중복 어댑터는
    등장할 때마다 따로 poll한다.
    times가 0인 항목은 빈 tuple이며 그 어댑터는 poll하지 않으므로,
    클라이언트 미연결 어댑터에서도 예외가 나지 않는다. 빈 입력이면
    빈 tuple을 돌려준다.

    Raises:
        ValueError: adapters와 times_list의 길이가 다르면 낸다.
            길이 검사가 모든 poll보다 먼저 끝나므로 어떤 어댑터의
            poll도 호출되지 않는다.
        ValueError: 어느 times라도 음수이면 낸다. 길이 검사 다음에
            적용되므로 poll()을 호출하지 않으며, 미연결 어댑터에서도
            이 검사가 먼저 적용된다.
        NotImplementedError: 어느 어댑터라도 연결되지 않았고 그
            어댑터의 times가 양수이면 그 어댑터의 첫 poll()에서 낸다.
            어댑터 순서대로 poll하므로 앞선 어댑터들의 poll은 이미
            일어났을 수 있으나, 세션은 없으므로 상태 변경은 없다.
    """
    adapters_tuple = tuple(adapters)
    times_tuple = tuple(times_list)
    if len(adapters_tuple) != len(times_tuple):
        raise ValueError(
            "어댑터 수와 반복 횟수 수가 다릅니다: "
            f"{len(adapters_tuple)} != {len(times_tuple)}"
        )
    for times in times_tuple:
        if times < 0:
            raise ValueError(f"times는 0 이상이어야 한다: {times}")
    return tuple(
        tuple(adapter.poll() for _ in range(times))
        for adapter, times in zip(adapters_tuple, times_tuple)
    )

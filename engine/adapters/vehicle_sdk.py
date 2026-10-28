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
    "apply_raws",
    "apply_raws_for_sessions",
    "poll_into_sessions",
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

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

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from engine.signals import DoorState, IgnitionState, LockState, SignalSnapshot

if TYPE_CHECKING:
    from engine.session import CareSession, SessionState

__all__ = [
    "VehicleSdkAdapter",
    "raw_from_snapshot",
    "snapshot_from_raw",
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

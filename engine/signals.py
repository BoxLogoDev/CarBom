"""차량 신호 모델.

이 모듈은 플랫폼 독립적인 신호 표현만 소유한다.
신호가 시뮬레이터에서 오는지 실 SDK에서 오는지는 이 모듈이 모른다.
호출자는 어댑터에서 원본 신호를 이 모듈의 타입으로 바꿔 엔진에 넘긴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DoorState(Enum):
    """문 개폐 상태."""

    OPEN = "open"
    CLOSED = "closed"


class IgnitionState(Enum):
    """시동 상태."""

    ON = "on"
    OFF = "off"


class LockState(Enum):
    """차량 잠금 상태."""

    LOCKED = "locked"
    UNLOCKED = "unlocked"


class SignalEventType(Enum):
    """개별 신호 이벤트 종류."""

    REAR_DOOR_OPENED = "rear_door_opened"
    REAR_DOOR_CLOSED = "rear_door_closed"
    REAR_BELT_BUCKLED = "rear_belt_buckled"
    REAR_BELT_UNBUCKLED = "rear_belt_unbuckled"
    IGNITION_ON = "ignition_on"
    IGNITION_OFF = "ignition_off"
    LOCKED = "locked"
    UNLOCKED = "unlocked"
    HVAC_ON = "hvac_on"
    HVAC_OFF = "hvac_off"
    CABIN_TEMP_CHANGED = "cabin_temp_changed"


@dataclass(frozen=True)
class SignalSnapshot:
    """한 시점의 차량 신호 전체.

    Attributes:
        rear_door: 뒷문 개폐 상태.
        rear_seat_belt_buckled: 후석 벨트 체결 여부.
        ignition: 시동 on/off 상태.
        hvac_on: 공조 작동 여부.
        cabin_temp_c: 실내 온도(섭씨). 아직 모르면 None이다.
        lock: 차량 잠금 상태.
        timestamp: 신호 시각(epoch 초). 아직 모르면 None이다.
    """

    rear_door: DoorState = DoorState.CLOSED
    rear_seat_belt_buckled: bool = False
    ignition: IgnitionState = IgnitionState.OFF
    hvac_on: bool = False
    cabin_temp_c: float | None = None
    lock: LockState = LockState.UNLOCKED
    timestamp: float | None = None

    @property
    def rear_door_open(self) -> bool:
        """뒷문이 열렸으면 True를 돌려준다."""
        return self.rear_door is DoorState.OPEN

    @property
    def ignition_on(self) -> bool:
        """시동이 켜졌으면 True를 돌려준다."""
        return self.ignition is IgnitionState.ON

    @property
    def locked(self) -> bool:
        """차량이 잠겼으면 True를 돌려준다."""
        return self.lock is LockState.LOCKED


@dataclass(frozen=True)
class SignalEvent:
    """개별 신호 변화 한 건.

    Attributes:
        type: 이벤트 종류.
        timestamp: 이벤트 시각(epoch 초). 아직 모르면 None이다.
        cabin_temp_c: CABIN_TEMP_CHANGED 일 때의 실내 온도(섭씨).
        snapshot: 어댑터가 함께 넘기는 전체 스냅샷. 없으면 None이다.
            스냅샷이 있으면 세션은 그 값을 현재 신호로 쓴다.
    """

    type: SignalEventType
    timestamp: float | None = None
    cabin_temp_c: float | None = None
    snapshot: SignalSnapshot | None = None

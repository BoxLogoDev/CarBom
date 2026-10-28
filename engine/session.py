"""케어 세션 상태머신.

데이터 모양은 상태머신 하나다.
세션은 신호 스냅샷이나 개별 이벤트를 받아 현재 신호를 갱신한다.
세션은 후석 동승자 존재 여부를 추적한다.
세션은 현재 신호와 동승자 존재 여부로 다음 상태를 정한다.

동승자 판정 규칙은 두 줄이다.
후석 벨트가 체결되면 동승자가 있다고 본다.
벨트가 풀린 상태에서 뒷문이 열리면 동승자가 내렸다고 본다.

핵심 예외 규칙은 한 줄이다.
시동이 꺼졌고 차량이 잠겼고 뒷문이 닫혔고 동승자가 남아 있으면 EXCEPTION 이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from engine.signals import (
    DoorState,
    IgnitionState,
    LockState,
    SignalEvent,
    SignalEventType,
    SignalSnapshot,
)


class SessionState(Enum):
    """케어 세션 상태."""

    IDLE = "idle"
    BOARDING = "boarding"
    ONBOARD = "onboard"
    DRIVING = "driving"
    ARRIVED = "arrived"
    ALIGHTING = "alighting"
    COMPLETED = "completed"
    EXCEPTION = "exception"


@dataclass(frozen=True)
class StateTransition:
    """상태 전이 한 건.

    Attributes:
        from_state: 전이 전 상태.
        to_state: 전이 후 상태.
        timestamp: 전이를 일으킨 신호의 시각(epoch 초). 없으면 None이다.
        snapshot: 전이를 일으킨 시점의 신호 스냅샷.
        reason: 전이 이유를 적는 짧은 문자열.
    """

    from_state: SessionState
    to_state: SessionState
    timestamp: float | None
    snapshot: SignalSnapshot
    reason: str


@dataclass
class CareSession:
    """승차부터 하차 확인까지 한 번의 케어 세션.

    호출자는 apply_snapshot 이나 apply_event 로 신호를 순서대로 넘긴다.
    update 는 두 입력을 모두 받는 편의 메서드다.
    호출자는 state 와 passenger_present 와 history 를 읽어 결과를 확인한다.
    """

    _snapshot: SignalSnapshot = field(default_factory=SignalSnapshot)
    _state: SessionState = SessionState.IDLE
    _passenger_present: bool = False
    history: list[StateTransition] = field(default_factory=list)

    @property
    def state(self) -> SessionState:
        """현재 세션 상태."""
        return self._state

    @property
    def passenger_present(self) -> bool:
        """후석 동승자가 차 안에 있으면 True다."""
        return self._passenger_present

    @property
    def current_snapshot(self) -> SignalSnapshot:
        """가장 최근 신호 스냅샷."""
        return self._snapshot

    def reset(self) -> None:
        """세션을 초기 상태로 되돌린다."""
        self._snapshot = SignalSnapshot()
        self._state = SessionState.IDLE
        self._passenger_present = False
        self.history = []

    def update(
        self, signal: SignalSnapshot | SignalEvent
    ) -> SessionState:
        """스냅샷이나 이벤트를 받아 상태를 전이하고 현재 상태를 돌려준다."""
        if isinstance(signal, SignalEvent):
            return self.apply_event(signal)
        return self.apply_snapshot(signal)

    def apply_snapshot(self, snapshot: SignalSnapshot) -> SessionState:
        """신호 스냅샷 한 건을 반영하고 현재 상태를 돌려준다."""
        self._snapshot = snapshot
        self._update_passenger(snapshot)
        self._advance(snapshot.timestamp)
        return self._state

    def apply_event(self, event: SignalEvent) -> SessionState:
        """신호 이벤트 한 건을 반영하고 현재 상태를 돌려준다."""
        if event.snapshot is not None:
            snapshot = event.snapshot
            if snapshot.timestamp is None and event.timestamp is not None:
                snapshot = replace(snapshot, timestamp=event.timestamp)
            return self.apply_snapshot(snapshot)
        snapshot = self._snapshot_from_event(event)
        return self.apply_snapshot(snapshot)

    def _snapshot_from_event(self, event: SignalEvent) -> SignalSnapshot:
        current = self._snapshot
        changes: dict[str, object] = {"timestamp": event.timestamp}
        if event.type is SignalEventType.REAR_DOOR_OPENED:
            changes["rear_door"] = DoorState.OPEN
        elif event.type is SignalEventType.REAR_DOOR_CLOSED:
            changes["rear_door"] = DoorState.CLOSED
        elif event.type is SignalEventType.REAR_BELT_BUCKLED:
            changes["rear_seat_belt_buckled"] = True
        elif event.type is SignalEventType.REAR_BELT_UNBUCKLED:
            changes["rear_seat_belt_buckled"] = False
        elif event.type is SignalEventType.IGNITION_ON:
            changes["ignition"] = IgnitionState.ON
        elif event.type is SignalEventType.IGNITION_OFF:
            changes["ignition"] = IgnitionState.OFF
        elif event.type is SignalEventType.LOCKED:
            changes["lock"] = LockState.LOCKED
        elif event.type is SignalEventType.UNLOCKED:
            changes["lock"] = LockState.UNLOCKED
        elif event.type is SignalEventType.HVAC_ON:
            changes["hvac_on"] = True
        elif event.type is SignalEventType.HVAC_OFF:
            changes["hvac_on"] = False
        elif event.type is SignalEventType.CABIN_TEMP_CHANGED:
            changes["cabin_temp_c"] = event.cabin_temp_c
        return replace(current, **changes)  # type: ignore[arg-type]

    def _update_passenger(self, snapshot: SignalSnapshot) -> None:
        if snapshot.rear_seat_belt_buckled:
            self._passenger_present = True
        elif self._passenger_present and snapshot.rear_door_open:
            self._passenger_present = False

    def _advance(self, timestamp: float | None) -> None:
        # 스냅샷 한 건이 여러 단계를 건너뛰어도 이력은 단계별로 남는다.
        for _ in range(len(SessionState) + 1):
            step = self._next_state()
            if step is None:
                return
            next_state, reason = step
            self.history.append(
                StateTransition(
                    from_state=self._state,
                    to_state=next_state,
                    timestamp=timestamp,
                    snapshot=self._snapshot,
                    reason=reason,
                )
            )
            self._state = next_state

    def _next_state(self) -> tuple[SessionState, str] | None:
        snapshot = self._snapshot
        state = self._state

        if state is SessionState.COMPLETED:
            return None

        if self._is_exception(snapshot) and state is not SessionState.EXCEPTION:
            return SessionState.EXCEPTION, "ignition_off_locked_passenger_present"

        if state is SessionState.IDLE:
            if snapshot.rear_door_open:
                return SessionState.BOARDING, "rear_door_opened"
            if self._passenger_present:
                return SessionState.ONBOARD, "passenger_onboard"
            return None

        if state is SessionState.BOARDING:
            if self._passenger_present and not snapshot.rear_door_open:
                return SessionState.ONBOARD, "passenger_onboard"
            if not snapshot.rear_door_open and not self._passenger_present:
                return SessionState.IDLE, "boarding_without_passenger"
            return None

        if state is SessionState.ONBOARD:
            if snapshot.ignition_on:
                return SessionState.DRIVING, "ignition_on"
            if snapshot.rear_door_open and not self._passenger_present:
                return SessionState.ALIGHTING, "passenger_alighting"
            return None

        if state is SessionState.DRIVING:
            if not snapshot.ignition_on:
                return SessionState.ARRIVED, "ignition_off"
            return None

        if state is SessionState.ARRIVED:
            if snapshot.rear_door_open or not self._passenger_present:
                return SessionState.ALIGHTING, "alighting_started"
            return None

        if state is SessionState.ALIGHTING:
            if not self._passenger_present and not snapshot.rear_door_open:
                return SessionState.COMPLETED, "alighting_confirmed"
            return None

        if state is SessionState.EXCEPTION:
            if not self._passenger_present and not snapshot.rear_door_open:
                return SessionState.COMPLETED, "alighting_confirmed_after_exception"
            if snapshot.rear_door_open:
                return SessionState.ALIGHTING, "rear_door_opened_after_exception"
            if not snapshot.locked and snapshot.ignition_on:
                return SessionState.ONBOARD, "unlocked_and_ignition_on_after_exception"
            return None

        return None

    def _is_exception(self, snapshot: SignalSnapshot) -> bool:
        return (
            not snapshot.ignition_on
            and snapshot.locked
            and not snapshot.rear_door_open
            and self._passenger_present
        )

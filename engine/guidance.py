"""안내 문구 엔진.

데이터 모양은 세션 상태별 안내 표 하나다.
상태가 수준과 기본 문구를 정한다.
목적지 맥락이 등원과 하원 표현을 바꾼다.
실내 온도는 32도 이상에서 문구에 온도를 넣는다.
실내 온도는 35도 이상에서 표현과 이유를 한 단계 올린다.
대량 헬퍼는 세션들을 입력 순서대로 읽어 안내들을 돌려주며,
세션을 바꾸지 않는다.
짝 헬퍼는 세션마다 다른 목적지 맥락을 짝지어 안내들을 돌려준다.
단일 세션 헬퍼는 세션 하나에 목적지 맥락 여럿을 적용해 안내들을 돌려준다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum, IntEnum

from engine.session import CareSession, SessionState
from engine.signals import SignalSnapshot

_HOT_CABIN_C = 32.0
_DANGEROUS_CABIN_C = 35.0


class GuidanceLevel(IntEnum):
    """안내 강도. 값이 클수록 강하다."""

    NONE = 0
    INFO = 1
    REMIND = 2
    URGENT = 3


class DestinationContext(Enum):
    """목적지 맥락."""

    GENERAL = "general"
    DROPOFF = "dropoff"
    PICKUP = "pickup"


@dataclass(frozen=True)
class Guidance:
    """안내 한 건.

    Attributes:
        level: 안내 강도.
        state: 안내를 만든 세션 상태.
        text: 사용자에게 보여줄 한국어 문구. 안내가 없으면 빈 문자열이다.
        reason: 안내 이유를 적는 짧은 문자열.
    """

    level: GuidanceLevel
    state: SessionState
    text: str
    reason: str = ""


def _normalize_context(
    context: DestinationContext | str | None,
) -> DestinationContext:
    if isinstance(context, DestinationContext):
        return context
    if isinstance(context, str):
        try:
            return DestinationContext(context.strip().lower())
        except ValueError:
            return DestinationContext.GENERAL
    return DestinationContext.GENERAL


def _format_temp(cabin_temp_c: float) -> str:
    return f"{cabin_temp_c:g}"


def _none(state: SessionState, reason: str) -> Guidance:
    return Guidance(
        level=GuidanceLevel.NONE, state=state, text="", reason=reason
    )


def _boarding(state: SessionState, context: DestinationContext) -> Guidance:
    if context is DestinationContext.DROPOFF:
        text = "등원 준비 중입니다. 뒷좌석 승차와 안전벨트를 확인해 주세요."
        reason = "boarding_dropoff"
    elif context is DestinationContext.PICKUP:
        text = "하원 준비 중입니다. 뒷좌석 승차와 안전벨트를 확인해 주세요."
        reason = "boarding_pickup"
    else:
        text = "뒷좌석 승차 중입니다. 승차와 안전벨트를 확인해 주세요."
        reason = "boarding"
    return Guidance(
        level=GuidanceLevel.INFO, state=state, text=text, reason=reason
    )


def _arrived(
    state: SessionState,
    cabin_temp_c: float | None,
    context: DestinationContext,
) -> Guidance:
    if context is DestinationContext.DROPOFF:
        text = "도착했습니다. 등원 하차 전 뒷좌석을 확인해 주세요."
        reason = "arrived_dropoff_check_rear_seat"
    elif context is DestinationContext.PICKUP:
        text = "도착했습니다. 하원 하차 전 뒷좌석을 확인해 주세요."
        reason = "arrived_pickup_check_rear_seat"
    else:
        text = "도착했습니다. 하차 전 뒷좌석을 확인해 주세요."
        reason = "arrived_check_rear_seat"
    if cabin_temp_c is not None and cabin_temp_c >= _DANGEROUS_CABIN_C:
        text = (
            f"{text} 실내 온도 {_format_temp(cabin_temp_c)}도로 높습니다. "
            "즉시 뒷좌석을 확인해 주세요."
        )
        reason = f"{reason}_dangerous_cabin_temp"
    elif cabin_temp_c is not None and cabin_temp_c >= _HOT_CABIN_C:
        text = f"{text} 실내 온도 {_format_temp(cabin_temp_c)}도입니다."
        reason = f"{reason}_hot_cabin"
    return Guidance(
        level=GuidanceLevel.REMIND, state=state, text=text, reason=reason
    )


def _exception(
    state: SessionState, cabin_temp_c: float | None
) -> Guidance:
    if cabin_temp_c is not None and cabin_temp_c >= _DANGEROUS_CABIN_C:
        text = (
            "위험합니다. 잠긴 차량의 뒷좌석에 동승자가 남아 있을 수 있고 "
            f"실내 온도 {_format_temp(cabin_temp_c)}도입니다. "
            "즉시 뒷좌석을 확인해 주세요."
        )
        reason = "passenger_left_locked_dangerous_cabin_temp"
    elif cabin_temp_c is not None and cabin_temp_c >= _HOT_CABIN_C:
        text = (
            "잠긴 차량의 뒷좌석에 동승자가 남아 있을 수 있습니다. "
            f"실내 온도 {_format_temp(cabin_temp_c)}도입니다. "
            "뒷좌석을 확인해 주세요."
        )
        reason = "passenger_left_locked_hot_cabin"
    else:
        text = (
            "잠긴 차량의 뒷좌석에 동승자가 남아 있을 수 있습니다. "
            "뒷좌석을 확인해 주세요."
        )
        reason = "passenger_left_locked"
    return Guidance(
        level=GuidanceLevel.URGENT, state=state, text=text, reason=reason
    )


def guidance_for(
    state: SessionState,
    snapshot: SignalSnapshot | None,
    passenger_present: bool = False,
    context: DestinationContext | str | None = DestinationContext.GENERAL,
) -> Guidance:
    """상태와 신호와 동승자 존재 여부로 안내를 만든다."""
    normalized = _normalize_context(context)
    cabin_temp_c = snapshot.cabin_temp_c if snapshot is not None else None

    if state is SessionState.IDLE:
        return _none(state, "idle")

    passenger_expected_states = (
        SessionState.BOARDING,
        SessionState.ALIGHTING,
        SessionState.COMPLETED,
    )
    if not passenger_present and state not in passenger_expected_states:
        return _none(state, "no_passenger")

    if state is SessionState.BOARDING:
        return _boarding(state, normalized)

    if state is SessionState.ONBOARD:
        return Guidance(
            level=GuidanceLevel.INFO,
            state=state,
            text="뒷좌석 승차가 확인되었습니다. 출발 전 안전벨트를 확인해 주세요.",
            reason="passenger_onboard",
        )

    if state is SessionState.DRIVING:
        return Guidance(
            level=GuidanceLevel.INFO,
            state=state,
            text="안전 운전 중입니다. 운전 중에는 화면을 조작하지 마세요.",
            reason="driving",
        )

    if state is SessionState.ARRIVED:
        return _arrived(state, cabin_temp_c, normalized)

    if state is SessionState.ALIGHTING:
        return Guidance(
            level=GuidanceLevel.INFO,
            state=state,
            text="하차 중입니다. 뒷좌석이 비었는지 확인해 주세요.",
            reason="alighting",
        )

    if state is SessionState.COMPLETED:
        return Guidance(
            level=GuidanceLevel.INFO,
            state=state,
            text="하차 확인이 완료되었습니다.",
            reason="completed",
        )

    if state is SessionState.EXCEPTION:
        return _exception(state, cabin_temp_c)

    return _none(state, "no_guidance")


def guidance_for_session(
    session: CareSession,
    context: DestinationContext | str | None = DestinationContext.GENERAL,
) -> Guidance:
    """세션의 현재 상태와 스냅샷으로 안내를 만든다."""
    return guidance_for(
        session.state,
        session.current_snapshot,
        passenger_present=session.passenger_present,
        context=context,
    )


def guidances_for_sessions(
    sessions: Iterable[CareSession],
    context: DestinationContext | str | None = DestinationContext.GENERAL,
) -> tuple[Guidance, ...]:
    """세션들을 순서대로 읽어 안내들을 돌려준다. 세션은 바꾸지 않는다.

    guidance_for_session의 대량 변환이다.
    입력 순서를 그대로 유지하고, 빈 입력이면 빈 tuple을 돌려준다.
    """
    return tuple(
        guidance_for_session(session, context=context)
        for session in sessions
    )


def guidances_for_sessions_by_context(
    sessions: Iterable[CareSession],
    contexts: Iterable[DestinationContext | str | None],
) -> tuple[Guidance, ...]:
    """세션마다 다른 목적지 맥락을 짝지어 안내들을 돌려준다. 세션은 바꾸지 않는다.

    guidances_for_sessions(같은 맥락을 모든 세션에 적용)의 짝 버전이다.
    sessions와 contexts를 먼저 각각 tuple로 구체화하고, 입력 순서대로
    짝지어 각 세션에 guidance_for_session(session, context=context)를
    적용한 tuple을 돌려준다. 빈 입력(둘 다 빈 경우)이면 빈 tuple이다.
    중복은 중복 그대로 유지하고, 각 context는 Enum·문자열·None을
    그대로 전달한다(정규화는 guidance_for_session 경로가 담당한다).

    Raises:
        ValueError: sessions와 contexts의 길이가 다르면 낸다.
            길이 검사가 모든 안내 생성보다 먼저 끝나므로 부분 결과는
            돌려주지 않는다.
    """
    sessions_tuple = tuple(sessions)
    contexts_tuple = tuple(contexts)
    if len(sessions_tuple) != len(contexts_tuple):
        raise ValueError(
            "세션 수와 목적지 맥락 수가 다릅니다: "
            f"{len(sessions_tuple)} != {len(contexts_tuple)}"
        )
    return tuple(
        guidance_for_session(session, context=context)
        for session, context in zip(sessions_tuple, contexts_tuple)
    )


def guidances_for_session_by_contexts(
    session: CareSession,
    contexts: Iterable[DestinationContext | str | None],
) -> tuple[Guidance, ...]:
    """세션 하나에 목적지 맥락 여럿을 적용해 안내들을 돌려준다. 세션은 바꾸지 않는다.

    guidances_for_sessions(같은 맥락을 모든 세션에 적용)와
    guidances_for_sessions_by_context(세션마다 다른 맥락을 짝지어 적용)와
    짝을 이루는, 세션 하나에 맥락 여럿을 적용하는 경로다.
    simulator의 snapshots_for_scenario_by_starts(하나의 이름·여러 시작
    시각)와 같은 단일 기준 × 다중 파라미터 대칭이다.
    contexts를 먼저 tuple로 구체화하고, 입력 순서대로 각 원소에
    guidance_for_session(session, context=원소)를 적용한 tuple을 돌려준다.
    빈 입력이면 빈 tuple이다. 중복은 중복 그대로 유지하고, 각 context는
    Enum·문자열·None을 그대로 전달한다(정규화는 guidance_for_session
    경로가 담당한다).
    """
    contexts_tuple = tuple(contexts)
    return tuple(
        guidance_for_session(session, context=context)
        for context in contexts_tuple
    )


__all__ = [
    "DestinationContext",
    "Guidance",
    "GuidanceLevel",
    "guidance_for",
    "guidance_for_session",
    "guidances_for_session_by_contexts",
    "guidances_for_sessions",
    "guidances_for_sessions_by_context",
]

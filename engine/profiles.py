"""동승 프로필.

데이터 모양은 동승자 종류별 프로필 표 하나다.
종류가 표시명과 벨트 감지 가능 여부와 수동 확인 필요 여부를 정한다.
반려동물은 이동장이 벨트로 고정되면 벨트로 감지한다.
반려동물은 벨트가 체결되지 않으면 수동 탑승 확인이 필요하다.
그 밖의 종류는 벨트 미체결이어도 수동 확인을 요구하지 않는다.
대량 헬퍼 profiles_for는 종류들을 순서대로 읽어 프로필 tuple을 돌려준다.
알 수 없는 값은 profile_for와 같이 성인 프로필로 처리한다.
대량 판정 헬퍼 needs_manual_confirmations는 프로필들을 순서대로 읽어 수동 확인 필요 여부 tuple을 돌려준다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum


class PassengerKind(Enum):
    """동승자 종류."""

    CHILD = "child"
    PET = "pet"
    ELDER = "elder"
    ADULT = "adult"


@dataclass(frozen=True)
class PassengerProfile:
    """동승자 프로필 한 건.

    Attributes:
        kind: 동승자 종류.
        label: 사용자에게 보여줄 한국어 표시명.
        belt_detectable: 후석 벨트 체결로 동승자를 감지할 수 있으면 True다.
        requires_manual_confirmation_when_unbelted: 벨트가 체결되지 않았을 때
            수동 탑승 확인이 필요하면 True다.
        reminder_note: 프로필에 맞는 짧은 한국어 안내 메모.
    """

    kind: PassengerKind
    label: str
    belt_detectable: bool
    requires_manual_confirmation_when_unbelted: bool
    reminder_note: str


_PROFILES: dict[PassengerKind, PassengerProfile] = {
    PassengerKind.CHILD: PassengerProfile(
        kind=PassengerKind.CHILD,
        label="아이",
        belt_detectable=True,
        requires_manual_confirmation_when_unbelted=False,
        reminder_note="카시트와 안전벨트를 확인해 주세요.",
    ),
    PassengerKind.PET: PassengerProfile(
        kind=PassengerKind.PET,
        label="반려동물",
        belt_detectable=True,
        requires_manual_confirmation_when_unbelted=True,
        reminder_note=(
            "이동장이 벨트로 고정되지 않았으면 탑승을 직접 확인해 주세요."
        ),
    ),
    PassengerKind.ELDER: PassengerProfile(
        kind=PassengerKind.ELDER,
        label="부모님",
        belt_detectable=True,
        requires_manual_confirmation_when_unbelted=False,
        reminder_note="승차와 안전벨트를 천천히 확인해 주세요.",
    ),
    PassengerKind.ADULT: PassengerProfile(
        kind=PassengerKind.ADULT,
        label="성인",
        belt_detectable=True,
        requires_manual_confirmation_when_unbelted=False,
        reminder_note="안전벨트를 확인해 주세요.",
    ),
}


def _normalize_kind(
    kind: PassengerKind | str | None,
) -> PassengerKind:
    if isinstance(kind, PassengerKind):
        return kind
    if isinstance(kind, str):
        try:
            return PassengerKind(kind.strip().lower())
        except ValueError:
            return PassengerKind.ADULT
    return PassengerKind.ADULT


def profile_for(kind: PassengerKind | str | None) -> PassengerProfile:
    """종류 값으로 동승자 프로필을 돌려준다.

    알 수 없는 문자열이나 None은 성인(일반) 프로필로 처리한다.
    """
    return _PROFILES[_normalize_kind(kind)]


def profiles_for(
    kinds: Iterable[PassengerKind | str | None],
) -> tuple[PassengerProfile, ...]:
    """종류들을 순서대로 읽어 프로필들을 돌려준다.

    profile_for의 대량 변환이다.
    입력 순서를 그대로 유지하고, 빈 입력이면 빈 tuple을 돌려준다.
    """
    return tuple(profile_for(kind) for kind in kinds)


def all_profiles() -> tuple[PassengerProfile, ...]:
    """모든 프로필을 아이·반려동물·부모님·성인 순서로 돌려준다."""
    return tuple(_PROFILES[kind] for kind in PassengerKind)


def needs_manual_confirmation(
    profile: PassengerProfile, belt_buckled: bool
) -> bool:
    """벨트 상태 기준으로 수동 탑승 확인이 필요한지 돌려준다.

    벨트가 체결됐으면 항상 False다.
    벨트가 체결되지 않았으면 프로필의 설정을 그대로 따른다.
    """
    if belt_buckled:
        return False
    return profile.requires_manual_confirmation_when_unbelted


def needs_manual_confirmations(
    profiles: Iterable[PassengerProfile], belt_buckled: bool
) -> tuple[bool, ...]:
    """프로필들을 순서대로 읽어 수동 탑승 확인이 필요한지 돌려준다.

    needs_manual_confirmation의 대량 판정이다.
    입력 순서를 그대로 유지하고, 빈 입력이면 빈 tuple을 돌려준다.
    """
    return tuple(
        needs_manual_confirmation(profile, belt_buckled=belt_buckled)
        for profile in profiles
    )


__all__ = [
    "PassengerKind",
    "PassengerProfile",
    "all_profiles",
    "needs_manual_confirmation",
    "needs_manual_confirmations",
    "profile_for",
    "profiles_for",
]

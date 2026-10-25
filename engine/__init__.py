"""플랫폼 독립 코어 엔진 패키지."""

from engine.guidance import (
    DestinationContext,
    Guidance,
    GuidanceLevel,
    guidance_for,
    guidance_for_session,
)
from engine.session import CareSession, SessionState, StateTransition
from engine.signals import (
    DoorState,
    IgnitionState,
    LockState,
    SignalEvent,
    SignalEventType,
    SignalSnapshot,
)

__all__ = [
    "CareSession",
    "DestinationContext",
    "DoorState",
    "Guidance",
    "GuidanceLevel",
    "IgnitionState",
    "LockState",
    "SessionState",
    "SignalEvent",
    "SignalEventType",
    "SignalSnapshot",
    "StateTransition",
    "guidance_for",
    "guidance_for_session",
]

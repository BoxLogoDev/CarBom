"""플랫폼 독립 코어 엔진 패키지."""

from engine.guidance import (
    DestinationContext,
    Guidance,
    GuidanceLevel,
    guidance_for,
    guidance_for_session,
)
from engine.profiles import (
    PassengerKind,
    PassengerProfile,
    all_profiles,
    needs_manual_confirmation,
    profile_for,
)
from engine.report import (
    CareReport,
    CareReportLog,
    report_for_session,
    reports_for_sessions,
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
    "CareReport",
    "CareReportLog",
    "CareSession",
    "DestinationContext",
    "DoorState",
    "Guidance",
    "GuidanceLevel",
    "IgnitionState",
    "LockState",
    "PassengerKind",
    "PassengerProfile",
    "SessionState",
    "SignalEvent",
    "SignalEventType",
    "SignalSnapshot",
    "StateTransition",
    "all_profiles",
    "guidance_for",
    "guidance_for_session",
    "needs_manual_confirmation",
    "profile_for",
    "report_for_session",
    "reports_for_sessions",
]

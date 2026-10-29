"""케어 리포트.

데이터 모양은 세션 한 건의 결과 요약 하나다.
리포트는 세션의 최종 상태와 전이 이력에서만 계산한다.
리포트는 세션을 바꾸지 않는다.
완료 여부는 최종 상태가 COMPLETED 인지로 정한다.
예외 여부는 전이 이력에 EXCEPTION 진입이 있는지로 정한다.
소요 시각은 첫 전이와 마지막 전이의 timestamp 차이로 정한다.
최대 실내 온도는 전이 이력 스냅샷들과 현재 스냅샷 중에서 정한다.
누적함의 집계는 리포트 값들에서만 계산한다. 온도·소요 시간이 없는
리포트는 그 집계에서 빼고, 대상이 하나도 없으면 None 이다.
대량 헬퍼는 세션들을 입력 순서대로 읽어 리포트들을 돌려주며,
세션을 바꾸지 않는다.
누적함의 대량 추가는 리포트들을 입력 순서대로 누적하고 돌려준다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from engine.session import CareSession, SessionState, StateTransition


@dataclass(frozen=True)
class CareReport:
    """케어 리포트 한 건.

    Attributes:
        final_state: 리포트를 만든 시점의 세션 상태.
        completed: 최종 상태가 COMPLETED 이면 True다.
        exception_occurred: 전이 이력에 EXCEPTION 으로의 전이가 있으면 True다.
        exception_count: EXCEPTION 진입 횟수.
        transition_count: 전이 이력 건수.
        passenger_present: 리포트를 만든 시점의 동승자 존재 여부.
        started_at: 첫 전이의 timestamp. 전이가 없으면 None이다.
        ended_at: 마지막 전이의 timestamp. 전이가 없으면 None이다.
        duration_seconds: started_at 과 ended_at 의 차이.
            둘 중 하나라도 없으면 None이다.
        max_cabin_temp_c: 전이 이력 스냅샷들과 현재 스냅샷의
            cabin_temp_c 중 최대값. 값이 하나도 없으면 None이다.
        transitions: 세션 history 의 복사본.
    """

    final_state: SessionState
    completed: bool
    exception_occurred: bool
    exception_count: int
    transition_count: int
    passenger_present: bool
    started_at: float | None
    ended_at: float | None
    duration_seconds: float | None
    max_cabin_temp_c: float | None
    transitions: tuple[StateTransition, ...]

    @property
    def summary(self) -> str:
        """한국어 한 줄 요약."""
        if self.completed and not self.exception_occurred:
            return "하차 확인 완료 · 예외 없음"
        if self.completed:
            return "예외 발생 후 하차 확인 완료"
        if self.exception_occurred:
            return "예외 발생 · 하차 미확인"
        return "진행 중 · 하차 미확인"


def report_for_session(session: CareSession) -> CareReport:
    """세션을 읽어 케어 리포트를 만든다. 세션은 바꾸지 않는다."""
    transitions = tuple(session.history)
    exception_count = sum(
        1
        for transition in transitions
        if transition.to_state is SessionState.EXCEPTION
    )
    started_at = transitions[0].timestamp if transitions else None
    ended_at = transitions[-1].timestamp if transitions else None
    duration_seconds = (
        ended_at - started_at
        if started_at is not None and ended_at is not None
        else None
    )
    cabin_temps = [
        temp
        for temp in (
            *(
                transition.snapshot.cabin_temp_c
                for transition in transitions
            ),
            session.current_snapshot.cabin_temp_c,
        )
        if temp is not None
    ]
    return CareReport(
        final_state=session.state,
        completed=session.state is SessionState.COMPLETED,
        exception_occurred=exception_count > 0,
        exception_count=exception_count,
        transition_count=len(transitions),
        passenger_present=session.passenger_present,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=duration_seconds,
        max_cabin_temp_c=max(cabin_temps) if cabin_temps else None,
        transitions=transitions,
    )


def reports_for_sessions(
    sessions: Iterable[CareSession],
) -> tuple[CareReport, ...]:
    """세션들을 순서대로 읽어 케어 리포트들을 돌려준다. 세션은 바꾸지 않는다.

    report_for_session의 대량 변환이다.
    입력 순서를 그대로 유지하고, 빈 입력이면 빈 tuple을 돌려준다.
    """
    return tuple(report_for_session(session) for session in sessions)


@dataclass
class CareReportLog:
    """케어 리포트 누적함."""

    _reports: list[CareReport] = field(default_factory=list)

    def add_report(self, report: CareReport) -> None:
        """리포트 한 건을 누적한다."""
        self._reports.append(report)

    def add_reports(
        self, reports: Iterable[CareReport]
    ) -> tuple[CareReport, ...]:
        """리포트들을 순서대로 누적하고 추가된 리포트들을 돌려준다.

        add_report의 대량 적용이다.
        입력 순서를 그대로 유지하고, 빈 입력이면 빈 tuple을 돌려주며
        누적함은 변하지 않는다. 중복 리포트는 제거하지 않고 그대로
        누적한다.
        """
        added = tuple(reports)
        for report in added:
            self.add_report(report)
        return added

    def add_session(self, session: CareSession) -> CareReport:
        """세션 리포트를 만들어 누적하고 돌려준다."""
        report = report_for_session(session)
        self.add_report(report)
        return report

    def add_sessions(
        self, sessions: Iterable[CareSession]
    ) -> tuple[CareReport, ...]:
        """세션들의 리포트를 만들어 순서대로 누적하고 돌려준다.

        add_session의 대량 적용이다.
        빈 입력이면 빈 tuple을 돌려주고 누적함은 변하지 않는다.
        """
        reports = reports_for_sessions(sessions)
        for report in reports:
            self.add_report(report)
        return reports

    @property
    def reports(self) -> tuple[CareReport, ...]:
        """누적된 리포트들의 복사본."""
        return tuple(self._reports)

    def __len__(self) -> int:
        return len(self._reports)

    @property
    def completed_count(self) -> int:
        """완료된 리포트 수."""
        return sum(1 for report in self._reports if report.completed)

    @property
    def sessions_with_exception(self) -> int:
        """예외가 발생한 세션 수."""
        return sum(
            1 for report in self._reports if report.exception_occurred
        )

    @property
    def total_exception_count(self) -> int:
        """누적된 모든 리포트의 예외 진입 횟수 합계."""
        return sum(report.exception_count for report in self._reports)

    @property
    def max_cabin_temp_c(self) -> float | None:
        """누적된 모든 리포트의 최대 실내 온도 중 가장 큰 값.

        온도가 기록된 리포트가 하나도 없으면 None이다.
        """
        temps = [
            report.max_cabin_temp_c
            for report in self._reports
            if report.max_cabin_temp_c is not None
        ]
        return max(temps) if temps else None

    @property
    def average_duration_seconds(self) -> float | None:
        """소요 시간이 기록된 리포트들의 평균 소요 시간(초).

        소요 시간이 기록된 리포트가 하나도 없으면 None이다.
        """
        durations = [
            report.duration_seconds
            for report in self._reports
            if report.duration_seconds is not None
        ]
        if not durations:
            return None
        return sum(durations) / len(durations)


__all__ = [
    "CareReport",
    "CareReportLog",
    "report_for_session",
    "reports_for_sessions",
]

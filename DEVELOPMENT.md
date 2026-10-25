# 카봄 개발 기록

개발 방식: 창고노트(StockNotes)와 같은 상시 개선 사이클 — Muse Code `/poteto-mode`(모델 Muse Wonder Full, `muse-wonder-full-1.0`)에 단위 위임, 페퍼가 감독 검증.
기간: 2026-10-24 ~ 2026-11-14 (공모전 제출 전날까지). 2026-10-24 주인님 지시로 Meta 해커톤 사이클과 병행 가동한다. 해커톤 집중 구간(10-27~11-05)에는 1단계 코어 엔진 범위를 우선한다. 제출 마감 2026-11-15 23:59.

## 최종 산출 목표 (2026-11-14까지)

1. 코어 엔진(engine/) — 케어 세션 상태머신·신호 모델·안내 문구·동승 프로필·케어 리포트 + 단위 테스트 통과
2. 시연 데모(demo/) — 차량 화면 + 운전자 폰 화면 재현, 시뮬레이션 신호로 등원 정상 흐름·하차 깜빡 예외 흐름 시연 가능
3. 앱 화면 시안 스크린샷 — 데모 주요 화면 캡처를 `~/workspace/goals/pleos/files/시안/`에 정리 (접수양식 7번 참고자료용)
4. GitHub 저장소 BoxLogoDev/CarBom 회차별 동기화 (개발 중 비공개, 제출 직전 공개 전환은 주인님 확인 후)

## 기준

- 공개 자료(스크린샷·README·저장소)에 개발자 실명·연락처·소속을 넣지 않는다 (공모전 양식 주의사항).
- 회사(LS) 관련 표현을 넣지 않는다.
- 설계가 바뀌는 큰 변경은 실행하지 말고 「제안」에만 남긴다.

## 반영 완료

- 2026-10-24 · 엔진 기능 · 코어 엔진 첫 단위 — 신호 모델(`engine/signals.py`: SignalSnapshot·SignalEvent, 뒷문·후석 벨트·시동·공조/실내온도·잠금)과 케어 세션 상태머신(`engine/session.py`: IDLE→BOARDING→ONBOARD→DRIVING→ARRIVED→ALIGHTING→COMPLETED, 시동 OFF+잠금+동승자 잔류 시 EXCEPTION 전이, 전이 이력 기록), `engine/__init__.py` re-export, `tests/test_session.py` 테스트 10개(등원 정상 흐름·하차 깜빡 예외 흐름 포함). 감독 검증: 변경 파일 직접 확인, `python3 -m unittest discover -s tests` 10개 전부 통과, 공개 정보(실명·연락처·소속·LS 표현) 0건 확인. Muse Code 세션은 파일 완성 후 산출 없이 멈춰 감독자가 종료하고 검증을 직접 수행함. [페퍼 · 2026-10-24 · 카봄 사이클 1회차]

- 2026-10-25 · QA · 고정 시나리오 각도 추가 — 하차 깜빡 + 실내 온도 상승 예외 흐름 테스트(`tests/test_session_qa.py`, 테스트 3개: 잠금 시 EXCEPTION 진입, 온도 단계 상승(28.0→32.0→35.5℃, 공조 OFF) 중 EXCEPTION 유지·동승자 잔류·최신 온도 반영·COMPLETED 전이 없음, 온도 상승 뒤 뒷문 열림→ALIGHTING→COMPLETED 회복). 결함은 발견되지 않음. 감독 검증: 변경 파일(신규 파일 1개) 직접 확인, 엔진·기존 테스트 무변경, `python3 -m unittest discover -s tests` 13개 전부 통과(기존 10 + 신규 3), 공개 정보(실명·연락처·소속·LS 표현) 0건 확인. Muse Code 세션은 파일 완성 후 종료 신호를 보내지 않아 25분 제한으로 감독자가 종료하고 검증을 직접 수행함. [페퍼 · 2026-10-25 · 카봄 사이클 2회차]

- 2026-10-25 · 엔진 기능 · 안내 문구 엔진 — `engine/guidance.py`(GuidanceLevel IntEnum NONE<INFO<REMIND<URGENT, Guidance, DestinationContext GENERAL/DROPOFF/PICKUP, `guidance_for`·`guidance_for_session`): 상태별 단계 문구(등원 DROPOFF 맥락 포함), EXCEPTION은 URGENT, 실내 온도 32℃ 이상 문구에 온도 포함·35℃ 이상 표현/reason escalation, 동승자 없음·IDLE은 NONE+빈 문구(COMPLETED는 INFO 완료 문구, BOARDING은 승차 진행으로 INFO). `engine/__init__.py` re-export 추가, `tests/test_guidance.py` 테스트 11개. 감독 검증: 변경 파일 3개 직접 확인, 기존 엔진·테스트 무변경, `python3 -m unittest discover -s tests` 24개 전부 통과(기존 13 + 신규 11), 공개 정보(실명·연락처·소속·LS 표현) 0건 확인. 실행 경과: 1차 세션은 테스트 파일을 만든 뒤 런타임 재시작으로 중단돼, 테스트를 살린 좁은 단위로 1회 재위임해 구현을 완성했고, 파일 완성 후 종료 신호가 없어 감독자가 세션을 종료하고 검증을 직접 수행함. [페퍼 · 2026-10-25 · 카봄 사이클 3회차]

## 제안

(없음)

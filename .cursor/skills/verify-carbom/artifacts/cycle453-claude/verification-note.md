# 카봄 사이클 453 검증 노트

목적은 제출 마감 2026-11-15를 앞두고 검증 스킬 상태와 고정 시나리오 기대 결과를 기록하는 것이다.
이 사이클은 제출 자료와 문서 카테고리다.
신규 기능과 QA와 데모 확장은 범위 밖이다.
이 파일이 유일한 산출이다.

## 1. 검증 스킬 doctor 결과

doctor 명령은 실행 환경 실패로 완료되지 않았다.
시도한 명령은 `python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py doctor`다.
실패 사유는 셸 샌드박스 시작 실패다.
원문 메시지는 bubblewrap이 proc 마운트 권한을 얻지 못했다는 내용이다.
따라서 doctor 판정은 미확정이다.
이 노트는 doctor가 통과했다고 주장하지 않는다.
환경이 회복되면 같은 명령을 다시 실행해 결과를 확정해야 한다.
doctor가 확인할 항목은 스킬 문서에 정의돼 있다.
항목은 프로젝트 루트와 Python 3.10 이상 여부다.
항목은 필수 엔진 파일과 데모 파일 존재 여부다.
항목은 `node --check demo/demo.js` 결과다.

## 2. 고정 시나리오 3종 기대 최종 상태

기대값 출처는 검증 스킬 문서와 검증 도우미 스크립트다.
스크립트의 기대값 표는 아래 3종을 고정한다.

- `dropoff_normal`의 기대 최종 상태는 COMPLETED다.
- `forgotten_rising_temp`의 기대 최종 상태는 EXCEPTION이다.
- `forgotten_rising_temp`는 동승자가 남아 있는 상태다.
- `forgotten_rising_temp`의 안내 수준은 URGENT다.
- `pet_dropoff`의 기대 최종 상태는 COMPLETED다.

구동 경로는 공개 API만 쓴다.
경로는 시뮬레이터 어댑터 재생과 하차 맥락 안내와 케어 리포트다.
이 사이클에서는 구동을 새로 수행하지 않았다.
기대값만 제출 준비 확인용으로 기록한다.

## 제출 준비 잔여

doctor 재실행이 남아 있다.
환경 회복 뒤 doctor를 실행하고 종료 코드 0을 확인해야 한다.
그 전에는 체크아웃 건강 상태를 확정할 수 없다.

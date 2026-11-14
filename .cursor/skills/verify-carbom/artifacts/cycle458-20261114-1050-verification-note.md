# 카봄 458회차 검증 노트

- 회차. 458회차. 제출 자료와 문서 카테고리. 제출 마감 준비 잔여 확인.
- 기준 시각. 2026-11-14 10:50 KST 폴더명 기준. 사이클 종료는 2026-11-14 23:59 KST이다.
- 범위. 검증 전용이다. 신규 기능과 QA 확장과 데모 확장과 추가 정정은 하지 않았다.

## 실행 결과

이 세션에서는 샌드박스가 명령 실행 전에 실패했다. 그래서 아래 명령들은 시작되지 않았다. 종료 코드와 최종 상태와 테스트 개수는 이 세션에서 얻지 못했다. 감독자가 직접 재실행해야 한다.

- doctor. 실행 못 함. 종료 코드 없음.
  - 명령. `python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py doctor`
- drive dropoff_normal. 실행 못 함. 종료 코드 없음. 최종 상태 확인 못 함.
  - 명령. `python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py drive --scenario dropoff_normal --out .cursor/skills/verify-carbom/artifacts/cycle458-20261114-1050-dropoff_normal`
  - 기대값. COMPLETED. 전이 6.
- drive forgotten_rising_temp. 실행 못 함. 종료 코드 없음. 최종 상태 확인 못 함.
  - 명령. `python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py drive --scenario forgotten_rising_temp --out .cursor/skills/verify-carbom/artifacts/cycle458-20261114-1050-forgotten_rising_temp`
  - 기대값. EXCEPTION. 동승자 잔류. URGENT. 35.5도.
- drive pet_dropoff. 실행 못 함. 종료 코드 없음. 최종 상태 확인 못 함.
  - 명령. `python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py drive --scenario pet_dropoff --out .cursor/skills/verify-carbom/artifacts/cycle458-20261114-1050-pet_dropoff`
  - 기대값. COMPLETED.
- unittest. 실행 못 함. 개수 확인 못 함.
  - 명령. `python3 -m unittest discover -s tests`
  - 기대값. 테스트 1312개 전부 통과.
- node check. 실행 못 함. 결과 확인 못 함.
  - 명령. `node --check demo/demo.js`

## 샌드박스 오류

처음 실행한 셸 명령은 `git status --porcelain` 확인이었다. 도구가 아래 오류를 반환했다. 명령 자체는 시작되지 않았다.

```text
environment failure: bubblewrap setup failed before command execution: bwrap: Can't mount proc on /newroot/proc: Operation not permitted
```

같은 이유로 doctor와 drive 3종과 unittest와 node check를 이 세션에서 실행할 수 없었다. artifacts 아래 cycle458 drive 폴더 3개는 이 세션에서 생성하지 못했다.

## 코드 변경

코드 변경은 없다. 이 세션에서 `engine/`와 `tests/`와 `demo/`와 `README.md`와 `PLAN.md`와 `DEVELOPMENT.md`를 수정하지 않았다. 쓴 파일은 이 검증 노트 하나뿐이다.

## 재실행 안내

감독자는 프로젝트 루트에서 위 명령 6개를 그대로 재실행하면 된다. 재실행 결과로 종료 코드와 최종 상태와 unittest 개수를 이 노트에 채우면 된다.

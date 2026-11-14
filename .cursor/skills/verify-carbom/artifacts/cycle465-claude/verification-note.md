# 카봄 사이클 465회차 검증 노트

작성일: 2026-11-14
카테고리: 제출 자료·문서
제출 마감: 2026-11-15 23:59

## 이 회차의 성격

이 회차는 제출 준비 잔여 확인 회차이다.
이 회차에는 코드 변경이 없다.
신규 기능, QA, 데모 확장과 추가 정정은 하지 않았다.
`engine/`, `tests/`, `demo/`, `README.md`, `PLAN.md`, `DEVELOPMENT.md`의 본문은 변경하지 않았다.
이 세션에서 쓴 파일은 이 노트 1개뿐이다.

## 검증 절차

프로젝트 로컬 검증 스킬(`.cursor/skills/verify-carbom/SKILL.md`) 절차를 따랐다.
스킬이 정한 순서는 doctor 먼저, 그 다음 drive이다.
doctor 명령은 `python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py doctor`이다.
drive 명령은 `python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py drive --scenario <이름> --out <폴더>`이다.

doctor와 drive의 직접 실행을 시도했다.
첫 셸 호출이 샌드박스 설정 실패(bubblewrap, `Can't mount proc on /newroot/proc: Operation not permitted`)로 명령 시작 전에 막혔다.
같은 셸로는 이후 명령도 실행할 수 없었다.
drive 증거 파일(`drive-<시나리오>.json`, `drive-<시나리오>.txt`)도 이 회차의 산출 파일 1개 제한 때문에 만들지 않았다.

doctor 결과: 미확정 — 감독자 재실행 필요.
drive 결과: 미확정 — 감독자 재실행 필요.
단위 테스트 직접 실행 결과: 미확정 — 감독자 재실행 필요.
git 상태 직접 확인 결과: 미확정 — 감독자 재실행 필요.

위의 미확정 항목을 통과했다고 기록하지 않는다.

## 고정 시나리오 3종 기대값

감독자 재실행 때 대조할 기대값은 다음과 같다.

- `dropoff_normal`: 최종 상태 COMPLETED, 전이 6.
- `forgotten_rising_temp`: 최종 상태 EXCEPTION, 동승자 잔류, 안내 수준 URGENT, 실내 온도 35.5도.
- `pet_dropoff`: 최종 상태 COMPLETED.

## 단위 테스트 기대값

- 단위 테스트 기대값: 1312개.
- `README.md` 표기: 1312개 (이 세션에서 `README.md`에서 검색으로 확인, 31행).

## 시안 3장 체크 항목

아래 확인이 필요하다. 이 세션에서는 셸 장애로 파일 목록, 바이트 수와 이미지 크기를 직접 확인하지 못했다.

- [ ] `~/workspace/goals/pleos/files/시안/`에 시안 3장이 있는지 확인한다.
- [ ] 파일명이 `카봄-시안-01-등원정상-도착확인.png`, `카봄-시안-02-하차깜빡-긴급알림.png`, `카봄-시안-03-반려동물-하차완료.png`인지 확인한다.
- [ ] 각 파일의 바이트 수를 확인한다.
- [ ] 각 파일의 크기가 1180x900인지 확인한다.

## 주인님 잔여 몫

아래 항목은 주인님 몫이며 대신하지 않았다.

- [ ] 접수양식 04의 동의 체크, 본인 서명, 서명일자.
- [ ] 8번 숏폼 제작과 게시.
- [ ] 저장소 공개 전환.
- [ ] 최종 메일 발송 지시. 마감은 2026-11-15 23:59이다.

## 공개 자료 체크 항목

- [ ] 공개 자료에 실명이 없어야 한다.
- [ ] 공개 자료에 연락처가 없어야 한다.
- [ ] 공개 자료에 소속이 없어야 한다.
- [ ] 공개 자료에 LS 표현이 없어야 한다.

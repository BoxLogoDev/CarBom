# 카봄 사이클 459 검증 노트

목적은 제출 마감 2026-11-15를 앞두고 제출 준비 잔여를 확인하는 것이다.
신규 기능과 QA 확장과 데모 확장은 수행하지 않았다.
코드와 README와 문서 정정은 수행하지 않았다.
이 파일이 이번 회차의 유일한 신규 산출이다.
이 세션에서 편집 도구로 쓴 파일은 이 노트뿐이다.
engine과 tests와 demo와 README와 PLAN은 변경하지 않았다.
pstack 해석은 Muse 어댑터를 기준으로 했다.
위임은 사용하지 않았고 작업은 이 세션에서 순차로 수행했다.
모든 단계는 세션 모델로 수행했다.
`scripts/*.ts` 헬퍼 스크립트는 실행하지 않았다.
프로젝트 로컬 검증 스킬 문서를 읽었다.
기준 문서는 `.cursor/skills/verify-carbom/SKILL.md`다.

## 1. doctor 시도 결과

doctor 종료 코드는 없다.
doctor 판정은 미확정이다.
이 노트는 doctor가 통과했다고 주장하지 않는다.
셸 호출이 명령 실행 전에 실패했다.
실패 원문은 `bwrap: Can't mount proc on /newroot/proc: Operation not permitted`다.
런타임은 이후 셸 명령도 같은 방식으로 실패한다고 안내했다.
그래서 셸을 다시 호출하지 않았다.
doctor 프로세스는 시작되지 않았다.
시도하려 한 doctor 명령은 아래 명령이다.

```bash
python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py doctor
```

환경이 회복되면 같은 명령을 다시 실행해야 한다.
재실행에서 종료 코드와 필수 파일 확인과 `node --check demo/demo.js` 결과를 확정해야 한다.

## 2. 고정 시나리오 3종 drive 시도 결과

drive 프로세스도 같은 셸 실패로 시작되지 않았다.
실측 최종 상태는 3종 모두 미확정이다.
아래 최종 상태는 검증 스킬 문서에서 읽은 기대값이다.
기대값을 이번 회차의 실측 결과로 기록하지 않는다.

- `dropoff_normal`의 기대 최종 상태는 COMPLETED다. 실측 최종 상태는 미확정이다.
- `forgotten_rising_temp`의 기대 최종 상태는 EXCEPTION이다. 실측 최종 상태는 미확정이다. 기대 조건은 동승자 잔류와 안내 URGENT다.
- `pet_dropoff`의 기대 최종 상태는 COMPLETED다. 실측 최종 상태는 미확정이다.

재실행 명령은 아래 명령이다.

```bash
python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py drive --scenario dropoff_normal --out .cursor/skills/verify-carbom/artifacts/cycle459-claude
python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py drive --scenario forgotten_rising_temp --out .cursor/skills/verify-carbom/artifacts/cycle459-claude
python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py drive --scenario pet_dropoff --out .cursor/skills/verify-carbom/artifacts/cycle459-claude
```

환경이 회복되면 위 명령으로 전이 목록과 안내와 리포트를 확정해야 한다.

## 3. 단위 테스트 수 1312개 표기 일치 확인

단위 테스트 수 표기는 두 파일에서 일치한다.
확인 위치는 `README.md` 31행이다.
해당 문장은 고정 시나리오 3종을 포함해 단위 테스트 1312개가 있다고 적는다.
확인 위치는 제출메일 초안 19행이다.
제출메일 초안 파일명은 `제출메일-초안-2026-11-09.md`다.
해당 문장은 단위 테스트 1,312개를 포함한다고 적는다.
두 표기는 쉼표 유무만 다르다.
숫자는 모두 1312개로 같다.
제출메일 초안 전체에서 구 표기 1,039개는 없었다.
이번 회차에서는 셸 실패로 테스트 실측 실행을 수행하지 못했다.
표기 일치를 테스트 전수 통과 실측으로 기록하지 않는다.
환경이 회복되면 `python3 -m unittest discover -s tests`로 실측을 확정해야 한다.

## 4. 시안 3장 존재 확인

시안 3장 존재는 확인했다.
확인 방법은 각 PNG 파일을 직접 읽은 것이다.
저장 위치는 `~/workspace/goals/pleos/files/시안/`이다.

- `카봄-시안-01-등원정상-도착확인.png`가 존재한다. 크기는 61,626바이트다. 해상도는 1180x900이다. 화면 단계는 4/6이다. 세션 상태는 ARRIVED다. 안내 단계는 REMIND다.
- `카봄-시안-02-하차깜빡-긴급알림.png`가 존재한다. 크기는 77,149바이트다. 해상도는 1180x900이다. 화면 단계는 8/8이다. 세션 상태는 EXCEPTION이다. 안내 단계는 URGENT다. 실내 온도는 35.5℃다.
- `카봄-시안-03-반려동물-하차완료.png`가 존재한다. 크기는 56,768바이트다. 해상도는 1180x900이다. 화면 단계는 6/6이다. 세션 상태는 COMPLETED다. 안내 단계는 INFO다.

## 5. 주인님 잔여 몫

아래 항목은 주인님 몫이라 대신 수행하지 않았다.
서명과 숏폼과 저장소 공개 전환과 메일 발송은 수행하지 않았다.

- 동의가 남아 있다. 세부 항목은 04 동의 체크다.
- 서명이 남아 있다. 세부 항목은 본인 서명과 서명일자다.
- 숏폼이 남아 있다. 세부 항목은 8번 숏폼 제작과 게시다.
- 저장소 공개 전환이 남아 있다.
- 메일 발송이 남아 있다. 세부 항목은 최종 메일 발송 지시다.

## 6. 판정 요약

doctor 종료 코드는 미확정이다.
시나리오 3종 실측 최종 상태는 미확정이다.
시나리오 3종 기대 최종 상태는 COMPLETED와 EXCEPTION과 COMPLETED다.
단위 테스트 수 표기는 README와 제출메일 초안 모두 1312개로 일치한다.
시안 3장 존재는 확인했다.
주인님 잔여 몫은 동의와 서명과 숏폼과 저장소 공개 전환과 메일 발송 지시다.
셸 환경 회복 뒤 doctor와 drive 3종과 단위 테스트를 재실행해 실측을 확정해야 한다.

# 카봄 사이클 462회차 검증 노트

## 1. 회차 성격

이 회차는 2026-11-15 23:59 KST 제출 마감 준비 잔여 확인이다.
이 회차에서 신규 개발을 하지 않는다.
신규 기능 추가를 하지 않는다.
QA 확장을 하지 않는다.
데모 확장을 하지 않는다.
추가 정정을 하지 않는다.
`engine/`을 수정하지 않는다.
`tests/`를 수정하지 않는다.
`demo/`를 수정하지 않는다.
`README.md`를 수정하지 않는다.
`PLAN.md`를 수정하지 않는다.
`DEVELOPMENT.md`를 수정하지 않는다.
유일한 산출물은 이 파일이다.
이 파일의 경로는 `.cursor/skills/verify-carbom/artifacts/cycle462-claude/verification-note.md`이다.

## 2. verify-carbom 실행 시도 결과

프로젝트 로컬 검증 스킬은 `.cursor/skills/verify-carbom/SKILL.md`이다.
헬퍼 스크립트는 `.cursor/skills/verify-carbom/scripts/verify_carbom.py`이다.
이 세션에서 두 파일을 읽어 명령과 기대값을 확인했다.
아래 기대값은 헬퍼의 `EXPECTED_FINAL_STATE`와 스킬 문서의 정의이다.
아래 기대값은 이 세션의 관측 결과가 아니다.

- `dropoff_normal`의 기대 최종 상태는 COMPLETED이다.
- `forgotten_rising_temp`의 기대 최종 상태는 EXCEPTION이다.
- `forgotten_rising_temp`에서는 동승자가 남은 상태와 URGENT 안내가 기대 정의에 들어 있다.
- `pet_dropoff`의 기대 최종 상태는 COMPLETED이다.

시도 대상 명령은 아래 네 가지이다.

```bash
cd ~/workspace/projects/carbom
python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py doctor
python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py drive --scenario dropoff_normal --out .cursor/skills/verify-carbom/artifacts/cycle462-Muse
python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py drive --scenario forgotten_rising_temp --out .cursor/skills/verify-carbom/artifacts/cycle462-Muse
python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py drive --scenario pet_dropoff --out .cursor/skills/verify-carbom/artifacts/cycle462-Muse
```

이 세션의 첫 셸 호출은 명령 실행 전에 실패했다.
관측된 오류는 다음과 같다.

```text
bubblewrap setup failed before command execution: bwrap: Can't mount proc on /newroot/proc: Operation not permitted
```

명령은 시작되지 않았다.
종료 코드도 관측되지 않았다.
표준 출력도 관측되지 않았다.
따라서 이 세션에서 doctor를 직접 실행하지 못했다.
따라서 이 세션에서 drive 3종도 직접 실행하지 못했다.
이 노트는 doctor 통과를 주장하지 않는다.
이 노트는 drive 통과를 주장하지 않는다.
이 세션에서 drive 증거 파일인 JSON과 텍스트 파일은 생성되지 않았다.

판정은 아래와 같다.

- doctor. 미확정, 감독자 재실행 필요.
- `dropoff_normal` drive. 미확정, 감독자 재실행 필요.
- `forgotten_rising_temp` drive. 미확정, 감독자 재실행 필요.
- `pet_dropoff` drive. 미확정, 감독자 재실행 필요.

감독자 재실행에서는 위 네 명령을 그대로 실행한다.
doctor 성공 기준은 종료 코드 0과 `doctor: OK` 출력이다.
drive 성공 기준은 각 명령의 종료 코드 0과 `drive: OK` 출력이다.
drive 성공 기준에는 최종 상태와 기대 최종 상태의 일치도 포함된다.
감독자 재실행 뒤에 생성되는 drive 증거 파일은 이 회차의 단일 산출물 조건과 별개로 취급한다.
그 증거 파일은 재실행 회차의 산출물이다.

## 3. 주인님 잔여 몫

아래 네 가지는 주인님 잔여 몫이다.
이 세션은 아래 네 가지를 대행하지 않는다.
이 세션은 아래 네 가지를 수행했다고 주장하지 않는다.

1. 접수양식 04 동의 체크와 본인 서명과 서명일자.
2. 8번 숏폼 제작과 게시.
3. GitHub 저장소 `BoxLogoDev/CarBom` 공개 전환.
4. 최종 제출 메일 발송 지시.

## 4. 완료 조건

완료 조건은 노트 파일 1개만 생성되고 다른 파일은 무변경일 것이다.
생성 대상은 `.cursor/skills/verify-carbom/artifacts/cycle462-claude/verification-note.md` 1개이다.
이 세션에서 작업 공간에 쓰기 도구로 만든 파일은 이 노트뿐이다.
이 세션의 다른 도구 호출은 읽기 전용 확인이었다.
셸 샌드박스 오류 때문에 이 세션에서 `git status --porcelain` 대조는 수행하지 못했다.
감독자는 재실행과 함께 `git status --porcelain`으로 이 노트만 새로 나타나는지 확인한다.
그 확인 전까지 작업 트리 전체의 무변경 판정도 감독자 확인 몫으로 남는다.

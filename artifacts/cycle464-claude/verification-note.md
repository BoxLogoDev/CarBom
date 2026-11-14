# 카봄 사이클 464회차 검증 노트

목표는 제출 마감 전에 제출 자료와 문서 표기가 서로 어긋나지 않는지 확인하는 것이다.
문제는 문서마다 테스트 수와 시나리오와 시안 파일명이 다르면 제출 직전에 정정이 필요해진다는 점이다.
가장 작은 변경은 이 노트 파일 1개를 새로 만드는 것이다.

## 1. 이 단위의 성격

이 단위는 코드 변경 없는 최종 확인이다.
이 단위는 제출 준비 전용이다.
이 단위는 신규 기능과 QA와 데모 확장과 추가 정정을 하지 않는다.
이 세션은 기존 파일을 수정하지 않는다.
대상에는 engine과 tests와 demo가 포함된다.
대상에는 README.md와 PLAN.md와 DEVELOPMENT.md가 포함된다.
새로 만드는 파일은 이 노트 1개뿐이다.

## 2. verify-carbom 실행 시도

절차 출처는 `.cursor/skills/verify-carbom/SKILL.md`이다.
doctor 명령은 해당 파일 41행부터 44행에 있다.
drive 명령은 해당 파일 62행부터 66행에 있다.
drive 대상은 dropoff_normal과 forgotten_rising_temp과 pet_dropoff 3종이다.
기대 최종 상태는 해당 파일 68행부터 70행에 있다.
dropoff_normal의 기대값은 COMPLETED이다.
forgotten_rising_temp의 기대값은 EXCEPTION이다.
forgotten_rising_temp는 동승자 잔류와 URGENT 안내를 함께 기대한다.
pet_dropoff의 기대값은 COMPLETED이다.

이 세션은 셸 실행을 시도했다.
셸은 명령을 시작하지 못했다.
관측된 오류는 bubblewrap 설정 실패이다.
오류 문구는 proc 마운트 권한 없음이다.
doctor는 실행되지 않았다.
drive 3종은 실행되지 않았다.
단위 테스트 실행과 demo.js 문법 검사도 실행되지 않았다.
판정은 미확정 — 감독자 재실행 필요이다.
이 노트는 통과 결과를 지어내지 않는다.
감독자는 아래 명령을 재실행해야 한다.

- `cd ~/workspace/projects/carbom`
- `python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py doctor`
- `python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py drive --scenario dropoff_normal --out .cursor/skills/verify-carbom/artifacts/<run-name>`
- `python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py drive --scenario forgotten_rising_temp --out .cursor/skills/verify-carbom/artifacts/<run-name>`
- `python3 .cursor/skills/verify-carbom/scripts/verify_carbom.py drive --scenario pet_dropoff --out .cursor/skills/verify-carbom/artifacts/<run-name>`
- `python3 -m unittest discover -s tests`
- `node --check demo/demo.js`

## 3. 문서 표기 대조

이 절은 파일 표기를 직접 읽어 대조한 결과이다.
이 절은 테스트를 실행한 결과가 아니다.
이 절은 시안 이미지 파일의 존재와 크기를 확인한 결과가 아니다.

README.md 31행은 단위 테스트 1312개라고 적는다.
제출메일 초안 19행은 단위 테스트 1,312개라고 적는다.
두 숫자는 같다.
차이는 천 단위 쉼표 표기뿐이다.
접수양식 작성초안 본문에는 단위 테스트 수 표기가 없다.
접수양식 작성초안은 테스트 수와 충돌하지 않는다.

`engine/adapters/simulator.py` 16행부터 20행은 SCENARIO_NAMES를 정의한다.
값은 dropoff_normal과 forgotten_rising_temp과 pet_dropoff 3종이다.
verify-carbom 스킬의 drive 대상 3종과 이름이 같다.
README.md 20행은 고정 시나리오 3종이라고 적는다.
README.md 31행부터 35행은 등원 정상 흐름과 하차 깜빡과 반려동물 변형을 나열한다.
시나리오 개수와 의미는 서로 어긋나지 않는다.

접수양식 작성초안 항목 7은 88행부터 90행에 있다.
89행은 시안 파일명 3개를 적는다.
파일명은 `시안/카봄-시안-01-등원정상-도착확인.png`이다.
파일명은 `시안/카봄-시안-02-하차깜빡-긴급알림.png`이다.
파일명은 `시안/카봄-시안-03-반려동물-하차완료.png`이다.
90행은 GitHub 저장소 BoxLogoDev/CarBom을 적는다.
90행은 개발 중 비공개라고 적는다.
90행은 제출 시 공개 전환을 제출 직전 확인 후라고 적는다.
제출메일 초안 18행은 시안 3장을 등원 정상 흐름과 하차 깜빡과 반려동물 하차 완료로 설명한다.
제출메일 초안 19행은 같은 저장소 주소를 적는다.
시안 3장의 순서와 의미는 시나리오 3종과 어긋나지 않는다.
01은 dropoff_normal에 대응한다.
02는 forgotten_rising_temp에 대응한다.
03은 pet_dropoff에 대응한다.

어긋나는 곳은 위 4개 출처 범위에서 찾지 못했다.
테스트 수는 1312로 일치한다.
시나리오 이름은 3종으로 일치한다.
시안 파일명은 3장으로 일치한다.
남은 미확정은 실행 결과이다.
실측 테스트 개수와 통과 여부는 감독자 재실행이 확정한다.
시안 이미지 파일의 존재와 크기는 감독자 재실행이 확정한다.

## 4. 주인님 잔여 몫

이 절은 목록만 적는다.
이 세션은 아래 항목을 대신하지 않는다.
마감은 2026-11-15 23:59이다.

- 접수양식 04 동의 체크와 본인 서명과 서명일자
- 8번 숏폼 제작과 게시
- 저장소 공개 전환
- 최종 메일 발송 지시

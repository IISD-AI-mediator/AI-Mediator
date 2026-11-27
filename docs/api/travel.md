# 여행방 내부 HTTP API

동행의 브라우저 화면은 같은 출처의 Flask 서버에 방 생성을 요청하고, 참여한 방의 상태를 주기적으로 조회한다. Flask, 방 저장소, 조율 실행기, LangGraph는 하나의 웹 서비스 안에서 동작한다. 서버 내부에서는 Python 메서드 호출과 실행기 깨우기 신호를 사용한다. `/r/<invite>`는 초대 화면 주소이고, `/healthz`는 배포 상태 점검용이다. [제품 요구사항](../prd/travel.md) · [아키텍처 결정](../adr/travel.md) · [구현 명세](../design/travel-implementation.md)

## 호출 목록

`<invite>`에는 방 생성 응답의 초대 코드를 넣는다. 성공 시 아래 여섯 요청은 모두 HTTP 200과 JSON을 반환한다.

| 메서드와 경로 | 호출자와 용도 | 성공 응답 |
| --- | --- | --- |
| `POST /api/rooms` | 방장이 방을 생성하고 첫 참가자로 입장 | `{"invite":"…"}`와 방장 쿠키 |
| `GET /api/rooms/<invite>` | 방문자가 입장 가능 여부를, 참가자가 진행 상태와 결과를 조회 | 권한에 따른 방 상태 객체 |
| `POST /api/rooms/<invite>/join` | 초대받은 사람이 빈 좌석에 입장 | `{"invite":"…"}`와 참가자 쿠키 |
| `POST /api/rooms/<invite>/ready` | 방장을 포함한 참가자가 자기 조건을 제출 | `{"ok":true}` |
| `POST /api/rooms/<invite>/notes` | 참가자가 파이터 모드에서 자기 에이전트에게 지시 | `{"seq":1}`처럼 참가자별 접수 번호 반환 |
| `POST /api/rooms/<invite>/retry` | 참가자가 실패한 단계의 재실행을 요청 | `{"ok":true}` |

모든 POST는 `Content-Type: application/json`으로 JSON 객체를 보낸다. 요청 본문 한도는 32 KiB다. `Origin` 헤더가 있으면 호스트와 포트가 요청 대상과 일치해야 한다. 생성·입장 응답은 `travel_member`라는 HttpOnly 쿠키를 해당 방의 `/api/rooms/<invite>` 경로에 설정한다. 이후 브라우저가 이 쿠키를 보낸다. API 응답은 `Cache-Control: no-store`를 사용한다.

## 방 생성과 입장

방 생성에는 `name`(1~24자), `capacity`(방장을 포함한 정원, 정수 2~8), `request_id`가 필요하다. `fixed`는 공통 확정 조건이며 기본값은 빈 객체다. `mediator`는 판사 말투이며 생략하면 기본 프리셋을 쓴다. 서버에 개설 코드가 설정돼 있으면 `team_code` 문자열도 보낸다. 입장 요청은 `name`과 `request_id`만 있으면 된다.

```json
{
  "name": "민지",
  "capacity": 3,
  "request_id": "sample_create_735fc9e2a161",
  "fixed": {"destination": "부산"}
}
```

위 JSON의 `request_id`는 예시 값이다. 실제 클라이언트는 새 방을 만들거나 새로 입장하거나 새 지시를 보낼 때마다 20~128자의 임의 문자열을 생성한다. 영문 대소문자, 숫자, `_`, `-`를 쓸 수 있다. 응답을 받지 못해 **같은 동작을 재전송할 때는 처음 사용한 값**을 보낸다.

- 생성은 같은 ID와 같은 방 설정이면 기존 초대 코드와 방장 쿠키를 돌려준다. 같은 ID로 방 설정을 바꾸면 409, 새 방을 만들 때 서버의 전체 방 개설 한도에 도달했으면 429다.
- 입장은 같은 방에서 같은 ID와 이름을 다시 보내면 기존 참가자 쿠키를 돌려준다. 같은 ID에 다른 이름은 409다. 이미 입장한 브라우저가 새 ID로 입장하면 현재 좌석을 유지한다. 새 참가자는 대기 중이고 빈자리가 있는 방에만 들어갈 수 있다. 마감·정원 초과·이름 중복은 409다.

## 준비 완료와 개인 지시

`/ready`는 `preferences`(기본 `{}`), `extra`(추가 요청, 최대 600자, 기본 빈 문자열), `persona`(개인 에이전트 말투)를 받는다. 모두 맡기려면 `{}`를 보낸다. 직접 정한 항목에는 값과 중요도 `prefer`, `important`, `must` 중 하나를 함께 보낸다.

```json
{
  "preferences": {
    "local_transport": {"value": "대중교통", "priority": "must"},
    "budget": {"value": {"amount": 550000, "currency": "KRW"}, "priority": "important"}
  },
  "extra": "오전에는 여유 있게 출발하고 싶어요."
}
```

| 입력 | 형식 |
| --- | --- |
| 여행 항목 | `destination`, `origin`, `dates`, `budget`, `transport`, `flight_schedule`, `local_transport`, `departure_time`, `lodging`, `food`, `activities`, `accessibility`. 생성의 `fixed`에는 값을 직접 넣고, 준비의 `preferences`에는 위 예시처럼 값과 중요도를 넣는다. |
| 날짜·예산 | `dates`는 `{"start":"2027-05-01","end":"2027-05-03"}` 형식이다. 두 날짜의 차이는 0~365일이다. `budget.amount`는 1~100억 정수이고 `currency`는 지원 통화 코드다. |
| 선택·텍스트 | `transport`, `local_transport`, `departure_time`은 해당 선택지 문자열을 받는다. `flight_schedule`은 최대 400자, 나머지 텍스트 항목은 최대 160자다. [지원 통화와 항목별 선택지](../../travel_app/domain.py) |
| 판사·개인 말투 | `mediator`와 `persona`는 각각 해당 역할의 프리셋 이름 또는 객체를 받는다. 객체에서 `preset`을 생략하면 해당 역할의 첫 프리셋을 쓴다. `aggression`·`politeness`·`mz`는 0~10 정수이며 기본값은 5다. `instruction`은 최대 180자이며 기본값은 빈 문자열이다. |

방장이 확정한 항목을 `preferences`에 넣으면 409다. `/ready`는 요청 ID 없이 정규화된 프로필로 재제출을 처리한다. 같은 프로필은 다시 200, 준비 완료 후 변경된 프로필은 409다. 정원이 차고 마지막 참가자가 제출하면 조율이 시작된다.

`/notes`에는 `request_id`와 `text`(1~400자)를 보낸다. 응답의 `seq`는 해당 참가자의 첫 지시부터 1씩 증가한다. 처리 여부는 상태 조회의 `member.notes[].handled`에서 확인한다. 새 지시는 `floor.open`인 동안 참가자당 한 회차에 4개까지 접수한다. 같은 ID와 내용으로 재전송하면 마감 후에도 기존 번호를 받는다. 같은 ID에 다른 내용 또는 마감 후 새 지시는 409, 회차 한도 초과는 429다.

## 상태 조회와 오류 복구

`GET /api/rooms/<invite>`에는 본문이 없다. 존재하는 방이면 유효한 참가자 쿠키가 없어도 초대 화면에 필요한 정보를 돌려준다.

| 응답 대상 | 필드와 의미 |
| --- | --- |
| 공통 | `invite`, `capacity`, `fixed`, `joined`(입장 수), `ready`(준비 수), `member` |
| 방문자 | `member: null`, `can_join`(대기 중이고 빈 좌석이 있는지). 이 행과 공통 행의 필드만 받는다. |
| 참가자 본인 | `member`에 `seat`, `name`, `ready`, `profile`(제출 전 `null`), `agent`, `notes`가 들어 있다. `notes[]`의 필드는 `seq`, `text`, `round`, `handled`다. `members[]`의 공개 명단에는 각자의 `seat`, `name`, `ready`가 들어 있다. |
| 참가자의 방 진행 상태 | `mediator`, `mode`(`waiting`, `negotiating`, `fight`, `done`, `error`), `round`, `events[]`(공개 발언과 상태 변화), `history[]`(회차별 판단), `floor`(`null` 또는 `topic`, `open`, `deadline`), `server_time`, `error`(문자열 또는 `null`), `can_retry`. 시간은 Unix 초 단위다. |
| 참가자의 최종 여행안 | `result`는 확정 전 `null`이다. 완료 시 `round`, `entries`, `conflicts`, `itinerary`, `evidence`를 받는다. 회차별 판단과 최종안의 각 항목에는 `value`, `reason`, `status`가 있다. 상태값은 `fixed`(사전 확정), `agreed`(합의), `suggested`(AI 제안), `unresolved`(미해결), `verify`(확인 필요)다. |

값이 있는 새 결정은 출처를 `origin`으로 표시한다. `host`는 방장 확정, `participant`는 참가자가 제출하거나 수용한 조건, `agent`는 AI가 낸 값이다. 미해결 항목에 검색 근거도 부족하면 `verification_reason`에 별도의 확인 사유가 들어간다. 개인 지시 원문은 본인의 `member.notes`에서만 읽을 수 있다.

날짜별 일정의 `activity_status`는 `planned`(일정 반영), `candidate`(후보 · 확인 필요), `undecided`(미정) 중 하나다. 후보에 확인할 사유가 있으면 `activity_reason`에 표시한다. 기존 방은 당시 저장된 필드만 반환할 수 있다.

새 공개 발언의 `events[].voice_source`는 실제 표현을 만든 경로다. `generated`는 모델이 작성한 발언, `generated_core`는 모델이 별도로 작성한 짧은 발언이다. `generated_frame`은 첫 제안에서 모델이 작성한 앞말과 뒷말 사이에 서버가 확정값을 한 번 넣은 경우다. 세 경로 모두 게시할 문장 전체가 의미 검사를 통과해야 한다. `structured`는 모델이 고른 말높이·도입 방식으로 서버가 결정값과 협상 행동을 표현한 문장이고, `baseline`은 서버 기본문이다. 일반 단계 안내와 이전 버전의 기록에서는 생략할 수 있다.

참가자는 `can_retry`가 참일 때 `POST /api/rooms/<invite>/retry`에 `{}`를 보내고 상태를 다시 조회한다. 성공은 실행 재개 요청을 접수했다는 뜻이다. 이 요청은 `request_id`로 중복 처리하지 않는다. 방이 이미 오류 상태를 벗어났으면 409, 오류 상태에서 방당 수동 재시도 3회를 소진했으면 429다.

오류 본문의 `error`는 사용자에게 보여 줄 메시지다. 입력·권한·상태 오류에는 `field`가 함께 오며 특정 입력과 관련이 없으면 `null`이다. 잘못된 JSON처럼 Flask가 처리한 HTTP 오류에서는 `field`가 생략될 수 있다.

| HTTP 상태 | 대표 원인 |
| --- | --- |
| 400 | 잘못된 JSON, 객체가 아닌 본문, 입력 형식·길이·값 오류 |
| 403 | 잘못된 방 개설 코드, 타 호스트의 Origin, 참가자 세션이 필요한 동작 |
| 404 | 존재하지 않는 초대 코드 |
| 409 | 제출 내용 충돌, 입장·지시 마감, 현재 상태에서 불가능한 재시도 |
| 413 · 415 | 각각 본문 크기 초과, JSON이 아닌 요청 형식 |
| 429 | 방 개설 수, 회차별 지시 수, 방별 수동 재시도 수 한도 초과 |

[HTTP 라우트](../../travel_app/__init__.py) · [방 상태와 세션별 응답](../../travel_app/store.py) · [4인 통합 시험](../../tests/test_group_travel.py) · [재전송 및 복구 시험](../../tests/test_room_recovery.py)

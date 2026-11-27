# OPEN-04 · 서울 여행방의 첫 공개 제안

마지막 자연 방에서 서윤과 민재의 첫 제안은 모두 실제 작성·검토를 거쳐 두 사람에게 같은 문장으로 게시됐다. 각 원본의 `calls` 배열은 1번부터 센다. 공개 번호는 이벤트의 `id`다. 개인 모델은 `gemini-3.1-flash-lite`, 판사는 `gemini-3.8-flash`다. 같은 서울 1박 2일 입력과 45초 토론창을 사용했다. [서울 입력](../../scripts/two_person_seoul.json) · [설계](../design/travel-flow.md#open-04--두-사람이-처음-제안할-때) · [ADR-010·011](../adr/travel.md)

## 최종 실측 · 작성 응답에서 공개문까지

| 방 · 안건 | 작성 → 의미 검토 → 공개 | 실제 게시된 전문 |
|---|---|---|
| 자연 방 · 서윤의 활동 | 14 → 16 → 3 · `generated_core` | 이번 여행의 활동으로 국립중앙박물관 전시 관람을 제안합니다. |
| 자연 방 · 민재의 교통 | 15 → 17 → 4 · `generated_frame` | 아, 현지에서는 택시 이용하자. |
| 예산 대조 · 서윤 | 1 → 3 → 2 · `generated_frame` | 1인당 예산은 350,000 KRW 이내로 설정하고 싶습니다. |
| 예산 대조 · 민재 | 2 → 4 → 3 · `generated_frame` | 아, 현지에서는 택시 이용하자. |
| 박물관 대조 · 서윤 | 1 → 4 → 2 · `generated_core` | 하고 싶은 활동으로 국립중앙박물관 전시 관람을 제안합니다. |
| 박물관 대조 · 민재 | 2 → 3 → 3 · `generated_frame` | 아, 현지에서는 택시 이용하자. |

자연 방은 두 독립 HTTP 세션의 방 생성·초대·준비 완료부터 실행했다. 첫 판사 요청 18번에서 좌석별 안건과 값을 읽었다. 서윤은 자기 활동을 정중하게 제안하며 효율이나 비용을 설명하지 않았다. 민재의 “아,”는 자기 제안을 꺼내는 감탄이고, 반말 “이용하자”에 다른 사람의 승낙이나 편의성 주장은 없다. 택시 문장은 응답의 앞말 `아, 현지에서는 ` + 값 `택시` + 뒷말 ` 이용하자.`를 공백까지 그대로 이어 복원했다. 서윤의 앞뒤 문장 필드에는 미완성 조사 `(을)를`가 남아 게시되지 않았다. 같은 응답의 독립 후보 `이번 여행의 활동으로 {value}을(를) 제안합니다.`에서 받침 ‘ㅁ’에 맞는 ‘을’을 확정한 전문을 16번이 검토했다. 모든 행에서 해당 공개 전문과 기준문을 대조했고, 검토는 `own_offer`, 원안·후보 모두 `defend`, 추가·누락 없음이었다. [자연 방 원본](../../instance/gemini-replay-pxzp5ocf/trace.json)

두 대조 방은 원 시나리오의 참가자·조건을 유지하고 첫 제안 안건을 지정했다. 예산 대조의 금액은 1인 지출 상한이고 박물관 대조에서는 관람을 희망할 뿐 소재나 입장료를 단정하지 않았다. 양쪽 공개 조회가 일치했고 각 방의 첫 발언에 실모델 호출은 작성 2회와 검토 2회였다. 박물관 대조 민재의 다른 후보 “현지에서는 택시 타고 다니는 게 제일 편해.”는 공개되지 않았다. [예산 작성·검토](../../instance/fixed-openings-4m2x72_j/propose.json) · [예산 공개문](../../instance/fixed-openings-4m2x72_j/public.json) · [박물관 작성·검토](../../instance/fixed-openings-nwj3efjd/propose.json) · [박물관 공개문](../../instance/fixed-openings-nwj3efjd/public.json)

**후속 토론과 최종 여행안.** 자연 방은 2026-11-27 23:05:41 KST에 시작해 125.95초에 완료됐다. 실모델 호출은 개인 26회·판사 14회였고 전송 오류와 방 재시도는 없었다. 53.83초에 받은 민재 지시 1번은 처리 완료였고 원문이 전달된 요청은 민재의 협상 31번·지시 확인 32번뿐이었다. 두 판사 요청에서 민재의 이동 조건이 ‘택시 필수’에서 ‘대중교통 선호’로 바뀌었다. 공개 8번은 “오케이, 그럼 현지 이동수단은 대중교통 이용하는 걸로 양보할게.”였다(작성 33번, 검토 34번, `generated_core`). 서윤의 후속 교통 발언 7번은 효율성 설명이 탈락해 `structured`로 게시됐다. 두 세션의 공개 이벤트 11개·판정 이력 2개·최종 항목 12개 전부가 같았다. 서윤의 지시 목록은 비었고 세 페르소나 지시, 서윤의 개인 요청, 민재 쪽지 원문은 양측 공개 응답 및 Chrome 공개 목록에 없었다. [호출·지시·양측 공개 원본](../../instance/gemini-replay-pxzp5ocf/trace.json)

12월 5~6일 대전→서울 기차는 사전 확정, 1인 예산 350,000 KRW와 대중교통은 합의였다. 숙박 항목의 서울가든호텔은 확인 필요였고 출발 시각·항공편·음식·접근성도 확인 필요였다. 활동 항목 전체는 확인 필요, 5일 국립중앙박물관 전시 관람은 후보, 6일 ‘뚝섬한강공원 관련 활동’은 일정에 반영됐다. 두 날의 이동은 대중교통이었다. 이 상태 표시는 방이 반환한 판정이다. [결정·날짜별 일정 원본](../../instance/gemini-replay-pxzp5ocf/trace.json)

**360px 키보드·접근성.** 실측의 격리된 Chrome 컨텍스트 두 개에서 Enter로 `전체 공개 대화`를 펼쳤다. 11건 모두 API와 화자·순서·전문이 같았고 가로 넘침은 없었다. 별도 로컬 HTTP 시험방에서는 실측 1~2번을 먼저 보여 주고 3·4번을 한 번에 추가했다. 두 화면 모두 순서를 유지했고 `aria-live="polite"`는 마지막 화자와 전문을 알렸다. 따로 도착시킨 3번과 4번도 각각 해당 화자와 전문을 알렸다. 7번에서 대화에 초점을 두고 Home을 누른 뒤 8번을 추가하자 양쪽 모두 초점과 읽던 위치 0px를 유지했다. Tab 한 번, Enter로 `새 발언 보기`를 실행했을 때 끝과의 거리는 0px였고 버튼이 숨겨졌다. Chrome 157.0.8103.51, Playwright 1.65.2에서 확인했다. 음성 낭독기 자체의 발음은 측정하지 않았다. [키보드 검사 코드](../../instance/open04_keyboard_evidence.py) · [양측 결과](../../instance/gemini-replay-pxzp5ocf/keyboard.json)

## 변경 전과 보완 과정에서 확인한 실패

| 자연 방 | 실제 후보와 판단 | 두 참가자가 읽은 첫 발언 |
|---|---|---|
| 변경 전 · 예산 | 서윤 9번 “전체적인 효율성을 고려해서 1인당 예산을 350,000 KRW 이내로 설정하는 안을 제안합니다.” 14번은 “1인 예산은 350,000 KRW 이내로 설정하는 것이 가장 효율적일 것 같습니다.” 11·16번이 효율성 근거를 거절했다. | 3번 “1인 예산은 ‘350,000 KRW’ 이내로 잡는 안을 제안합니다.” · `structured` |
| 변경 전 · 택시 | 민재 10번 “오, 그거 괜찮네! 현지에서는 택시 이용을 제안할게.” 13번은 “오, 그건 좀 아닌 거 같아. 현지에서는 택시 이용을 제안해.” 12·15번 모델은 긍정 판정했으나 상대의 말을 들었다는 독립된 앞 문장은 게시되지 않았다. | 4번 “오, 현지에서는 ‘택시’ 이용을 제안할게.” · `structured` |
| 첫 보완판 · 박물관과 택시 | 서윤 8번은 “이번 여행에서 즐길 활동으로 국립중앙박물관 전시 관람을 제안하며, 해당 항목에 대해 인당 예산을 10만 원 이내로 정하고 진행하는 것은 어떨까요?”였다. 승인받지 않은 숫자로 로컬 검사에서 탈락한 뒤 재작성 기회가 없었다. 민재의 9번은 별도 검토 10번을 통과했다. | 3번 “하고 싶은 활동에 대해서는 ‘국립중앙박물관 전시 관람’ 안을 제안합니다.” · `structured`. 4번 “와, 진짜 대박이다, 우리 현지에서는 택시 이용하자.” · `generated_core` |
| 두 번째 보완판 · 예산과 택시 | 서윤 11·16번은 상한을 다시 풀이했다. 14·17번 검토가 덧붙인 설명을 거절했다. 민재 12번은 렌터카를 지어냈고, 13번 “와, 좋다, 현지에서는 택시 이용하자.”에 15번 검토가 `own_offer`와 행동 `yield`를 함께 반환했다. | 3·4번 모두 변경 전과 동일한 `structured` 문장. |
| 세 번째 보완판 · 예산과 택시 | 값의 앞말과 뒷말을 따로 생성했다. 서윤 10번이 쓴 “1인당 예산은 350,000 KRW 이내로 설정했으면 해요.”와 민재 11번이 쓴 “아, 택시 타고 다니자.”는 각자의 제안이었다. 하지만 의미 검토 7건 모두 분류 칸에 설명문, 행동 칸에 배열을 보내 서버가 거절했다. | 3·4번 모두 변경 전과 동일한 `structured` 문장. 민재의 8번 “오케이, 그럼 현지 이동수단은 대중교통 이용하는 걸로 내가 양보할게.”는 `generated_core`였다. |

세 자연 방은 차례로 128.86초·177.09초·121.12초에 끝났다. 첫 보완판의 예산·택시 대조에서는 두 모델 문장이 통과했지만 같은 코드의 자연 방에서 서윤이 실패했다. 두 번째 보완판의 예산·택시 대조에서 민재의 첫 문장은 렌터카, 서윤의 재작성은 50만 원을 제시했다. 박물관 대조의 서윤은 다시 쓴 활동 제안에 대해 검토가 원문의 인용을 완성하지 못해 기본문을 읽었다. 잘못 제시한 10만 원·렌터카·50만 원은 해당 공개문에 없었다. [변경 전 원본](../../instance/gemini-replay-2yxh6ndi/trace.json) · [첫 보완판 자연 방](../../instance/gemini-replay-8bsuhklj/trace.json) · [첫 보완판 대조](../../instance/fixed-openings-2q1u5bd6/propose.json) · [두 번째 보완판 자연 방](../../instance/gemini-replay-jy__vf9f/trace.json) · [예산 대조](../../instance/fixed-openings-4zkiupq2/propose.json) · [박물관 대조](../../instance/fixed-openings-0gsg624u/propose.json)

공통 Git 기준점은 `213567c5046e85bc906b49f8f2b692b306bcd2c5`다. 아래는 실행 시점 작업 트리와 실패 기록의 SHA-256 접두사다. 자연 방은 `trace.json`, 대조는 `propose.json`과 `public.json` 순이다. 각 자연 방 원본의 `hashes`에 제품과 실행기 전체 지문이 있다.

| 작업 트리 · tone / prompts | 자연 방 | 예산 대조 | 박물관 대조 |
|---|---|---|---|
| 변경 전 · `692bcd1c7bbf / 9a0f13447357` | `d5d691fe4a86a656` | — | — |
| 첫 보완판 · `3e6d0d15970d / 2caccfb64a81` | `c909da8494c6b7a4` | `dc0dc4fb76cfd272 / 5d96043fdb483b58` | — |
| 두 번째 보완판 · `4790ccc7af8d / e62ab41544c4` | `f4d332b6f0512138` | `ad9d7bf70c9b2050 / 73e430184e94360e` | `b9e20e954473d92e / 08c613c8b7be1fb8` |
| 세 번째 보완판 · `ebbbc3288b9f / 492f99a71253` | `c989001cfc8cbf48` | `06b61b2151a7908c / 348112744db93ad2` | 생략 |

세 번째 보완판의 예산·택시 고정 대조도 분류값 형식 오류로 두 건 모두 기본문을 게시했다. 같은 오류가 드러나 이 버전의 박물관 대조는 생략했다. [세 번째 보완판 자연 방](../../instance/gemini-replay-awbnb2of/trace.json) · [예산 대조 원본](../../instance/fixed-openings-ki_ovd97/propose.json) · [대조 공개문](../../instance/fixed-openings-ki_ovd97/public.json)

## 독립 검증 환경

Windows, Python 3.11.9, SQLite 3.45.1, Flask 3.1.1, LangGraph 1.2.15. 회귀 시험은 외부 모델·검색 응답을 통제한다. WSGI는 프로세스 내 세션, HTTP 설정은 방 시나리오를 별도 쿠키를 쓰는 루프백 클라이언트로 실행한다. 첫 보완판은 87/87개(WSGI 6.805초, HTTP 10.337초), 두 번째 보완판은 89/89개(9.034초, 10.778초), 두 번째 보완판의 집중 검사 47/47개(2.466초)가 통과했다. 생략 0개. 첫 HTTP 실행의 샌드박스 오류 10013을 기록하고 루프백이 허용된 환경에서 전체를 다시 실행했다.

세 번째 보완판은 WSGI 94/94개(8.513초), HTTP 94/94개(10.640초), 집중 검사 52/52개(2.532초)가 통과했다. 변경 전 방의 작성·검토 응답 네 건씩을 별도 시험에서 `render_speech`에 원문 그대로 재입력했다. 서윤 9→11→14→16번과 민재 10→12→13→15번이 예전과 동일한 두 기본문으로 복구됐다. 재작성 요청은 원래 인자에 각각 `repair=true`와 `unsupported_claim` 또는 `single_offer` 사유만 추가했다. [표현·보호 회귀 검사](../../tests/test_persona.py) · [실제 Gemini HTTP 요청 형식 검사](../../tests/test_agent_prompts.py)

**최종 승인본**은 WSGI 96/96개(8.494초), HTTP 96/96개(10.134초), 집중 54/54개(2.513초)에 생략 0개였다. 앞의 이전 응답 재입력도 같은 결과였다. 발언 앞뒤의 공백·조사 변형 시 생성 출처 거절, 값 양쪽에서 만들어지는 비인가 숫자·비공개 구절, 거짓 긍정, 상한이 있는 재작성, 검토·연결 실패 시 한 번만 게시, 첫 발언용 HTTP 스키마를 검사했다. 전송 JSON에 `responseJsonSchema`를 지정하고 실모델의 응답 및 공개문을 각 방에서 다시 확인했다. [표현 회귀](../../tests/test_persona.py) · [전송 회귀](../../tests/test_agent_prompts.py)

```powershell
$env:GEMINI_API_KEY = 'offline-test-key'
$env:TRAVEL_TEST_TRANSPORT = 'wsgi'
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
$env:TRAVEL_TEST_TRANSPORT = 'http'
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
$env:TRAVEL_TEST_TRANSPORT = 'wsgi'
$env:PYTHONPATH = 'tests'
.\.venv\Scripts\python.exe -B -m unittest -q test_persona test_agent_prompts test_turn_memory test_pair_intent test_judge.JudgeTests.test_legacy_room_mixed_events_and_mediator_contract_survive_refresh
```

실제 모델 재생은 구성된 키를 사용할 수 있는 별도의 PowerShell에서 수행한다. 주제·문구·시간은 이후 실행에서 달라질 수 있다. 마지막 키보드 검사는 보존한 자연 방 기록과 임시 SQLite를 사용하며 모델을 호출하지 않는다.

```powershell
.\.venv\Scripts\python.exe -B -u scripts/replay_gemini_room.py --browser --require-generated-openings
.\.venv\Scripts\python.exe -B -u scripts/replay_reaffirmation.py --openings-only
.\.venv\Scripts\python.exe -B -u scripts/replay_reaffirmation.py --openings-only activities
.\.venv\Scripts\python.exe -B instance/open04_keyboard_evidence.py instance/gemini-replay-pxzp5ocf/trace.json
```

최종 세 실행에서 원본에 기록된 제품·재생기·시나리오 지문을 디스크와 비교해 모두 일치했다. SHA-256 접두사는 tone `ebbbc3288b9f`, prompts `83868a7571cc`, models `df7c7fdd8ae0`, decisions `f794ac156cf3`, test_persona `54f383576af9`, test_agent_prompts `663149b5c74f`, 자연 재생기 `33cd5e18b67f`, 대조 재생기 `124ba79f1449`, 시나리오 `8fd5306ae46a`다. HTML·CSS 포함 제품 23개 파일의 집합 지문은 `91fe7b916d3ddabbc33697d50467cf8d35e7bc1884fca5b75cb125a94a13bc1b`, 시험 15개는 `8ae966234127381a9e6bdbdd8a4f7663254f63e77a155547e1bac0b6a01640d1`다. 상대 POSIX 경로순으로 정렬한 `경로 + 공백 + 소문자 파일 SHA-256 + LF`를 UTF-8로 연결해 해시했다.

| 최종 실행 기록 | SHA-256 |
|---|---|
| 자연 방 `trace.json` | `9aad372fb9ee8482e060851e0cc30498c551e510970eb10b3503defe930c3871` |
| 자연 방 키보드 `keyboard.json` | `69b619c397227491322919b56493fcb2f445baa4acafcf9ce64e7cbf4ea8c264` |
| 예산 대조 `propose.json` / `public.json` | `1bbaf7b99a271eccd5459fcdaaa51be058eca4f2f56ec7e0d6ba3cb19683574d` / `2caeda4b3ddfba1bf40469f56fbcd144cd40103d3c89d8bc0ea542df2d3c165c` |
| 박물관 대조 `propose.json` / `public.json` | `214f18daab8aab2939c4109e49e856684c918b8db5145b1617f100f8392bbfa4` / `f30ede792130b599e8f663cdf76318c9c3dadee47bb163b059fad322b302e091` |

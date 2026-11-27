# TURN-03 · 서윤의 예산 제안과 재확인

## 최종 실측 · 서윤의 두 발언과 민재의 양보

최종 예산 대조에서 **서윤의 첫 제안과 재확인은 모두 실제 Gemini가 생성하고 별도 의미 검토를 통과했다.** 두 프로세스의 PID는 `14264`와 `42760`이었다. 같은 SQLite 방, 서윤·민재 두 독립 세션에서 동일한 공개 이벤트 5건을 받았다. 공개한 첫 문장은 새 작업자의 협상·표현 입력에 들어갔다. [첫 제안 작업자](../../instance/budget-reaffirm-xhhpgpr8/propose.json) · [재확인 작업자](../../instance/budget-reaffirm-xhhpgpr8/speak.json) · [두 세션 원문](../../instance/budget-reaffirm-xhhpgpr8/public.json)

| 단계 | 실제 공개 전문 | 생성·검토 근거(각 파일에서 1부터) |
|---|---|---|
| 처음 | 1인당 여행 경비는 350,000 KRW 이내로 설정하는 편이 합리적일 것 같습니다. | `propose.json` 1번 `core_speech` → 4번 `defend/defend`. 긴 후보의 “예산 범위를 명확히 해야 이후 계획을 세울 때 무리가 없을 테니까요.”는 게시하지 않았다. |
| 같은 상한 방어 | 1인 예산은 350,000 KRW 이내로 유지하겠습니다. | `speak.json` 1번 후보는 재정 안정성 설명을 붙여 2번 검토가 거절했다. 3번의 독립된 수정 `core_speech` → 4번 `maintain/maintain`. |

두 템플릿의 `{value}`를 `350,000 KRW`로 한 번 치환하면 게시 전문과 일치했다. 두 문장 모두 `generated_core`이고 확정된 사실과 열린 협상 행동이 유지됐다. 첫 제안의 “합리적일 것 같습니다”는 그 안을 권하는 화자의 의견이다. 두 번째 작업자의 `previous_own`은 첫 방어의 항목 `budget`·값 `350000/KRW`·행동 `defend`·공개 전문을 정확히 담았다. 두 세션에 공개한 문장은 기준문·문체 복구문과 달랐고 각 의미검사의 요청·인용 전문 및 양쪽 행동이 일치했다.

자연 방의 실제 토론 주제는 현지 이동이었다. 첫 제안에서 서윤의 효율성 설명은 의미 검토 11·16번이 거절했고, 민재가 첫 택시 제안에 붙인 별도의 반응·거절 문구는 검토 모델의 긍정 판정에도 서버 검사를 통과하지 못했다. 서버는 Gemini가 각각 선택한 `formal_polite/none`과 `informal/attention` 문체에 확정값·제안 행동을 결합했다. 반면 두 토론 발언은 별도 생성한 핵심문이 그대로 검토를 통과했다. [최종 전체 방](../../instance/gemini-replay-2yxh6ndi/trace.json)

| 자연 방 번호 | 두 참가자에게 게시된 전문 | 출처 |
|---|---|---|
| 3 서윤 | 1인 예산은 ‘350,000 KRW’ 이내로 잡는 안을 제안합니다. | `structured`, 9번이 선택한 격식체 |
| 4 민재 | 오, 현지에서는 ‘택시’ 이용을 제안할게. | `structured`, 10번이 선택한 반말·감탄 |
| 7 서윤 | 현지 이동수단으로 대중교통 이용을 제안합니다. | `generated_core`, 생성 24번·검토 25번 |
| 8 민재 | 오, 생각해보니 현지 이동수단은 ‘대중교통’ 쪽으로 양보할게. | `generated_core`, 생성 28번·검토 29번 |

전체 방은 2026-11-27 22:22:10 KST에 시작해 128.86초에 완료됐다. 개인 `gemini-3.1-flash-lite` 23건·판사 `gemini-3.8-flash` 12건, 전송 오류와 방 수동 재시도는 0건이었다. 45초 토론창에서 43.33초에 접수한 민재 지시 1번은 `handled=true`였다. 원문을 실제로 담은 요청은 민재 협상 26번과 해당 지시 확인 27번뿐이었다. 판사 17·30번과 표현 검토, 공개 응답, Chrome 공개 대화에는 지시 원문이 없었고 서윤의 지시 목록은 비어 있었다.

첫 판사 입력에서 서윤은 `대중교통/must`, 민재는 `택시/must`였다. 마지막 판사 입력에서 서윤은 그대로이고 민재는 `대중교통/prefer`로 바뀌었다. 두 사람의 상한은 여전히 `350000/KRW`, `500000/KRW`였다. 최종 `budget`은 `350000/KRW`, `local_transport`는 `대중교통`이며 모두 `agreed/participant`였다. 서로 다른 예산 상한은 이 실행의 충돌 목록에 없었다. 민재의 이전 택시 제안과 그 뒤의 실제 양보는 대화 기록에 함께 남았다. 확정 자료가 없는 박물관 관람·한강 산책은 날짜별 후보였고, 롯데시티호텔 구로는 확인 필요, 휠체어 접근 가능 숙소는 AI 제안이었다.

두 독립 HTTP 세션의 공개 이벤트 11개·판정 이력 2개·최종 결정 12개 전체가 같았다. Chrome의 두 `360×800` 컨텍스트에서 Enter로 상세 항목을 열어 11개 화자·발언 전문을 각각 API와 대조했다. 날짜별 일정 2건·결정 행 12개가 양쪽에서 같았고 가로 넘침은 없었다. 실제 생성 5건 모두 원본 후보의 값 치환, 의미 검토 요청·응답, 공개 텍스트를 대조했다. 문체 복구 2건도 당시 모델의 문체 선택과 서버에 저장된 값·행동을 다시 결합한 결과가 공개문과 같았다.

자연 방에서는 서윤이 처음 말한 주제와 그다음 주제가 달랐다. 예산을 두 번 말했을 때의 효과는 같은 방을 두 프로세스가 이어서 읽은 별도 대조에서 확인했다. 두 재생 모두 이 제품 리비전에서 각 1회 관측했다. 모든 모델 응답이 자유 발화로 채택된다는 보장이나 사용량과 관계없는 모델 자체의 장기 기억은 이 결과로 입증할 수 없다. 각 실측의 파일별 제품 SHA-256을 현재 작업 트리와 대조했고, 두 실측이 기록한 공통 파일도 같았다.

## 판정 기준과 재현 조건

서윤이 한 사람당 `350,000 KRW` 상한을 처음 제안하고 같은 방에서 다시 방어할 때, 두 번째 공개문만 읽어도 앞선 상한을 유지한다는 점과 금액·통화를 알 수 있어야 한다. 서윤은 자신이 지정한 정중한 회계 담당자의 말투를, 민재는 친구에게 말하듯 짧은 반말을 사용한다. 민재가 직접 택시 필수를 철회하면 `대중교통/선호`로 양보하고, 미승인 조건·이유·약속 및 비공개 원문은 게시하지 않아야 한다. 두 사람은 같은 화면과 같은 공개 기록을 읽어야 한다. [ADR-009](../adr/travel.md) · [발언 흐름](../design/travel-flow.md) · [구현 명세](../design/travel-implementation.md)

두 실측에 동일한 서울 1박 2일 입력을 사용했다. 서윤은 예산 상한 35만 원과 대중교통·국립중앙박물관 전시 관람을, 민재는 상한 50만 원과 택시·한강 산책을 제출한다. 자연 재생은 입장부터 최종 판단·Chrome 결과까지 실행한다. 대조 재생은 서윤의 첫 안건을 예산으로 지정하고 다음 예산 방어 행동을 고정해, 같은 서울 입력에서도 판사가 다른 안건을 택하는 영향을 제거한다. 대조 재생의 두 발언 모두 Gemini가 작성한 후보여야 하며 정확히 게시된 전문이 별도의 실모델 의미 검토를 통과해야 한다. [서울 입력](../../scripts/two_person_seoul.json) · [전체 재생](../../scripts/replay_gemini_room.py) · [대조 재생](../../scripts/replay_reaffirmation.py)

## 수정 전과 첫 보완판

기존 원자료에서 3번과 7번은 모두 “1인 예산 상한에 대해 ‘350,000 KRW’ 안을 제안합니다.”였다. 이전 방의 `VOICE_PROMPT` 네 건(호출 순서 8·13·23·25)은 같은 `public_message`와 같은 서윤 페르소나를 받았고, 각 후보는 금액의 합리성·효율 또는 앞으로의 계획을 덧붙였다. 두 행동을 구별할 자신의 직전 발언이 입력에 없었다. 두 번 모두 `formal_polite/none` 복구를 선택해 같은 문장을 게시했다. 당시에도 민재는 대중교통으로 양보했고 두 사람 모두 35만 원 상한을 받았다. [이전 검증 기록](live-two-person-gemini-after.md) · [기존 방 원본](../../instance/gemini-replay-skvjxgxx/trace.json)

첫 보완판의 자연 재생은 106.70초에 완료됐다. 토론 안건은 현지 이동이었다. 서윤의 첫 제안과 토론 발언은 “1인 예산은 350,000 KRW 이내로 잡는 안을 제안합니다.”와 “현지에서는 '대중교통' 이용을 제안합니다.”로 달랐다. 민재는 “오, 생각해보니 현지 이동수단은 대중교통 쪽으로 양보할게.”라고 했다. 여기서는 두 발언의 주제도 달랐다. [첫 보완판 전체 방](../../instance/gemini-replay-3jsnfavm/trace.json)

같은 안건을 강제한 첫 대조 재생에서는 최초 제안이 `generated_core`, 재확인이 `structured`였다. 후자는 “1인 예산은 앞서 말씀드린 대로 ‘350,000 KRW’ 이내로 유지하겠습니다.”로 의미는 맞았으나, 두 발언 모두 새로 생성한 문장을 게시해야 하는 대조 기준에 미달했다. 두 번째 발언의 첫 `core_speech`는 원본 기준문과 완전히 같았다. 수정 응답의 `core_speech`는 “1인 예산은 말씀드린 대로 {value} 이내로 유지하겠습니다.”였다. 두 번의 의미 검사 기회를 모두 추가 판단이 딸린 긴 후보에 사용해 이 새 핵심문에는 검토 요청이 없었다. 의미 검사를 통과했을지는 관측하지 못했다. [첫 대조 제안](../../instance/budget-reaffirm-lcazwgrs/propose.json) · [첫 대조 재확인](../../instance/budget-reaffirm-lcazwgrs/speak.json) · [첫 대조 공개 결과](../../instance/budget-reaffirm-lcazwgrs/public.json)

첫 보완판은 가짜 키를 사용한 WSGI 77/77개(7.416초), 루프백 HTTP 77/77개(10.048초), 발언·동의·구형 방 집중 시험 33/33개(2.155초)가 통과했고 생략은 없었다. 샌드박스에서 루프백 접속이 Windows 오류 10013으로 차단된 HTTP 실행은 허용된 환경에서 전체 재실행했다.

## 두 번째 보완판 · 같은 예산을 다시 말한 Gemini 대조 재생

첫 작업자(PID `36816`)와 두 번째 작업자(PID `23932`)는 같은 SQLite 방을 차례대로 열었다. 모델은 `gemini-3.1-flash-lite`였다. 입장·준비·공개 조회에는 서윤과 민재의 독립 Flask 세션을 사용했다. 첫 제안 데이터와 다음 토론 행동, 토론 개시 이벤트를 고정했고, 한국어 문장 생성과 의미 검토는 실제 Gemini를 호출했다. 두 작업자는 각각 `judge`, `floor` 단계로 커밋했다. 서윤·민재 두 세션의 공개 이벤트 5건은 완전히 같았다.

| 서윤의 발언 | 두 세션에 게시된 전문 | 원본 JSON 호출 순서(1부터) |
|---|---|---|
| 예산 제안 | 1인당 예산은 350,000 KRW 이내로 설정하는 편이 합리적일 것 같습니다. | `propose.json` 1번 응답의 `core_speech`, 4번 의미 검토에서 원문과 후보 모두 `defend`. “합리적일 것 같습니다”는 이 상한을 권하는 화자의 의견이다. 긴 후보의 전체 지출·일정 계획 설명은 게시되지 않았다. |
| 예산 재확인 | 1인 예산은 이전과 같이 350,000 KRW 이내로 유지하겠습니다. | `speak.json` 1번의 “안정적일 것 같습니다”는 2번 검토에서 `maintain` → `defend`로 판정돼 거절됐다. 3번 수정 응답의 `core_speech`는 4번 검토에서 원문과 후보 모두 `maintain`이었다. |

두 문장의 `voice_source`는 `generated_core`였다. 각 후보의 `{value}`를 서버값으로 한 번 치환해 실제 공개 텍스트와 글자 단위로 비교했다. 별도의 검토 요청은 두 경우 모두 **게시한 문장 전체**를 받았다. 긍정 응답의 `added`·`missing`은 비어 있고, 양쪽 행동 인용과 `matches`는 기준문과 후보 전문을 포괄했다. 민재의 첫 택시 제안은 `structured`였다. 두 후보의 검토 모델이 제안을 양보로 분류해 서버가 행동 불일치를 거절했다. [제안 작업자 원본](../../instance/budget-reaffirm-vtm51ckm/propose.json) · [재확인 작업자 원본](../../instance/budget-reaffirm-vtm51ckm/speak.json) · [양쪽 공개 결과](../../instance/budget-reaffirm-vtm51ckm/public.json)

첫 표현 요청에서 이전 화자의 입장과 최근 발언은 모두 비어 있었다. 두 번째 작업자의 협상 입력과 첫·수정 표현 요청에는 똑같은 `previous_own`이 있었다. 안건은 `budget`, 이전 행동은 `defend`, 값은 `350000/KRW`, 발언은 위의 첫 공개문 **전문**이었다. 최근 문맥은 서윤의 예산 제안, 민재가 실제로 게시한 택시 제안, 토론 개시 공지 순이었다. 탈락한 화법 초안과 사적 입력은 포함되지 않았다. 두 프로세스의 대화 연속성은 방 조회에서 읽어 복원했다. 이 대조 재생은 모델 서비스가 자체적으로 지난 호출을 기억하는지 측정하지 않는다.

같은 보완판의 자연 방 3번에서 “하고 싶은 활동으로는 국립중앙박물관 전시 관람을(를) 제안합니다.”가 게시됐다. 12번 생성 응답이 남긴 조사 선택 표기가 15번 의미 검토를 통과해 최종 텍스트에 노출됐다. 이 방은 144.34초, 모델 전송 40건이었고 근거 검토 1회에서 응답 형식 오류가 발생했다. 예산·교통 최종 결정과 민재의 동의, 양쪽 Chrome 화면의 화자·본문 11건은 일치했다. [두 번째 보완판 전체 방](../../instance/gemini-replay-1l5jje5l/trace.json)

## 세 번째 보완판 · 의미 검토의 오판

예산 대조에서 서윤의 두 발언은 “1인당 예산을 350,000 KRW 이내로 설정하는 안을 제안합니다.”와 “1인 예산은 350,000 KRW 이내로 유지하겠습니다.”였다. 두 문장 모두 `generated_core`였고, 서로 다른 작업자 `38640`·`4884`가 같은 방을 사용했다. 재확인 첫 후보에 붙인 경비 효율성 주장은 거부됐다. [대조 제안](../../instance/budget-reaffirm-itk1gbvd/propose.json) · [대조 재확인](../../instance/budget-reaffirm-itk1gbvd/speak.json) · [대조 공개 결과](../../instance/budget-reaffirm-itk1gbvd/public.json)

자연 방은 125.75초에 끝났고 37번의 전송이 모두 응답했다. 서윤·민재의 이동 조건과 최종 합의, 11개 발언과 두 Chrome 화면은 일치했다. 그러나 실제 민재 4번은 “아, 딴 건 몰라도 현지에서는 택시 이용하자. 이게 제일 편하잖아.”였다. 15번 검토 응답은 두 문장을 통째로 “현지에서는 ‘택시’ 이용을 제안해요.”에 대응시키고 `faithful: true`를 반환했다. 이용자가 제출한 것은 택시 필수 조건이었다. 편의성 최상급은 승인된 근거가 없어 실패로 판정했다. [세 번째 보완판 원본](../../instance/gemini-replay-agb91k7h/trace.json)

## 독립 회귀 시험과 화면 검증

Windows, Python 3.11.9, Flask 3.1.1, LangGraph 1.2.15, SQLite 3.45.1에서 두 번째 보완판은 WSGI 79/79개(7.774초), 루프백 HTTP 79/79개(9.923초), 집중 시험 35/35개(2.293초)가 통과했다. 건너뛴 시험은 0개였다. 회귀 시험의 모델·검색은 고정 응답을 사용했다.

세 번째 보완판은 WSGI 83/83개(8.196초), 루프백 HTTP 83/83개(10.255초), 집중 시험 39/39개(2.057초)가 통과했고 생략은 없었다. 별도로 두 번째 방의 12번 실제 생성 응답과 15번의 **종전 긍정 판정**을 그대로 재투입했다. 검토기가 받은 전문은 매번 “하고 싶은 활동으로는 국립중앙박물관 전시 관람을 제안합니다.”였고, 수정 전 조사 표기가 포함된 옛 인용은 새 문장을 승인하지 못해 안전한 복구문이 게시됐다. 조사 경계 8건에서 택시·경주는 `를`, 서울은 `로`, 부산은 `으로`였고 `350,000 KRW을(를)`, 날짜 뒤 `이(가)`, 띄어 쓴 이중 조사, 지원하지 않는 짝은 거절됐다.

최종 코드 `692bcd1c7bbf`에서 WSGI **85/85개**(7.811초), 루프백 HTTP **85/85개**(10.527초), 집중 시험 **41/41개**(2.122초)가 통과했다. 생략은 0개였다. 추가로 세 번째 방의 실제 택시 생성 응답 14번과 의미 검토 응답 15번을 첫 시도와 재시도 모두에 주입했다. 서버가 예전 `faithful: true`를 거절해 “현지에서는 ‘택시’ 이용을 제안해요.”를 공개했다. 같은 공개 경로에 이전 실측의 예산 제안과 민재 양보 후보·긍정 응답을 각각 입력하면 두 문장은 원래 전문 그대로 `generated_core`로 게시됐다. 독립된 문장으로 덧붙인 주장을 막은 사례다. 한 문장 안에 합쳐진 설명이 정당한지는 계속 의미 검토의 정확도에 영향을 받는다.

| 확인할 경계 | 실행 결과 |
|---|---|
| 방·화자·안건·값 | 다른 방·사람·안건의 같은 숫자, 통화 또는 금액 변경, 같은 값의 과거 양보·대안·확인은 새 방어를 재확인으로 만들지 않았다. 표시가 빠진 구형 발언이 더 최근이면 이전의 표시 있는 발언으로 소급하지 않았다. 일치하는 본인의 최신 같은 안건 입장만 재사용했다. |
| 게시 시점과 재시작 | 임대 만료 후 재시도에서 늦은 이전 작업 결과는 커밋되지 않았다. 최초 병렬 제안은 서로의 미게시 문장을 보지 못했다. 새 앱 인스턴스는 게시한 첫 발언을 사용했고 과거 이벤트·양쪽 공개본이 보존됐다. 모델 실패 시 두 번째 발언도 값과 유지 여부를 전달했다. |
| 의미와 복구 | 추가 약속이 들어간 긴 후보의 앞부분을 잘라 게시하지 않았다. 별도 생성한 핵심문도 행동 변경, 미승인 숫자, 금액 중복, 비공개 원문, 이전 제안 복사, 부정·조건을 잘라낸 사례에서 차단됐다. 1차 대조의 실패 형태를 고정 응답으로 재현해 재작성된 핵심문에 두 번째 검사 기회가 주어지는지 확인했다. 핵심문이 없으면 완전한 긴 후보도 검사했다. |
| 동의·구형 방 | 다른 좌석의 동의·출처 없는 값·모델의 자율 양보를 사람의 동의로 확정하지 않았다. 비공개 지시 검토 실패는 보류 후 재시도했다. 예전 완료 방의 공개 기록·판정·결과를 복원해 두 세션에서 재조회했다. |

독립 Chrome 키보드 점검은 첫 보완판과 최종판 양쪽 실측의 1~7번 공개 발언을 각각 로컬 시험방에 넣고 `360×800`에서 진행했다. 대화에 포커스를 둔 뒤 Home으로 0px까지 올라가 같은 방에 각 실행의 8번 민재 발언을 추가했다. 다음 조회가 끝나도 읽던 위치와 대화 포커스가 유지됐다. `aria-live="polite"` 안내 원문은 민재 이름과 실제 양보 전문을 담았다. Tab 한 번으로 `새 발언 보기`로 이동해 Enter를 누르자 맨 아래로 이동했고 버튼이 숨겨졌다. Chrome `157.0.8103.51`, Playwright `1.65.2`를 사용했다. 음성 낭독기 자체의 발음은 점검하지 않았다. [발언·기억 시험](../../tests/test_turn_memory.py) · [표현·검토 시험](../../tests/test_persona.py) · [동의 회귀 시험](../../tests/test_pair_intent.py)

## 재현 명령과 원자료

저장소 루트에서 Windows PowerShell로 실행한다. `GEMINI_API_KEY`의 아래 값은 회귀 시험 프로세스용이다.

```powershell
$env:GEMINI_API_KEY = 'offline-test-key'
$env:TRAVEL_TEST_TRANSPORT = 'wsgi'
.\.venv\Scripts\python.exe -B -m unittest discover -s tests
$env:PYTHONPATH = 'tests'
.\.venv\Scripts\python.exe -B -m unittest -v test_turn_memory test_persona test_pair_intent test_judge.JudgeTests.test_legacy_room_mixed_events_and_mediator_contract_survive_refresh
$env:TRAVEL_TEST_TRANSPORT = 'http'
.\.venv\Scripts\python.exe -B -m unittest discover -s tests
```

실제 모델 재생은 구성된 Gemini 키를 사용할 수 있는 새 PowerShell에서 실행한다. 외부 응답, 주제와 시간은 실행마다 달라진다. 전체 재생은 루프백 HTTP·Chrome을, 예산 대조 재생은 개별 Python 작업자 두 개를 사용한다.

```powershell
.\.venv\Scripts\python.exe -B -u scripts/replay_gemini_room.py --browser
.\.venv\Scripts\python.exe -B -u scripts/replay_reaffirmation.py
```

아래 명령은 보존한 실측에 추가 요금 없이 두 화면과 두 예산 후보의 독립 의미 검토를 검산한다. 네트워크 연결이 필요하지 않다.

```powershell
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
@'
import json
from pathlib import Path
from travel_app.tone import supported_speech

def read(path):
    return json.loads(Path(path).read_text(encoding="utf8"))

room = read("instance/gemini-replay-2yxh6ndi/trace.json")
assert room["scenario"] == read("scripts/two_person_seoul.json")
assert room["public_views"][0] == room["public_views"][1]
assert room["browser"][0] == room["browser"][1] and not room["browser"][0]["overflow"]
assert room["browser"][0]["speech"] == [e["text"] for e in room["events"]]
assert room["browser"][0]["speakers"] == [e["speaker"] for e in room["events"]]
folder = Path("instance/budget-reaffirm-xhhpgpr8")
public = read(folder / "public.json")
assert public["views"][0] == public["views"][1]
pair = [e for e in public["views"][0] if e["speaker"] == "서윤의 에이전트" and e["topic"] == "budget"]
first, second = [read(folder / name) for name in ("propose.json", "speak.json")]
assert len(pair) == 2 and pair[0]["text"] != pair[1]["text"] and first["worker_pid"] != second["worker_pid"]
assert second["debate_input"]["public_turn_memory"]["previous_own"] == dict(
    topic="budget", value=public["budget"]["value"], act="defend", speech=pair[0]["text"])
for e, stage, gen, check, act in zip(pair, (first, second), (0, 2), (3, 3), ("defend", "maintain")):
    source, review = stage["calls"][gen], stage["calls"][check]
    assert e["voice_source"] == "generated_core" and source["prompt"] == "VOICE_PROMPT"
    assert source["response"]["core_speech"].replace("{value}", "350,000 KRW") == e["text"]
    assert review["prompt"] == "FAITHFULNESS_PROMPT" and review["request"]["candidate_speech"] == e["text"]
    assert supported_speech(review["response"], review["request"]["public_message"], e["text"],
                            action=act, value="350,000 KRW", label="1인 예산 상한")
print("OK")
'@ | .\.venv\Scripts\python.exe -B -
```

| 보존한 원자료 (`instance/` 기준) | SHA-256 |
|---|---|
| `gemini-replay-skvjxgxx/trace.json` · 수정 전 | `62b5b2aad5423cd86c9d5d77027d22213aa39413543dc2d3029d849ef58c68f4` |
| `gemini-replay-3jsnfavm/trace.json` · 첫 보완판 | `a79b4a2266daeebcb94177b9872ed37efa75253661c4b0a6692468a7df9a65d7` |
| `budget-reaffirm-lcazwgrs/propose.json` | `ea0c192baa5681c4aa33239d79b965597fc0ec3ed2d83f386e4a5882fed95e2e` |
| `budget-reaffirm-lcazwgrs/speak.json` | `073a6a911635257812d58611e3527ab0ba6b17dfd7ab9a91d35d239a5dad2812` |
| `budget-reaffirm-lcazwgrs/public.json` | `71a32963cbad1bd26200495791b6417d452c835729061a76a87c6f37e7597c85` |
| `gemini-replay-1l5jje5l/trace.json` · 두 번째 보완판 | `f0a6f5db23757790ec00fa4601078a45ff68ff276ac312ce2d983099e5aaa03a` |
| `budget-reaffirm-vtm51ckm/propose.json` | `7f993257875d64137b8ebaed5f246ba7db99a29fb201a0a019deb2d40cc8a99e` |
| `budget-reaffirm-vtm51ckm/speak.json` | `173c78f94acf99bff69afaeca904ad6b13b8a90ac2abd8c1fda1b087c37db568` |
| `budget-reaffirm-vtm51ckm/public.json` | `097789645c7084d774a026d9733785f612dd60e30930962d39857278d5fe7cff` |
| `gemini-replay-agb91k7h/trace.json` · 세 번째 보완판 | `4e3111d2c6f5b402537510c5ebb95c2aa6d60ab795a40fb4ad17b499e16f0b74` |
| `budget-reaffirm-itk1gbvd/propose.json` | `922dc1ac00bc3b531fbf4a1ff1f0b3512a06106f3744ac60ed3429a4acc4c321` |
| `budget-reaffirm-itk1gbvd/speak.json` | `603421280c7c2527a1387a69c20b0105125e9f2a623d67e173c31e9f4e7bac37` |
| `budget-reaffirm-itk1gbvd/public.json` | `01e65c38654f7da8f1d32a06d71f9d90355e4c1cffd62153a23c0d84ca1fa0c6` |
| `gemini-replay-2yxh6ndi/trace.json` · 최종 전체 방 | `d5d691fe4a86a656d8186b5525008a12ac158daa909941c470f83dd42acbdc11` |
| `budget-reaffirm-xhhpgpr8/propose.json` · 최종 | `1b188e8413127c544b6e1cb88967d76f0bbe89cc3b2e78f152629eaf4bb09442` |
| `budget-reaffirm-xhhpgpr8/speak.json` | `1a0f8ee537cf0a0e91c1157d72ae71efcc57ba26ffeadaac250b570e19a51ca2` |
| `budget-reaffirm-xhhpgpr8/public.json` | `4670a32b26ba4ffee1282f0d0814cb08e213068aba66e6ec93a41c8fb04cc326` |

실행 기준은 `213567c5046e85bc906b49f8f2b692b306bcd2c5` 위 작업 트리다. 최종 Python·JavaScript 제품 21개 파일 SHA-256 집합 지문은 `478254f109398507958aa31e7c3e46df4bc1e09ae71572e868fb7edb62f40611`, HTML·CSS를 포함한 제품 23개는 `8e037e9021c5e2ac47fe9c0799648dee4946aa34f5fcd1e71b40e017df658729`, `tests/*.py` 15개는 `b17d67ed124fa52518d50a4995f87dd1c7b34f932c62dbfaf71a212793142e5f`다. 지문은 상대 POSIX 경로순으로 정렬한 `경로 + 공백 + 파일 SHA-256 소문자 + LF` 문자열을 UTF-8로 연결해 SHA-256을 계산했다.

| 입력 파일 | SHA-256 |
|---|---|
| `travel_app/tone.py` | `692bcd1c7bbfd0ee2345ecc85c62567b5d74ce5a0b7752ef45553b7a0f048813` |
| `travel_app/prompts.py` | `9a0f13447357610ace137f20961d1ea7265365f91833dcffb4550a3310859eb5` |
| `travel_app/graph.py` | `b13b1ba09c48dd176dc30d231eb8c86af97c13aeb71cfc80d3b11e4c0b154531` |
| `travel_app/store.py` | `dedced1915838efae5bdfb0dc77b2e342de3278196cf850d8a829ce0decf4592` |
| `tests/test_turn_memory.py` | `7477c910a90a310b5bc2823f95181e3abfd31adcf21e3389b395fde87fabaabf` |
| `tests/test_persona.py` | `4ae11ff6638dde8dfce282632f989b7ec7c8c4f46b8bc66934ce9b39eb664e9e` |
| `tests/test_room_recovery.py` | `db45b0b015813ce4c4701790fcceaa6fbbfe6e34b91face863f41d1f69a564fd` |
| `scripts/replay_gemini_room.py` | `8d5ab4688c2f5c485d2f8b0d5dbd347506271e409ffe77f488891dcee5c23821` |
| `scripts/replay_reaffirmation.py` | `2d0240a42a5bed2b11c5a57e0c111978718b10dac87898557f0653c4199fbc0f` |
| `scripts/two_person_seoul.json` | `8fd5306ae46adc47364ebe355ebdd9cf2ccdab41fb17db35a28fd95b5d4759df` |

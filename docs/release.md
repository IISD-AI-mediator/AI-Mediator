# 동행 v1.0.1

이 버전은 여행방의 항공 운임과 식당 검색에서 출처를 해석하는 방식을 수정한다.

* 같은 노선·날짜·시간대·통화의 운임이라도 인원과 왕복 조건이 분명해야 ‘1인 왕복 운임’으로 표시한다. 2인 합산 금액, 편도 요금, 조건을 확인할 수 없는 인용은 ‘확인 필요’로 표시한다.
* 요청한 숙소 인근 지점이 해당 메뉴를 판매한다는 근거를 확인한다. 다른 지점에서만 판매하는 메뉴는 여행방에서 확인된 식당 정보로 쓰지 않는다.
* 이전 버전에서 만든 방을 다시 열 때도 저장된 출처를 바탕으로 공개할 검색 정보를 판단한다.

로컬 회귀 시험 15개가 통과했다. 별도로 v1.0.0에서 만든 방을 두 번 다시 열어, 2인 총액은 숨겨지고 출처가 있는 1인 왕복 73만 원은 유지되는 것을 확인했다. 운임과 식당의 출처에는 고정된 시험 응답을 사용했다. [회귀 시험 코드](https://github.com/IISD-AI-mediator/AI-Mediator/blob/v1.0.1/tests/test_quote_and_branch_conditions.py)

Windows용 Conda 환경은 `iisd`, Python은 3.13이다. 실행 방법, 화면 흐름과 모델 사용 비용은 README에 정리했다. 기존 `v1.0.0` 태그와 릴리스는 당시 배포한 커밋을 가리킨다.

[동행 웹앱](https://iisd-travel-mediator-bogc.onrender.com) · [실행 방법과 아키텍처](https://github.com/IISD-AI-mediator/AI-Mediator/blob/v1.0.1/README.md) · [LangGraph 이미지](https://github.com/IISD-AI-mediator/AI-Mediator/blob/v1.0.1/docs/langraph/travel-graph.png) · [이전 릴리스](https://github.com/IISD-AI-mediator/AI-Mediator/releases/tag/v1.0.0)

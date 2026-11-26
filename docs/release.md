# 동행 v1.0.0

여행방에 팀원을 초대하고 각자의 일정, 예산, 이동 수단과 필수 조건을 제출하면 개인 에이전트와 결정자가 공동 여행안을 작성한다.

* 방장은 확정된 계획과 중재자의 성격을 설정한다. 참여자들은 초대 링크로 접속해 개인 의견과 에이전트의 말투를 정한다.
* 전원이 준비하면 LangGraph가 개인별 제안을 병렬로 수집한다. 필요할 때 검색 에이전트가 출처와 확인 시각을 기록한다.
* 의견이 갈리면 단체 채팅이 열린다. 참여자는 자기 에이전트에게 추가 지시를 보내고, 결정자는 잠정 결정을 수정하거나 양립할 수 없는 조건을 미합의로 기록한다.
* 최종 화면에서 고정 조건, 결정 이유, 일자별 일정과 추가 확인할 정보를 확인할 수 있다. 활동·숙소의 출처가 목적지를 뒷받침할 때만 세부 장소를 확정한다.

Windows에서는 저장소 최상위에서 `conda env create -f environment.yml`, `conda activate iisd`를 차례로 실행한다. PowerShell에 `GEMINI_API_KEY`를 설정한 뒤 `python -m travel_app`으로 시작하면 `http://127.0.0.1:8000`에서 열 수 있다.

4인 여행방 20개에서 즉시 합의와 파이트 후 합의를 각각 10회 확인했다. 이 통합 시험은 실제 Flask·LangGraph·SQLite에 고정된 Gemini·검색 응답을 연결해 실행했다.

[실행 방법과 비용](https://github.com/IISD-AI-mediator/AI-Mediator/blob/v1.0.0/README.md) · [LangGraph 이미지](https://github.com/IISD-AI-mediator/AI-Mediator/blob/v1.0.0/docs/langraph/travel-graph.png) · [검증 기록](https://github.com/IISD-AI-mediator/AI-Mediator/blob/v1.0.0/docs/test/group-travel.md)

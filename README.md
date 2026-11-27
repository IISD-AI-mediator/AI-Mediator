# 동행 · AI 여행 조율

동행은 함께 여행할 2~8명이 예산·일정·선호를 조율하는 웹앱이다. 개인 에이전트가 각자의 조건을 제안하면 판사 에이전트가 조율 모드에서 여행안을 결정한다. 의견이 갈리면 파이터 모드에서 쟁점을 논의하고, 판사가 최종 여행안과 미해결 항목을 정리한다. 중앙대학교 Interactive Intelligent System Design 팀 프로젝트다. [제품 요구사항](docs/prd/travel.md)

## 실행 방법

[배포된 동행 열기](https://iisd-travel-mediator-bogc.onrender.com)

`여행방 만들기`에서 닉네임과 총인원을 정하면 방이 열린다. 바로 다음 화면에서 `링크 복사`를 눌러 동행에게 보내고, `내 여행 조건 입력`을 눌러 계속한다. 초대받은 사람은 받은 링크를 열어 닉네임으로 같은 방에 입장한다.

Windows에서 로컬로 실행하려면 Anaconda PowerShell Prompt에서 저장소 루트로 이동한다. 처음 한 번 Python 3.13 환경을 만든다.

```powershell
conda env create -f environment.yml
```

이미 `iisd` 환경이 있으면 의존성을 갱신한다.

```powershell
conda env update -n iisd -f environment.yml
```

저장소 루트에 UTF-8 텍스트 파일 `.env`를 만들거나 기존 파일을 열고, 아래 예시 값을 자신의 Gemini API 키로 바꿔 저장한다. 이 파일은 Git에서 제외된다.

```dotenv
GEMINI_API_KEY=여기에_자신의_API_키_입력
```

앱은 `.env`에서 `GEMINI_API_KEY`만 읽는다. PowerShell이나 호스팅 서비스에 같은 이름의 환경변수가 설정되어 있으면 빈 값이어도 그 값이 우선한다. 키를 저장한 뒤에는 저장소 루트에서 다음 명령으로 실행한다.

```powershell
conda activate iisd
python -m travel_app
```

브라우저에서 [로컬 동행](http://127.0.0.1:8000)을 연다. 한 PC에서 두 명으로 참여하려면 일반 창과 시크릿 창을 사용한다.

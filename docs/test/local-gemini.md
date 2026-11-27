# KEY-01 · 저장된 Gemini 키로 로컬 앱 시작

2026-11-27, Windows에서 Python 3.11.9, Flask 3.1.1, Werkzeug 3.1.9, python-dotenv 1.2.4와 SQLite로 확인했다. 기준 커밋은 `213567c5046e85bc906b49f8f2b692b306bcd2c5`다. [ADR-007](../adr/travel.md#adr-007--로컬-gemini-키를-앱과-제공자-점검에-연결한다) · [이전 의미 판정 검증](semantic-review.md)

## 수정 전 재현

기준 커밋의 `travel_app`과 `VERSION`을 임시 디렉터리에 풀고 루트의 `.env`에 가상 키를 저장했다. 프로세스에서 `GEMINI_API_KEY`를 제거하고 `create_app`에 임시 SQLite 경로와 `START_WORKER=False`를 전달했다. 개인 모델에 저장된 값과 파일의 값이 일치하는지 검사한 결과는 `False`였다. 실제 개발 작업 트리에서도 수정 전에 루트 파일에 키가 있었지만 앱 설정에서 키를 찾을 수 없었다.

## 자동 시험

집중 시험은 임시 프로젝트 루트와 별도의 작업 디렉터리를 만들고 격리된 프로세스 환경을 사용한다. 작업 디렉터리의 `.env`와 `.flaskenv`에는 프로젝트 파일과 충돌하는 값을 넣었다. 프로젝트 파일의 파싱, 앱 생성, SQLite 연결과 워크플로 구성을 실제 코드로 실행했다. [집중 시험](../../tests/test_local_gemini.py)

| 확인한 경로 | 기대값과 관찰 결과 |
| --- | --- |
| WSGI 앱 | UTF-8 BOM 파일의 따옴표 안에 공백, `${PART}`, `#`를 포함한 값을 넣었다. 따옴표 밖의 주석은 제거되고 안쪽 문자는 그대로 두 모델에 전달됐다. 파일의 `ROOM_CREATE_CODE`는 앱에 반영되지 않았고 프로세스 환경은 실행 전과 동일했다. `/healthz`가 `ok`를 반환했다. |
| 명시한 설정과 프로세스 키 | 앱 설정에 키나 빈 문자열을 지정하면 프로세스 키가 있어도 설정값이 전달됐다. 프로세스에 키나 빈 문자열을 지정하면 파일에 키가 있어도 프로세스 값이 전달됐다. 각 경우 하위 조회를 시도하면 실패하도록 해 두 경로 모두 조회를 생략하는지 확인했다. |
| 키가 없는 상태 | 루트 파일 부재, 다른 항목만 존재, 키 이름만 선언, 빈 값의 네 경우에 두 모델의 키는 빈 문자열이었다. 앱은 기동되어 상태 요청에 200으로 응답했고 모델 호출 시 기존 키 설정 오류가 발생했다. |
| Waitress 미설치 상태의 모듈 실행 | `FLASK_SKIP_DOTENV=0`으로 설정하고 `travel_app.__main__`을 실행했다. Werkzeug 서버에 환경에서 지정한 호스트와 포트, 프로젝트 파일의 키를 쓰는 앱, 스레드 사용과 재로딩 해제가 전달됐다. 서버 소켓을 여는 함수는 대역으로 교체했다. 작업 디렉터리의 두 설정 파일은 프로세스 환경에 영향을 주지 않았다. |
| 릴리스 제공자 점검 | 버전 미지정과 불일치에서 키 조회·제공자 생성·출력은 모두 없었다. 버전이 일치하면 개인 모델 생성, 판사 모델 생성, 개인 모델 검색 세 호출이 프로젝트 파일의 키를 사용했다. 생성·검색 응답을 대체해 세 건의 `verified` 출력을 확인했다. |

다음 명령은 별도 PowerShell 프로세스에서 시험용 환경변수를 설정한다.

```powershell
powershell -NoProfile -Command {
    $env:GEMINI_API_KEY = "unit-test-placeholder"
    $env:TRAVEL_TEST_TRANSPORT = "wsgi"
    .\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_local_gemini.py -v
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    .\.venv\Scripts\python.exe -B -m unittest discover -s tests
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    Remove-Item Env:TRAVEL_TEST_TRANSPORT
    .\.venv\Scripts\python.exe -B -m unittest discover -s tests
    exit $LASTEXITCODE
}
```

집중 시험 6개가 0.182초에, WSGI 전체 시험 45개가 6.015초에 통과했다. 별도 기본 전송 실행에서도 로컬 HTTP를 포함한 전체 45개가 7.970초에 통과했다. 생략한 시험은 없다.

## 실제 모델과 검색 호출

같은 작업 트리에서 개발자가 저장해 둔 루트 파일의 키로 별도 점검을 수행했다. `python -m travel_app`과 임시 SQLite로 시작한 로컬 서버의 `/healthz`가 HTTP 200과 `ok`를 반환했다. 아래 세 입력에는 실제 외부 제공자 요청이 총 네 번 이뤄졌고 모두 응답했다. 점검에는 키 값을 기록하지 않았다.

| 입력과 실제 호출 | 기대값과 관찰 결과 |
| --- | --- |
| 채식 라멘을 확인하는 개인 모델 `gemini-3.1-flash-lite` | 제품의 인용 검토 지시문에 쇠고기 육수인 0번과 식물성 재료만 쓰고 주차장은 없다는 1번을 보냈다. 0번은 거절, 1번은 승인됐다. |
| 박물관 관람 뒤 강변 산책을 심사하는 판사 모델 `gemini-3.8-flash` | 제품의 활동 검토 함수에 두 필수 활동을 순서대로 수행하는 일정을 전달했다. 두 활동이 모두 승인됐다. |
| 서울 국립중앙박물관 전시 관람 검색 | `grounded_search`가 Google 검색과 후속 인용 검토를 실행했다. HTTPS 출처 6개가 돌아왔고 요청을 뒷받침하는 출처로 1개가 채택됐다. 검색 결과 수는 이 실행에서 관찰한 값이다. |

## 실행 파일

| 파일 | SHA-256 앞 16자리 |
| --- | --- |
| `travel_app/config.py` | `C206A212C1B3604C` |
| `travel_app/__init__.py` | `CA9F39922F843D56` |
| `travel_app/__main__.py` | `34B2BA476FD4A212` |
| `scripts/check_live_providers.py` | `1DE406C464B88D97` |
| `requirements.txt` | `743C761BDF46D77D` |
| `README.md` | `EFC1759C4C21F0E2` |
| `.env.example` | `A6FDE683CCDD09D9` |
| `tests/test_local_gemini.py` | `84371FEAAF5D3CE0` |

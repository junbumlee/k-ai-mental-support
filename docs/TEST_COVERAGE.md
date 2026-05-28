# 테스트 커버리지 평가 및 테스트 인프라 구축 결과

작성일: 2026-05-28

## 요약

이 저장소에는 기존 테스트 실행기, 커버리지 설정, 테스트 파일이 없었다. 백엔드 기능이 `api/index.py` 한 파일에 집중되어 있어 FastAPI `TestClient`와 `pytest-cov` 기반의 단위·라우트 테스트 인프라를 먼저 구축했다.

최종 실행 결과:

```text
29 passed, 1 warning in 0.10s
api/index.py coverage: 92.94%
```

## 구축한 테스트 인프라

| 파일 | 역할 |
| --- | --- |
| `requirements-dev.txt` | 개발·테스트 전용 의존성 분리: `pytest`, `pytest-cov` |
| `pytest.ini` | 기본 테스트 경로와 coverage 실행 옵션 정의 |
| `.coveragerc` | coverage 측정 범위와 리포트 포맷 정의 |
| `tests/conftest.py` | FastAPI 테스트 클라이언트, 세션 쿠키, 환경변수 격리 fixture |
| `tests/test_utils.py` | 세션 서명, 안전 리다이렉트, 위기 문구, JSON 추출, 금지문자 제거, 프롬프트 구성 테스트 |
| `tests/test_routes.py` | 인증/온보딩/프로필/분석/리더 API 라우트 테스트 |
| `tests/test_providers.py` | MiniMax/NVIDIA LLM 호출 래퍼의 성공·실패·스크러빙 분기 테스트 |

## 실행 방법

```bash
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
python -m pytest
```

또는 가상환경을 직접 지정해 실행한다.

```bash
.venv/bin/python -m pytest
```

`pytest.ini`에 coverage 옵션을 넣어 두었기 때문에 위 명령만으로 터미널 커버리지 표와 `coverage.xml`이 생성된다.

## 평가한 기존 공백

초기 상태에서 확인된 공백:

- 테스트 파일이 없었다.
- `pytest`, coverage 설정이 없었다.
- `/api/analyze`, `/api/leader`의 안전장치와 LLM 폴백 경로를 자동 검증하지 못했다.
- Google OAuth, 세션 쿠키, 온보딩 필수 프로필 검증을 회귀 테스트로 막지 못했다.
- LLM 응답의 JSON 추출, 금지문자 제거, 구두점 정규화 같은 품질 방어선이 테스트되지 않았다.

## 보완한 핵심 시나리오

### 인증·세션

- 서명된 세션 쿠키 roundtrip
- 변조된 토큰, 만료 토큰 거부
- 로그인 전 `/`, `/api/analyze`, `/api/leader`, `/api/profile` 접근 차단
- 프로필 미완성 사용자의 `/leaders` 접근 시 온보딩 리다이렉트
- `/api/me`, `/logout`, `/api/logout` 동작

### 온보딩·프로필

- 필수 프로필 필드 누락 시 `400`과 missing 목록 반환
- 프로필 저장 시 기존 세션에 병합하고 세션 쿠키 재발급
- 입력값 trim, 빈 값 제거, 길이 제한

### CBT 분석 API

- 위기 문구가 들어오면 LLM 호출 없이 즉시 `mode=crisis` 반환
- MiniMax 1차 성공 시 NVIDIA 폴백 미호출
- MiniMax/NVIDIA 모두 실패 시 템플릿 fallback 반환
- payload validation 실패 시 `422`

### LLM provider wrapper

- API key 미설정 시 외부 호출 없이 `None`
- MiniMax `base_resp` 실패, 빈 choices, HTTP/parse 실패 처리
- MiniMax content가 list로 올 때 병합
- NVIDIA 성공, 빈 choices, 네트워크 예외 처리
- LLM 응답에 한자·가나 문자가 섞여도 payload scrub 수행

### 유틸리티 방어선

- `_safe_next()`가 외부 URL, `//`, `/auth/*`, `/api/*`를 차단
- `<think>...</think>`와 코드펜스가 붙은 LLM 응답에서 JSON 블록 추출
- 전각·아랍어 구두점 정규화
- 카테고리 힌트와 반복 맥락이 프롬프트에 포함되는지 검증

## 커버리지 결과

최종 실행 커버리지:

```text
Name           Stmts   Miss Branch BrPart   Cover   Missing
-----------------------------------------------------------
api/index.py     436     20    102     18  92.94%   33, 36, 40, 105-106, 133, 385, 425->431, 504, 511->514, 568->571, 609, 628, 644, 679, 702, 706-708, 712, 901, 914->917, 918-919
-----------------------------------------------------------
TOTAL            436     20    102     18  92.94%
```

## 남은 공백

아직 의도적으로 남겨둔 영역:

- 실제 Google OAuth 서버, MiniMax, NVIDIA API를 호출하는 통합 테스트는 없다. 현재 테스트는 fake async client로 네트워크를 차단한다.
- 브라우저 `localStorage`, 탭 전환, STT, 정적 JS 렌더링은 커버하지 않는다.
- Jinja 템플릿 HTML의 세부 DOM 구조 검증은 하지 않는다.
- `.env.local` 로딩 분기는 테스트하지 않았다. 테스트 환경에서는 환경변수를 fixture로 격리한다.

## 관찰된 경고

테스트 중 Starlette 템플릿 경고가 1개 나온다.

```text
DeprecationWarning: The `name` is not the first parameter anymore.
Replace `TemplateResponse(name, {"request": request})` by `TemplateResponse(request, name)`.
```

현재 동작은 깨지지 않지만, 이후 FastAPI/Starlette 업그레이드 전 `TEMPLATES.TemplateResponse("index.html", {"request": request})` 형태를 새 호출 방식으로 바꾸는 것이 좋다.

## 다음 보완 권장

1. Playwright 기반 브라우저 테스트를 추가해 글쓰기, 기록 저장, 설정, 리더스 화면의 실제 사용자 플로우를 검증한다.
2. LLM provider 계약 테스트를 opt-in 명령으로 분리한다. 예: `RUN_LLM_CONTRACT_TESTS=1`.
3. `/health`가 테스트를 계속 집계할 수 있도록 `CLAUDE.md`의 Health Stack을 유지한다.

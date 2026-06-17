# 테스트 커버리지 구축 Lessons Learned

작성일: 2026-05-28

## 배경

이번 작업은 테스트가 없는 FastAPI 기반 MVP에 `pytest`와 `pytest-cov`를 도입하고, `api/index.py`의 주요 인증·분석·LLM 폴백 흐름을 자동 검증하는 과정이었다. 최종 결과는 `29 passed`, `api/index.py` 커버리지 `92.94%`였다.

## 중요한 교훈

### 1. 커버리지 숫자보다 위험 경로 식별이 먼저다

처음부터 90% 이상을 목표로 잡기보다, 사용자가 실제로 피해를 볼 수 있는 경로를 먼저 골라야 했다.

이 프로젝트에서 우선순위가 높았던 경로:

- 로그인하지 않은 사용자의 분석 API 접근 차단
- 프로필 미완성 사용자의 온보딩 강제
- 자해·자살 신호 감지 시 LLM 호출 없이 위기 안내 반환
- OpenRouter 실패 시 NVIDIA 폴백, 둘 다 실패 시 템플릿 fallback 반환
- LLM 응답의 JSON 추출 실패나 금지문자 혼입 방어

커버리지는 이 위험 경로가 테스트됐는지 확인하는 지표로 쓰는 것이 좋다. 숫자 자체가 목적이 되면 덜 중요한 줄만 실행하고 핵심 회귀는 놓칠 수 있다.

### 2. 외부 API는 기본 테스트에서 차단해야 한다

OpenRouter, MiniMax, NVIDIA, Google OAuth는 실제 네트워크를 타면 테스트가 느리고 불안정해진다. API key 유무, provider 장애, 응답 포맷 변화에 따라 테스트가 흔들리기 때문이다.

이번에는 fake async client와 monkeypatch를 사용해 다음을 검증했다.

- API key가 없으면 provider 호출 없이 `None` 반환
- provider 응답이 정상일 때 `FeedbackPayload` 생성
- 빈 choices, provider error, 네트워크 예외를 fallback으로 처리
- 한자·가나 문자가 섞인 LLM 응답을 scrub 처리

기본 테스트는 결정적이어야 한다. 실제 provider 계약 테스트는 별도 opt-in 명령으로 분리하는 편이 맞다.

### 3. 테스트 환경은 운영 환경과 의도적으로 분리해야 한다

`requirements.txt`는 Vercel 런타임 의존성이고, `requirements-dev.txt`는 테스트 도구 의존성이다. 이 둘을 분리한 것이 중요했다.

분리 효과:

- 배포 함수에 불필요한 pytest/coverage 패키지가 들어가지 않는다.
- 테스트 도구 버전 변경이 런타임 의존성 변경처럼 보이지 않는다.
- 로컬 개발자는 명확하게 `pip install -r requirements-dev.txt`만 추가 실행하면 된다.

테스트 산출물인 `.coverage`, `coverage.xml`, `.pytest_cache/`도 `.gitignore`에 넣어 작업트리를 깨끗하게 유지했다.

### 4. 세션 쿠키는 유틸 함수 단위와 라우트 단위를 같이 봐야 한다

세션은 `_encode_signed()`와 `_decode_signed()` 단위 테스트만으로는 충분하지 않았다. 실제 라우트에서 쿠키가 어떻게 쓰이는지도 같이 봐야 했다.

확인한 항목:

- 정상 서명 토큰 roundtrip
- 변조 토큰 거부
- 만료 토큰 거부
- `/api/me` 인증 상태 반환
- `/logout`, `/api/logout` 쿠키 삭제
- 프로필 저장 시 세션 쿠키 재발급

인증 코드는 작은 유틸과 실제 HTTP 경로가 어긋나기 쉽다. 둘 다 테스트해야 회귀를 잘 막는다.

### 5. 위기 대응 경로는 LLM보다 앞에 있어야 한다

심리 케어 앱에서 가장 중요한 방어선은 LLM 응답 품질보다 위기 문구 short-circuit이다. 테스트는 이 조건을 명확히 고정해야 한다.

이번 테스트의 핵심 검증:

- 위기 문구가 있으면 `mode=crisis` 반환
- 핫라인 정보가 포함됨
- OpenRouter/NVIDIA 함수가 호출되면 테스트가 실패하도록 설정

이 테스트는 단순 커버리지 이상의 의미가 있다. 향후 리팩터링 중 실수로 LLM을 먼저 호출하는 구조가 들어오면 바로 잡아낸다.

### 6. LLM 응답 후처리는 별도 테스트 가치가 크다

LLM은 JSON만 달라고 해도 코드펜스, `<think>...</think>`, 주변 텍스트, 전각 구두점, 금지문자를 섞을 수 있다. 이 프로젝트는 `_extract_json()`, `_normalize_text()`, `_scrub_payload()`가 그런 변동성을 흡수한다.

테스트한 이유:

- 프롬프트 품질만 믿으면 런타임 오류가 난다.
- provider를 바꾸면 응답 포맷이 조금씩 달라진다.
- 사용자에게 한자·일본어·아랍어 문자가 보이는 것을 서버 레벨에서 막아야 한다.

LLM 기능은 모델 호출보다 후처리와 fallback이 더 자주 장애를 막는다.

### 7. 커버리지 리포트의 Missing 라인은 다음 작업 목록이다

최종 커버리지는 `92.94%`였지만 남은 라인을 그대로 100%까지 밀어붙이지는 않았다. 남은 공백 중 일부는 실제 외부 통합, `.env.local` 로딩, deprecated 템플릿 호출 분기처럼 별도 목적의 테스트가 필요한 영역이다.

현재 남은 주요 공백:

- 실제 Google OAuth 서버와의 end-to-end 통합
- 실제 OpenRouter/MiniMax/NVIDIA 계약 테스트
- 브라우저 `localStorage`, 탭 전환, STT, 정적 JS 흐름
- 템플릿 DOM 구조 검증

즉, Missing 라인은 "무조건 테스트를 더 써야 하는 곳"이 아니라 "다음에 어떤 검증 레벨이 필요한지 판단할 목록"이다.

### 8. 백엔드 커버리지만으로 제품 품질을 보장할 수 없다

이번 커버리지는 `api/index.py` 중심이다. 서버 로직 안정성은 크게 좋아졌지만, 실제 사용자는 브라우저 UI를 통해 제품을 쓴다.

아직 서버 테스트가 보장하지 못하는 것:

- 사용자가 세 줄 일기를 입력하고 결과 카드를 보는 흐름
- `localStorage` 저장·삭제·복원
- 리더스 화면의 입력/렌더링
- Web Speech API가 없는 브라우저에서의 UI 상태
- 모바일 화면에서 버튼과 텍스트가 겹치지 않는지 여부

다음 품질 단계는 Playwright 같은 브라우저 테스트다. 서버 커버리지는 기반이고, 사용자 플로우 검증은 별도 레이어로 필요하다.

### 9. 경고도 문서화해야 한다

테스트는 모두 통과했지만 Starlette `TemplateResponse` deprecation warning이 남았다.

```text
DeprecationWarning: The `name` is not the first parameter anymore.
Replace `TemplateResponse(name, {"request": request})` by `TemplateResponse(request, name)`.
```

이 경고는 당장 실패는 아니지만, FastAPI/Starlette 업그레이드 시 깨질 가능성을 알려준다. 테스트 결과 문서에 남겨두면 다음 작업자가 "왜 경고가 있지?"를 다시 조사하지 않아도 된다.

### 10. `/health`가 반복 실행 가능한 상태여야 한다

테스트 인프라를 한 번 구축하는 것보다, 다음 점검에서 자동으로 같은 검증이 실행되는 것이 더 중요하다. 그래서 `CLAUDE.md`의 Health Stack에 아래 명령을 추가했다.

```text
test: .venv/bin/python -m pytest
```

이제 `/health`나 수동 점검에서 테스트 명령을 다시 발견할 수 있다. 테스트는 한 번의 이벤트가 아니라 회귀를 계속 막는 장치여야 한다.

## 이번 프로젝트에 적용할 원칙

1. 인증, 안전장치, fallback은 기능 추가보다 먼저 테스트한다.
2. 외부 LLM/API 호출은 기본 테스트에서 fake로 고정한다.
3. 실제 provider 계약 테스트는 느리고 불안정할 수 있으므로 opt-in으로 분리한다.
4. 커버리지 90% 이상은 좋은 신호지만, 브라우저 사용자 플로우 테스트 없이는 완성으로 보지 않는다.
5. 테스트 경고와 남은 공백은 숨기지 말고 문서에 남긴다.

## 다음에 할 일

1. Starlette `TemplateResponse` 호출 방식을 최신 형태로 수정하고 경고를 제거한다.
2. Playwright 테스트를 추가해 글쓰기, 분석 요청, 기록 저장, 리더스 화면을 검증한다.
3. `RUN_LLM_CONTRACT_TESTS=1` 같은 플래그로 실제 MiniMax/NVIDIA 계약 테스트를 분리한다.
4. CI나 배포 전 점검에서 `.venv/bin/python -m pytest`가 실행되도록 연결한다.

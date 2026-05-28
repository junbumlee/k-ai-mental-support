# oh-my-claudecode Loop 재실행 기록: PDF 내보내기 전환

작성일: 2026-05-28

## 목표

이전 반복에서 구현한 Markdown 내보내기는 로컬 디바이스에서 가독성이 떨어졌다. 이번 재작업의 목표는 기록 내보내기를 **PDF 내보내기** 흐름으로 바꾸고, OMC Loop 방식으로 최소 3회 이상 구현·검증·수정을 반복하는 것이다.

최종 사용자 경험:

- 기록 탭에서 `PDF 내보내기` 버튼을 누른다.
- 새 인쇄 창이 열리고, 브라우저의 인쇄 기능에서 `PDF로 저장`을 선택할 수 있다.
- 기록은 카드형 PDF 레이아웃으로 정리된다.
- 일반 버전과 리더스 버전 모두 같은 PDF export helper를 사용한다.

## OMC 상태

설치 확인:

```bash
omc --version
```

결과:

```text
4.14.4
```

Ralph loop 재시도:

```bash
claude -p --permission-mode bypassPermissions --max-budget-usd 2 \
  '/ralph --no-deslop "Replace the current Markdown history export with a more readable PDF export ..."'
```

결과:

```text
Your organization has disabled Claude subscription access for Claude Code
Use an Anthropic API key instead, or ask your admin to enable access
```

결론:

- `oh-my-claudecode` CLI 설치와 setup은 완료되어 있다.
- 현재 환경에서는 Claude Code 조직 정책 때문에 `/ralph` 자동 루프가 실행되지 않는다.
- 따라서 이번에도 OMC/Ralph의 핵심 방식인 **구현 -> 검증 -> 수정** 루프를 수동으로 3회 수행했다.

## 3회 반복 로그

### Iteration 1: Markdown export를 PDF export로 교체

문제:

- Markdown 파일은 모바일/일반 로컬 뷰어에서 줄 간격, 제목 계층, 카드 구분이 약해 읽기 어렵다.
- 사용자는 기록을 “보관하고 다시 읽는 문서”로 기대한다.

수정:

- 버튼 라벨을 `Markdown 내보내기`에서 `PDF 내보내기`로 변경했다.
- `static/export.js`를 Markdown 생성기에서 PDF 인쇄용 HTML 생성기로 바꿨다.
- 외부 PDF 라이브러리를 추가하지 않고, 브라우저 인쇄 창을 열어 `PDF로 저장`할 수 있게 했다.
- PDF HTML에 `@page`, 카드 레이아웃, 제목/메타 정보, 항목별 섹션 스타일을 넣었다.

변경 파일:

- `static/export.js`
- `static/app.js`
- `static/leaders.js`
- `templates/index.html`
- `templates/leaders.html`

### Iteration 2: PDF export 테스트로 교체

문제:

- 기존 테스트는 Markdown 문자열을 검증하고 있었다.
- PDF 전환 후에는 인쇄용 HTML 구조, 파일명, HTML escaping, 버튼 라벨을 검증해야 한다.

수정:

- `tests/test_markdown_export.py`를 제거했다.
- `tests/test_pdf_export.py`를 추가했다.
- Node subprocess로 `static/export.js`를 직접 require하여 PDF HTML 생성 함수를 검증했다.

검증 항목:

- `<h1>` 제목과 기록 수가 포함된다.
- textarea 줄바꿈이 별도 문단으로 보존된다.
- `<script>` 같은 문자가 HTML escape된다.
- `@page` 인쇄 스타일이 포함된다.
- 파일명이 `.pdf` 확장자로 생성된다.
- 템플릿 버튼 라벨이 `PDF 내보내기`로 바뀌었다.

검증 명령:

```bash
.venv/bin/python -m pytest
```

결과:

```text
33 passed, 1 warning in 0.24s
api/index.py coverage: 92.94%
```

### Iteration 3: 인쇄 문서 제목 품질 수정

문제:

- PDF 저장 시 브라우저가 문서 `<title>`을 파일명 후보로 쓸 수 있다.
- 처음 수정에서는 `.pdf` 확장자를 제거하려는 정규식이 과하게 이스케이프되어 제목에서 확장자가 안정적으로 제거되지 않았다.

수정:

- `filename.replace(/\.pdf$/, "")`로 정규식을 고쳤다.
- 테스트에 `<title>worrydoll-20260528</title>` 검증을 추가했다.

재검증:

```text
33 passed, 1 warning in 0.24s
```

## 최종 구현 결과

추가/변경된 동작:

- 일반 기록 탭: `PDF 내보내기`
- 리더스 기록 탭: `PDF 내보내기`
- 기록이 없으면 다운로드 흐름 대신 `내보낼 기록이 아직 없어요` toast 표시
- 기록이 있으면 새 창에 인쇄용 문서를 열고 브라우저 인쇄/PDF 저장 흐름을 시작
- PDF 문서에는 다음 항목이 포함된다.
  - 제목
  - 내보낸 시각
  - 기록 수
  - 날짜
  - 카테고리
  - 상황
  - 그때 떠오른 생각
  - 스스로 시도한 재구성
  - 공감
  - 생각의 습관
  - 되묻기
  - 관찰 과제

검증 결과:

```text
33 passed, 1 warning
```

로컬 정적 파일 확인:

```text
http://127.0.0.1:3100/static/export.js -> 200 OK
```

남은 경고:

```text
Starlette TemplateResponse DeprecationWarning
```

이 경고는 이번 PDF export와 직접 관련이 없으며, 기존 테스트 인프라 구축 때부터 남아 있던 FastAPI/Starlette 호출 방식 경고다.

## 이번 재루프에서 가장 놀라웠던 점

가장 놀라웠던 점은, **사용자 피드백 하나가 기능의 정의를 완전히 바꿨다는 것**이다.

처음에는 “내보내기”를 데이터 추출 문제로 봤다. 그래서 Markdown은 구현이 간단하고 개발자에게 읽기 쉬운 형식이라 충분해 보였다. 하지만 실제 로컬 디바이스에서 읽는 사용자의 관점에서는 Markdown 파일이 문서가 아니라 원본 텍스트 덩어리처럼 보일 수 있다.

재루프를 돌리면서 기준이 바뀌었다.

1. 1회차 기준: 기록을 파일로 뽑을 수 있는가?
2. 2회차 기준: PDF 문서 구조가 테스트 가능한가?
3. 3회차 기준: 저장되는 PDF 제목과 실제 읽기 경험까지 괜찮은가?

이 점이 multi-iteration 방식의 장점이었다. 첫 구현은 기능의 존재를 만든다. 두 번째 반복은 기능의 계약을 만든다. 세 번째 반복은 사용자가 실제로 만지는 결과물의 품질을 본다.

## 한계와 결정

이번 구현은 클라이언트에서 바이너리 PDF를 직접 생성하지 않는다. 대신 브라우저의 인쇄 창을 열고 `PDF로 저장`을 사용한다.

이 결정을 한 이유:

- 외부 PDF 라이브러리를 추가하지 않아 번들/배포 부담이 없다.
- 한글 폰트 렌더링을 브라우저가 처리하므로 깨질 가능성이 낮다.
- 모바일과 데스크톱 모두 기본 인쇄/PDF 저장 흐름을 제공한다.
- 현재 프로젝트는 번들러 없는 vanilla JS 구조라, 무거운 PDF 생성 라이브러리 도입은 과하다.

다만 단점도 있다.

- 브라우저 팝업 차단 설정에 영향을 받을 수 있다.
- 사용자가 인쇄 창에서 직접 `PDF로 저장`을 선택해야 한다.
- Playwright로 실제 다운로드 파일 내용을 검증하는 테스트는 아직 없다.

## 다음 개선

1. Playwright로 localStorage 샘플 기록을 넣고 `PDF 내보내기` 클릭 후 인쇄 창 생성까지 검증한다.
2. 팝업 차단 시 안내 문구를 더 구체화한다.
3. 사용자가 바로 다운로드되는 PDF를 원하면, 그때 `jsPDF` 또는 서버 사이드 PDF 생성 방식을 별도 검토한다.

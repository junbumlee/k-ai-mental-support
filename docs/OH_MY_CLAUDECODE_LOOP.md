# oh-my-claudecode Loop 적용 기록

작성일: 2026-05-28

> 후속 사용자 피드백에 따라 이 Markdown 내보내기 기능은 PDF 내보내기로 대체됐다. 최신 재실행 기록은 `docs/OH_MY_CLAUDECODE_PDF_LOOP.md`를 기준으로 본다.

## 목표

팀 프로젝트 레포지토리에 `oh-my-claudecode`를 설치하고, Loop 방식의 반복 개발을 사용해 새 기능 하나를 구현한다. 이번에 구현한 기능은 **기록 Markdown 내보내기**다.

사용자 관점의 기능:

- 일반 기록 탭에서 저장된 걱정 기록을 Markdown 파일로 내려받을 수 있다.
- 리더스 기록 탭에서도 저장된 리더십 고민 기록을 Markdown 파일로 내려받을 수 있다.
- 기록이 없으면 다운로드 대신 안내 toast를 보여준다.

## 설치 및 확인

참고 레포지토리: <https://github.com/yeachan-heo/oh-my-claudecode>

README 기준으로 OMC는 Claude Code plugin 설치 경로와 npm CLI 설치 경로를 제공한다. 현재 작업 환경은 Claude Code plugin UI가 아니라 터미널 기반 Codex 세션이므로 npm CLI 경로를 사용했다.

실행한 명령:

```bash
npm i -g oh-my-claude-sisyphus@latest
omc --version
omc setup --skip-hooks --no-plugin
```

확인 결과:

```text
omc version: 4.14.4
Agents: 19 synced
Skills: 36 synced
Hooks: configured
```

설치 중 `prebuild-install@7.1.3` deprecation warning이 출력됐지만, OMC README에서도 npm 설치 시 알려진 upstream dependency warning으로 설명하는 항목이다. 설치 자체는 성공했다.

## Loop 기능 사용 시도

OMC 문서상 대표 Loop 흐름은 다음과 같다.

- Team: `team-plan -> team-prd -> team-exec -> team-verify -> team-fix (loop)`
- Ralph: 작업이 검증 완료될 때까지 verify/fix를 반복하는 persistence loop
- UltraQA: quality gate가 통과할 때까지 diagnose/fix를 반복하는 QA loop

처음에는 Ralph loop를 직접 실행하려고 했다.

```bash
claude -p --permission-mode bypassPermissions \
  '/oh-my-claudecode:ralph --no-deslop "Implement a small history Markdown export feature ..."'
```

결과:

```text
Unknown command: /oh-my-claudecode:ralph
```

plugin-scoped 이름 대신 설치된 skill 이름으로도 시도했다.

```bash
claude -p --permission-mode bypassPermissions \
  '/ralph --no-deslop "Implement a small history Markdown export feature ..."'
```

결과:

```text
Your organization has disabled Claude subscription access for Claude Code
Use an Anthropic API key instead, or ask your admin to enable access
```

따라서 이 환경에서는 OMC 설치와 setup은 완료됐지만, Claude Code 기반 Ralph 자동 루프는 조직 정책 때문에 실행할 수 없었다. 이후 구현은 OMC/Ralph의 핵심 원칙인 **구현 -> 검증 -> 수정 반복**을 명시적으로 3회 수행하는 방식으로 진행했다.

## 3회 반복 로그

### Iteration 1: 기능 구현

목표:

- 기록 탭에 `Markdown 내보내기` 버튼 추가
- 일반 버전과 리더스 버전에서 같은 export helper 재사용
- 저장된 localStorage 기록을 Markdown 문자열로 변환
- 브라우저에서 `.md` 파일 다운로드

변경 파일:

- `static/export.js`
- `static/app.js`
- `static/leaders.js`
- `static/style.css`
- `templates/index.html`
- `templates/leaders.html`

결과:

- `WorryDollExport.buildEntriesMarkdown()` helper 추가
- `WorryDollExport.makeExportFilename()` helper 추가
- `WorryDollExport.downloadMarkdown()` helper 추가
- 일반 앱 파일명: `worrydoll-YYYYMMDD.md`
- 리더스 파일명: `worrydoll-leaders-YYYYMMDD.md`

### Iteration 2: 테스트 보강 및 검증

목표:

- Markdown 생성 로직을 자동 테스트로 고정
- 템플릿이 export helper를 페이지 스크립트보다 먼저 로드하는지 검증
- 빈 기록 상태와 파일명 생성 규칙 검증

추가 파일:

- `tests/test_markdown_export.py`

검증 명령:

```bash
.venv/bin/python -m pytest
```

결과:

```text
32 passed, 1 warning in 0.20s
api/index.py coverage: 92.94%
```

관찰:

- 기존 Starlette `TemplateResponse` deprecation warning은 계속 남아 있다.
- 새 Markdown export 테스트는 Node를 subprocess로 호출해 `static/export.js`를 직접 검증한다.

### Iteration 3: 형식 안정성 수정

문제:

textarea 입력은 여러 줄일 수 있다. 첫 구현에서는 Markdown bullet 값 안에 줄바꿈이 그대로 들어가, 내보낸 파일에서 항목 구조가 깨질 수 있었다.

수정:

```text
줄바꿈 포함 텍스트 -> " / "로 접어서 한 bullet 안에 유지
```

수정 파일:

- `static/export.js`
- `tests/test_markdown_export.py`

재검증:

```bash
.venv/bin/python -m pytest
```

결과:

```text
32 passed, 1 warning in 0.19s
api/index.py coverage: 92.94%
```

## 최종 구현 결과

추가된 사용자 기능:

- `기록` 탭 우측 상단에 `Markdown 내보내기` 버튼
- 저장 기록이 없을 때: `내보낼 기록이 아직 없어요`
- 저장 기록이 있을 때: Markdown 파일 다운로드 후 `Markdown 파일로 내보냈어요`
- Markdown에는 날짜, 카테고리, 상황, 자동화 사고, 재구성, 공감, 생각의 습관, 되묻기, 관찰 과제가 포함된다.

검증 결과:

```text
32 passed, 1 warning
```

로컬 확인:

```text
http://127.0.0.1:3001
```

서버 로그:

```text
/tmp/k-ai-mental-support-uvicorn-3001.log
```

## 가장 놀라웠던 점

여러 번의 반복을 거치는 AI 보조 개발에서 가장 놀라웠던 점은, **두 번째 이후 반복에서야 실제 품질 문제가 보이기 시작한다는 것**이었다.

첫 번째 반복에서는 "버튼을 만들고 파일을 다운로드한다"는 기능 자체에 집중하게 된다. 이 단계만 보면 구현은 끝난 것처럼 보인다. 하지만 두 번째 반복에서 테스트를 붙이자, 기능의 계약이 더 분명해졌다. 어떤 제목을 써야 하는지, 빈 기록은 어떻게 표현해야 하는지, 템플릿 로딩 순서는 맞는지 같은 질문이 생겼다.

세 번째 반복에서는 더 작은 품질 문제가 보였다. 사용자가 textarea에 여러 줄을 쓸 수 있다는 사실은 기능 설명에는 없었지만, 실제 데이터 형태를 생각하면 당연한 조건이었다. 이 조건을 발견하고 나니 Markdown export는 단순 다운로드 기능이 아니라 "나중에 읽을 수 있는 기록 파일을 만드는 기능"으로 기준이 바뀌었다.

즉, multi-iteration 방식의 가치는 단순히 AI가 더 오래 일한다는 점이 아니었다. 반복이 진행될수록 질문의 수준이 바뀐다.

1. 1회차: 기능이 존재하는가?
2. 2회차: 기능을 검증할 수 있는가?
3. 3회차: 실제 사용자 데이터에서도 결과물이 깨지지 않는가?

이 변화가 가장 인상적이었다. 한 번에 "완성"을 선언했다면 놓쳤을 작은 결함을, 반복 루프가 자연스럽게 다음 질문으로 밀어냈다.

## 남은 한계

- 이 환경에서는 Claude Code 조직 정책 때문에 OMC의 Ralph 자동 루프를 실제로 끝까지 실행하지 못했다.
- 대신 OMC 설치, setup, Ralph 호출 실패까지 확인하고, OMC/Ralph의 verify/fix loop 원칙을 3회 수동 반복했다.
- 브라우저에서 실제 다운로드 클릭을 자동화하는 Playwright 테스트는 아직 없다.
- 리더스와 일반 페이지 모두 기능은 붙었지만, 모바일 시각 검증은 수동 확인 대상이다.

## 다음 개선

1. Claude Code 접근 권한이 있는 환경에서 `/ralph` 또는 `/team ralph`를 다시 실행한다.
2. Playwright로 localStorage에 샘플 기록을 넣고 `Markdown 내보내기` 버튼 클릭까지 검증한다.
3. 다운로드 파일 내용을 브라우저 테스트에서 직접 확인한다.

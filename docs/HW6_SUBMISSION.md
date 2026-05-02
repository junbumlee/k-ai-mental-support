# HW6 제출 답변

> 일시: 2026-04-28
> 프로젝트: K직장인용 걱정인형 (걱정인형 리더스)
> 브랜치: `feature/leader-context-category`
> PR: https://github.com/junbumlee/k-ai-mental-support/pull/6
>
> 참고 문서:
> - [HW6.md](./HW6.md) — 초기 계획 (v1)
> - [HW6_v2.md](./HW6_v2.md) — 비판적 보완 계획 (v2)
> - [HW6_OFFICE_HOURS.md](./HW6_OFFICE_HOURS.md) — /office-hours 결과·design doc

---

## Part 1 — Review the direction with AI (`/office-hours`)

### 1. What is the biggest lesson?

> **dropdown 은 라벨이고, placeholder 는 정체성이다.**

v2 plan 까지는 "카테고리 select 하나 추가하면 일반 감정 앱과 차별화된다"고 가정했다. /office-hours 가 이 가정을 두 번 깨뜨렸다.

첫째, 사용자가 30초 안에 "리더용 도구"로 인식하게 만드는 진짜 신호는 **첫 입력란이 던지는 질문**이다 — dropdown 라벨이 아니라. 둘째, 우리 진짜 경쟁자는 다른 앱이 아니라 **술과 카톡이다**(분출만 하고 끝나는 행동). 이 두 발견이 합쳐져서 카테고리별 가이드 placeholder 라는 작은 변경이 의미를 가지게 됐다.

부수 lesson: AI 에게 "뭘 만들까"를 물으면 일반론을 받는다. **"이 두 원칙(CBT 되묻기 vs 구체적 솔루션) 사이에서 어디까지 양보할까"** 처럼 우리 제품의 실제 충돌 지점을 물어야 우리 제품에 맞는 답이 나온다.

### 2. Action items from /office-hours — 선택한 1개

도출된 4개:

| # | 액션 | HW6 적합도 | 선택 |
|---|---|---|---|
| **A1** | **카테고리별 입력 placeholder + 가이드 질문** | ★★★ | ✅ |
| A2 | 인지왜곡 라벨 자동 감지·표시 | ★ | × — CBT "진단 금지" 원칙 침해 위험 |
| A3 | "오늘 분출 / 한 발 가보기" 2-모드 분기 | ★★ | × — 1주 범위 초과 |
| A4 | 익명 리더 커뮤니티 (retention hook) | ☆ | × — 별도 단계 |

**A1 선택 이유**: 정체성 간극을 가장 직접 해소하면서 CBT 안전장치(`SYSTEM_PROMPT` 의 3원칙)를 침해하지 않는 유일한 옵션. 구현 비용도 가장 낮음.

### 3. Result of doing the action item

#### 정량
- 변경 파일 4개 / +118 줄 (단, docs 제외)
- `templates/index.html`, `static/app.js`, `static/style.css`, `api/index.py`
- `SYSTEM_PROMPT` 0 라인 변경 → CBT 안전장치 100% 보존

#### 정성
v2 plan 만 따라갔으면 "카테고리 dropdown" 1개로 끝났을 작업이, /office-hours 를 거치면서 **"카테고리 + 그 카테고리만의 가이드 질문"** 이라는 한 단계 진화된 wedge 로 바뀜.

`_build_user_block` 단위 출력 비교:

```
[main 브랜치 — 카테고리 개념 없음]
[상황]
팀원이 시큰둥
[그때 떠오른 생각]
날 무시한다
...

[feature 브랜치 — 카테고리="팀원 관리"]
[상황 맥락]
사용자가 오늘 '팀원 관리' 맥락에서 이 일을 떠올렸습니다.
팀원의 행동·태도·동기에 대한 리더로서의 해석을 염두에 두고 읽어주세요.

[상황]
팀원이 시큰둥
...
```

LLM 이 받는 컨텍스트 자체가 **"리더 시각의 해석"** 을 명시적으로 요구하게 됨. 같은 입력에서도 응답의 결이 리더 도메인으로 좁혀질 가능성이 커짐.

---

## Part 2 — Build a feature in a separate branch

### 4. Git branch URL

- **브랜치**: https://github.com/junbumlee/k-ai-mental-support/tree/feature/leader-context-category
- **PR**: https://github.com/junbumlee/k-ai-mental-support/pull/6

### 5. Biggest challenge in building a feature

**작은 UI 변경 1개를 의미 있게 만들려면 4개 레이어가 동시에 움직여야 한다.**

처음엔 "select 하나 추가" 작업이라고 봤다. 실제로는:
1. UI (chip + 동적 placeholder)
2. 클라이언트 상태 (selectedCategory + reset 처리)
3. 데이터 (payload + localStorage backward compat)
4. 프롬프트 (user 블록 prefix — **시스템 프롬프트는 절대 못 건드림**)

가장 어려웠던 건 4번. CBT "AI 가 사고를 대신 재구성하지 않는다" 원칙 때문에 `SYSTEM_PROMPT` 를 건드리는 순간 안전장치가 깨진다. 변경 지점을 user 블록 prefix 한 줄로 한정하는 것이 가장 안전하면서도 효과를 내는 절충점이라는 걸 깨닫는 데 시간이 걸림.

### 6. Biggest meta-cognition lesson

**"무엇을 만들까"보다 "어디까지 안 만들까"를 먼저 정의해야 한다.**

v1 / v2 / office-hours 를 거치면서 액션 후보가 점점 늘어났다 (A1~A4). 처음엔 "다 좋아 보이니 다 하자" 충동이 강했지만, 진짜 일이 빨라진 건 **A2(인지왜곡 자동 라벨링) 와 A4(커뮤니티) 를 의식적으로 빼는 결정** 을 내린 뒤였다. A2 는 매력적이지만 CBT 진단 금지 원칙과 충돌하고, A4 는 retention 답으로 강력하지만 1주 범위 초과.

부산물: AI 에게 막연히 "리뷰해줘"가 아니라 **"이 두 원칙이 충돌할 때 어느 쪽을 보존할까"** 처럼 판단 기준을 주고 물으면 답의 해상도가 올라간다.

### 7. Biggest technical lesson

**프롬프트 엔지니어링은 시스템 프롬프트만 건드리는 게 아니다 — user 블록 구조가 더 안전하면서도 효과적인 변경 지점일 수 있다.**

처음엔 카테고리 정보를 `SYSTEM_PROMPT` 의 한 섹션으로 추가하는 게 자연스러워 보였다. 하지만 그건 13개 인지왜곡 분류표·예시·언어 가드레일까지 함께 흔들 위험이 있고, 무엇보다 CBT 3원칙을 손상시킬 가능성이 있었다.

대안으로 user 블록 앞에 `[상황 맥락]` prefix 한 줄만 주입하는 방식을 채택. 이게 더 좋았던 이유:
- **변경 폭이 작다** — 한 dict + 한 함수
- **롤백이 쉽다** — `CATEGORY_HINTS` 비우면 끝
- **검증이 가능하다** — `_build_user_block` 단위 출력만 보면 됨
- **시스템 안정성 보존** — 한자/가나 가드레일·JSON 스키마 강제 등 기존 안전장치 그대로

부수 발견: `Optional[str] + Field(max_length=20)` + dict.get() 조합으로 잘못된 카테고리도 graceful 처리. validation error 던질 필요 없음.

### 8. Responses from team members

> **TBD** — PR 공유 후 수집 예정.

**팀원에게 던질 고정 3 질문** ([HW6_v2.md 섹션 5](./HW6_v2.md)):

1. **정체성**: "이 화면을 처음 본 사람이 '리더용 도구'라고 1초 안에 알아챌 것 같은가? Yes/No + 이유 한 줄."
2. **마찰**: "카테고리 선택이 '도움이 되는 가이드'로 느껴지는가, '귀찮은 분류 강요'로 느껴지는가?"
3. **CBT 원칙**: "피드백이 여전히 '되묻기' 결을 유지하고 있는가, 아니면 훈계조로 바뀌었는가?"

수집 후 이 섹션 업데이트.

---

## Appendix — 일관된 스토리 (HW6_v2.md 섹션 3.1 인용)

> 우리는 리더용 도구를 표방했지만 MVP 는 일반 감정 앱처럼 보였다.
> /office-hours 로 이 간극을 짚었고, 제품 정체성을 가장 빠르게 선명하게 만드는
> 작은 기능 — 리더 상황 카테고리 + **카테고리별 가이드 placeholder** + 카테고리-인지
> 프롬프트 prefix — 을 골라 별도 브랜치에 구현했다.
>
> 한 발짝 더: dropdown 은 라벨이고, placeholder 는 정체성이다.

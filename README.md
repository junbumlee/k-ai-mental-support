# 걱정인형 (Worry Doll)

직장인을 위한 AI 기반 CBT(인지행동치료) 심리 케어 서비스. 회사별이 아닌 **고민 유형별**로 사용자를 연결해 블라인드·세줄일기와 차별화하고, 인사담당자 출신 상담사 코칭으로 수익화를 계획.

## 프로젝트 타입

- **유형**: Python 기반 웹 애플리케이션 (서버리스)
- **배포 대상**: Vercel (Python Runtime)
- **개발 단계**: MVP (1차 코딩 — 세줄일기 스타일의 문답형 기록 UI + LLM 피드백)

## 기술 스택

| 레이어 | 기술 | 선택 사유 |
| --- | --- | --- |
| 백엔드 | FastAPI | 비동기, Vercel 서버리스 호환, Pydantic 스키마 내장 |
| 프론트엔드 | Jinja2 템플릿 + Vanilla JS | MVP 단계 — 별도 번들러/프레임워크 없이 경량 |
| LLM | MiniMax (`MiniMax-M2`, Token Plan 호환) | 한국어 CBT 프레임 피드백. `chatcompletion_v2` OpenAI 호환 API |
| 저장소 | 브라우저 `localStorage` (MVP) → Vercel Postgres (2차) | MVP는 서버 상태 없이 시작, 사용자 확보 후 DB 전환 |
| 배포 | Vercel | 서버리스 함수로 Python API + 정적 자산 서빙 |
| STT | Web Speech API (MVP) → Whisper API (2차) | 초기에는 브라우저 내장 STT로 진입 장벽 최소화 |

## 디렉토리 구조

```
k-ai-mental-support/
├── api/
│   └── index.py          # FastAPI 엔트리 (Vercel 서버리스 함수)
├── templates/
│   └── index.html        # 걱정인형 메인 페이지
├── static/
│   ├── style.css
│   └── app.js            # 기록/피드백/로컬 저장 로직
├── vercel.json           # Vercel 라우팅 & 빌드 설정
├── requirements.txt      # Python 의존성
├── README.md
└── CLAUDE.md             # Claude Code 가이드
```

## 로컬 개발

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn api.index:app --reload --port 3000
# → http://localhost:3000
```

LLM 피드백을 활성화하려면 환경변수 설정:

```bash
export MINIMAX_API_KEY=...                              # 필수 — MiniMax 콘솔에서 발급
export MINIMAX_MODEL=MiniMax-M2                         # 선택 — 기본값 (Token Plan 호환)
export MINIMAX_BASE_URL=https://api.minimaxi.chat/v1    # 선택 — 해외 리전 기본값
```

`.env.local` 파일에 두면 `.gitignore`가 걸러줍니다. 키가 없으면 백엔드는 fallback 템플릿 피드백을 반환합니다(배포 막힘 없이 UI 확인 가능).

## Vercel 배포

```bash
vercel                    # 프리뷰 배포
vercel --prod             # 프로덕션 배포
```

대시보드에서 `MINIMAX_API_KEY`(필요 시 `MINIMAX_MODEL`, `MINIMAX_BASE_URL`도)를 Environment Variable로 등록해야 LLM 피드백이 동작합니다.

---

## 서비스 기획

### 1. 핵심 포지셔닝

- **블라인드와 차별**: 회사별 정보 교환이 아니라 **고민 유형별** 공감 네트워크
- **세줄일기와 차별**: 포괄적 일반인 대상이 아니라 **직장 내 사회생활 고민** 특화
- **마음건강센터와 차별**: 낙인 없는 가벼운 진입, 일상적 사고 교정

### 2. 서비스 개요

1. **직장 고민 기록 & 분석 (LLM 기반)**
   - 사용자 프로필(직무/연차) 입력 → 고민 자동 Categorize
   - 매일 텍스트 또는 STT로 기록 → CBT 프레임 기반 피드백
2. **같은 고민 직장인 매칭**
   - 고민 카테고리별 익명 대화 공간 (2차)
3. **전문가 연결 (수익화)**
   - 인사담당자 출신 상담사의 코칭 솔루션 연결

### 3. 이론적 기반: 인지행동치료(CBT)

잘못된 행동은 부정적 감정과 사고에서 기인. 행동과 감정은 직접 바꾸기 어렵기 때문에 **사고(해석)** 를 바꾼다는 CBT를 기반. 병리적 상태가 아닌 일상적 자기인식·의사결정 영역에 적용.

**사용자 여정**: 부정적 환경 노출 → 자동화 사고 → 사고 관찰 → 사고 기록 → 사고 분석 → 사고 판단 → 사고 재구성(or 수용)

### 4. AI 적용 원칙

- **Quiz**: CBT 이론 학습 점검. 사고 분석·재구성 단계는 AI 개입 금지(치료 효과 저하).
- **STT**: 기억 왜곡과 기록 허들(온라인 CBT 이탈률 57%의 주요 원인) 완화.
- **LLM 피드백**: 부정 사고 유형 10~15가지, 교정 방법론 5~7가지를 RAG화 → 고품질 피드백.

### 5. Pre-mortem 리스크

- **할루시네이션**: 잘못된 사고 교정이 사용자 상태를 악화시킬 수 있음 → 법적·사회적 문제 가능. **크라이시스 키워드 감지 + 전문 상담 안내 게이트**를 백엔드에 내장.
- **이용률 저하**: 사고 교정 자체가 고통스러운 과정 → 진입 허들 최소화(세줄 문답, STT), 정서적 안전감 주는 UI 필수.

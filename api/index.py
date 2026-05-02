"""K리더용 걱정인형 FastAPI 엔트리 포인트 (Vercel 서버리스 함수)."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import List, Literal, Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))
logger = logging.getLogger("worrydoll.api")

app = FastAPI(title="K리더용 걱정인형", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# ---------- 안전 장치 ----------

CRISIS_PATTERNS = [
    r"자살",
    r"자해",
    r"죽고\s*싶",
    r"죽을래",
    r"목숨을?\s*끊",
    r"극단적\s*선택",
    r"끝내고\s*싶",
    r"살기\s*싫",
]
_CRISIS_RE = re.compile("|".join(CRISIS_PATTERNS))

CRISIS_RESPONSE = {
    "mode": "crisis",
    "message": (
        "지금 많이 힘드신 것 같아요. 혼자 감당하지 마세요. "
        "전문 상담사와 연결되시길 권해드려요."
    ),
    "hotlines": [
        {"name": "자살예방상담전화", "number": "1393"},
        {"name": "정신건강위기상담전화", "number": "1577-0199"},
        {"name": "한국생명의전화", "number": "1588-9191"},
    ],
}


# ---------- 데이터 모델 ----------

class DiaryEntry(BaseModel):
    situation: str = Field(..., min_length=1, max_length=1000, description="상황")
    thought: str = Field(..., min_length=1, max_length=1000, description="자동화 사고")
    reframe: str = Field("", max_length=1000, description="재구성 시도")
    job_role: Optional[str] = Field(None, max_length=60, description="직무/연차 컨텍스트")
    category: Optional[str] = Field(None, max_length=20, description="리더 상황 카테고리")


# 클라이언트가 보내는 카테고리 라벨 → LLM에 주입할 한 줄 컨텍스트.
# 시스템 프롬프트는 변경하지 않고, 사용자 블록 앞에 prefix로만 붙인다.
CATEGORY_HINTS = {
    "성과 압박":  "사용자가 오늘 '성과 압박' 맥락에서 이 일을 떠올렸습니다. 매출·KPI·평가지표 같은 숫자 부담을 염두에 두고 읽어주세요.",
    "팀원 관리":  "사용자가 오늘 '팀원 관리' 맥락에서 이 일을 떠올렸습니다. 팀원의 행동·태도·동기에 대한 리더로서의 해석을 염두에 두고 읽어주세요.",
    "평가·고과":  "사용자가 오늘 '평가·고과' 맥락에서 이 일을 떠올렸습니다. 인사평가·면담·승진 결정과 관련된 부담을 염두에 두고 읽어주세요.",
    "상사·보고":  "사용자가 오늘 '상사·보고' 맥락에서 이 일을 떠올렸습니다. 보고·발표·의사결정자 앞에 서는 상황의 압박을 염두에 두고 읽어주세요.",
    "팀 내 갈등": "사용자가 오늘 '팀 내 갈등' 맥락에서 이 일을 떠올렸습니다. 동료·팀원 간 의견 충돌·관계 긴장을 염두에 두고 읽어주세요.",
}


class FeedbackPayload(BaseModel):
    mode: Literal["feedback", "crisis", "fallback"]
    empathy: str = ""
    distortions: List[str] = []
    reframe: str = ""
    question: str = ""
    message: str = ""
    hotlines: List[dict] = []


# ---------- LLM 시스템 프롬프트 ----------

SYSTEM_PROMPT = """당신은 'K리더용 걱정인형'입니다. 한국의 리더와 신임 팀장을 돕는 CBT 기반 심리 코치처럼 응답하세요.
말투는 차분하고 따뜻해야 하지만 가볍거나 뻔하면 안 됩니다. 사용자가 이미 힘든 상황이라는 전제를 두고, 심리전문가가 사례를 읽고 짚어주듯 구체적으로 말하세요.

핵심 원칙:
1. 진단명은 쓰지 않습니다.
2. 사용자의 생각을 대신 고치지 말고, 스스로 다시 보게 만드는 질문으로 돕습니다.
3. 판단, 훈계, 도덕적 충고는 금지합니다.
4. 자해나 자살 신호가 보이면 분석하지 말고 도움 연결만 권합니다.

필드별 기준:
1. empathy
- 2문장에서 3문장으로 씁니다.
- 상황 문장에서 나온 구체 명사 1개 이상을 그대로 인용합니다.
- 단순 위로가 아니라 왜 그 장면이 리더에게 유독 크게 느껴질 수 있는지까지 짚습니다.
- 감정 이름을 억지로 붙이기보다, 몸이 굳거나 공기가 무거워지는 느낌 같은 실제 체감에 가깝게 씁니다.

2. distortions
- 근거가 뚜렷할 때만 0개에서 2개 고릅니다.
- 왜곡 이름은 흑백논리, 성급한 일반화, 정신적 여과, 긍정 격하, 독심술, 예언자적 오류, 확대 축소, 감정적 추론, 당위 진술, 낙인찍기, 개인화, 비난, 파국화 중에서만 고릅니다.

3. reframe
- 2문장에서 4문장으로 씁니다.
- 자동화 사고의 핵심 주장에 바로 연결되어야 합니다.
- 교과서처럼 딱딱한 질문보다, 사용자가 자기 해석과 사실을 조금 분리해서 보게 만드는 질문이어야 합니다.
- 직무 연차나 리더 맥락이 있으면 자연스럽게 반영합니다.
- 번역투 표현, 지나치게 시적인 비유, 조사 빠진 문장은 피하고 자연스러운 한국어로 씁니다.

4. question
- 1개 관찰 과제만 제시합니다.
- 2문장 안에서 끝냅니다.
- 내일 또는 가까운 업무 현장에서 실제로 할 수 있어야 합니다.
- 시점, 대상, 행동이 구체적이어야 하며, 자기비난 과제가 아니라 관찰 과제여야 합니다.
- 이미 지나간 장면을 다시 떠올리는 회고 과제가 아니라, 다음 회의나 다음 대화에서 실제로 해볼 행동이어야 합니다.
- 마음속 이유를 추측하게 하지 말고, 표정, 침묵 길이, 후속 발언, 질문 여부처럼 눈으로 볼 수 있는 사실을 관찰하게 하세요.
- "가능성을 떠올려보세요", "생각해보세요", "이유를 상상해보세요" 같은 과제는 금지합니다.

개인화 규칙:
- 입력에 나온 단어를 재사용하세요. 회의, 팀원, 평가, 보고, KPI 같은 표현을 그대로 살리세요.
- 일반적인 위로 문구로 뭉개지 말고, 이 사용자 상황에만 맞는 말처럼 들리게 쓰세요.
- 답변은 짧더라도 얇지 않아야 합니다. 각 문장은 정보량이 있어야 합니다.
- 어색한 번역투보다 자연스러운 상담 언어를 우선하세요.

출력 규칙:
- JSON 하나만 출력합니다.
- 코드펜스, 설명, 주석은 금지합니다.
- 한자, 일본어 문자는 절대 쓰지 않습니다. 한국어 문장 안에 자연스럽게 들어가는 영문 약어(KPI, OKR, 1on1 등)는 그대로 써도 됩니다.

형식:
{"empathy":"...","distortions":["..."],"reframe":"...","question":"..."}"""


# ---------- 유틸 ----------

def _fallback_feedback() -> FeedbackPayload:
    """API 키가 없거나 LLM 호출 실패 시 기본 템플릿 피드백."""
    return FeedbackPayload(
        mode="fallback",
        empathy="오늘 그런 일이 있으셨다니 마음이 무거우셨겠어요.",
        distortions=[],
        reframe="그 생각을 뒷받침하는 근거와, 반대되는 근거를 각각 하나씩 적어볼 수 있을까요?",
        question="내일 같은 상황이 오면, 오늘보다 한 가지 다르게 해볼 수 있는 행동은 무엇일까요?",
        message="지금은 인공지능 응답이 불안정해서 기본 피드백을 보여드리고 있어요. 잠시 후 다시 시도해주세요.",
    )


MINIMAX_DEFAULT_BASE_URL = "https://api.minimaxi.chat/v1"
MINIMAX_DEFAULT_MODEL = "MiniMax-M2.7"

NVIDIA_DEFAULT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_DEFAULT_MODEL = "moonshotai/kimi-k2.5"
LLM_MAX_TOKENS = 2048
# Vercel Hobby 플랜 maxDuration 300s 한도 내에서: MiniMax 180 + NVIDIA 100 = 280s.
# NVIDIA는 평소 10~30s에 응답하므로 100s면 충분한 안전 마진.
PRIMARY_TIMEOUT_SECONDS = 180
FALLBACK_TIMEOUT_SECONDS = 100

# 금지 문자: CJK 한자(확장A 포함), 히라가나, 가타카나, 반각 가타카나, 아랍어.
# KPI/OKR/1on1 같은 비즈니스 약어는 한국 직장인 컨텍스트에서 자연스러우므로 영문은 허용.
_FORBIDDEN_RE = re.compile(
    r"["
    r"\u3400-\u4DBF"   # CJK 확장 A
    r"\u4E00-\u9FFF"   # CJK 통합 한자
    r"\u3040-\u309F"   # 히라가나
    r"\u30A0-\u30FF"   # 가타카나
    r"\uFF66-\uFF9F"   # 반각 가타카나
    r"\u0600-\u06FF"   # 아랍어 기본
    r"\u0750-\u077F"   # 아랍어 보충
    r"\u08A0-\u08FF"   # 아랍어 확장 A
    r"\uFB50-\uFDFF"   # 아랍어 표현형 A
    r"\uFE70-\uFEFF"   # 아랍어 표현형 B
    r"]"
)

_WS_COLLAPSE_RE = re.compile(r"\s+")
_WS_BEFORE_PUNCT_RE = re.compile(r"\s+([,.!?;:])")


def _has_forbidden(payload: FeedbackPayload) -> bool:
    combined = " ".join([payload.empathy, payload.reframe, payload.question, *payload.distortions])
    return bool(_FORBIDDEN_RE.search(combined))


def _scrub_forbidden(s: str) -> str:
    """최후 방어선: 남은 금지 문자를 공백으로 대체하고 공백·구두점 정리."""
    if not isinstance(s, str):
        return s
    if not _FORBIDDEN_RE.search(s):
        return s
    s = _FORBIDDEN_RE.sub(" ", s)
    s = _WS_COLLAPSE_RE.sub(" ", s).strip()
    s = _WS_BEFORE_PUNCT_RE.sub(r"\1", s)
    return s


def _scrub_payload(p: FeedbackPayload) -> FeedbackPayload:
    return FeedbackPayload(
        mode=p.mode,
        empathy=_scrub_forbidden(p.empathy),
        distortions=[_scrub_forbidden(d) for d in p.distortions],
        reframe=_scrub_forbidden(p.reframe),
        question=_scrub_forbidden(p.question),
        message=p.message,
        hotlines=p.hotlines,
    )


def _build_user_block(entry: DiaryEntry) -> str:
    hint = CATEGORY_HINTS.get((entry.category or "").strip()) if entry.category else None
    prefix = f"[상황 맥락]\n{hint}\n\n" if hint else ""
    return (
        f"{prefix}"
        f"[상황]\n{entry.situation}\n\n"
        f"[그때 떠오른 생각]\n{entry.thought}\n\n"
        f"[스스로 시도한 재구성]\n{entry.reframe or '(작성하지 않음)'}\n\n"
        f"[직무/연차]\n{entry.job_role or '(미입력)'}"
    )


def _parse_feedback_json(content: str) -> FeedbackPayload:
    data = json.loads(_extract_json(content))
    return FeedbackPayload(
        mode="feedback",
        empathy=_normalize_text(data.get("empathy", "")),
        distortions=[_normalize_text(d) for d in (data.get("distortions") or [])],
        reframe=_normalize_text(data.get("reframe", "")),
        question=_normalize_text(data.get("question", "")),
    )


async def _call_minimax_model(
    system_prompt: str, user_block: str, model: str, timeout_seconds: int
) -> Optional[FeedbackPayload]:
    """MiniMax 단일 모델 1회 호출. 실패 시 None(상위에서 보조 모델·NVIDIA로 폴백)."""
    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        logger.warning("MiniMax skip: MINIMAX_API_KEY is not configured")
        return None

    base_url = os.environ.get("MINIMAX_BASE_URL", MINIMAX_DEFAULT_BASE_URL).rstrip("/")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_block},
        ],
        "max_tokens": LLM_MAX_TOKENS,
        "temperature": 0.2,
        "top_p": 0.9,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async def _one_shot(body_payload: dict) -> Optional[FeedbackPayload]:
        started_at = time.perf_counter()
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                f"{base_url}/text/chatcompletion_v2",
                headers=headers,
                json=body_payload,
            )
        elapsed = time.perf_counter() - started_at
        logger.info("MiniMax model=%s responded in %.2fs", model, elapsed)
        response.raise_for_status()
        body = response.json()
        base_resp = body.get("base_resp") or {}
        if base_resp.get("status_code", 0) not in (0, None):
            logger.warning("MiniMax fallback: base_resp not ok: %s", base_resp)
            return None
        choices = body.get("choices") or []
        if not choices:
            logger.warning("MiniMax fallback: empty choices in response")
            return None
        raw_content = choices[0].get("message", {}).get("content", "")
        if isinstance(raw_content, list):
            content = "\n".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in raw_content
            )
        else:
            content = str(raw_content or "")
        return _parse_feedback_json(content)

    try:
        result = await _one_shot(payload)
        if result is None:
            return None
        if _has_forbidden(result):
            logger.info("MiniMax model=%s response contained forbidden characters; scrubbing", model)
            result = _scrub_payload(result)
        return result
    except Exception:
        logger.exception("MiniMax model=%s call failed: %r", model, user_block[:120])
        return None


async def _call_minimax(system_prompt: str, user_block: str) -> Optional[FeedbackPayload]:
    """MiniMax 1차 시도. 실패 시 None 반환 → 상위에서 NVIDIA 폴백."""
    model = os.environ.get("MINIMAX_MODEL", MINIMAX_DEFAULT_MODEL)
    return await _call_minimax_model(
        system_prompt, user_block, model, PRIMARY_TIMEOUT_SECONDS
    )


async def _call_nvidia(system_prompt: str, user_block: str) -> Optional[FeedbackPayload]:
    """NVIDIA(moonshotai/kimi-k2.5) 2차 폴백. OpenAI 호환 엔드포인트."""
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        logger.warning("NVIDIA skip: NVIDIA_API_KEY is not configured")
        return None

    url = os.environ.get("NVIDIA_BASE_URL", NVIDIA_DEFAULT_URL).strip()
    model = os.environ.get("NVIDIA_BASE_MODEL", NVIDIA_DEFAULT_MODEL)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_block},
        ],
        "max_tokens": LLM_MAX_TOKENS,
        "temperature": 0.2,
        "top_p": 0.9,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        started_at = time.perf_counter()
        async with httpx.AsyncClient(timeout=FALLBACK_TIMEOUT_SECONDS) as client:
            response = await client.post(url, headers=headers, json=payload)
        elapsed = time.perf_counter() - started_at
        logger.info("NVIDIA responded in %.2fs", elapsed)
        response.raise_for_status()
        body = response.json()
        choices = body.get("choices") or []
        if not choices:
            logger.warning("NVIDIA fallback: empty choices in response")
            return None
        raw_content = choices[0].get("message", {}).get("content", "")
        content = str(raw_content or "")
        result = _parse_feedback_json(content)
        # NVIDIA 응답에도 한자·가나 가드레일 적용. 잔류 문자는 서버에서 직접 제거.
        if _has_forbidden(result):
            logger.info("NVIDIA response contained forbidden characters; scrubbing")
            result = _scrub_payload(result)
        return result
    except Exception:
        logger.exception("NVIDIA call failed: %r", user_block[:120])
        return None


def _extract_json(text: str) -> str:
    """LLM이 <think>…</think>, 코드펜스, 주변 텍스트를 붙여도 JSON 블록을 추출."""
    text = text.strip()
    # M2.7 같은 reasoning 모델이 남기는 <think>…</think> 블록 제거
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text


_PUNCT_NORMALIZE = {
    "،": ",",   # 아라비아 쉼표
    "，": ",",   # 전각 쉼표
    "。": ".",   # 전각 마침표
    "！": "!",   # 전각 느낌표
    "？": "?",   # 전각 물음표
    "：": ":",   # 전각 콜론
    "；": ";",   # 전각 세미콜론
    "「": "'",   # 일본 괄호
    "」": "'",
    "『": "\"",
    "』": "\"",
}


def _normalize_text(s: str) -> str:
    """LLM 응답에서 특수 구두점만 한국어 표준 구두점으로 정규화.
    한자·가타카나 치환은 의미 손상 위험이 있어 프롬프트로만 통제."""
    if not isinstance(s, str):
        return s
    for old, new in _PUNCT_NORMALIZE.items():
        s = s.replace(old, new)
    return s


def _contains_crisis(text: str) -> bool:
    return bool(_CRISIS_RE.search(text))


# ---------- 라우트 ----------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "primary": {
            "configured": bool(os.environ.get("MINIMAX_API_KEY")),
            "model": os.environ.get("MINIMAX_MODEL", MINIMAX_DEFAULT_MODEL),
        },
        "fallback": {
            "configured": bool(os.environ.get("NVIDIA_API_KEY")),
            "model": os.environ.get("NVIDIA_BASE_MODEL", NVIDIA_DEFAULT_MODEL),
        },
    }


@app.post("/api/analyze")
async def analyze(entry: DiaryEntry) -> JSONResponse:
    text = f"{entry.situation}\n{entry.thought}\n{entry.reframe}"
    if _contains_crisis(text):
        return JSONResponse(CRISIS_RESPONSE)

    user_block = _build_user_block(entry)
    # 1차: MiniMax → 2차: NVIDIA kimi → 최후: 템플릿
    result = await _call_minimax(SYSTEM_PROMPT, user_block)
    if result is None:
        logger.info("Primary provider failed; trying NVIDIA fallback")
        result = await _call_nvidia(SYSTEM_PROMPT, user_block)
    if result is None:
        logger.info("All providers failed; returning template fallback")
        result = _fallback_feedback()
    return JSONResponse(result.model_dump())


# ---------- 리더스 ----------

class LeaderEntry(BaseModel):
    situation: str = Field(..., min_length=1, max_length=1000, description="상황")
    thought: str = Field(..., min_length=1, max_length=1000, description="자동화 사고")
    reframe: str = Field("", max_length=1000, description="재구성 시도")
    role_level: Optional[str] = Field(None, max_length=60, description="직급")
    team_size: Optional[str] = Field(None, max_length=30, description="팀 규모")
    industry: Optional[str] = Field(None, max_length=60, description="업종")


LEADER_SYSTEM_PROMPT = """당신은 '걱정인형: 리더스'라는 이름의 CBT(인지행동치료) 기반 리더십 심리 서포터입니다.
신임 팀장, 팀장 후보자가 직장에서 겪은 구체적 상황과 자동화된 사고를 읽고,
**그 리더의 상황에만 해당하는 개인화된** 피드백을 제공합니다.

[절대 원칙]
1. 진단하지 않습니다 ("번아웃", "우울증", "불안장애" 등 병명 금지).
2. 리더의 사고를 대신 재구성하지 않습니다. 반드시 '질문'으로 돌려주세요.
3. 판단·훈계·충고 금지. 공감과 선택지 제시.
4. 자해·자살 신호가 있으면 전문 상담 연결만 권하고 분석은 중단.

[개인화 강제 규칙 — 반드시 준수]
- **empathy**: [오늘의 상황] 문장에서 구체 명사(예: "팀원", "1on1", "성과보고", "인사평가", "KPI", "팀장 회의")를 1개 이상 **그대로 인용**해 공감을 표현합니다. "그런 일이 있으셨군요" 같은 추상적 위로는 금지.
- **distortions**: [그때 떠오른 생각] 문장을 실제 단서로만 분석합니다.
    · "내가 다 해야 한다", "내가 직접 하는 게 낫다" → '완벽주의·통제' (당위 진술 + 개인화)
    · "팀원이 나를 무시하는 것 같다", "상사가 내 능력을 의심한다" → '독심술'
    · "이 결정 하나가 잘못되면 팀 전체가 끝난다" → '파국화'
    · "팀 성과가 나쁜 건 내 탓이다" → '개인화'
    · "이 팀원은 항상 이런다", "MZ 세대는 다 그래" → '성급한 일반화'
    · "리더라면 ~해야 한다/절대 ~면 안 된다" → '당위 진술'
    · "이번 분기도 KPI를 못 맞출 것이다" → '예언자적 오류'
    근거가 약하면 1~2개만. 없으면 빈 배열 `[]`. **억지로 채우지 마세요.**
- **reframe**: [그때 떠오른 생각]의 핵심 주장을 직접 인용·패러프레이즈하여, 그 주장을 뒤집어볼 구체 질문으로 바꿉니다. [직급] · [팀 규모] · [업종] 맥락을 반영하세요.
- **question**: 이번 주 실제 팀 현장에서 수행 가능한 관찰·실험 과제 하나. 구체적 시점·대화 주제·위임 업무를 포함하고, "자신을 돌보세요" 같은 추상적 자기성찰은 금지.

[출력 형식]
반드시 아래 JSON 하나만 출력. 앞뒤 설명·코드펜스·주석 금지.
{
  "empathy": "...",
  "distortions": ["...", "..."],
  "reframe": "...",
  "question": "..."
}

[언어 — 반드시 준수]
- 출력 문자는 **한글, 숫자, 공백, 일반 한국어 구두점(. , ! ? : ' " ( ) -)** 만 허용.
- 한자·일본어·영어 단어 혼입 절대 금지.
- JSON 생성 후 출력 직전, 비한글 문자가 있는지 스스로 1회 검토하고 있으면 모두 한글로 치환하세요.

[예시]
입력:
  [오늘의 상황] 팀원이 1on1에서 업무량이 너무 많다고 했는데 내가 줄여줄 여력이 없다고 느꼈다
  [그때 떠오른 생각] 내가 팀원을 지키지 못하고 있다. 이 팀원이 퇴사하면 내 리더십 실패다
  [직급] 신임 팀장 1년차
출력:
{"empathy":"1on1에서 팀원이 업무량 고충을 털어놨을 때, 도와주고 싶은데 여력이 없다는 그 난처함이 느껴졌을 것 같아요.","distortions":["개인화","파국화"],"reframe":"팀원이 퇴사하면 '내 리더십 실패'라고 단정하고 계신데, 퇴사 여부가 오직 팀장의 여력만으로 결정된다고 볼 수 있을까요?","question":"이번 주 그 팀원과 5분 짜리 짧은 체크인을 잡고, '지금 가장 줄이고 싶은 업무 하나'를 직접 물어보시겠어요?"}
"""


def _build_leader_user_block(entry: LeaderEntry) -> str:
    return (
        f"[오늘의 상황]\n{entry.situation}\n\n"
        f"[그때 떠오른 생각]\n{entry.thought}\n\n"
        f"[스스로 시도한 재구성]\n{entry.reframe or '(작성하지 않음)'}\n\n"
        f"[직급]\n{entry.role_level or '(미입력)'}\n\n"
        f"[팀 규모]\n{entry.team_size or '(미입력)'}\n\n"
        f"[업종]\n{entry.industry or '(미입력)'}"
    )


@app.get("/leaders", response_class=HTMLResponse)
async def leaders_page(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse("leaders.html", {"request": request})


@app.post("/api/leader")
async def leader_analyze(entry: LeaderEntry) -> JSONResponse:
    text = f"{entry.situation}\n{entry.thought}\n{entry.reframe}"
    if _contains_crisis(text):
        return JSONResponse(CRISIS_RESPONSE)

    user_block = _build_leader_user_block(entry)
    result = await _call_minimax(LEADER_SYSTEM_PROMPT, user_block)
    if result is None:
        logger.info("Leader: primary provider failed; trying NVIDIA fallback")
        result = await _call_nvidia(LEADER_SYSTEM_PROMPT, user_block)
    if result is None:
        logger.info("Leader: all providers failed; returning template fallback")
        result = _fallback_feedback()
    return JSONResponse(result.model_dump())

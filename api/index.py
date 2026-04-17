"""걱정인형 FastAPI 엔트리 포인트 (Vercel 서버리스 함수)."""

from __future__ import annotations

import json
import os
import re
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

app = FastAPI(title="걱정인형", docs_url=None, redoc_url=None)
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


class FeedbackPayload(BaseModel):
    mode: Literal["feedback", "crisis", "fallback"]
    empathy: str = ""
    distortions: List[str] = []
    reframe: str = ""
    question: str = ""
    message: str = ""
    hotlines: List[dict] = []


# ---------- LLM 시스템 프롬프트 ----------

SYSTEM_PROMPT = """당신은 '걱정인형'이라는 이름의 CBT(인지행동치료) 기반 심리 서포터입니다.
한국의 직장인을 대상으로, 일상에서의 자동화된 사고를 스스로 관찰·재구성할 수 있도록 돕는 역할입니다.

[절대 원칙]
- 진단하지 않습니다. "우울증", "불안장애" 등의 병명을 언급하지 않습니다.
- 사용자의 사고를 대신 재구성하지 않습니다. 균형 잡힌 관점을 탐색하도록 '질문'을 돌려줍니다.
- 판단·훈계·충고하지 않습니다. 공감과 선택지 제시가 기본 태도입니다.
- 자해·자살 신호가 있으면 즉시 전문 상담 연결을 권하고, 사고 분석을 중단합니다.

[CBT 왜곡 유형 참고 목록]
흑백논리, 성급한 일반화, 정신적 여과, 긍정 격하, 독심술, 예언자적 오류,
확대/축소, 감정적 추론, 당위 진술, 낙인찍기, 개인화, 비난, 파국화

[응답 형식]
반드시 다음 JSON 스키마만 출력하세요. 어떤 설명도 붙이지 마세요.
{
  "empathy": "한두 문장으로 사용자의 감정을 인정하는 말",
  "distortions": ["감지된 왜곡 유형", ...],  // 0~3개
  "reframe": "사용자가 떠올릴 수 있는 균형 잡힌 관점을 '질문' 형태로 한 문장",
  "question": "내일 한 가지 관찰해볼 수 있는 구체적 질문"
}

[톤]
- 따뜻하고 차분하게. 끝맺음은 존댓말.
- 직장 맥락(상사, 동료, 업무 실패, 평가 불안 등)을 고려해 구체적으로.

[언어]
- 모든 응답 텍스트는 오직 한국어(한글)로만 작성합니다.
- 중국어·영어·일본어 단어를 섞지 마세요. 외래 고유명사도 한글 표기로 전환합니다.
"""


# ---------- 유틸 ----------

def _fallback_feedback(entry: DiaryEntry) -> FeedbackPayload:
    """API 키가 없거나 LLM 호출 실패 시 기본 템플릿 피드백."""
    return FeedbackPayload(
        mode="fallback",
        empathy="오늘 그런 일이 있으셨다니 마음이 무거우셨겠어요.",
        distortions=[],
        reframe="그 생각을 뒷받침하는 근거와, 반대되는 근거를 각각 하나씩 적어볼 수 있을까요?",
        question="내일 같은 상황이 오면, 오늘보다 한 가지 다르게 해볼 수 있는 행동은 무엇일까요?",
    )


MINIMAX_DEFAULT_BASE_URL = "https://api.minimaxi.chat/v1"
MINIMAX_DEFAULT_MODEL = "MiniMax-M2"


async def _call_minimax(entry: DiaryEntry) -> FeedbackPayload:
    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        return _fallback_feedback(entry)

    base_url = os.environ.get("MINIMAX_BASE_URL", MINIMAX_DEFAULT_BASE_URL).rstrip("/")
    model = os.environ.get("MINIMAX_MODEL", MINIMAX_DEFAULT_MODEL)

    user_block = (
        f"[상황]\n{entry.situation}\n\n"
        f"[그때 떠오른 생각]\n{entry.thought}\n\n"
        f"[스스로 시도한 재구성]\n{entry.reframe or '(작성하지 않음)'}\n\n"
        f"[직무/연차]\n{entry.job_role or '(미입력)'}"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_block},
        ],
        "max_tokens": 600,
        "temperature": 0.7,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{base_url}/text/chatcompletion_v2",
                headers=headers,
                json=payload,
            )
        response.raise_for_status()
        body = response.json()
        base_resp = body.get("base_resp") or {}
        if base_resp.get("status_code", 0) not in (0, None):
            return _fallback_feedback(entry)
        choices = body.get("choices") or []
        if not choices:
            return _fallback_feedback(entry)
        content = choices[0].get("message", {}).get("content", "")
        data = json.loads(_extract_json(content))
        return FeedbackPayload(
            mode="feedback",
            empathy=data.get("empathy", ""),
            distortions=data.get("distortions", []) or [],
            reframe=data.get("reframe", ""),
            question=data.get("question", ""),
        )
    except Exception:
        return _fallback_feedback(entry)


def _extract_json(text: str) -> str:
    """LLM이 코드펜스를 두르거나 앞뒤에 텍스트를 붙여도 JSON 블록을 추출."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text


def _contains_crisis(entry: DiaryEntry) -> bool:
    blob = f"{entry.situation}\n{entry.thought}\n{entry.reframe}"
    return bool(_CRISIS_RE.search(blob))


# ---------- 라우트 ----------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "llm": bool(os.environ.get("MINIMAX_API_KEY")),
        "model": os.environ.get("MINIMAX_MODEL", MINIMAX_DEFAULT_MODEL),
    }


@app.post("/api/analyze")
async def analyze(entry: DiaryEntry) -> JSONResponse:
    if _contains_crisis(entry):
        return JSONResponse(CRISIS_RESPONSE)
    payload = await _call_minimax(entry)
    return JSONResponse(payload.model_dump())

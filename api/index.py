"""K리더용 걱정인형 FastAPI 엔트리 포인트 (Vercel 서버리스 함수)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))
logger = logging.getLogger("worrydoll.api")


def _load_local_env() -> None:
    """로컬 uvicorn 실행에서만 .env.local을 보조로 읽는다."""
    if os.environ.get("VERCEL"):
        return
    env_path = BASE_DIR / ".env.local"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_local_env()

app = FastAPI(title="K리더용 걱정인형", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# ---------- 인증 / 세션 ----------

SESSION_COOKIE = "worrydoll_session"
OAUTH_STATE_COOKIE = "worrydoll_oauth_state"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 14
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
EPHEMERAL_SESSION_SECRET = secrets.token_urlsafe(32)
PROFILE_REQUIRED_FIELDS = (
    "company_type",
    "industry",
    "age_group",
    "org_culture",
    "leader_authority",
)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def _session_secret() -> bytes:
    secret = (
        os.environ.get("SESSION_SECRET")
        or os.environ.get("GOOGLE_CLIENT_SECRET")
        or EPHEMERAL_SESSION_SECRET
    )
    return secret.encode("utf-8")


def _sign(value: str) -> str:
    digest = hmac.new(_session_secret(), value.encode("utf-8"), hashlib.sha256).digest()
    return _b64url(digest)


def _encode_signed(payload: Dict[str, Any]) -> str:
    body = _b64url(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return f"{body}.{_sign(body)}"


def _decode_signed(token: Optional[str]) -> Optional[Dict[str, Any]]:
    if not token or "." not in token:
        return None
    body, signature = token.rsplit(".", 1)
    if not hmac.compare_digest(signature, _sign(body)):
        return None
    try:
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
    except Exception:
        return None
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and exp < time.time():
        return None
    return payload if isinstance(payload, dict) else None


def _is_secure_request(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or forwarded_proto == "https" or bool(os.environ.get("VERCEL"))


def _safe_next(value: Optional[str], default: str = "/") -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return default
    if value.startswith("/auth/") or value.startswith("/api/"):
        return default
    return value


def _oauth_configured() -> bool:
    return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))


def _google_redirect_uri(request: Request) -> str:
    configured = os.environ.get("GOOGLE_REDIRECT_URI")
    if configured:
        return configured
    return str(request.url_for("google_callback"))


def _get_session(request: Request) -> Optional[Dict[str, Any]]:
    return _decode_signed(request.cookies.get(SESSION_COOKIE))


def _profile_complete(profile: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(profile, dict):
        return False
    return all(bool(str(profile.get(field) or "").strip()) for field in PROFILE_REQUIRED_FIELDS)


def _set_signed_cookie(request: Request, response, name: str, payload: Dict[str, Any], max_age: int) -> None:
    response.set_cookie(
        name,
        _encode_signed(payload),
        max_age=max_age,
        httponly=True,
        secure=_is_secure_request(request),
        samesite="lax",
        path="/",
    )


def _clear_cookie(response, name: str) -> None:
    response.delete_cookie(name, path="/")


def _set_session_cookie(request: Request, response, session: Dict[str, Any]) -> None:
    now = int(time.time())
    session["iat"] = session.get("iat") or now
    session["exp"] = now + SESSION_MAX_AGE_SECONDS
    _set_signed_cookie(request, response, SESSION_COOKIE, session, SESSION_MAX_AGE_SECONDS)


def _require_session_redirect(request: Request) -> Optional[RedirectResponse]:
    session = _get_session(request)
    if not session:
        return RedirectResponse(f"/login?next={_safe_next(request.url.path)}", status_code=303)
    if not _profile_complete(session.get("profile")):
        return RedirectResponse(f"/onboarding?next={_safe_next(request.url.path)}", status_code=303)
    return None


def _clean_profile(data: Dict[str, Any]) -> Dict[str, str]:
    fields = (
        "job_role",
        "role_level",
        "team_size",
        "company_type",
        "industry",
        "age_group",
        "org_culture",
        "leader_authority",
    )
    cleaned: Dict[str, str] = {}
    for field in fields:
        value = data.get(field)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            cleaned[field] = text[:80]
    return cleaned


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
    category_count: Optional[int] = Field(None, ge=1, le=1000, description="같은 카테고리 선택 횟수")
    company_type: Optional[str] = Field(None, max_length=20, description="회사 구분")
    industry: Optional[str] = Field(None, max_length=30, description="업종")
    age_group: Optional[str] = Field(None, max_length=20, description="나이대")
    org_culture: Optional[str] = Field(None, max_length=20, description="조직문화")
    leader_authority: Optional[str] = Field(None, max_length=20, description="리더 구분")


class UserProfile(BaseModel):
    job_role: Optional[str] = Field(None, max_length=60)
    role_level: Optional[str] = Field(None, max_length=60)
    team_size: Optional[str] = Field(None, max_length=30)
    company_type: Optional[str] = Field(None, max_length=20)
    industry: Optional[str] = Field(None, max_length=30)
    age_group: Optional[str] = Field(None, max_length=20)
    org_culture: Optional[str] = Field(None, max_length=20)
    leader_authority: Optional[str] = Field(None, max_length=20)


# 클라이언트가 보내는 카테고리 라벨 → LLM에 주입할 한 줄 컨텍스트.
# 시스템 프롬프트는 변경하지 않고, 사용자 블록 앞에 prefix로만 붙인다.
CATEGORY_HINTS = {
    "성과 압박":  "사용자가 오늘 '성과 압박' 맥락에서 이 일을 떠올렸습니다. 매출·KPI·평가지표 같은 숫자 부담을 염두에 두고 읽어주세요.",
    "팀원 관리":  "사용자가 오늘 '팀원 관리' 맥락에서 이 일을 떠올렸습니다. 팀원의 행동·태도·동기에 대한 리더로서의 해석을 염두에 두고 읽어주세요.",
    "업무 역량":  "사용자가 오늘 '업무 역량' 맥락에서 이 일을 떠올렸습니다. 역할 전환, 실무 전문성, 의사결정 자신감, 위임 역량에 대한 부담을 염두에 두고 읽어주세요.",
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


class DiagnosisEntry(BaseModel):
    createdAt: Optional[str] = Field(None, max_length=40)
    category: Optional[str] = Field(None, max_length=30)
    situation: str = Field("", max_length=1000)
    thought: str = Field("", max_length=1000)
    reframe: str = Field("", max_length=1000)
    feedback: str = Field("", max_length=1200)


class DiagnosisCommunityPost(BaseModel):
    createdAt: Optional[str] = Field(None, max_length=40)
    category: Optional[str] = Field(None, max_length=30)
    content: str = Field("", max_length=1200)
    comments: List[str] = Field(default_factory=list, max_length=5)


class DeepDiagnosisRequest(BaseModel):
    diagnosis_type: Literal["stress", "burnout", "relationship"]
    profile: UserProfile = Field(default_factory=UserProfile)
    entries: List[DiagnosisEntry] = Field(default_factory=list, max_length=20)
    community_posts: List[DiagnosisCommunityPost] = Field(default_factory=list, max_length=20)


class DeepDiagnosisPayload(BaseModel):
    mode: Literal["diagnosis", "fallback"]
    title: str = ""
    summary: str = ""
    key_patterns: List[str] = []
    risk_signals: List[str] = []
    protective_factors: List[str] = []
    action_plan: List[str] = []
    reflection_questions: List[str] = []
    message: str = ""
    disclaimer: str = "이 리포트는 의료적 진단이나 치료가 아니라, 작성 기록을 바탕으로 한 자기이해용 분석입니다."


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


DEEP_DIAGNOSIS_SYSTEM_PROMPT = """당신은 'K리더용 걱정인형'의 심층 분석 리포트 작성자입니다.
사용자가 브라우저에 저장한 [쓰기] 상담 기록과 [커뮤니티] 공유 글을 읽고, 한국 직장 리더의 심리 패턴을 분석합니다.

절대 원칙:
1. 의료 진단명, 병명, 확정적 위험 판정은 쓰지 않습니다.
2. "우울증", "불안장애", "공황장애", "번아웃 진단"처럼 진단으로 들리는 표현은 금지합니다.
3. 사용자를 평가하거나 훈계하지 않습니다. 관찰 가능한 패턴과 다음 행동만 제안합니다.
4. 기록에 없는 사실을 꾸며내지 않습니다. 근거가 약하면 "아직 기록이 적어 조심스럽게 보면"이라고 밝힙니다.
5. 자해나 자살 신호가 보이면 분석하지 말고 도움 연결만 권해야 합니다.

분석 관점:
- stress: 성과 압박, 평가, 보고, 통제 가능성과 통제 불가능성의 혼선, 업무 긴장도를 중심으로 봅니다.
- burnout: 에너지 소진 신호, 회복 여지, 책임 과부하, 반복되는 자기비난을 중심으로 봅니다.
- relationship: 팀원, 상사, 평가 면담, 갈등, 보고 관계에서의 해석 습관과 대화 패턴을 중심으로 봅니다.

출력 품질:
- 기록 속 실제 단어를 2개 이상 자연스럽게 재사용합니다. 예: KPI, 회의, 팀원, 보고, 평가, 갈등.
- summary는 3문장 이상 5문장 이하로 씁니다.
- key_patterns, risk_signals, protective_factors, action_plan은 각각 3개 이상 5개 이하로 씁니다.
- reflection_questions는 3개만 씁니다.
- action_plan은 이번 주 업무 현장에서 실행 가능한 행동이어야 합니다. 관찰 대상, 시점, 행동이 보여야 합니다.
- risk_signals는 겁주는 표현이 아니라 "주의해서 볼 신호"로 씁니다.

출력 규칙:
- JSON 하나만 출력합니다.
- 코드펜스, 설명, 주석은 금지합니다.
- 한자, 일본어, 아랍어 문자는 절대 쓰지 않습니다. 한국어 문장 안의 자연스러운 영문 약어(KPI, OKR, 1on1 등)는 허용합니다.

형식:
{
  "title": "...",
  "summary": "...",
  "key_patterns": ["...", "...", "..."],
  "risk_signals": ["...", "...", "..."],
  "protective_factors": ["...", "...", "..."],
  "action_plan": ["...", "...", "..."],
  "reflection_questions": ["...", "...", "..."]
}"""


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


DIAGNOSIS_LABELS = {
    "stress": "직무 스트레스 진단",
    "burnout": "번아웃 위험도",
    "relationship": "리더 관계 스트레스",
}


def _fallback_deep_diagnosis(payload: DeepDiagnosisRequest) -> DeepDiagnosisPayload:
    label = DIAGNOSIS_LABELS.get(payload.diagnosis_type, "심층 진단")
    categories: Dict[str, int] = {}
    for entry in payload.entries:
        if entry.category:
            categories[entry.category] = categories.get(entry.category, 0) + 1
    for post in payload.community_posts:
        if post.category:
            categories[post.category] = categories.get(post.category, 0) + 1
    top_category = max(categories.items(), key=lambda item: item[1])[0] if categories else "최근 업무 장면"
    return DeepDiagnosisPayload(
        mode="fallback",
        title=f"{label} 리포트",
        summary=(
            f"현재 인공지능 분석 응답이 불안정해 기본 리포트를 보여드립니다. "
            f"최근 기록에서는 '{top_category}' 맥락이 반복적으로 나타납니다. "
            "같은 주제가 이어질수록 사실, 해석, 다음 행동을 분리해 보는 것이 도움이 됩니다."
        ),
        key_patterns=[
            f"'{top_category}' 관련 장면이 기록과 커뮤니티 활동에 반복해서 등장합니다.",
            "업무 상황을 리더 개인의 책임으로 빠르게 연결하는 흐름이 있을 수 있습니다.",
            "상담 기록과 공개적으로 나눈 고민이 함께 쌓이면서 반복 맥락을 더 선명하게 볼 수 있습니다.",
        ],
        risk_signals=[
            "같은 장면을 반복해서 떠올리며 업무 후에도 긴장이 쉽게 풀리지 않는지 살펴보세요.",
            "한 번의 보고, 평가, 대화를 전체 리더십 평가로 확대하고 있는지 확인해보세요.",
            "휴식보다 보완 행동만 계속 늘어나는 흐름이 있는지 주의해서 보세요.",
        ],
        protective_factors=[
            "기록을 남기고 있다는 점은 감정과 사실을 분리해 볼 수 있는 좋은 기반입니다.",
            "커뮤니티에 고민을 공유했다면 혼자 결론 내리지 않는 통로가 이미 생긴 상태입니다.",
            "카테고리별로 고민을 나누면 막연한 불안보다 구체적인 업무 장면을 다루기 쉬워집니다.",
        ],
        action_plan=[
            "이번 주 가장 자주 등장한 장면 하나를 골라, 사실과 해석을 각각 한 줄씩 분리해 적어보세요.",
            "다음 회의나 보고 전, 내가 통제할 수 있는 준비 행동 1개와 통제할 수 없는 반응 1개를 나눠보세요.",
            "긴장이 커지는 대화 뒤에는 바로 결론을 내리지 말고, 확인된 발언과 내 추측을 따로 기록해보세요.",
        ],
        reflection_questions=[
            "최근 기록에서 내가 가장 빨리 책임으로 받아들이는 장면은 무엇인가요?",
            "상대의 실제 발언과 내가 해석한 의미 사이에 차이가 있었던 순간은 언제였나요?",
            "이번 주에 하나만 덜 떠안는다면 어떤 업무나 감정 부담을 내려놓을 수 있을까요?",
        ],
        message="지금은 기본 리포트를 보여드리고 있어요. 잠시 후 다시 시도하면 더 개인화된 분석을 받을 수 있습니다.",
    )


MINIMAX_DEFAULT_BASE_URL = "https://api.minimaxi.chat/v1"
MINIMAX_DEFAULT_MODEL = "MiniMax-M2.7"

OPENROUTER_DEFAULT_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_DEFAULT_MODEL = "minimax/minimax-m2.7"
OPENROUTER_DEFAULT_REASONING_EFFORT = "minimal"

NVIDIA_DEFAULT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_DEFAULT_MODEL = "minimaxai/minimax-m2.7"
LLM_MAX_TOKENS = 2048
DEEP_DIAGNOSIS_MAX_TOKENS = 3072
# Vercel Hobby 플랜 maxDuration 300s 한도 내에서: OpenRouter 180 + NVIDIA 100 = 280s.
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


def _diagnosis_text_parts(p: DeepDiagnosisPayload) -> List[str]:
    return [
        p.title,
        p.summary,
        *p.key_patterns,
        *p.risk_signals,
        *p.protective_factors,
        *p.action_plan,
        *p.reflection_questions,
        p.message,
        p.disclaimer,
    ]


def _has_forbidden_diagnosis(payload: DeepDiagnosisPayload) -> bool:
    return bool(_FORBIDDEN_RE.search(" ".join(_diagnosis_text_parts(payload))))


def _scrub_diagnosis_payload(p: DeepDiagnosisPayload) -> DeepDiagnosisPayload:
    return DeepDiagnosisPayload(
        mode=p.mode,
        title=_scrub_forbidden(p.title),
        summary=_scrub_forbidden(p.summary),
        key_patterns=[_scrub_forbidden(item) for item in p.key_patterns],
        risk_signals=[_scrub_forbidden(item) for item in p.risk_signals],
        protective_factors=[_scrub_forbidden(item) for item in p.protective_factors],
        action_plan=[_scrub_forbidden(item) for item in p.action_plan],
        reflection_questions=[_scrub_forbidden(item) for item in p.reflection_questions],
        message=_scrub_forbidden(p.message),
        disclaimer=_scrub_forbidden(p.disclaimer),
    )


def _format_profile_context(entry) -> str:
    pairs = [
        ("직무/연차", getattr(entry, "job_role", None)),
        ("직급", getattr(entry, "role_level", None)),
        ("팀 규모", getattr(entry, "team_size", None)),
        ("회사 구분", getattr(entry, "company_type", None)),
        ("업종", getattr(entry, "industry", None)),
        ("나이대", getattr(entry, "age_group", None)),
        ("조직문화", getattr(entry, "org_culture", None)),
        ("리더 구분", getattr(entry, "leader_authority", None)),
    ]
    lines = [f"- {label}: {value}" for label, value in pairs if value]
    return "\n".join(lines) if lines else "(미입력)"


def _build_user_block(entry: DiaryEntry) -> str:
    hint = CATEGORY_HINTS.get((entry.category or "").strip()) if entry.category else None
    prefix = f"[상황 맥락]\n{hint}\n\n" if hint else ""
    repeat = ""
    if entry.category and entry.category_count and entry.category_count > 1:
        repeat = (
            f"[반복 맥락]\n"
            f"브라우저 저장 기록 기준 '{entry.category}' 카테고리를 {entry.category_count}번째 선택했습니다. "
            "같은 범주 안에서도 이번에는 어떤 대상, 장면, 기준이 달라졌는지 더 구체적으로 짚어주세요.\n\n"
        )
    return (
        f"{prefix}"
        f"{repeat}"
        f"[상황]\n{entry.situation}\n\n"
        f"[그때 떠오른 생각]\n{entry.thought}\n\n"
        f"[스스로 시도한 재구성]\n{entry.reframe or '(작성하지 않음)'}\n\n"
        f"[사용자 정보]\n{_format_profile_context(entry)}"
    )


def _deep_diagnosis_text(payload: DeepDiagnosisRequest) -> str:
    parts: List[str] = []
    for entry in payload.entries:
        parts.extend([entry.situation, entry.thought, entry.reframe, entry.feedback])
    for post in payload.community_posts:
        parts.append(post.content)
        parts.extend(post.comments)
    return "\n".join(part for part in parts if part)


def _build_deep_diagnosis_user_block(payload: DeepDiagnosisRequest, profile: UserProfile) -> str:
    label = DIAGNOSIS_LABELS.get(payload.diagnosis_type, payload.diagnosis_type)
    entry_lines = []
    for idx, entry in enumerate(payload.entries[:20], start=1):
        entry_lines.append(
            "\n".join(
                [
                    f"{idx}. 날짜: {entry.createdAt or '미상'}",
                    f"   분류: {entry.category or '미분류'}",
                    f"   상황: {entry.situation or '(없음)'}",
                    f"   자동 생각: {entry.thought or '(없음)'}",
                    f"   재구성: {entry.reframe or '(없음)'}",
                    f"   기존 피드백: {entry.feedback or '(없음)'}",
                ]
            )
        )

    post_lines = []
    for idx, post in enumerate(payload.community_posts[:20], start=1):
        comments = " / ".join(comment for comment in post.comments[:5] if comment) or "(댓글 없음)"
        post_lines.append(
            "\n".join(
                [
                    f"{idx}. 날짜: {post.createdAt or '미상'}",
                    f"   분류: {post.category or '미분류'}",
                    f"   글: {post.content or '(없음)'}",
                    f"   댓글: {comments}",
                ]
            )
        )

    return (
        f"[진단 종류]\n{label} ({payload.diagnosis_type})\n\n"
        f"[사용자 정보]\n{_format_profile_context(profile)}\n\n"
        f"[쓰기 상담 기록]\n{chr(10).join(entry_lines) if entry_lines else '(기록 없음)'}\n\n"
        f"[커뮤니티 활동]\n{chr(10).join(post_lines) if post_lines else '(활동 없음)'}"
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


def _normalize_json_list(value: Any, limit: int = 5) -> List[str]:
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else [value]
    items = []
    for item in raw_items:
        text = _normalize_text(str(item or "")).strip()
        if text:
            items.append(text[:500])
        if len(items) >= limit:
            break
    return items


def _parse_diagnosis_json(content: str) -> DeepDiagnosisPayload:
    data = json.loads(_extract_json(content))
    payload = DeepDiagnosisPayload(
        mode="diagnosis",
        title=_normalize_text(str(data.get("title") or "심층 분석 리포트")).strip()[:120],
        summary=_normalize_text(str(data.get("summary") or "")).strip()[:1400],
        key_patterns=_normalize_json_list(data.get("key_patterns")),
        risk_signals=_normalize_json_list(data.get("risk_signals")),
        protective_factors=_normalize_json_list(data.get("protective_factors")),
        action_plan=_normalize_json_list(data.get("action_plan")),
        reflection_questions=_normalize_json_list(data.get("reflection_questions"), limit=3),
    )
    if not payload.summary:
        raise ValueError("diagnosis summary is empty")
    return payload


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
    """레거시 MiniMax 직접 호출. 실패 시 None 반환."""
    model = os.environ.get("MINIMAX_MODEL", MINIMAX_DEFAULT_MODEL)
    return await _call_minimax_model(
        system_prompt, user_block, model, PRIMARY_TIMEOUT_SECONDS
    )


async def _call_minimax_diagnosis(
    system_prompt: str, user_block: str
) -> Optional[DeepDiagnosisPayload]:
    """레거시 MiniMax 직접 호출 기반 심층 진단. 실패 시 None 반환."""
    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        logger.warning("MiniMax diagnosis skip: MINIMAX_API_KEY is not configured")
        return None

    base_url = os.environ.get("MINIMAX_BASE_URL", MINIMAX_DEFAULT_BASE_URL).rstrip("/")
    model = os.environ.get("MINIMAX_MODEL", MINIMAX_DEFAULT_MODEL)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_block},
        ],
        "max_tokens": DEEP_DIAGNOSIS_MAX_TOKENS,
        "temperature": 0.2,
        "top_p": 0.9,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        started_at = time.perf_counter()
        async with httpx.AsyncClient(timeout=PRIMARY_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{base_url}/text/chatcompletion_v2",
                headers=headers,
                json=payload,
            )
        elapsed = time.perf_counter() - started_at
        logger.info("MiniMax diagnosis model=%s responded in %.2fs", model, elapsed)
        response.raise_for_status()
        body = response.json()
        base_resp = body.get("base_resp") or {}
        if base_resp.get("status_code", 0) not in (0, None):
            logger.warning("MiniMax diagnosis fallback: base_resp not ok: %s", base_resp)
            return None
        choices = body.get("choices") or []
        if not choices:
            logger.warning("MiniMax diagnosis fallback: empty choices in response")
            return None
        raw_content = choices[0].get("message", {}).get("content", "")
        if isinstance(raw_content, list):
            content = "\n".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in raw_content
            )
        else:
            content = str(raw_content or "")
        result = _parse_diagnosis_json(content)
        if _has_forbidden_diagnosis(result):
            logger.info("MiniMax diagnosis response contained forbidden characters; scrubbing")
            result = _scrub_diagnosis_payload(result)
        return result
    except Exception:
        logger.exception("MiniMax diagnosis model=%s call failed: %r", model, user_block[:120])
        return None


async def _call_openrouter(system_prompt: str, user_block: str) -> Optional[FeedbackPayload]:
    """OpenRouter MiniMax M2.7 1차 provider. OpenAI 호환 엔드포인트."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        logger.warning("OpenRouter skip: OPENROUTER_API_KEY is not configured")
        return None

    url = os.environ.get("OPENROUTER_BASE_URL", OPENROUTER_DEFAULT_URL).strip()
    model = os.environ.get("OPENROUTER_MODEL", OPENROUTER_DEFAULT_MODEL)
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_block},
        ],
        "max_tokens": LLM_MAX_TOKENS,
        "temperature": 0.2,
        "top_p": 0.9,
    }
    reasoning_effort = os.environ.get(
        "OPENROUTER_REASONING_EFFORT", OPENROUTER_DEFAULT_REASONING_EFFORT
    ).strip()
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort, "exclude": True}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": os.environ.get("OPENROUTER_APP_NAME", "K AI Mental Support"),
    }
    referer = os.environ.get("OPENROUTER_SITE_URL")
    if referer:
        headers["HTTP-Referer"] = referer

    try:
        started_at = time.perf_counter()
        async with httpx.AsyncClient(timeout=PRIMARY_TIMEOUT_SECONDS) as client:
            response = await client.post(url, headers=headers, json=payload)
        elapsed = time.perf_counter() - started_at
        logger.info("OpenRouter model=%s responded in %.2fs", model, elapsed)
        response.raise_for_status()
        body = response.json()
        choices = body.get("choices") or []
        if not choices:
            logger.warning("OpenRouter fallback: empty choices in response")
            return None
        raw_content = choices[0].get("message", {}).get("content", "")
        if isinstance(raw_content, list):
            content = "\n".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in raw_content
            )
        else:
            content = str(raw_content or "")
        result = _parse_feedback_json(content)
        if _has_forbidden(result):
            logger.info("OpenRouter model=%s response contained forbidden characters; scrubbing", model)
            result = _scrub_payload(result)
        return result
    except Exception:
        logger.exception("OpenRouter model=%s call failed: %r", model, user_block[:120])
        return None


async def _call_nvidia(system_prompt: str, user_block: str) -> Optional[FeedbackPayload]:
    """NVIDIA MiniMax M2.7 2차 폴백. OpenAI 호환 엔드포인트."""
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


async def _call_openrouter_diagnosis(
    system_prompt: str, user_block: str
) -> Optional[DeepDiagnosisPayload]:
    """OpenRouter 기반 심층 진단 리포트 생성."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        logger.warning("OpenRouter diagnosis skip: OPENROUTER_API_KEY is not configured")
        return None

    url = os.environ.get("OPENROUTER_BASE_URL", OPENROUTER_DEFAULT_URL).strip()
    model = os.environ.get("OPENROUTER_MODEL", OPENROUTER_DEFAULT_MODEL)
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_block},
        ],
        "max_tokens": DEEP_DIAGNOSIS_MAX_TOKENS,
        "temperature": 0.2,
        "top_p": 0.9,
    }
    reasoning_effort = os.environ.get(
        "OPENROUTER_REASONING_EFFORT", OPENROUTER_DEFAULT_REASONING_EFFORT
    ).strip()
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort, "exclude": True}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": os.environ.get("OPENROUTER_APP_NAME", "K AI Mental Support"),
    }
    referer = os.environ.get("OPENROUTER_SITE_URL")
    if referer:
        headers["HTTP-Referer"] = referer

    try:
        started_at = time.perf_counter()
        async with httpx.AsyncClient(timeout=PRIMARY_TIMEOUT_SECONDS) as client:
            response = await client.post(url, headers=headers, json=payload)
        elapsed = time.perf_counter() - started_at
        logger.info("OpenRouter diagnosis model=%s responded in %.2fs", model, elapsed)
        response.raise_for_status()
        body = response.json()
        choices = body.get("choices") or []
        if not choices:
            logger.warning("OpenRouter diagnosis fallback: empty choices in response")
            return None
        raw_content = choices[0].get("message", {}).get("content", "")
        if isinstance(raw_content, list):
            content = "\n".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in raw_content
            )
        else:
            content = str(raw_content or "")
        result = _parse_diagnosis_json(content)
        if _has_forbidden_diagnosis(result):
            logger.info("OpenRouter diagnosis response contained forbidden characters; scrubbing")
            result = _scrub_diagnosis_payload(result)
        return result
    except Exception:
        logger.exception("OpenRouter diagnosis call failed: %r", user_block[:120])
        return None


async def _call_nvidia_diagnosis(
    system_prompt: str, user_block: str
) -> Optional[DeepDiagnosisPayload]:
    """NVIDIA 기반 심층 진단 리포트 폴백."""
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        logger.warning("NVIDIA diagnosis skip: NVIDIA_API_KEY is not configured")
        return None

    url = os.environ.get("NVIDIA_BASE_URL", NVIDIA_DEFAULT_URL).strip()
    model = os.environ.get("NVIDIA_BASE_MODEL", NVIDIA_DEFAULT_MODEL)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_block},
        ],
        "max_tokens": DEEP_DIAGNOSIS_MAX_TOKENS,
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
        logger.info("NVIDIA diagnosis responded in %.2fs", elapsed)
        response.raise_for_status()
        body = response.json()
        choices = body.get("choices") or []
        if not choices:
            logger.warning("NVIDIA diagnosis fallback: empty choices in response")
            return None
        raw_content = choices[0].get("message", {}).get("content", "")
        if isinstance(raw_content, list):
            content = "\n".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in raw_content
            )
        else:
            content = str(raw_content or "")
        result = _parse_diagnosis_json(content)
        if _has_forbidden_diagnosis(result):
            logger.info("NVIDIA diagnosis response contained forbidden characters; scrubbing")
            result = _scrub_diagnosis_payload(result)
        return result
    except Exception:
        logger.exception("NVIDIA diagnosis call failed: %r", user_block[:120])
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

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    next_path = _safe_next(request.query_params.get("next"))
    session = _get_session(request)
    if session:
        destination = next_path if _profile_complete(session.get("profile")) else f"/onboarding?next={next_path}"
        return RedirectResponse(destination, status_code=303)
    return TEMPLATES.TemplateResponse(
        "login.html",
        {
            "request": request,
            "next": next_path,
            "oauth_configured": _oauth_configured(),
            "error": request.query_params.get("error"),
        },
    )


@app.get("/onboarding", response_class=HTMLResponse)
async def onboarding_page(request: Request) -> HTMLResponse:
    session = _get_session(request)
    if not session:
        return RedirectResponse(f"/login?next={_safe_next(request.query_params.get('next'))}", status_code=303)
    return TEMPLATES.TemplateResponse(
        "onboarding.html",
        {
            "request": request,
            "user": session.get("user") or {},
            "profile": session.get("profile") or {},
            "next": _safe_next(request.query_params.get("next")),
        },
    )


@app.get("/auth/google/start")
async def google_start(request: Request):
    if not _oauth_configured():
        return RedirectResponse("/login?error=google_not_configured", status_code=303)

    state = secrets.token_urlsafe(32)
    next_path = _safe_next(request.query_params.get("next"))
    state_payload = {"state": state, "next": next_path, "exp": int(time.time()) + 600}
    params = {
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "redirect_uri": _google_redirect_uri(request),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    response = RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}", status_code=303)
    _set_signed_cookie(request, response, OAUTH_STATE_COOKIE, state_payload, 600)
    return response


@app.get("/auth/google/callback")
async def google_callback(request: Request):
    if not _oauth_configured():
        return RedirectResponse("/login?error=google_not_configured", status_code=303)

    state_payload = _decode_signed(request.cookies.get(OAUTH_STATE_COOKIE))
    state = request.query_params.get("state")
    code = request.query_params.get("code")
    if not state_payload or state_payload.get("state") != state or not code:
        return RedirectResponse("/login?error=invalid_state", status_code=303)

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            token_response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": os.environ["GOOGLE_CLIENT_ID"],
                    "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                    "redirect_uri": _google_redirect_uri(request),
                    "grant_type": "authorization_code",
                },
            )
            token_response.raise_for_status()
            id_token = token_response.json().get("id_token")
            if not id_token:
                return RedirectResponse("/login?error=missing_token", status_code=303)
            tokeninfo_response = await client.get(GOOGLE_TOKENINFO_URL, params={"id_token": id_token})
            tokeninfo_response.raise_for_status()
            tokeninfo = tokeninfo_response.json()
    except Exception:
        logger.exception("Google OAuth callback failed")
        return RedirectResponse("/login?error=oauth_failed", status_code=303)

    email_verified = tokeninfo.get("email_verified") in (True, "true", "True", "1")
    if tokeninfo.get("aud") != os.environ["GOOGLE_CLIENT_ID"] or not email_verified:
        return RedirectResponse("/login?error=invalid_token", status_code=303)

    user = {
        "sub": tokeninfo.get("sub", ""),
        "email": tokeninfo.get("email", ""),
        "name": tokeninfo.get("name") or tokeninfo.get("email", ""),
        "picture": tokeninfo.get("picture", ""),
    }
    session = {"user": user, "profile": {}}
    next_path = _safe_next(state_payload.get("next"))
    response = RedirectResponse(f"/onboarding?next={next_path}", status_code=303)
    _clear_cookie(response, OAUTH_STATE_COOKIE)
    _set_session_cookie(request, response, session)
    return response


@app.get("/logout")
async def logout_page():
    response = RedirectResponse("/login", status_code=303)
    _clear_cookie(response, SESSION_COOKIE)
    return response


@app.post("/api/logout")
async def logout_api() -> JSONResponse:
    response = JSONResponse({"ok": True})
    _clear_cookie(response, SESSION_COOKIE)
    return response


@app.get("/api/me")
async def me(request: Request) -> JSONResponse:
    session = _get_session(request)
    if not session:
        return JSONResponse({"authenticated": False})
    return JSONResponse(
        {
            "authenticated": True,
            "user": session.get("user") or {},
            "profile": session.get("profile") or {},
            "profile_complete": _profile_complete(session.get("profile")),
        }
    )


@app.post("/api/profile")
async def save_profile(profile: UserProfile, request: Request) -> JSONResponse:
    session = _get_session(request)
    if not session:
        return JSONResponse({"ok": False, "message": "로그인이 필요합니다."}, status_code=401)

    current = session.get("profile") if isinstance(session.get("profile"), dict) else {}
    merged = {**current, **_clean_profile(profile.model_dump())}
    missing = [field for field in PROFILE_REQUIRED_FIELDS if not merged.get(field)]
    if missing:
        return JSONResponse(
            {"ok": False, "message": "필수 사용자 정보를 모두 선택해주세요.", "missing": missing},
            status_code=400,
        )

    session["profile"] = merged
    response = JSONResponse({"ok": True, "profile": merged})
    _set_session_cookie(request, response, session)
    return response


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    redirect = _require_session_redirect(request)
    if redirect:
        return redirect
    return TEMPLATES.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "auth": {
            "google_configured": _oauth_configured(),
        },
        "primary": {
            "configured": bool(os.environ.get("OPENROUTER_API_KEY")),
            "model": os.environ.get("OPENROUTER_MODEL", OPENROUTER_DEFAULT_MODEL),
        },
        "minimax": {
            "configured": bool(os.environ.get("MINIMAX_API_KEY")),
            "model": os.environ.get("MINIMAX_MODEL", MINIMAX_DEFAULT_MODEL),
        },
        "fallback": {
            "configured": bool(os.environ.get("NVIDIA_API_KEY")),
            "model": os.environ.get("NVIDIA_BASE_MODEL", NVIDIA_DEFAULT_MODEL),
        },
    }


@app.post("/api/analyze")
async def analyze(entry: DiaryEntry, request: Request) -> JSONResponse:
    if not _get_session(request):
        return JSONResponse({"message": "로그인이 필요합니다."}, status_code=401)
    text = f"{entry.situation}\n{entry.thought}\n{entry.reframe}"
    if _contains_crisis(text):
        return JSONResponse(CRISIS_RESPONSE)

    user_block = _build_user_block(entry)
    # 1차: OpenRouter → 2차: MiniMax direct → 3차: NVIDIA → 최후: 템플릿
    result = await _call_openrouter(SYSTEM_PROMPT, user_block)
    if result is None:
        logger.info("Primary provider failed; trying direct MiniMax")
        result = await _call_minimax(SYSTEM_PROMPT, user_block)
    if result is None:
        logger.info("Direct MiniMax failed; trying NVIDIA fallback")
        result = await _call_nvidia(SYSTEM_PROMPT, user_block)
    if result is None:
        logger.info("All providers failed; returning template fallback")
        result = _fallback_feedback()
    return JSONResponse(result.model_dump())


@app.post("/api/deep-diagnosis")
async def deep_diagnosis(payload: DeepDiagnosisRequest, request: Request) -> JSONResponse:
    session = _get_session(request)
    if not session:
        return JSONResponse({"message": "로그인이 필요합니다."}, status_code=401)
    if not payload.entries and not payload.community_posts:
        return JSONResponse(
            {"message": "심층 진단을 만들 상담 기록이나 커뮤니티 활동이 아직 없어요."},
            status_code=400,
        )

    if _contains_crisis(_deep_diagnosis_text(payload)):
        return JSONResponse(CRISIS_RESPONSE)

    session_profile = session.get("profile") if isinstance(session.get("profile"), dict) else {}
    client_profile = payload.profile.model_dump(exclude_none=True)
    profile = UserProfile(**{**client_profile, **session_profile})
    user_block = _build_deep_diagnosis_user_block(payload, profile)

    result = await _call_openrouter_diagnosis(DEEP_DIAGNOSIS_SYSTEM_PROMPT, user_block)
    if result is None:
        logger.info("Deep diagnosis: primary provider failed; trying direct MiniMax")
        result = await _call_minimax_diagnosis(DEEP_DIAGNOSIS_SYSTEM_PROMPT, user_block)
    if result is None:
        logger.info("Deep diagnosis: direct MiniMax failed; trying NVIDIA fallback")
        result = await _call_nvidia_diagnosis(DEEP_DIAGNOSIS_SYSTEM_PROMPT, user_block)
    if result is None:
        logger.info("Deep diagnosis: all providers failed; returning template fallback")
        result = _fallback_deep_diagnosis(payload)
    return JSONResponse(result.model_dump())


# ---------- 리더스 ----------

class LeaderEntry(BaseModel):
    situation: str = Field(..., min_length=1, max_length=1000, description="상황")
    thought: str = Field(..., min_length=1, max_length=1000, description="자동화 사고")
    reframe: str = Field("", max_length=1000, description="재구성 시도")
    role_level: Optional[str] = Field(None, max_length=60, description="직급")
    team_size: Optional[str] = Field(None, max_length=30, description="팀 규모")
    industry: Optional[str] = Field(None, max_length=60, description="업종")
    company_type: Optional[str] = Field(None, max_length=20, description="회사 구분")
    age_group: Optional[str] = Field(None, max_length=20, description="나이대")
    org_culture: Optional[str] = Field(None, max_length=20, description="조직문화")
    leader_authority: Optional[str] = Field(None, max_length=20, description="리더 구분")


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
        f"[사용자 정보]\n{_format_profile_context(entry)}"
    )


@app.get("/leaders", response_class=HTMLResponse)
async def leaders_page(request: Request) -> HTMLResponse:
    redirect = _require_session_redirect(request)
    if redirect:
        return redirect
    return TEMPLATES.TemplateResponse("leaders.html", {"request": request})


@app.post("/api/leader")
async def leader_analyze(entry: LeaderEntry, request: Request) -> JSONResponse:
    if not _get_session(request):
        return JSONResponse({"message": "로그인이 필요합니다."}, status_code=401)
    text = f"{entry.situation}\n{entry.thought}\n{entry.reframe}"
    if _contains_crisis(text):
        return JSONResponse(CRISIS_RESPONSE)

    user_block = _build_leader_user_block(entry)
    result = await _call_openrouter(LEADER_SYSTEM_PROMPT, user_block)
    if result is None:
        logger.info("Leader: primary provider failed; trying direct MiniMax")
        result = await _call_minimax(LEADER_SYSTEM_PROMPT, user_block)
    if result is None:
        logger.info("Leader: direct MiniMax failed; trying NVIDIA fallback")
        result = await _call_nvidia(LEADER_SYSTEM_PROMPT, user_block)
    if result is None:
        logger.info("Leader: all providers failed; returning template fallback")
        result = _fallback_feedback()
    return JSONResponse(result.model_dump())

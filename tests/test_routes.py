from urllib.parse import parse_qs, urlparse

import pytest

from api import index as api_index
from tests.conftest import set_session_cookie


def analyze_payload():
    return {
        "situation": "팀원이 회의에서 보고를 빠뜨렸다",
        "thought": "내가 리더로 부족해서 이런 일이 생겼다",
        "reframe": "사실을 더 확인해볼 수 있다",
        "category": "팀원 관리",
        "category_count": 2,
    }


def deep_diagnosis_payload():
    return {
        "diagnosis_type": "stress",
        "profile": {
            "company_type": "대기업",
            "industry": "IT",
            "age_group": "30대",
            "org_culture": "수평적",
            "leader_authority": "인사권 있음",
        },
        "entries": [
            {
                "createdAt": "2026-06-17T10:00:00.000Z",
                "category": "성과 압박",
                "situation": "KPI 보고에서 질문을 받았다",
                "thought": "내가 리더로 부족하다",
                "reframe": "질문은 확인일 수도 있다",
                "feedback": "다음 회의에서 기준을 확인해보세요.",
            }
        ],
        "community_posts": [
            {
                "createdAt": "2026-06-17T11:00:00.000Z",
                "category": "상사·보고",
                "content": "임원 보고 후 침묵이 계속 마음에 남는다",
                "comments": ["비슷한 경험이 있어요"],
            }
        ],
    }


def test_public_health_and_me_without_session(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {
        "ok": True,
        "auth": {"google_configured": False},
        "primary": {"configured": False, "model": api_index.OPENROUTER_DEFAULT_MODEL},
        "minimax": {"configured": False, "model": api_index.MINIMAX_DEFAULT_MODEL},
        "fallback": {"configured": False, "model": api_index.NVIDIA_DEFAULT_MODEL},
    }

    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json() == {"authenticated": False}


def test_me_with_session_and_logout(client, complete_profile):
    set_session_cookie(client, profile=complete_profile)

    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["authenticated"] is True
    assert me.json()["profile_complete"] is True

    logout_page = client.get("/logout")
    assert logout_page.status_code == 303
    assert logout_page.headers["location"] == "/login"
    assert api_index.SESSION_COOKIE in logout_page.headers["set-cookie"]

    set_session_cookie(client, profile=complete_profile)
    logout_api = client.post("/api/logout")
    assert logout_api.status_code == 200
    assert logout_api.json() == {"ok": True}
    assert api_index.SESSION_COOKIE in logout_api.headers["set-cookie"]


def test_page_auth_redirects(client, complete_profile):
    root = client.get("/")
    assert root.status_code == 303
    assert root.headers["location"] == "/login?next=/"

    set_session_cookie(client, profile={})
    leaders = client.get("/leaders")
    assert leaders.status_code == 303
    assert leaders.headers["location"] == "/onboarding?next=/leaders"

    set_session_cookie(client, profile=complete_profile)
    index = client.get("/")
    assert index.status_code == 200


def test_onboarding_requires_session(client):
    response = client.get("/onboarding?next=/leaders")
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/leaders"


def test_login_page_redirects_authenticated_users(client, complete_profile):
    set_session_cookie(client, profile={})
    incomplete = client.get("/login?next=/leaders")
    assert incomplete.status_code == 303
    assert incomplete.headers["location"] == "/onboarding?next=/leaders"

    set_session_cookie(client, profile=complete_profile)
    complete = client.get("/login?next=/leaders")
    assert complete.status_code == 303
    assert complete.headers["location"] == "/leaders"


def test_google_start_requires_config_and_sanitizes_next(client, monkeypatch):
    not_configured = client.get("/auth/google/start?next=/leaders")
    assert not_configured.status_code == 303
    assert not_configured.headers["location"] == "/login?error=google_not_configured"

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    configured = client.get("/auth/google/start?next=/api/analyze")
    assert configured.status_code == 303
    parsed = urlparse(configured.headers["location"])
    params = parse_qs(parsed.query)

    assert parsed.netloc == "accounts.google.com"
    assert params["client_id"] == ["client-id"]
    assert params["scope"] == ["openid email profile"]
    assert params["state"]
    assert api_index.OAUTH_STATE_COOKIE in configured.headers["set-cookie"]


def test_google_callback_rejects_invalid_state(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")

    response = client.get("/auth/google/callback?state=wrong&code=code")

    assert response.status_code == 303
    assert response.headers["location"] == "/login?error=invalid_state"


def test_google_callback_sets_session_on_verified_token(client, monkeypatch):
    class FakeResponse:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self.body

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, data):
            assert url == api_index.GOOGLE_TOKEN_URL
            assert data["code"] == "valid-code"
            return FakeResponse({"id_token": "id-token"})

        async def get(self, url, params):
            assert url == api_index.GOOGLE_TOKENINFO_URL
            assert params == {"id_token": "id-token"}
            return FakeResponse(
                {
                    "aud": "client-id",
                    "email_verified": "true",
                    "sub": "google-user",
                    "email": "leader@example.com",
                    "name": "Leader",
                    "picture": "https://example.com/avatar.png",
                }
            )

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(api_index.httpx, "AsyncClient", FakeAsyncClient)
    client.cookies.set(
        api_index.OAUTH_STATE_COOKIE,
        api_index._encode_signed({"state": "state-1", "next": "/leaders"}),
    )

    response = client.get("/auth/google/callback?state=state-1&code=valid-code")

    assert response.status_code == 303
    assert response.headers["location"] == "/onboarding?next=/leaders"
    assert api_index.OAUTH_STATE_COOKIE in response.headers["set-cookie"]
    assert api_index.SESSION_COOKIE in response.headers["set-cookie"]


def test_profile_api_requires_session_and_required_fields(client, complete_profile):
    unauthenticated = client.post("/api/profile", json=complete_profile)
    assert unauthenticated.status_code == 401

    set_session_cookie(client, profile={})
    missing = client.post("/api/profile", json={"company_type": "스타트업"})
    assert missing.status_code == 400
    assert "industry" in missing.json()["missing"]

    saved = client.post("/api/profile", json=complete_profile)
    assert saved.status_code == 200
    assert saved.json()["ok"] is True
    assert saved.json()["profile"]["industry"] == "소프트웨어"
    assert api_index.SESSION_COOKIE in saved.headers["set-cookie"]


def test_analyze_requires_session(client):
    response = client.post("/api/analyze", json=analyze_payload())
    assert response.status_code == 401
    assert response.json() == {"message": "로그인이 필요합니다."}


def test_analyze_crisis_short_circuits_llm(client, complete_profile, monkeypatch):
    async def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM provider should not be called for crisis input")

    monkeypatch.setattr(api_index, "_call_openrouter", fail_if_called)
    monkeypatch.setattr(api_index, "_call_minimax", fail_if_called)
    monkeypatch.setattr(api_index, "_call_nvidia", fail_if_called)
    set_session_cookie(client, profile=complete_profile)

    response = client.post(
        "/api/analyze",
        json={**analyze_payload(), "thought": "죽고 싶다는 생각이 들었다"},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "crisis"
    assert response.json()["hotlines"][0]["number"] == "1393"


def test_analyze_returns_primary_feedback_without_fallback(client, complete_profile, monkeypatch):
    async def primary(*args, **kwargs):
        return api_index.FeedbackPayload(
            mode="feedback",
            empathy="회의에서 보고 누락을 보며 많이 무거우셨겠어요.",
            distortions=["개인화"],
            reframe="이 일이 전부 리더 책임인지 확인해볼 수 있을까요?",
            question="다음 회의에서 보고 기준을 한 문장으로 확인해보세요.",
        )

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("Fallback provider should not be called")

    monkeypatch.setattr(api_index, "_call_openrouter", primary)
    monkeypatch.setattr(api_index, "_call_minimax", fail_if_called)
    monkeypatch.setattr(api_index, "_call_nvidia", fail_if_called)
    set_session_cookie(client, profile=complete_profile)

    response = client.post("/api/analyze", json=analyze_payload())

    assert response.status_code == 200
    assert response.json()["mode"] == "feedback"
    assert response.json()["distortions"] == ["개인화"]


def test_analyze_returns_template_fallback_when_all_providers_fail(client, complete_profile, monkeypatch):
    async def unavailable(*args, **kwargs):
        return None

    monkeypatch.setattr(api_index, "_call_openrouter", unavailable)
    monkeypatch.setattr(api_index, "_call_minimax", unavailable)
    monkeypatch.setattr(api_index, "_call_nvidia", unavailable)
    set_session_cookie(client, profile=complete_profile)

    response = client.post("/api/analyze", json=analyze_payload())

    assert response.status_code == 200
    assert response.json()["mode"] == "fallback"
    assert "기본 피드백" in response.json()["message"]


def test_deep_diagnosis_requires_session_and_activity(client, complete_profile):
    unauthenticated = client.post("/api/deep-diagnosis", json=deep_diagnosis_payload())
    assert unauthenticated.status_code == 401

    set_session_cookie(client, profile=complete_profile)
    empty = client.post(
        "/api/deep-diagnosis",
        json={"diagnosis_type": "stress", "entries": [], "community_posts": []},
    )
    assert empty.status_code == 400
    assert "활동" in empty.json()["message"]


def test_deep_diagnosis_crisis_short_circuits_llm(client, complete_profile, monkeypatch):
    async def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM provider should not be called for crisis input")

    monkeypatch.setattr(api_index, "_call_openrouter_diagnosis", fail_if_called)
    monkeypatch.setattr(api_index, "_call_minimax_diagnosis", fail_if_called)
    monkeypatch.setattr(api_index, "_call_nvidia_diagnosis", fail_if_called)
    set_session_cookie(client, profile=complete_profile)

    payload = deep_diagnosis_payload()
    payload["entries"][0]["thought"] = "죽고 싶다는 생각이 들었다"
    response = client.post("/api/deep-diagnosis", json=payload)

    assert response.status_code == 200
    assert response.json()["mode"] == "crisis"


def test_deep_diagnosis_returns_primary_report_without_fallback(client, complete_profile, monkeypatch):
    async def primary(*args, **kwargs):
        return api_index.DeepDiagnosisPayload(
            mode="diagnosis",
            title="직무 스트레스 리포트",
            summary="KPI 보고와 임원 보고 장면이 반복됩니다. 책임을 빠르게 개인화하는 흐름이 보입니다. 다음 보고 전 확인 질문을 준비해볼 수 있습니다.",
            key_patterns=["성과 질문을 능력 평가로 해석합니다", "보고 후 침묵을 오래 붙잡습니다", "책임을 혼자 떠안습니다"],
            risk_signals=["업무 후에도 긴장이 남습니다", "질문 하나를 전체 평가로 확대합니다", "회복 행동이 부족합니다"],
            protective_factors=["기록을 남깁니다", "커뮤니티에 공유합니다", "재구성을 시도합니다"],
            action_plan=["다음 보고 전 기준 질문을 하나 준비합니다", "회의 후 사실과 해석을 나눠 적습니다", "통제 가능한 행동 하나만 고릅니다"],
            reflection_questions=["무엇을 사실로 확인했나요?", "어떤 해석이 붙었나요?", "무엇을 덜 떠안을 수 있나요?"],
        )

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("Fallback provider should not be called")

    monkeypatch.setattr(api_index, "_call_openrouter_diagnosis", primary)
    monkeypatch.setattr(api_index, "_call_minimax_diagnosis", fail_if_called)
    monkeypatch.setattr(api_index, "_call_nvidia_diagnosis", fail_if_called)
    set_session_cookie(client, profile=complete_profile)

    response = client.post("/api/deep-diagnosis", json=deep_diagnosis_payload())

    assert response.status_code == 200
    assert response.json()["mode"] == "diagnosis"
    assert response.json()["title"] == "직무 스트레스 리포트"
    assert len(response.json()["action_plan"]) == 3


def test_deep_diagnosis_uses_minimax_when_openrouter_unavailable(client, complete_profile, monkeypatch):
    async def unavailable(*args, **kwargs):
        return None

    async def direct_minimax(*args, **kwargs):
        return api_index.DeepDiagnosisPayload(
            mode="diagnosis",
            title="MiniMax 심층 리포트",
            summary="OpenRouter가 없어도 기존 MiniMax direct 키로 심층 진단을 생성합니다.",
            key_patterns=["성과 압박 기록이 반복됩니다"],
            risk_signals=["업무 후 긴장이 남습니다"],
            protective_factors=["기록을 남기고 있습니다"],
            action_plan=["다음 보고 전 확인 질문을 준비합니다"],
            reflection_questions=["무엇을 사실로 확인했나요?"],
        )

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("NVIDIA provider should not be called when MiniMax succeeds")

    monkeypatch.setattr(api_index, "_call_openrouter_diagnosis", unavailable)
    monkeypatch.setattr(api_index, "_call_minimax_diagnosis", direct_minimax)
    monkeypatch.setattr(api_index, "_call_nvidia_diagnosis", fail_if_called)
    set_session_cookie(client, profile=complete_profile)

    response = client.post("/api/deep-diagnosis", json=deep_diagnosis_payload())

    assert response.status_code == 200
    assert response.json()["mode"] == "diagnosis"
    assert response.json()["title"] == "MiniMax 심층 리포트"


def test_deep_diagnosis_returns_template_fallback_when_all_providers_fail(client, complete_profile, monkeypatch):
    async def unavailable(*args, **kwargs):
        return None

    monkeypatch.setattr(api_index, "_call_openrouter_diagnosis", unavailable)
    monkeypatch.setattr(api_index, "_call_minimax_diagnosis", unavailable)
    monkeypatch.setattr(api_index, "_call_nvidia_diagnosis", unavailable)
    set_session_cookie(client, profile=complete_profile)

    response = client.post("/api/deep-diagnosis", json=deep_diagnosis_payload())

    assert response.status_code == 200
    assert response.json()["mode"] == "fallback"
    assert "기본 리포트" in response.json()["message"]


@pytest.mark.parametrize("path", ["/api/leader", "/api/analyze"])
def test_analysis_endpoints_validate_payload(client, complete_profile, path):
    set_session_cookie(client, profile=complete_profile)
    response = client.post(path, json={"situation": "", "thought": ""})
    assert response.status_code == 422


def test_leader_endpoint_uses_fallback_provider(client, complete_profile, monkeypatch):
    async def primary_unavailable(*args, **kwargs):
        return None

    async def fallback(*args, **kwargs):
        return api_index.FeedbackPayload(
            mode="feedback",
            empathy="성과보고 질문이 날카롭게 느껴졌을 수 있어요.",
            distortions=["파국화"],
            reframe="질문 하나가 전체 평가를 뜻한다고 볼 수 있을까요?",
            question="다음 보고 전 확인 질문 하나를 준비해보세요.",
        )

    monkeypatch.setattr(api_index, "_call_openrouter", primary_unavailable)
    monkeypatch.setattr(api_index, "_call_minimax", primary_unavailable)
    monkeypatch.setattr(api_index, "_call_nvidia", fallback)
    set_session_cookie(client, profile=complete_profile)

    response = client.post(
        "/api/leader",
        json={
            "situation": "성과보고에서 질문을 받았다",
            "thought": "이번 보고가 망하면 끝이다",
            "reframe": "",
            "role_level": "신임 팀장",
        },
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "feedback"
    assert response.json()["distortions"] == ["파국화"]


def test_leader_endpoint_requires_session_and_short_circuits_crisis(client, complete_profile, monkeypatch):
    unauthenticated = client.post(
        "/api/leader",
        json={"situation": "팀 회의", "thought": "내가 부족하다"},
    )
    assert unauthenticated.status_code == 401

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM provider should not be called for crisis input")

    monkeypatch.setattr(api_index, "_call_openrouter", fail_if_called)
    monkeypatch.setattr(api_index, "_call_minimax", fail_if_called)
    monkeypatch.setattr(api_index, "_call_nvidia", fail_if_called)
    set_session_cookie(client, profile=complete_profile)

    crisis = client.post(
        "/api/leader",
        json={"situation": "성과보고", "thought": "목숨을 끊고 싶다"},
    )

    assert crisis.status_code == 200
    assert crisis.json()["mode"] == "crisis"

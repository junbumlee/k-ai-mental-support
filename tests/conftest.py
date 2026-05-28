from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import index as api_index


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    for key in (
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REDIRECT_URI",
        "MINIMAX_API_KEY",
        "MINIMAX_MODEL",
        "MINIMAX_BASE_URL",
        "NVIDIA_API_KEY",
        "NVIDIA_BASE_MODEL",
        "NVIDIA_BASE_URL",
        "VERCEL",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def client():
    with TestClient(api_index.app, follow_redirects=False) as test_client:
        yield test_client


def session_payload(profile=None):
    return {
        "user": {
            "sub": "user-1",
            "email": "leader@example.com",
            "name": "Test Leader",
            "picture": "",
        },
        "profile": profile if profile is not None else {},
    }


@pytest.fixture()
def complete_profile():
    return {
        "company_type": "스타트업",
        "industry": "소프트웨어",
        "age_group": "30대",
        "org_culture": "수평적",
        "leader_authority": "팀장",
        "job_role": "기획 7년차",
        "role_level": "신임 팀장",
        "team_size": "5명",
    }


def set_session_cookie(client, profile=None):
    client.cookies.set(
        api_index.SESSION_COOKIE,
        api_index._encode_signed(session_payload(profile)),
    )

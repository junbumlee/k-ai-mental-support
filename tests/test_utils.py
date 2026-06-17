import time

from api import index as api_index


def test_safe_next_accepts_only_local_user_pages():
    assert api_index._safe_next("/leaders") == "/leaders"
    assert api_index._safe_next("/onboarding?step=1") == "/onboarding?step=1"
    assert api_index._safe_next("https://example.com") == "/"
    assert api_index._safe_next("//example.com") == "/"
    assert api_index._safe_next("/auth/google/start") == "/"
    assert api_index._safe_next("/api/analyze") == "/"


def test_signed_session_roundtrip_and_rejection_cases():
    token = api_index._encode_signed({"sub": "user-1", "exp": int(time.time()) + 60})

    assert api_index._decode_signed(token)["sub"] == "user-1"
    assert api_index._decode_signed(token + "tampered") is None
    assert api_index._decode_signed("not-a-token") is None

    expired = api_index._encode_signed({"sub": "user-1", "exp": int(time.time()) - 1})
    assert api_index._decode_signed(expired) is None


def test_profile_helpers_trim_limit_and_detect_completion(complete_profile):
    dirty = {
        "job_role": "  " + ("기획" * 50) + "  ",
        "company_type": " 스타트업 ",
        "industry": "",
        "ignored": "value",
    }

    cleaned = api_index._clean_profile(dirty)

    assert cleaned["job_role"] == "기획" * 40
    assert cleaned["company_type"] == "스타트업"
    assert "industry" not in cleaned
    assert "ignored" not in cleaned
    assert api_index._profile_complete(complete_profile) is True
    assert api_index._profile_complete({"company_type": "스타트업"}) is False
    assert api_index._profile_complete(None) is False


def test_text_safety_helpers_extract_normalize_and_scrub_json():
    raw = """<think>internal</think>
```json
{"empathy":"회의，힘드셨겠어요。","distortions":["個人化"],"reframe":"다음 회의에서 확인해볼까요？","question":"팀원에게 물어보세요！"}
```"""

    payload = api_index._parse_feedback_json(raw)
    assert payload.mode == "feedback"
    assert payload.empathy == "회의,힘드셨겠어요."
    assert payload.question == "팀원에게 물어보세요!"
    assert api_index._has_forbidden(payload) is True

    scrubbed = api_index._scrub_payload(payload)
    assert api_index._has_forbidden(scrubbed) is False
    assert scrubbed.distortions == [""]


def test_deep_diagnosis_parse_scrub_and_prompt_builder(complete_profile):
    raw = """```json
{"title":"職務 스트레스 리포트","summary":"KPI 보고가 반복됩니다.","key_patterns":["責任을 혼자 집니다"],"risk_signals":["긴장이 남습니다"],"protective_factors":["기록합니다"],"action_plan":["다음 보고 전 질문합니다"],"reflection_questions":["무엇을 확인했나요?"]}
```"""

    payload = api_index._parse_diagnosis_json(raw)
    assert payload.mode == "diagnosis"
    assert api_index._has_forbidden_diagnosis(payload) is True

    scrubbed = api_index._scrub_diagnosis_payload(payload)
    assert api_index._has_forbidden_diagnosis(scrubbed) is False
    assert scrubbed.key_patterns == ["을 혼자 집니다"]

    request = api_index.DeepDiagnosisRequest(
        diagnosis_type="stress",
        profile=api_index.UserProfile(**complete_profile),
        entries=[
            api_index.DiagnosisEntry(
                createdAt="2026-06-17T10:00:00.000Z",
                category="성과 압박",
                situation="KPI 보고에서 질문을 받았다",
                thought="내가 부족하다",
                feedback="다음 회의에서 기준을 확인해보세요.",
            )
        ],
        community_posts=[
            api_index.DiagnosisCommunityPost(
                category="상사·보고",
                content="임원 보고 후 침묵이 마음에 남는다",
                comments=["비슷한 경험이 있어요"],
            )
        ],
    )
    user_block = api_index._build_deep_diagnosis_user_block(
        request, api_index.UserProfile(**complete_profile)
    )
    assert "[진단 종류]" in user_block
    assert "직무 스트레스 진단" in user_block
    assert "KPI 보고에서 질문을 받았다" in user_block
    assert "임원 보고 후 침묵" in user_block


def test_crisis_and_prompt_builders_include_safety_and_context():
    assert api_index._contains_crisis("오늘은 정말 죽고 싶다는 생각이 들었다") is True
    assert api_index._contains_crisis("오늘 회의가 길었다") is False

    diary_entry = api_index.DiaryEntry(
        situation="팀원이 보고를 누락했다",
        thought="내가 리더로 부족하다",
        reframe="다른 근거도 있다",
        job_role="기획 7년차",
        category="팀원 관리",
        category_count=3,
        company_type="스타트업",
    )
    user_block = api_index._build_user_block(diary_entry)
    assert "[상황 맥락]" in user_block
    assert "'팀원 관리' 카테고리를 3번째 선택했습니다" in user_block
    assert "- 직무/연차: 기획 7년차" in user_block
    assert "- 회사 구분: 스타트업" in user_block

    leader_entry = api_index.LeaderEntry(
        situation="성과보고에서 질문을 받았다",
        thought="내 결정은 틀렸다",
        role_level="신임 팀장",
        team_size="5명",
    )
    leader_block = api_index._build_leader_user_block(leader_entry)
    assert "[오늘의 상황]" in leader_block
    assert "- 직급: 신임 팀장" in leader_block
    assert "- 팀 규모: 5명" in leader_block

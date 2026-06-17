import asyncio

from api import index as api_index


class FakeResponse:
    def __init__(self, body=None, error=None):
        self.body = body or {}
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return self.body


def run(coro):
    return asyncio.run(coro)


def test_call_minimax_returns_none_without_api_key():
    assert run(api_index._call_minimax("system", "user")) is None


def test_call_minimax_diagnosis_returns_none_without_api_key():
    assert run(api_index._call_minimax_diagnosis("system", "user")) is None


def test_call_openrouter_returns_none_without_api_key():
    assert run(api_index._call_openrouter("system", "user")) is None


def test_call_openrouter_success_and_scrub(monkeypatch):
    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers, json):
            assert url == api_index.OPENROUTER_DEFAULT_URL
            assert headers["Authorization"] == "Bearer openrouter-key"
            assert headers["X-Title"] == "K AI Mental Support"
            assert json["model"] == api_index.OPENROUTER_DEFAULT_MODEL
            assert json["reasoning"] == {"effort": "minimal", "exclude": True}
            return FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"empathy":"주간회의가 무거웠겠어요","distortions":["個人化"],'
                                    '"reframe":"다른 근거를 볼 수 있을까요?","question":"다음 회의에서 질문하세요"}'
                                )
                            }
                        }
                    ]
                }
            )

    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setattr(api_index.httpx, "AsyncClient", FakeAsyncClient)

    result = run(api_index._call_openrouter("system", "user"))

    assert result.mode == "feedback"
    assert result.distortions == [""]


def test_call_openrouter_returns_none_for_empty_choices_and_errors(monkeypatch):
    class EmptyChoicesClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers, json):
            return FakeResponse({"choices": []})

    class FailingClient(EmptyChoicesClient):
        async def post(self, url, headers, json):
            raise RuntimeError("network down")

    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setattr(api_index.httpx, "AsyncClient", EmptyChoicesClient)
    assert run(api_index._call_openrouter("system", "user")) is None

    monkeypatch.setattr(api_index.httpx, "AsyncClient", FailingClient)
    assert run(api_index._call_openrouter("system", "user")) is None


def test_call_minimax_model_success_with_list_content_and_scrubbing(monkeypatch):
    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers, json):
            assert url == "https://api.minimaxi.chat/v1/text/chatcompletion_v2"
            assert headers["Authorization"] == "Bearer minimax-key"
            assert json["model"] == "test-model"
            return FakeResponse(
                {
                    "base_resp": {"status_code": 0},
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {
                                        "text": '{"empathy":"회의가 무거웠겠어요","distortions":["個人化"],'
                                    },
                                    {
                                        "text": '"reframe":"다른 근거를 볼 수 있을까요?","question":"다음 회의에서 질문하세요"}'
                                    },
                                ]
                            }
                        }
                    ],
                }
            )

    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.setattr(api_index.httpx, "AsyncClient", FakeAsyncClient)

    result = run(api_index._call_minimax_model("system", "user", "test-model", 3))

    assert result.mode == "feedback"
    assert result.distortions == [""]
    assert api_index._has_forbidden(result) is False


def test_call_minimax_model_returns_none_for_bad_provider_payloads(monkeypatch):
    class BadBaseRespClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers, json):
            return FakeResponse({"base_resp": {"status_code": 2061}})

    class EmptyChoicesClient(BadBaseRespClient):
        async def post(self, url, headers, json):
            return FakeResponse({"base_resp": {"status_code": 0}, "choices": []})

    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.setattr(api_index.httpx, "AsyncClient", BadBaseRespClient)
    assert run(api_index._call_minimax_model("system", "user", "model", 3)) is None

    monkeypatch.setattr(api_index.httpx, "AsyncClient", EmptyChoicesClient)
    assert run(api_index._call_minimax_model("system", "user", "model", 3)) is None


def test_call_minimax_model_handles_http_or_parse_errors(monkeypatch):
    class FailingAsyncClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers, json):
            return FakeResponse(error=RuntimeError("provider failed"))

    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.setattr(api_index.httpx, "AsyncClient", FailingAsyncClient)

    assert run(api_index._call_minimax_model("system", "user", "model", 3)) is None


def test_call_minimax_diagnosis_success_with_list_content(monkeypatch):
    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers, json):
            assert url == "https://api.minimaxi.chat/v1/text/chatcompletion_v2"
            assert headers["Authorization"] == "Bearer minimax-key"
            assert json["model"] == api_index.MINIMAX_DEFAULT_MODEL
            assert json["max_tokens"] == api_index.DEEP_DIAGNOSIS_MAX_TOKENS
            return FakeResponse(
                {
                    "base_resp": {"status_code": 0},
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {
                                        "text": '{"title":"스트레스 深층 리포트","summary":"성과 압박과 보고 후 긴장이 반복됩니다.",'
                                    },
                                    {
                                        "text": '"key_patterns":["보고 질문을 전체 평가로 해석합니다"],'
                                        '"risk_signals":["퇴근 후에도 긴장이 남습니다"],'
                                        '"protective_factors":["기록을 남기고 있습니다"],'
                                        '"action_plan":["다음 보고 전 확인 질문을 준비합니다"],'
                                        '"reflection_questions":["무엇을 사실로 확인했나요?"]}'
                                    },
                                ]
                            }
                        }
                    ],
                }
            )

    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.setattr(api_index.httpx, "AsyncClient", FakeAsyncClient)

    result = run(api_index._call_minimax_diagnosis("system", "user"))

    assert result.mode == "diagnosis"
    assert result.title == "스트레스 층 리포트"
    assert result.summary == "성과 압박과 보고 후 긴장이 반복됩니다."


def test_call_minimax_diagnosis_returns_none_for_bad_payloads(monkeypatch):
    class BadBaseRespClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers, json):
            return FakeResponse({"base_resp": {"status_code": 2061}})

    class EmptyChoicesClient(BadBaseRespClient):
        async def post(self, url, headers, json):
            return FakeResponse({"base_resp": {"status_code": 0}, "choices": []})

    class InvalidJsonClient(BadBaseRespClient):
        async def post(self, url, headers, json):
            return FakeResponse(
                {
                    "base_resp": {"status_code": 0},
                    "choices": [{"message": {"content": "not json"}}],
                }
            )

    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.setattr(api_index.httpx, "AsyncClient", BadBaseRespClient)
    assert run(api_index._call_minimax_diagnosis("system", "user")) is None

    monkeypatch.setattr(api_index.httpx, "AsyncClient", EmptyChoicesClient)
    assert run(api_index._call_minimax_diagnosis("system", "user")) is None

    monkeypatch.setattr(api_index.httpx, "AsyncClient", InvalidJsonClient)
    assert run(api_index._call_minimax_diagnosis("system", "user")) is None


def test_call_nvidia_returns_none_without_api_key():
    assert run(api_index._call_nvidia("system", "user")) is None


def test_call_nvidia_success_and_scrub(monkeypatch):
    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers, json):
            assert url == api_index.NVIDIA_DEFAULT_URL
            assert headers["Authorization"] == "Bearer nvidia-key"
            assert json["model"] == api_index.NVIDIA_DEFAULT_MODEL
            return FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"empathy":"보고 질문이 무거웠겠어요","distortions":["破局化"],'
                                    '"reframe":"질문 하나가 전체 평가일까요?","question":"다음 보고에서 기준을 확인하세요"}'
                                )
                            }
                        }
                    ]
                }
            )

    monkeypatch.setenv("NVIDIA_API_KEY", "nvidia-key")
    monkeypatch.setattr(api_index.httpx, "AsyncClient", FakeAsyncClient)

    result = run(api_index._call_nvidia("system", "user"))

    assert result.mode == "feedback"
    assert result.distortions == [""]


def test_call_nvidia_returns_none_for_empty_choices_and_errors(monkeypatch):
    class EmptyChoicesClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers, json):
            return FakeResponse({"choices": []})

    class FailingClient(EmptyChoicesClient):
        async def post(self, url, headers, json):
            raise RuntimeError("network down")

    monkeypatch.setenv("NVIDIA_API_KEY", "nvidia-key")
    monkeypatch.setattr(api_index.httpx, "AsyncClient", EmptyChoicesClient)
    assert run(api_index._call_nvidia("system", "user")) is None

    monkeypatch.setattr(api_index.httpx, "AsyncClient", FailingClient)
    assert run(api_index._call_nvidia("system", "user")) is None

import json

import httpx2
import pytest

from app.errors import AppError
from app.llm import DeepSeekModel
from pydantic import SecretStr
from tests.helpers import config


def completion(message=None, finish_reason="stop"):
    return {"id": "test", "object": "chat.completion", "created": 1, "model": "configured-model",
            "choices": [{"index": 0, "message": message or {"role": "assistant", "content": "{}"},
                         "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}}


async def test_official_sdk_wire_tool_calls_and_json_mode():
    seen = []
    def response(request):
        seen.append((request, json.loads(request.content)))
        message = {"role": "assistant", "tool_calls": [{"id": "sdk-call", "type": "function",
            "function": {"name": "get_issue", "arguments": '{"repository":"YYB367/learning-mcp-server","issue_number":1}'}}]}
        return httpx2.Response(200, json=completion(message, "tool_calls") if len(seen) == 1 else completion())
    settings = config(deepseek_model="configured-model", deepseek_base_url="https://api.deepseek.test/v1")
    settings.deepseek_api_key = SecretStr("test-canary-key")
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(response), trust_env=False)
    model = DeepSeekModel(settings, http_client=http)
    try:
        msg, usage = await model.complete([{"role": "user", "content": "read"}], [{"type": "function", "function": {
            "name": "get_issue", "parameters": {"type": "object"}}}])
        assert msg["tool_calls"][0]["id"] == "sdk-call" and usage["total_tokens"] == 30
        await model.complete([{"role": "user", "content": "return JSON"}], None)
    finally:
        await model.close()
    first_request, first_body = seen[0]
    assert str(first_request.url) == "https://api.deepseek.test/v1/chat/completions"
    assert first_request.headers["authorization"] == "Bearer test-canary-key"
    assert first_body["model"] == "configured-model" and first_body["thinking"]["type"] == "disabled"
    assert first_body["tool_choice"] == "auto"
    assert "test-canary-key" not in json.dumps(first_body)
    assert seen[1][1]["response_format"] == {"type": "json_object"}
    assert "tools" not in seen[1][1]


@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_no_automatic_retries_or_raw_errors(status):
    seen = []
    def response(request):
        seen.append(request)
        return httpx2.Response(status, json={"error": {"message": "upstream-secret-canary", "type": "error"}})
    settings = config()
    settings.deepseek_api_key = SecretStr("test-key")
    model = DeepSeekModel(settings, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(response)))
    try:
        with pytest.raises(AppError) as caught:
            await model.complete([{"role": "user", "content": "JSON"}], None)
        assert caught.value.code == "model_api_error"
        assert "upstream-secret-canary" not in caught.value.message and len(seen) == 1
    finally:
        await model.close()


async def test_model_timeout():
    def response(request):
        raise httpx2.ReadTimeout("upstream-secret-canary")
    settings = config()
    settings.deepseek_api_key = SecretStr("test-key")
    model = DeepSeekModel(settings, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(response)))
    try:
        with pytest.raises(AppError, match="model_timeout"):
            await model.complete([{"role": "user", "content": "JSON"}], None)
    finally:
        await model.close()


async def test_model_truncated_result():
    settings = config()
    settings.deepseek_api_key = SecretStr("test-key")
    model = DeepSeekModel(settings, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(
        lambda request: httpx2.Response(200, json=completion(finish_reason="length")))))
    try:
        with pytest.raises(AppError, match="model_incomplete"):
            await model.complete([{"role": "user", "content": "JSON"}], None)
    finally:
        await model.close()

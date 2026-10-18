import asyncio

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from app.config import MODEL_OUTPUT_TOKENS, Settings
from app.errors import AppError


class DeepSeekModel:
    def __init__(self, settings: Settings, http_client=None):
        if not settings.deepseek_api_key.get_secret_value():
            raise AppError("model_not_configured", "请在新项目 .env 中填写 DEEPSEEK_API_KEY。")
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.deepseek_api_key.get_secret_value(),
            base_url=settings.deepseek_base_url,
            max_retries=0, timeout=settings.model_timeout_seconds,
            http_client=http_client,
        )

    async def complete(self, messages: list[dict], tools: list[dict] | None):
        kwargs = {
            "model": self.settings.deepseek_model, "messages": messages,
            "temperature": 0.2, "max_tokens": MODEL_OUTPUT_TOKENS,
            # V1 supports non-thinking tool calls. Reasoning history is not silently dropped.
            "extra_body": {"thinking": {"type": "disabled"}},
        }
        if tools is not None:
            kwargs.update(tools=tools, tool_choice="auto")
        else:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            async with asyncio.timeout(self.settings.model_timeout_seconds):
                response = await self.client.chat.completions.create(**kwargs)
            if not response.choices:
                raise AppError("model_invalid_response", "模型未返回候选结果。")
            choice = response.choices[0]
            if choice.finish_reason not in ("stop", "tool_calls"):
                raise AppError("model_incomplete", "模型输出未完成，可能被长度或内容限制截断。")
            usage = response.usage.model_dump() if response.usage else {}
            return choice.message.model_dump(exclude_none=True), usage
        except (TimeoutError, APITimeoutError):
            raise AppError("model_timeout", "模型请求超时。") from None
        except APIStatusError:
            raise AppError("model_api_error", "模型接口拒绝请求或暂时不可用，请核对密钥、模型名称和接口配置。") from None
        except APIConnectionError:
            raise AppError("model_connection_error", "无法连接模型接口。") from None

    async def close(self) -> None:
        await self.client.close()

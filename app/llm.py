"""DeepSeek LLM 封装（OpenAI 兼容接口）。"""
import json
import re

from openai import OpenAI

from app.config import settings


class MissingAPIKeyError(RuntimeError):
    """API key 未配置时抛出，用于给出明确的用户提示。"""


_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.api_key_configured:
            raise MissingAPIKeyError(
                "尚未配置 DEEPSEEK_API_KEY：请编辑 E:\\software\\agentic-rag\\.env，"
                "在 DEEPSEEK_API_KEY= 后填入你的 DeepSeek API Key，然后重启服务。"
            )
        _client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout=60,
        )
    return _client


def chat(messages: list[dict], json_mode: bool = False, temperature: float | None = None) -> str:
    """调用对话模型，返回文本。json_mode=True 时强制输出 JSON。"""
    kwargs: dict = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = get_client().chat.completions.create(
        model=settings.deepseek_model,
        messages=messages,
        temperature=settings.llm_temperature if temperature is None else temperature,
        **kwargs,
    )
    return (resp.choices[0].message.content or "").strip()


def parse_json(text: str) -> dict:
    """容错解析 LLM 输出的 JSON（剥掉 markdown 代码块围栏等）。"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 剥 ```json ... ``` 围栏
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 截取首尾大括号
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"LLM 输出无法解析为 JSON: {text[:200]}")


def chat_json(messages: list[dict], temperature: float | None = None) -> dict:
    """要求模型输出 JSON 并解析为 dict；失败时重试一次。"""
    try:
        return parse_json(chat(messages, json_mode=True, temperature=temperature))
    except (ValueError, json.JSONDecodeError):
        retry = messages + [
            {"role": "user", "content": "上面的输出不符合 JSON 格式要求。请只输出一个合法的 JSON 对象，不要任何多余文字。"}
        ]
        return parse_json(chat(retry, json_mode=True, temperature=temperature))

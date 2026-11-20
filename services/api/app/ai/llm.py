"""LLM access layer (spec §9).

One provider speaks the OpenAI-compatible Chat Completions API, which covers:
  * local Qwen via Ollama  (LLM_BASE_URL=http://127.0.0.1:11434/v1, LLM_MODEL=qwen2.5:7b-instruct)
  * local vLLM / LM Studio (same API)
  * DeepSeek for development (LLM_BASE_URL=https://api.deepseek.com, LLM_MODEL=deepseek-chat)

Rules enforced here, not in prompts:
  * if the model is not local (`llm_is_local=false`) every text is PII-masked before it leaves
    the server and unmasked afterwards; external models are refused outside dev (config validator);
  * responses must be JSON; one repair retry, then a clean error;
  * the deterministic rule engine stays authoritative — callers downgrade AI verdicts.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import httpx

from app.ai.pii import mask, unmask
from app.core.config import LLMProvider as ProviderKind
from app.core.config import get_settings
from app.core.errors import IntegrationUnavailable

log = logging.getLogger(__name__)

_transport: httpx.AsyncBaseTransport | None = None  # test hook


def configure_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport
    get_llm.cache_clear()


@dataclass(frozen=True, slots=True)
class ChatResult:
    text: str
    model: str
    latency_ms: int
    usage: dict[str, Any]
    finish_reason: str | None = None  # "length" => output was cut by max_tokens


class LLM(Protocol):
    model: str
    is_local: bool

    async def chat(
        self, messages: list[dict[str, str]], *, json_mode: bool = False, max_tokens: int | None = None
    ) -> ChatResult: ...


class DisabledLLM:
    model = "none"
    is_local = True

    async def chat(
        self, messages: list[dict[str, str]], *, json_mode: bool = False, max_tokens: int | None = None
    ) -> ChatResult:
        raise IntegrationUnavailable("AI ulanmagan (LLM_PROVIDER=none)", code="ai_disabled")


class OpenAICompatibleLLM:
    def __init__(self) -> None:
        s = get_settings()
        self.base_url = s.llm_base_url.rstrip("/")
        self.model = s.llm_model
        self.is_local = s.llm_is_local
        self._headers = {"Content-Type": "application/json"}
        if s.llm_api_key:
            self._headers["Authorization"] = f"Bearer {s.llm_api_key}"
        self._timeout = s.llm_timeout_seconds
        self._max_tokens = s.llm_max_tokens
        self._temperature = s.llm_temperature

    async def chat(
        self, messages: list[dict[str, str]], *, json_mode: bool = False, max_tokens: int | None = None
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": max_tokens or self._max_tokens,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=_transport) as client:
                r = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=self._headers)
        except httpx.HTTPError as e:
            raise IntegrationUnavailable(
                f"AI xizmatiga ulanib bo'lmadi: {type(e).__name__}", code="ai_unavailable"
            ) from e
        if r.status_code in (401, 403):
            raise IntegrationUnavailable("AI kaliti noto'g'ri yoki ruxsat yo'q", code="ai_auth_failed")
        if r.status_code == 402:
            raise IntegrationUnavailable("AI hisobida mablag' tugagan", code="ai_quota")
        if r.status_code == 429:
            raise IntegrationUnavailable("AI so'rovlar limiti oshdi, keyinroq urining", code="ai_rate_limited")
        if r.is_error:
            raise IntegrationUnavailable(f"AI xizmati xatosi {r.status_code}", code="ai_unavailable")
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        text = choice.get("message", {}).get("content") or ""
        return ChatResult(
            finish_reason=choice.get("finish_reason"),
            text=text,
            model=data.get("model", self.model),
            latency_ms=int((time.perf_counter() - started) * 1000),
            usage=data.get("usage") or {},
        )


@lru_cache
def get_llm() -> LLM:
    s = get_settings()
    if s.llm_provider == ProviderKind.OPENAI_COMPATIBLE:
        return OpenAICompatibleLLM()
    return DisabledLLM()


def is_enabled() -> bool:
    return get_settings().llm_provider != ProviderKind.NONE


_SHORTER = (
    "\n\nMUHIM: javob qisqa bo'lsin — har bir matn maydoni 1 gap, "
    "issues ko'pi bilan 8 ta, obligations ko'pi bilan 8 ta."
)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _parse_json(text: str) -> dict[str, Any]:
    t = _FENCE.sub("", text.strip())
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in model output")
    value = json.loads(t[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("model output is not a JSON object")
    return value


@dataclass(frozen=True, slots=True)
class JsonAnswer:
    data: dict[str, Any]
    model: str
    latency_ms: int
    masked: bool


async def ask_json(system: str, user: str, *, max_tokens: int | None = None) -> JsonAnswer:
    """Ask for a JSON object. PII is masked for non-local models and restored in every string."""
    llm = get_llm()
    masked = not llm.is_local
    mapping: dict[str, str] = {}
    if masked:
        user, mapping = mask(user)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    res = await llm.chat(messages, json_mode=True, max_tokens=max_tokens)
    try:
        data = _parse_json(res.text)
    except (ValueError, json.JSONDecodeError):
        log.warning("llm_bad_json", extra={"model": res.model, "finish_reason": res.finish_reason})
        if res.finish_reason == "length":
            # Cut by the token limit: ask again from scratch for a shorter answer (appending the
            # truncated text would just make the model repeat it and be cut again).
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user + _SHORTER},
            ]
            retry_tokens = int((max_tokens or get_settings().llm_max_tokens) * 1.5)
        else:
            messages += [
                {"role": "assistant", "content": res.text[:4000]},
                {"role": "user", "content": "Javobingiz yaroqli JSON emas. Faqat bitta JSON obyekt qaytaring."},
            ]
            retry_tokens = max_tokens
        res = await llm.chat(messages, json_mode=True, max_tokens=retry_tokens)
        try:
            data = _parse_json(res.text)
        except (ValueError, json.JSONDecodeError) as e:
            raise IntegrationUnavailable("AI yaroqli javob qaytarmadi", code="ai_bad_output") from e
    if mapping:
        data = json.loads(unmask(json.dumps(data, ensure_ascii=False), mapping))
    return JsonAnswer(data=data, model=res.model, latency_ms=res.latency_ms, masked=masked)

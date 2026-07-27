"""
LLM provider abstraction.

The point of this file is to make the choice of language model a configuration
detail rather than an architectural commitment. v1 hard-wired Gemini into five
route handlers; changing model meant editing all five.

Equally important is what this abstraction is FOR. In CEREBRO v2 the language
model has exactly two jobs:

  1. `explain()`  — turn already-computed structured findings into analyst prose
  2. `extract_claims()` — segment an article into checkable factual assertions

It does NOT classify, score, or decide. Those are RoBERTa's and sklearn's jobs,
because those produce numbers you can put a confusion matrix under. If you ever
find yourself adding a `classify()` method here, that's the architecture
regressing to v1.

Default provider is Ollama: local, private, free, and good enough for prose.
No customer's inbox should leave their infrastructure to get a summary written.
"""

from __future__ import annotations

import json
import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Raised when a provider fails in a way the caller should handle."""


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    # Token counts where the provider reports them — needed for cost tracking
    # and for the latency/throughput numbers in your evaluation chapter.
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: float | None = None


class LLMProvider(ABC):
    """Minimal surface. Add methods only when a real caller needs them."""

    name: str = "base"

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        ...

    async def health(self) -> bool:
        try:
            r = await self.complete("Reply with OK.", max_tokens=5)
            return bool(r.text)
        except Exception as exc:  # noqa: BLE001 - health check must not raise
            log.warning("%s health check failed: %s", self.name, exc)
            return False


# ---------------------------------------------------------------------------
# Ollama — the default
# ---------------------------------------------------------------------------

class OllamaProvider(LLMProvider):
    """
    Local inference via Ollama's HTTP API.

    Model sizing guidance for a laptop:
      qwen2.5:7b-instruct   ~5 GB RAM, good instruction following  (recommended)
      llama3.1:8b-instruct  ~5 GB RAM, comparable
      qwen2.5:3b-instruct   ~2.5 GB RAM, noticeably weaker but usable
      phi3.5:3.8b-mini      ~2.5 GB RAM, strong for its size

    Expect 10-30 tok/s on CPU. That is fine for explanation generation, which
    happens once per detection and is not on the interactive hot path.
    """

    name = "ollama"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 180.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
        self.timeout = timeout

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if system:
            payload["system"] = system
        if json_schema:
            # Ollama supports structured outputs by passing a JSON schema.
            payload["format"] = json_schema

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}/api/generate", json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama request failed: {exc}") from exc

        return LLMResponse(
            text=data.get("response", ""),
            model=self.model,
            provider=self.name,
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
            latency_ms=(data.get("total_duration") or 0) / 1e6 or None,
        )


# ---------------------------------------------------------------------------
# Gemini — kept as a fallback, not a dependency
# ---------------------------------------------------------------------------

class GeminiProvider(LLMProvider):
    """
    Google Gemini via the REST API.

    Retained deliberately: it is fast and cheap, and useful as a quality ceiling
    to benchmark the local model against in your evaluation. But note that using
    it means sending content to a third party — unacceptable for the email
    module in any deployment handling real inboxes.
    """

    name = "gemini"
    _ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 timeout: float = 60.0) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.timeout = timeout
        if not self.api_key:
            log.warning("GeminiProvider constructed without an API key")

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        if not self.api_key:
            raise LLMError("GEMINI_API_KEY is not set")

        gen_config: dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        if json_schema:
            gen_config["responseMimeType"] = "application/json"
            gen_config["responseSchema"] = json_schema

        body: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": gen_config,
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        url = f"{self._ENDPOINT}/{self.model}:generateContent"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    url, json=body, headers={"x-goog-api-key": self.api_key}
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"Gemini request failed: {exc}") from exc

        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"Unexpected Gemini response shape: {data}") from exc

        usage = data.get("usageMetadata", {})
        return LLMResponse(
            text=text,
            model=self.model,
            provider=self.name,
            prompt_tokens=usage.get("promptTokenCount"),
            completion_tokens=usage.get("candidatesTokenCount"),
        )


# ---------------------------------------------------------------------------
# OpenAI-compatible — covers OpenAI, Groq, together.ai, vLLM, LM Studio
# ---------------------------------------------------------------------------

class OpenAICompatProvider(LLMProvider):
    """Any server speaking the OpenAI chat-completions API."""

    name = "openai_compat"

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None, timeout: float = 60.0) -> None:
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL",
                                               "https://api.openai.com/v1")).rstrip("/")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.timeout = timeout

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": json_schema, "strict": True},
            }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=body,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"OpenAI-compatible request failed: {exc}") from exc

        usage = data.get("usage", {})
        return LLMResponse(
            text=data["choices"][0]["message"]["content"],
            model=self.model,
            provider=self.name,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )


# ---------------------------------------------------------------------------
# Template fallback — the system must work with no LLM at all
# ---------------------------------------------------------------------------

class TemplateProvider(LLMProvider):
    """
    Deterministic, dependency-free fallback.

    This exists so that "no model available" degrades the *prose* and nothing
    else. Detection, scoring, and evidence retrieval are unaffected, because
    none of them depend on a language model. That property is worth protecting —
    it is the difference between an LLM-powered product and an LLM-dependent one.
    """

    name = "template"

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        findings = re.findall(r"\[(CRITICAL|HIGH|MEDIUM|LOW|INFO)\]\s+(\w+):\s*(.+)", prompt)
        if not findings:
            text = "No deterministic risk indicators were identified for this item."
        else:
            severe = [f for f in findings if f[0] in ("CRITICAL", "HIGH")]
            head = severe[0] if severe else findings[0]
            text = (
                f"{len(findings)} indicator(s) were identified, "
                f"{len(severe)} of them high severity. "
                f"The strongest signal is {head[1]}: {head[2]} "
                f"Recommend analyst review before any action is taken."
            )
        return LLMResponse(text=text, model="template-v1", provider=self.name)


# ---------------------------------------------------------------------------
# Factory + high-level helpers
# ---------------------------------------------------------------------------

class GroqProvider(OpenAICompatProvider):
    """
    Groq's free tier — the best no-cost hosted option as of July 2026.

    Free limits (no credit card): 30 requests/min, 14,400 requests/day,
    ~6,000 tokens/min depending on model. Serves Llama 3.3 70B at several
    hundred tokens/sec, which is faster than most paid APIs.

    For explanation generation at FYP demo scale — a few hundred calls a day —
    14,400 RPD is not a constraint you will notice.
    """

    name = "groq"

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 timeout: float = 60.0) -> None:
        super().__init__(
            base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
            api_key=api_key or os.getenv("GROQ_API_KEY", ""),
            model=model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            timeout=timeout,
        )


class CerebrasProvider(OpenAICompatProvider):
    """
    Cerebras free tier — comparable limits to Groq (30 RPM / 14,400 RPD,
    60,000 TPM), also OpenAI-compatible. Useful as a second free fallback so a
    demo does not die if one provider rate-limits you mid-presentation.
    """

    name = "cerebras"

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 timeout: float = 60.0) -> None:
        super().__init__(
            base_url=os.getenv("CEREBRAS_BASE_URL", "https://api.cerebras.ai/v1"),
            api_key=api_key or os.getenv("CEREBRAS_API_KEY", ""),
            model=model or os.getenv("CEREBRAS_MODEL", "llama-3.3-70b"),
            timeout=timeout,
        )


_PROVIDERS: dict[str, type[LLMProvider]] = {
    "ollama": OllamaProvider,
    "groq": GroqProvider,
    "cerebras": CerebrasProvider,
    "gemini": GeminiProvider,
    "openai": OpenAICompatProvider,
    "openai_compat": OpenAICompatProvider,
    "template": TemplateProvider,
}


def get_provider(name: str | None = None, **kwargs: Any) -> LLMProvider:
    """Resolve a provider by name, defaulting to LLM_PROVIDER env or Ollama."""
    key = (name or os.getenv("LLM_PROVIDER", "ollama")).lower()
    cls = _PROVIDERS.get(key)
    if cls is None:
        raise LLMError(
            f"Unknown LLM provider '{key}'. Available: {sorted(_PROVIDERS)}"
        )
    return cls(**kwargs)


class ResilientProvider(LLMProvider):
    """
    Try providers in order; fall through on failure.

    Recommended chain: Ollama → template. That gives you local-first with a
    guaranteed non-failing floor and no external dependency. Add Gemini in the
    middle only if you have accepted the privacy tradeoff for that data class.
    """

    name = "resilient"

    def __init__(self, providers: list[LLMProvider]) -> None:
        if not providers:
            raise ValueError("ResilientProvider needs at least one provider")
        self.providers = providers

    async def complete(self, prompt: str, **kwargs: Any) -> LLMResponse:
        last: Exception | None = None
        for provider in self.providers:
            try:
                return await provider.complete(prompt, **kwargs)
            except Exception as exc:  # noqa: BLE001 - fall through by design
                log.warning("provider %s failed, falling through: %s", provider.name, exc)
                last = exc
        raise LLMError(f"All providers failed. Last error: {last}")


def default_chain() -> ResilientProvider:
    """
    Build the fallback chain from LLM_PROVIDER and LLM_FALLBACKS.

    Recommended for a live demo:
        LLM_PROVIDER=groq
        LLM_FALLBACKS=cerebras,ollama

    Groq is fast enough that explanations appear instantly on stage; Cerebras
    covers a rate-limit hit; Ollama covers the venue wifi failing. The template
    provider is always appended last, so the chain can never hard-fail in front
    of a panel.
    """
    chain: list[LLMProvider] = []
    names = [os.getenv("LLM_PROVIDER", "ollama")]
    names += [n.strip() for n in os.getenv("LLM_FALLBACKS", "").split(",") if n.strip()]

    for name in names:
        try:
            chain.append(get_provider(name))
        except LLMError:
            log.warning("provider %r unavailable, skipping", name)

    chain.append(TemplateProvider())
    return ResilientProvider(chain)


# --- the two legitimate LLM tasks ------------------------------------------

CLAIM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "check_worthy": {"type": "number"},
                },
                "required": ["text", "check_worthy"],
            },
        }
    },
    "required": ["claims"],
}

_CLAIM_SYSTEM = (
    "You segment text into atomic, independently verifiable factual claims. "
    "A claim must be checkable against external evidence. Opinions, questions, "
    "and rhetorical statements are not claims. Do not judge whether a claim is "
    "true — that is decided downstream by retrieval and an entailment model. "
    "Score check_worthy 0-1 by how consequential and specific the claim is."
)


async def extract_claims(
    provider: LLMProvider, text: str, max_claims: int = 12
) -> list[dict[str, Any]]:
    """
    Segment an article into checkable claims.

    This is a legitimate LLM job: it is a linguistic transformation, not a
    judgement. The truth decision happens later, in retrieval + NLI.
    """
    prompt = (
        f"Extract up to {max_claims} atomic factual claims from the text below.\n\n"
        f"---\n{text[:8000]}\n---"
    )
    resp = await provider.complete(
        prompt, system=_CLAIM_SYSTEM, max_tokens=1024,
        temperature=0.0, json_schema=CLAIM_SCHEMA,
    )
    try:
        parsed = json.loads(resp.text)
        claims = parsed.get("claims", [])
    except (json.JSONDecodeError, AttributeError):
        # Fallback: naive sentence split. Degraded, but the pipeline continues.
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 40]
        claims = [{"text": s, "check_worthy": 0.5} for s in sentences[:max_claims]]
    return claims[:max_claims]


async def explain(provider: LLMProvider, prompt: str) -> str:
    """Generate analyst-facing prose from already-computed findings."""
    resp = await provider.complete(
        prompt,
        system=(
            "You are a security analyst writing concise incident notes. "
            "State only what the provided findings support. Never invent "
            "indicators, scores, or attribution."
        ),
        max_tokens=300,
        temperature=0.3,
    )
    return resp.text.strip()

"""Provider-agnostic LLM client with JSON-contract enforcement.

Providers
---------
* ``anthropic`` – used when ANTHROPIC_API_KEY is set (Messages API over HTTPS)
* ``openai``    – used when OPENAI_API_KEY is set (Chat Completions, JSON mode)
* ``offline``   – deterministic heuristic engine (no network). Every agent ships
  a heuristic generator that implements the same output contract, so the whole
  pipeline (RAG, Critic loop, guardrails, evals) is reproducible without keys.
  The same heuristic is also the *fallback* when an LLM keeps violating the
  contract (failure mode "malformed JSON -> retry -> fallback + flag").

Force a provider with BRD2ENG_LLM_PROVIDER=anthropic|openai|offline.

Backends (how an online provider is called)
-------------------------------------------
* ``langchain`` – LangChain chat models (``ChatAnthropic`` / ``ChatOpenAI``); default
  when the provider's ``langchain-*`` package is installed
* ``http``      – plain HTTPS with urllib (no extra dependencies)

Force one with BRD2ENG_LLM_BACKEND=langchain|http.

Response cache
--------------
BRD2ENG_LLM_CACHE=1 stores every contract-valid LLM response under .cache/llm/
(keyed by a hash of provider, model, max_tokens and the full prompt), so re-runs
and evals of the same input cost no tokens. Opt-in, because cached responses are
derived from BRD text; the folder is git-ignored.

Data boundary
-------------
An online provider receives (redacted) BRD text, so it is opt-in: set
BRD2ENG_ALLOW_EXTERNAL_CONTENT=1 (CLI: --allow-external) only after confirming
the endpoint is approved for the data. Otherwise construction fails with
ExternalContentNotAllowed and nothing is sent.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional, Type

from pydantic import BaseModel, ValidationError

from .config import AGENT_MODEL_TIER, MODEL_ROUTING, PRICE_PER_MTOK, ROOT

CACHE_DIR = ROOT / ".cache" / "llm"


@dataclass
class LLMResult:
    data: Optional[dict]
    tokens_in: int
    tokens_out: int
    model: str
    raw_text: str = ""
    cached: bool = False


def _detect_provider() -> str:
    forced = os.getenv("BRD2ENG_LLM_PROVIDER")
    if forced:
        return forced
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "offline"


LANGCHAIN_PACKAGES = {"anthropic": "langchain_anthropic", "openai": "langchain_openai"}
API_KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
ALLOW_EXTERNAL_ENV = "BRD2ENG_ALLOW_EXTERNAL_CONTENT"


class ExternalContentNotAllowed(RuntimeError):
    """An online provider was selected without the explicit data-boundary opt-in."""


TRACING_ENVS = ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2")


def gate_tracing() -> str:
    """LangSmith tracing (LANGSMITH_TRACING=true + LANGSMITH_API_KEY) records prompts, so it is held to the
    same data boundary: without the opt-in it is switched off for this process. Returns on | off | blocked."""
    if not any(os.getenv(k, "").lower() == "true" for k in TRACING_ENVS):
        return "off"
    if os.getenv(ALLOW_EXTERNAL_ENV) == "1":
        return "on"
    for k in TRACING_ENVS:
        os.environ[k] = "false"
    return "blocked"


def check_provider_ready(provider: str) -> None:
    """Fail fast (before any BRD is read) when an online provider is not configured or not approved."""
    if provider == "offline":
        return
    if provider not in API_KEY_ENV:
        raise ValueError(f"unsupported provider {provider!r} (use anthropic, openai or offline)")
    if not os.getenv(API_KEY_ENV[provider]):
        raise ExternalContentNotAllowed(f"{API_KEY_ENV[provider]} is not set in this environment.")
    if os.getenv(ALLOW_EXTERNAL_ENV) != "1":
        raise ExternalContentNotAllowed(
            f"Provider '{provider}' would receive BRD text. Use synthetic or approved data, then set "
            f"{ALLOW_EXTERNAL_ENV}=1 (or pass --allow-external). To stay offline set BRD2ENG_LLM_PROVIDER=offline.")


def _detect_backend(provider: str) -> str:
    forced = os.getenv("BRD2ENG_LLM_BACKEND")
    if forced:
        return forced
    pkg = LANGCHAIN_PACKAGES.get(provider)
    return "langchain" if pkg and importlib.util.find_spec(pkg) else "http"


def _transport_errors() -> tuple:
    """urllib errors plus the provider SDK base errors that LangChain chat models raise."""
    errors = [urllib.error.URLError, TimeoutError, KeyError]
    for mod in ("anthropic", "openai"):
        if importlib.util.find_spec(mod):
            errors.append(__import__(mod).APIError)
    return tuple(errors)


def _message_text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)


def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


class LLMClient:
    def __init__(self, provider: Optional[str] = None, timeout: int = 120):
        self.provider = provider or _detect_provider()
        check_provider_ready(self.provider)
        self.backend = "offline" if self.provider == "offline" else _detect_backend(self.provider)
        self.timeout = timeout
        self._chat_models: dict = {}

    @property
    def offline(self) -> bool:
        return self.provider == "offline"

    def model_for(self, agent: str) -> tuple[str, str]:
        tier = AGENT_MODEL_TIER.get(agent, "small")
        if self.offline:
            return "offline-heuristic", "offline"
        return MODEL_ROUTING[self.provider][tier], tier

    @staticmethod
    def cost(tier: str, tin: int, tout: int) -> float:
        pin, pout = PRICE_PER_MTOK.get(tier, (0, 0))
        return round(tin / 1e6 * pin + tout / 1e6 * pout, 6)

    # ------------------------------------------------------------ transport
    def _post(self, url: str, headers: dict, body: dict) -> dict:
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode())

    def _chat_model(self, model: str, max_tokens: int):
        """LangChain chat model per (model, max_tokens); contract retries stay in generate(), so SDK retries are low."""
        key = (model, max_tokens)
        if key not in self._chat_models:
            if self.provider == "anthropic":
                from langchain_anthropic import ChatAnthropic
                kw = {"base_url": os.environ["ANTHROPIC_BASE_URL"]} if os.getenv("ANTHROPIC_BASE_URL") else {}
                chat = ChatAnthropic(model=model, max_tokens=max_tokens, temperature=0.2,
                                     timeout=self.timeout, max_retries=1, **kw)
            elif self.provider == "openai":
                from langchain_openai import ChatOpenAI
                kw = {"base_url": os.environ["OPENAI_BASE_URL"].rstrip("/") + "/v1"} if os.getenv("OPENAI_BASE_URL") else {}
                chat = ChatOpenAI(model=model, temperature=0.2, timeout=self.timeout, max_retries=1, **kw) \
                    .bind(response_format={"type": "json_object"})
            else:
                raise RuntimeError(f"unsupported provider {self.provider}")
            self._chat_models[key] = chat
        return self._chat_models[key]

    def _call_langchain(self, model: str, system: str, user: str, max_tokens: int) -> LLMResult:
        from langchain_core.messages import HumanMessage, SystemMessage
        msg = self._chat_model(model, max_tokens).invoke([SystemMessage(system), HumanMessage(user)])
        text = _message_text(msg.content)
        usage = msg.usage_metadata or {}
        return LLMResult(_extract_json(text), usage.get("input_tokens", 0), usage.get("output_tokens", 0), model, text)

    def _cached_call(self, agent: str, system: str, user: str, max_tokens: int = 4000) -> LLMResult:
        """_call behind the opt-in response cache; only parseable JSON responses are stored."""
        if os.getenv("BRD2ENG_LLM_CACHE") != "1":
            return self._call(agent, system, user, max_tokens)
        model, _tier = self.model_for(agent)
        key = hashlib.sha256(json.dumps([self.provider, model, max_tokens, system, user]).encode()).hexdigest()
        path = CACHE_DIR / f"{key}.json"
        if path.exists():
            hit = json.loads(path.read_text(encoding="utf-8"))
            return LLMResult(hit["data"], 0, 0, hit["model"], hit["raw_text"], cached=True)
        res = self._call(agent, system, user, max_tokens)
        if res.data is not None:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"data": res.data, "model": res.model, "raw_text": res.raw_text}), encoding="utf-8")
        return res

    def _call(self, agent: str, system: str, user: str, max_tokens: int = 4000) -> LLMResult:
        model, _tier = self.model_for(agent)
        if self.backend == "langchain":
            return self._call_langchain(model, system, user, max_tokens)
        if self.provider == "anthropic":
            base = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
            out = self._post(f"{base}/v1/messages",
                             {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
                              "content-type": "application/json"},
                             {"model": model, "max_tokens": max_tokens, "temperature": 0.2, "system": system,
                              "messages": [{"role": "user", "content": user}]})
            text = "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text")
            usage = out.get("usage", {})
            return LLMResult(_extract_json(text), usage.get("input_tokens", 0), usage.get("output_tokens", 0), model, text)
        if self.provider == "openai":
            base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com").rstrip("/")
            out = self._post(f"{base}/v1/chat/completions",
                             {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                              "content-type": "application/json"},
                             {"model": model, "temperature": 0.2, "response_format": {"type": "json_object"},
                              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
            text = out["choices"][0]["message"]["content"]
            usage = out.get("usage", {})
            return LLMResult(_extract_json(text), usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), model, text)
        raise RuntimeError(f"unsupported provider {self.provider}")

    # ------------------------------------------------------------ contract-enforcing generate
    def generate(self, agent: str, model_cls: Type[BaseModel], system: str, user: str,
                 heuristic: Callable[[], BaseModel], span: dict, retries: int = 2) -> BaseModel:
        """Return a validated ``model_cls`` instance.

        offline  -> heuristic()
        online   -> LLM call, validate; on violation re-prompt with the errors;
                    after `retries` failures fall back to heuristic() and flag it.
        Token usage, model and fallbacks are written into the logging span.
        """
        model, tier = self.model_for(agent)
        span["model"] = model
        span["prompt_hash"] = __import__("hashlib").sha256((system + user).encode()).hexdigest()[:16]
        if self.offline:
            # token estimate so cost/latency dashboards still have a shape
            span["tokens_in"] = (len(system) + len(user)) // 4
            out = heuristic()
            span["tokens_out"] = len(out.model_dump_json()) // 4
            span["mode"] = "offline-heuristic"
            return out

        schema = json.dumps(model_cls.model_json_schema())
        prompt = f"{user}\n\nReturn ONLY a JSON object that validates against this JSON schema:\n{schema}"
        last_err = ""
        for attempt in range(retries + 1):
            try:
                res = self._cached_call(agent, system, prompt if not last_err else
                                 f"{prompt}\n\nYour previous answer violated the contract:\n{last_err}\nFix it.")
            except _transport_errors() as exc:
                last_err = f"transport error {exc}"
                span.setdefault("guardrail_triggers", []).append("llm_transport_error")
                continue
            if res.cached:
                span["cache_hits"] = span.get("cache_hits", 0) + 1
            span["tokens_in"] += res.tokens_in
            span["tokens_out"] += res.tokens_out
            span["cost_usd"] = round(span.get("cost_usd", 0) + self.cost(tier, res.tokens_in, res.tokens_out), 6)
            if res.data is None:
                last_err = "response was not parseable JSON"
                span.setdefault("guardrail_triggers", []).append("malformed_json")
                continue
            try:
                span["mode"] = f"llm(attempt={attempt + 1})"
                return model_cls.model_validate(res.data)
            except ValidationError as ve:
                last_err = str(ve)[:2000]
                span.setdefault("guardrail_triggers", []).append("schema_violation")
        span.setdefault("guardrail_triggers", []).append("llm_fallback_to_heuristic")
        span["mode"] = "fallback-heuristic"
        return heuristic()

    def judge(self, system: str, user: str, span: dict) -> Optional[dict]:
        """Free-form JSON judge call (LLM-as-Judge). Returns None offline."""
        if self.offline:
            return None
        model, tier = self.model_for("judge")
        span["model"] = model
        try:
            res = self._cached_call("judge", system, user, max_tokens=1500)
        except Exception as exc:  # judge failures must never break the pipeline
            span.setdefault("guardrail_triggers", []).append(f"judge_error:{type(exc).__name__}")
            return None
        span["tokens_in"] += res.tokens_in
        span["tokens_out"] += res.tokens_out
        span["cost_usd"] = round(span.get("cost_usd", 0) + self.cost(tier, res.tokens_in, res.tokens_out), 6)
        return res.data

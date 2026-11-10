"""Decision-model clients behind one interface: ``await client.decide(state, questions) -> DecisionResult``.

TypeSafe Jev, Cloudflare Clef and Parallel Decisions share the Jev request shape
(``{"state": ..., "questions": {name: {"type", "instructions", "criteria"}}}``) and answer shape, so one
HTTP client covers all three; :mod:`config` holds what differs. ``fake`` answers deterministically from
the state text for tests and dry runs and never touches the network.

Answers are normalized per question to ``{"type", "value", "choice", "probabilities", "confidence",
"refused", "missing"}``: ``value`` is P(yes) for ``noul``, the score rescaled to [0, 1] for ``score`` and
None for ``choice``. A refusal or an absent answer has ``value`` None and is never used to skip a clip.
"""

import asyncio
import hashlib
import json
import math
import os
import random
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from .config import (
    BACKOFF_INITIAL_SECONDS,
    BACKOFF_MAX_SECONDS,
    MAX_ATTEMPTS,
    PROVIDERS,
    RETRY_STATUSES,
    DEFAULT_DECISION_BASE_URL,
    ProviderSpec,
    estimate_tokens,
)
from .variants import score_levels

ERROR_TEXT_CHARS = 500


@dataclass
class DecisionResult:
    provider: str
    model: str
    answers: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)
    latency_s: float = 0.0
    http_status: int | None = None
    raw: Any = None
    citations: list = field(default_factory=list)
    error: str | None = None
    attempts: int = 1

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------------------
# Response parsing and normalization (pure)
# --------------------------------------------------------------------------------------


def _clamp01(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return min(1.0, max(0.0, number))


def _finite_probabilities(raw: Any) -> dict:
    """Probabilities as finite floats, or {} when any entry is unusable.

    One bad entry drops the whole distribution: scoring a partial one would read the dropped label as zero.
    """
    if not isinstance(raw, dict):
        return {}
    try:
        clean = {key: float(value) for key, value in raw.items()}
    except (TypeError, ValueError, OverflowError):
        return {}
    return clean if all(math.isfinite(value) for value in clean.values()) else {}


def _missing(qtype: str, refused: bool = False) -> dict:
    return {
        "type": qtype,
        "value": None,
        "choice": None,
        "probabilities": {},
        "confidence": None,
        "refused": refused,
        "missing": True,
    }


def normalize_answer(raw: Any, question: dict) -> dict:
    qtype = question.get("type")
    if not isinstance(raw, dict):
        return _missing(qtype)
    if raw.get("type") == "refusal":
        return _missing(qtype, refused=True)
    probabilities = _finite_probabilities(raw.get("probabilities"))
    answer = _missing(qtype)
    answer.update(missing=False, probabilities=probabilities, confidence=raw.get("confidence"))
    if qtype == "noul":
        value = raw.get("noul")
        if value is None:
            value = next((probabilities[k] for k in ("true", "yes", "True", "Yes") if k in probabilities), None)
        answer["value"] = _clamp01(value)
    elif qtype == "score":
        levels = score_levels(question)
        score = raw.get("score")
        if score is None and probabilities:
            try:
                score = sum(float(k) * prob for k, prob in probabilities.items())
            except (TypeError, ValueError):
                score = None
        try:
            score = float(score) if score is not None else None
        except (TypeError, ValueError, OverflowError):
            score = None
        if score is not None and not math.isfinite(score):
            score = None
        answer["value"] = _clamp01(score / (levels - 1)) if score is not None and levels > 1 else None
    elif qtype == "choice":
        answer["choice"] = raw.get("choice")
        if answer["choice"] is None and not probabilities:
            answer["missing"] = True
    if qtype != "choice" and answer["value"] is None:
        answer["missing"] = True
    return answer


def normalize_answers(raw_answers: Any, questions: dict) -> dict:
    raw_answers = raw_answers if isinstance(raw_answers, dict) else {}
    return {name: normalize_answer(raw_answers.get(name), q) for name, q in questions.items()}


def error_message(payload: Any, text: str = "") -> str:
    """Best-effort human message from any vendor's error body (detail / errors / message)."""
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
        if isinstance(detail, dict):
            return str(detail.get("message") or detail)
        if isinstance(detail, list) and detail:
            return "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail)
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            return "; ".join(str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in errors)
        if payload.get("message"):
            return str(payload["message"])
    return (text or str(payload))[:ERROR_TEXT_CHARS]


def unwrap(payload: Any) -> tuple[Any, str | None]:
    """Strip a Workers AI envelope ``{"result": ..., "success": ..., "errors": [...]}`` if present."""
    if isinstance(payload, dict) and "result" in payload and ("success" in payload or "errors" in payload):
        if payload.get("success") is False or payload.get("result") is None:
            return None, error_message(payload)
        return payload["result"], None
    return payload, None


def parse_usage(usage: Any) -> dict:
    if not isinstance(usage, dict):
        return {}
    out = {}
    pairs = (("input_tokens", ("input_tokens", "prompt_tokens")), ("output_tokens", ("output_tokens", "completion_tokens")))
    for ours, theirs in pairs:
        for key in theirs:
            if isinstance(usage.get(key), (int, float)):
                out[ours] = int(usage[key])
                break
    if isinstance(usage.get("cost"), (int, float)):  # OpenRouter reports the charge in USD
        out["cost"] = float(usage["cost"])
    return out


def parse_payload(payload: Any, questions: dict) -> tuple[dict, dict, list, str | None]:
    """(answers, usage, citations, error) from a 2xx body."""
    body, error = unwrap(payload)
    if error:
        return {}, {}, [], error
    if not isinstance(body, dict) or not isinstance(body.get("answers"), dict):
        return {}, {}, [], "response has no 'answers' object"
    citations = body.get("citations") if isinstance(body.get("citations"), list) else []
    return normalize_answers(body["answers"], questions), parse_usage(body.get("usage")), citations, None


def retry_delay(attempt: int, retry_after: str | None = None, rng: random.Random | None = None) -> float:
    if retry_after:
        try:
            return min(BACKOFF_MAX_SECONDS, max(0.0, float(retry_after)))
        except ValueError:
            pass
    base = min(BACKOFF_MAX_SECONDS, BACKOFF_INITIAL_SECONDS * 2 ** (attempt - 1))
    return base * (0.5 + 0.5 * (rng or random).random())


class RateLimiter:
    """Spaces request starts at least ``60 / rpm`` seconds apart (per provider)."""

    def __init__(self, rpm: float, clock=time.monotonic, sleep=asyncio.sleep):
        self.interval = 60.0 / rpm if rpm and rpm > 0 else 0.0
        self.clock = clock
        self.sleep = sleep
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        if not self.interval:
            return
        async with self._lock:
            now = self.clock()
            if self._next > now:
                await self.sleep(self._next - now)
                now = self._next
            self._next = now + self.interval


# --------------------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------------------


def missing_env(provider: str, env=None) -> list[str]:
    env = os.environ if env is None else env
    return [k for k in PROVIDERS[provider].env_keys if not env.get(k)]


class DecisionClient:
    """HTTP client for any provider that speaks the Jev request shape."""

    def __init__(
        self,
        spec: ProviderSpec,
        model: str,
        env=None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep=asyncio.sleep,
        rpm: float | None = None,
        timeout: float | None = None,
        max_attempts: int = MAX_ATTEMPTS,
    ):
        if model not in spec.models:
            raise ValueError(f"unknown model {model!r} for {spec.name}; choose from {sorted(spec.models)}")
        self.spec = spec
        self.model = model
        self.env = os.environ if env is None else env
        self.transport = transport
        self.sleep = sleep
        self.timeout = timeout or spec.timeout_seconds
        self.max_attempts = max(1, max_attempts)
        self.limiter = RateLimiter(rpm or spec.requests_per_minute, sleep=sleep)
        self._client: httpx.AsyncClient | None = None
        self._rng = random.Random(0)

    # -- request -------------------------------------------------------------------
    def build_body(self, state: str | dict, questions: dict) -> dict:
        body_model, _ = self.spec.models[self.model]
        body: dict = {}
        if body_model:
            body["model"] = body_model
        body["state"] = state
        body["questions"] = questions
        body.update(self.spec.extra_body)
        return body

    def build_url(self) -> str:
        _, model_path = self.spec.models[self.model]
        base_url = (self.env.get("DECISION_BASE_URL") or DEFAULT_DECISION_BASE_URL).rstrip("/")
        url = self.spec.url.format(
            account_id=self.env.get("CLOUDFLARE_ACCOUNT_ID", "<CLOUDFLARE_ACCOUNT_ID>"),
            model_path=model_path,
            base_url=base_url,
        )
        return url.replace("/v1/systemone/v1/systemone", "/v1/systemone")  # base URL given with the path

    def build_headers(self, redact: bool = False) -> dict:
        headers = {"Content-Type": "application/json", **self.spec.extra_headers}
        secret = self.env.get(self.spec.auth_env or "", "")
        if self.spec.auth_header and (secret or not self.spec.auth_optional):
            headers[self.spec.auth_header] = f"{self.spec.auth_prefix}{'<redacted>' if redact else secret}"
        return headers

    def validate(self, questions: dict) -> None:
        if not 1 <= len(questions) <= self.spec.max_questions:
            raise ValueError(f"{self.spec.name} takes 1 to {self.spec.max_questions} questions, got {len(questions)}")
        for name in questions:
            if not re.match(self.spec.question_id_pattern, name):
                raise ValueError(f"question id {name!r} is not valid for {self.spec.name}")

    # -- call ----------------------------------------------------------------------
    async def __aenter__(self):
        self._client = httpx.AsyncClient(transport=self.transport, timeout=self.timeout)
        return self

    async def __aexit__(self, *exc):
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def decide(self, state: str | dict, questions: dict) -> DecisionResult:
        self.validate(questions)
        body = self.build_body(state, questions)
        url, headers = self.build_url(), self.build_headers()
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(transport=self.transport, timeout=self.timeout)
        result = DecisionResult(provider=self.spec.name, model=self.model)
        try:
            attempt = 0
            while True:
                attempt += 1
                result.attempts = attempt
                await self.limiter.wait()
                started = time.monotonic()
                retry_after = None
                try:
                    response = await client.post(url, headers=headers, json=body)
                except httpx.HTTPError as exc:
                    result.latency_s = time.monotonic() - started
                    result.http_status, result.raw = None, None
                    result.error = f"{type(exc).__name__}: {exc}"[:ERROR_TEXT_CHARS]
                    retryable = True
                else:
                    result.latency_s = time.monotonic() - started
                    result.http_status = response.status_code
                    try:
                        payload = response.json()
                    except ValueError:
                        payload = None
                    result.raw = payload if payload is not None else response.text[:ERROR_TEXT_CHARS]
                    if 200 <= response.status_code < 300:
                        answers, usage, citations, error = parse_payload(payload, questions)
                        result.answers, result.usage, result.citations, result.error = answers, usage, citations, error
                        return result
                    result.error = f"HTTP {response.status_code}: {error_message(payload, response.text)}"
                    retryable = response.status_code in RETRY_STATUSES
                    retry_after = response.headers.get("retry-after")
                if not retryable or attempt == self.max_attempts:
                    return result
                await self.sleep(retry_delay(attempt, retry_after, self._rng))
        finally:
            if owns_client:
                await client.aclose()


class RateLimitStop(Exception):
    """A keyless route said "rate limited". The run stops; it never retries around the limit."""


RATE_LIMIT_RE = re.compile(r"rate.?limit|too many requests|quota", re.IGNORECASE)
MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_TOOL = "web_decisions"


def parse_mcp_message(response: httpx.Response, request_id: int | None) -> dict | None:
    """The JSON-RPC message answering ``request_id`` from a JSON or SSE (text/event-stream) body."""
    text = response.content.decode("utf-8", errors="replace")
    candidates = []
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        for line in text.splitlines():
            if line.startswith("data:"):
                try:
                    candidates.append(json.loads(line[5:].strip()))
                except ValueError:
                    continue
    elif text.strip():
        try:
            candidates.append(json.loads(text))
        except ValueError:
            return None
    for message in candidates:
        if isinstance(message, dict) and message.get("id") == request_id:
            return message
    return candidates[-1] if candidates and isinstance(candidates[-1], dict) else None


def _content_text(result: dict) -> str:
    return "\n".join(
        str(part.get("text", "")) for part in result.get("content") or [] if isinstance(part, dict)
    )


class McpDecisionClient(DecisionClient):
    """Parallel's keyless MCP route: initialize, notifications/initialized, then one tools/call per clip.

    One session per run. A rate-limit answer (HTTP 429, or a JSON-RPC / tool error that says so) raises
    :class:`RateLimitStop`; other failures are recorded as errors without retries, to stay polite.
    """

    def __init__(self, spec: ProviderSpec, model: str, **kwargs):
        super().__init__(spec, model, **kwargs)
        self.session_id: str | None = None
        self._next_id = 0

    def build_headers(self, redact: bool = False) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
            headers["MCP-Protocol-Version"] = MCP_PROTOCOL_VERSION
        return headers

    def rpc(self, method: str, params: dict | None = None, notify: bool = False) -> dict:
        message: dict = {"jsonrpc": "2.0", "method": method}
        if not notify:
            self._next_id += 1
            message["id"] = self._next_id
        if params is not None:
            message["params"] = params
        return message

    async def _post(self, message: dict) -> httpx.Response:
        client = self._client
        if client is None:
            raise RuntimeError("use the MCP client inside 'async with'")
        response = await client.post(self.build_url(), headers=self.build_headers(), json=message)
        if response.status_code == 429:
            raise RateLimitStop(f"HTTP 429 from {self.spec.name}")
        return response

    async def _ensure_session(self) -> None:
        if self.session_id:
            return
        init = self.rpc(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "precheck-eval", "version": "1"},
            },
        )
        response = await self._post(init)
        message = parse_mcp_message(response, init["id"]) or {}
        if response.status_code >= 400 or "error" in message:
            detail = error_message(message.get("error") or message, response.text)
            if RATE_LIMIT_RE.search(detail):
                raise RateLimitStop(detail)
            raise RuntimeError(f"MCP initialize failed: HTTP {response.status_code}: {detail}")
        self.session_id = response.headers.get("mcp-session-id")
        await self._post(self.rpc("notifications/initialized", notify=True))

    async def decide(self, state: str | dict, questions: dict) -> DecisionResult:
        self.validate(questions)
        result = DecisionResult(provider=self.spec.name, model=self.model)
        try:
            await self._ensure_session()
        except RuntimeError as exc:
            result.error = str(exc)[:ERROR_TEXT_CHARS]
            return result
        except httpx.HTTPError as exc:
            result.error = f"{type(exc).__name__}: {exc}"[:ERROR_TEXT_CHARS]
            return result
        call = self.rpc("tools/call", {"name": MCP_TOOL, "arguments": self.build_body(state, questions)})
        await self.limiter.wait()
        started = time.monotonic()
        try:
            response = await self._post(call)
        except httpx.HTTPError as exc:
            result.latency_s = time.monotonic() - started
            result.error = f"{type(exc).__name__}: {exc}"[:ERROR_TEXT_CHARS]
            return result
        result.latency_s = time.monotonic() - started
        result.http_status = response.status_code
        message = parse_mcp_message(response, call["id"])
        result.raw = message if message is not None else response.text[:ERROR_TEXT_CHARS]
        if message is None or response.status_code >= 400:
            result.error = f"HTTP {response.status_code}: {error_message(message, response.text)}"
            return result
        if "error" in message:
            detail = error_message(message["error"])
            if RATE_LIMIT_RE.search(detail):
                raise RateLimitStop(detail)
            result.error = f"MCP error: {detail}"[:ERROR_TEXT_CHARS]
            return result
        tool_result = message.get("result") or {}
        if tool_result.get("isError"):
            detail = _content_text(tool_result)
            if RATE_LIMIT_RE.search(detail):
                raise RateLimitStop(detail[:ERROR_TEXT_CHARS])
            result.error = f"tool error: {detail}"[:ERROR_TEXT_CHARS]
            return result
        payload = tool_result.get("structuredContent")
        if payload is None:
            try:
                payload = json.loads(_content_text(tool_result))
            except ValueError:
                payload = None
        result.raw = payload if payload is not None else result.raw
        result.answers, result.usage, result.citations, result.error = parse_payload(payload, questions)
        return result


# --------------------------------------------------------------------------------------
# Fake provider (deterministic, offline)
# --------------------------------------------------------------------------------------

FAKE_SIGNAL_WORD = "contradicts"  # the synthetic fixture writes this word more often into high-score clips


def _unit_hash(*parts: str) -> float:
    digest = hashlib.sha256("|".join(parts).encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class FakeClient:
    """Offline stand-in. ``fake-signal`` reads :data:`FAKE_SIGNAL_WORD` counts in the state (never a label);
    ``fake-random`` is noise. About 1 in 60 calls fails with HTTP 500 and 1 in 40 refuses ``harm_topic``."""

    def __init__(self, spec: ProviderSpec, model: str, **_ignored):
        if model not in spec.models:
            raise ValueError(f"unknown model {model!r} for fake; choose from {sorted(spec.models)}")
        self.spec = spec
        self.model = model

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    def build_body(self, state, questions: dict) -> dict:
        return {"model": self.model, "state": state, "questions": questions}

    def build_url(self) -> str:
        return self.spec.url

    def build_headers(self, redact: bool = False) -> dict:
        return {"Content-Type": "application/json"}

    def validate(self, questions: dict) -> None:
        return None

    @staticmethod
    def billed_tokens(state: str, questions: dict) -> int:
        """Like a real vendor, bill the whole request: state plus questions."""
        return estimate_tokens(json.dumps({"state": state, "questions": questions}, ensure_ascii=False))

    def raw_response(self, state: str, questions: dict) -> dict:
        text = state if isinstance(state, str) else str(state)
        if self.model == "fake-random":
            base = _unit_hash(text, "base")
        else:
            count = text.lower().count(FAKE_SIGNAL_WORD)
            base = _sigmoid(1.3 * (count - 2) + 2.0 * (_unit_hash(text, "noise") - 0.5))
        answers = {}
        for name, q in questions.items():
            p = min(1.0, max(0.0, base + 0.15 * (_unit_hash(text, name) - 0.5)))
            if name == "harm_topic" and _unit_hash(text, "refuse") < 0.025:
                answers[name] = {"type": "refusal"}
            elif q["type"] == "noul":
                answers[name] = {"type": "noul", "noul": round(p, 4)}
            elif q["type"] == "score":
                levels = score_levels(q)
                answers[name] = {"type": "score", "score": round(p * (levels - 1), 4), "confidence": 0.5}
            else:
                labels = sorted(q["criteria"])
                low = [lab for lab in labels if lab in ("religious", "advertising", "music_entertainment")]
                high = [lab for lab in labels if lab not in low]
                probs = {lab: (1 - p) / max(1, len(low)) for lab in low}
                probs.update({lab: p / max(1, len(high)) for lab in high})
                choice = max(probs, key=lambda k: (probs[k], k))
                answers[name] = {"type": "choice", "choice": choice, "confidence": probs[choice], "probabilities": probs}
        return {"model": self.model, "answers": answers, "usage": {"input_tokens": self.billed_tokens(text, questions), "output_tokens": 0}}

    async def decide(self, state, questions: dict) -> DecisionResult:
        text = state if isinstance(state, str) else str(state)
        result = DecisionResult(provider="fake", model=self.model, latency_s=0.05 + 0.1 * _unit_hash(text, "lat"))
        if _unit_hash(text, "error") < 1 / 60:
            result.http_status, result.raw = 500, {"detail": "fake server error"}
            result.error = "HTTP 500: fake server error"
            return result
        payload = self.raw_response(text, questions)
        result.http_status, result.raw = 200, payload
        result.answers, result.usage, result.citations, result.error = parse_payload(payload, questions)
        return result


def make_client(provider: str, model: str | None = None, **kwargs):
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; choose from {sorted(PROVIDERS)}")
    spec = PROVIDERS[provider]
    model = model or spec.default_model
    if spec.transport == "fake":
        return FakeClient(spec, model)
    if spec.transport == "mcp":
        return McpDecisionClient(spec, model, **kwargs)
    return DecisionClient(spec, model, **kwargs)

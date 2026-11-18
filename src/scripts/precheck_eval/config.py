"""Every vendor-specific fact the pre-check harness relies on, in one place.

Edit this file when a vendor changes a URL, a header, a model id, a limit or a price. Nothing else in the
package hardcodes them. Prices are USD; ``None`` means "not known yet" and the report prints "unknown"
instead of pretending the call was free.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Price:
    """Cost of one call: per million input/output tokens plus a flat per-call fee."""

    input_per_m: float | None = None
    output_per_m: float | None = 0.0
    per_call: float = 0.0

    def cost(self, input_tokens: int | None, output_tokens: int | None) -> float | None:
        if self.input_per_m is None and self.per_call == 0.0:
            return None
        total = self.per_call
        if self.input_per_m is not None:
            total += (input_tokens or 0) * self.input_per_m / 1e6
        if self.output_per_m is not None:
            total += (output_tokens or 0) * self.output_per_m / 1e6
        return total


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    url: str  # may contain {account_id}, {model_path} and {base_url}
    env_keys: tuple[str, ...]  # environment variables a real call needs
    auth_env: str | None  # the env var holding the secret
    auth_header: str | None
    auth_prefix: str = ""
    auth_optional: bool = False  # send the auth header only when auth_env is set
    # model name on the CLI -> (value sent as body["model"] or None, value substituted for {model_path})
    models: dict = field(default_factory=dict)
    default_model: str = ""
    prices: dict = field(default_factory=dict)  # model -> Price
    context_tokens: dict = field(default_factory=dict)  # model -> documented context (informational)
    extra_body: dict = field(default_factory=dict)
    extra_headers: dict = field(default_factory=dict)
    requests_per_minute: float = 60
    concurrency: int = 4
    timeout_seconds: float = 60.0
    max_questions: int = 64
    question_id_pattern: str = r"^[A-Za-z0-9_.-]{1,100}$"
    default_questions: str = "standard"
    default_variant: str = "full"
    transport: str = "http"  # "http" (Jev request shape), "mcp" (Parallel MCP tools/call) or "fake"
    web_grounded: bool = False  # answers draw on live web retrieval: a separate arm, not a text classifier
    notes: str = ""


# Sources: vendor docs fetched 2026-11-10 (VER-475 vendor notes). Prices are USD per 1M input tokens;
# output tokens are free on every decision model listed here.
PROVIDERS: dict[str, ProviderSpec] = {
    "typesafe": ProviderSpec(
        name="typesafe",
        url="https://api.typesafe.ai/v1/systemone",
        env_keys=("TYPESAFE_API_KEY",),
        auth_env="TYPESAFE_API_KEY",
        auth_header="Authorization",
        auth_prefix="Bearer ",
        models={"jev-latest": ("jev-latest", None), "jev-1.14": ("jev-1.14", None)},
        default_model="jev-latest",
        prices={"jev-latest": Price(input_per_m=0.042), "jev-1.14": Price(input_per_m=0.042)},
        # 64k per request, 32k per question (state + one question); over the limit is HTTP 400
        # max_tokens_exceeded, not truncation. "TypeSafe-Danger-Zone-Long-Context: true" raises both to 262k.
        context_tokens={"jev-latest": 32_000, "jev-1.14": 32_000},
        requests_per_minute=60,  # per-organization limits are only shown in the console
        notes="Probabilities reportedly move up to 0.16 between identical calls (use --repeats); "
        "Jev leans toward the first option of a choice (choice options are shuffled per clip).",
    ),
    "cloudflare": ProviderSpec(
        name="cloudflare",
        url="https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model_path}",
        env_keys=("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"),
        auth_env="CLOUDFLARE_API_TOKEN",
        auth_header="Authorization",
        auth_prefix="Bearer ",
        models={
            "clef": ("clef", "@cf/cloudflare/clef"),
            "clef-flash": ("clef-flash", "@cf/cloudflare/clef-flash"),
        },
        default_model="clef",
        prices={"clef": Price(input_per_m=0.24), "clef-flash": Price(input_per_m=0.038)},
        # Documented windows; long text state is truncated silently, and OpenRouter says Workers AI reads only
        # about the first 2,000 tokens. The report flags calls billed far below the estimated request size.
        context_tokens={"clef": 65_536, "clef-flash": 24_576},
        requests_per_minute=120,  # Workers AI text generation default is 300/min
        max_questions=64,
    ),
    "parallel": ProviderSpec(
        name="parallel",
        url="https://api.parallel.ai/v1/decisions",
        env_keys=("PARALLEL_API_KEY",),
        auth_env="PARALLEL_API_KEY",
        auth_header="x-api-key",
        models={"fast": (None, None)},  # the body carries "mode", not "model"
        default_model="fast",
        prices={"fast": Price(input_per_m=None, output_per_m=None, per_call=0.001)},
        context_tokens={"fast": 32_000},  # state plus the largest question
        extra_body={"mode": "fast"},
        requests_per_minute=300,  # vendor limit is 600/min; stay at half
        max_questions=100,
        question_id_pattern=r"^[A-Za-z0-9_-]+$",
        # VER-443: station metadata hijacked Parallel's web retrieval and loaded words pulled generic
        # fact-check sites, so Parallel gets the claim-only state and the neutral wording.
        default_questions="neutral",
        default_variant="claim",
        web_grounded=True,
        notes="Retrieval cannot be turned off; any answer can be a refusal (HTTP 200).",
    ),
    "parallel_mcp": ProviderSpec(
        # Keyless route, no account: MCP streamable HTTP, tools/call web_decisions. Rate-limited with
        # undocumented limits; the run stops cleanly on a rate-limit response and never retries around it.
        name="parallel_mcp",
        url="https://mcp.parallel.ai/mcp?tools=web_decisions",
        env_keys=(),
        auth_env=None,
        auth_header=None,
        models={"web_decisions": (None, None)},
        default_model="web_decisions",
        prices={"web_decisions": Price(input_per_m=0.0, output_per_m=0.0)},
        context_tokens={"web_decisions": 32_000},
        requests_per_minute=20,  # polite: one call every 3 s
        concurrency=1,
        max_questions=100,
        question_id_pattern=r"^[A-Za-z0-9_-]+$",
        default_questions="neutral",
        default_variant="claim",
        transport="mcp",
        web_grounded=True,
        notes="include_excerpts defaults to false on this route.",
    ),
    "openrouter": ProviderSpec(
        # Request and response follow the Jev shape (guide fetched 2026-11-10:
        # https://openrouter.ai/docs/guides/community/multimodal-decisions); the response adds "id",
        # "provider" and usage.cost (USD), which the report prefers over the price table. Refusal handling
        # and free-model rate limits are not documented there (unverified).
        name="openrouter",
        url="https://openrouter.ai/api/alpha/decisions",
        env_keys=("OPENROUTER_API_KEY",),
        auth_env="OPENROUTER_API_KEY",
        auth_header="Authorization",
        auth_prefix="Bearer ",
        models={
            "typesafe/jev-1.14": ("typesafe/jev-1.14", None),
            "cloudflare/clef": ("cloudflare/clef", None),
            "cloudflare/clef-flash": ("cloudflare/clef-flash", None),
            "parallel/decisions-fast:free": ("parallel/decisions-fast:free", None),
        },
        default_model="cloudflare/clef-flash",
        prices={
            "typesafe/jev-1.14": Price(input_per_m=0.042),
            "cloudflare/clef": Price(input_per_m=0.24),
            "cloudflare/clef-flash": Price(input_per_m=0.038),
            "parallel/decisions-fast:free": Price(input_per_m=0.0),
        },
        context_tokens={
            "typesafe/jev-1.14": 262_000,
            "cloudflare/clef": 65_536,  # Workers AI reads about the first 2,000 text tokens
            "cloudflare/clef-flash": 24_576,
            "parallel/decisions-fast:free": 32_000,
        },
        requests_per_minute=60,
        max_questions=64,
        question_id_pattern=r"^[A-Za-z0-9_-]{1,100}$",  # strictest of the routed vendors (Parallel)
    ),
    "jev_compatible": ProviderSpec(
        # Any server that speaks the Jev request/response shape, e.g. llama.cpp `llama-server` hosting the
        # open-weight Clef-flash GGUF (serves /v1/systemone only). CPU inference is slow: long timeout.
        name="jev_compatible",
        url="{base_url}/v1/systemone",
        env_keys=(),
        auth_env="DECISION_API_KEY",
        auth_header="Authorization",
        auth_prefix="Bearer ",
        auth_optional=True,
        models={"clef-flash": ("clef-flash", None), "clef": ("clef", None), "jev-latest": ("jev-latest", None)},
        default_model="clef-flash",
        prices={m: Price(input_per_m=0.0) for m in ("clef-flash", "clef", "jev-latest")},
        requests_per_minute=600,
        concurrency=1,
        timeout_seconds=600.0,
        max_questions=64,
    ),
    "fake": ProviderSpec(
        name="fake",
        url="fake://decide",
        env_keys=(),
        auth_env=None,
        auth_header=None,
        models={"fake-signal": ("fake-signal", None), "fake-random": ("fake-random", None)},
        default_model="fake-signal",
        prices={"fake-signal": Price(input_per_m=0.0), "fake-random": Price(input_per_m=0.0)},
        requests_per_minute=600_000,
        transport="fake",
    ),
}

DEFAULT_DECISION_BASE_URL = "http://127.0.0.1:8080"  # jev_compatible when DECISION_BASE_URL is unset

# Network behaviour shared by every real provider.
MAX_ATTEMPTS = 5
BACKOFF_INITIAL_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 60.0
RETRY_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524})

# State size: keep the state under this many estimated tokens (excerpt is truncated head + tail).
MAX_STATE_TOKENS = 6_000
CHARS_PER_TOKEN = 3.0  # conservative for Spanish and Arabic; only used for budgets and estimates
# A call billed for fewer than this share of its estimated request tokens was probably cut by the vendor.
TRUNCATION_SUSPECT_RATIO = 0.5

# Report defaults (all overridable on the CLI).
STAGE3_COST_PER_CLIP = {"gemini-3.5-flash": 0.09, "gemini-3.8-flash": 0.18}
CLIPS_PER_DAY = 400
BOOTSTRAP_SAMPLES = 1000
BOOTSTRAP_SEED = 475
RECALL_BAR = {"recall_90": 1.0, "recall_80": 0.95}
STRICT_RECALL_80 = 0.98
SKIP_RATE_GRID = (0.3, 0.4, 0.5, 0.6, 0.7)
SCORE_BANDS = ((0, 20), (20, 40), (40, 60), (60, 80), (80, 90), (90, 101))
TOP_STATIONS = 8

DEFAULT_OUTPUT_DIR = Path(os.getenv("PRECHECK_EVAL_DIR") or Path.home() / ".cache" / "verdad" / "precheck_eval")


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN + 0.999)


def price_for(provider: str, model: str) -> Price:
    spec = PROVIDERS[provider]
    return spec.prices.get(model, Price(input_per_m=None))


def is_web_grounded(provider: str, model: str) -> bool:
    if provider == "openrouter":
        return model.startswith("parallel/")
    spec = PROVIDERS.get(provider)
    return bool(spec and spec.web_grounded)

"""Provider clients, normalization, states, questions and leakage for the VER-475 pre-check (no network).

HTTP is served by ``httpx.MockTransport``; sleeps are patched out.
"""

import asyncio
import json

import httpx
import pytest

from src.scripts.precheck_eval import providers as p
from src.scripts.precheck_eval import variants as v
from src.scripts.precheck_eval.config import PROVIDERS, Price, is_web_grounded, price_for
from src.scripts.precheck_eval.dataset import Clip, load_dataset, model_input, parse_clip, read_ids_file, select_clips

QUESTIONS = v.questions_for("standard")


async def _no_sleep(_seconds):
    return None


def clip(**overrides) -> Clip:
    base = {
        "snippet_id": "s1",
        "split": "dev",
        "weight": 2.0,
        "stratum": "g35_lt40",
        "label": {"stage3_overall": 85, "final_overall": 85, "analyzed_by": "LABEL-SENTINEL-MODEL"},
        "meta": {
            "station_code": "KXYZ",
            "station_name": "Radio Prueba",
            "location_state": "TX",
            "recorded_at": "2026-11-01T10:00:00+00:00",
            "stage3_language": "LANGUAGE-SENTINEL",
            "live": True,
        },
        "input": {
            "stage1_explanation": "The host claims something about voting.",
            "stage1_keywords": ["fraude", "votos"],
            "stage1_categories": ["Election Integrity"],
            "stage1_transcript_excerpt": "padding " * 50 + "dicen que hubo fraude",
            "stage1_language": "Spanish",
            "stage1_extra": {"flagged_transcription": "hubo fraude en los votos", "core_excerpt": "core text"},
        },
    }
    base.update(overrides)
    return parse_clip(base)


def jev_answers(noul=0.8, score=3.0, refuse=None):
    answers = {
        "worth_analysis": {"type": "noul", "noul": noul},
        "checkable_claim": {"type": "noul", "noul": noul},
        "harm_topic": {"type": "noul", "noul": noul},
        "stage3_band": {"type": "score", "score": score, "confidence": 0.6, "probabilities": {"3": 1.0}},
        "content_type": {
            "type": "choice",
            "choice": "news_report",
            "confidence": 0.7,
            "probabilities": {"news_report": 0.7, "religious": 0.2, "advertising": 0.1},
        },
    }
    for name in refuse or ():
        answers[name] = {"type": "refusal"}
    return {"model": "jev-1.14", "answers": answers, "usage": {"input_tokens": 1200, "output_tokens": 3}}


# ---------------------------------------------------------------- config


def test_price_cost_and_lookup():
    assert Price(input_per_m=0.24).cost(1_000_000, 50) == pytest.approx(0.24)
    assert Price(input_per_m=None).cost(10, 0) is None
    assert Price(input_per_m=None, output_per_m=None, per_call=0.001).cost(99999, 0) == 0.001
    assert price_for("typesafe", "jev-latest").input_per_m == 0.042
    assert price_for("cloudflare", "clef-flash").input_per_m == 0.038
    assert price_for("typesafe", "nope").input_per_m is None


def test_web_grounded_arms():
    assert is_web_grounded("parallel", "fast") and is_web_grounded("parallel_mcp", "web_decisions")
    assert is_web_grounded("openrouter", "parallel/decisions-fast:free")
    assert not is_web_grounded("openrouter", "cloudflare/clef")
    assert not is_web_grounded("typesafe", "jev-latest") and not is_web_grounded("unknown", "x")


# ---------------------------------------------------------------- dataset


def test_parse_clip_validates():
    with pytest.raises(ValueError):
        parse_clip([])
    with pytest.raises(ValueError):
        parse_clip({"split": "dev"})
    with pytest.raises(ValueError):
        parse_clip({"snippet_id": "a", "split": "train"})
    with pytest.raises(ValueError):
        parse_clip({"snippet_id": "a", "split": "dev", "weight": "x"})
    with pytest.raises(ValueError):
        parse_clip({"snippet_id": "a", "split": "dev", "weight": 0})
    c = parse_clip({"snippet_id": "a", "split": "test", "weight": None, "label": {"stage3_overall": "bad"}})
    assert c.weight == 1.0 and c.score() is None and c.score("missing") is None


def test_load_dataset_skips_bad_lines_and_duplicates(tmp_path):
    path = tmp_path / "d.jsonl"
    rows = [
        json.dumps({"snippet_id": "a", "split": "dev"}),
        "",
        "{not json",
        json.dumps({"snippet_id": "a", "split": "test"}),
        json.dumps({"snippet_id": "b", "split": "test", "weight": 3}),
    ]
    path.write_text("\n".join(rows) + "\n")
    clips, problems = load_dataset(str(path))
    assert [c.snippet_id for c in clips] == ["a", "b"]
    assert len(problems) == 2 and "duplicate" in problems[1]


def test_select_and_ids_file(tmp_path):
    clips = [clip(snippet_id=f"s{i}", split="dev" if i % 2 else "test") for i in range(6)]
    assert [c.snippet_id for c in select_clips(clips, "dev")] == ["s1", "s3", "s5"]
    assert [c.snippet_id for c in select_clips(clips, "all", ids=["s2", "s3"], limit=1)] == ["s2"]
    (tmp_path / "ids.json").write_text('["s1", "s2"]')
    (tmp_path / "ids.txt").write_text("# comment\ns1\n\ns4\n")
    assert read_ids_file(str(tmp_path / "ids.json")) == ["s1", "s2"]
    assert read_ids_file(str(tmp_path / "ids.txt")) == ["s1", "s4"]


def test_model_input_has_no_label_or_stage3_language():
    mi = model_input(clip())
    assert set(mi) == {"input", "meta"}
    assert set(mi["meta"]) == {"station_name", "location_state", "recorded_at"}
    assert "LABEL-SENTINEL" not in json.dumps(mi) and "LANGUAGE-SENTINEL" not in json.dumps(mi)


@pytest.mark.parametrize("variant", sorted(v.STATE_VARIANTS))
@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_no_label_leaks_into_any_request(variant, provider):
    """The leakage rule: no label value and no Stage 3 language reaches any provider's request body."""
    client = p.make_client(provider, env={})
    state = v.build_state(model_input(clip()), variant)
    body = json.dumps(client.build_body(state.text, v.shuffle_choices(QUESTIONS, "s1")))
    for sentinel in ("LABEL-SENTINEL", "LANGUAGE-SENTINEL", "stage3_overall", "final_overall"):
        assert sentinel not in body


# ---------------------------------------------------------------- states and questions


def test_state_variants_carry_the_right_parts():
    mi = model_input(clip())
    full = v.build_state(mi, "full").text
    assert "Radio Prueba (TX)" in full and "2026-11-01" in full and "fraude, votos" in full
    assert "dicen que hubo fraude" in full
    flag = v.build_state(mi, "flag").text
    assert "dicen que" not in flag and "Election Integrity" in flag
    excerpt = v.build_state(mi, "excerpt").text
    assert "Screening note" not in excerpt and "Radio Prueba" in excerpt
    quote = v.build_state(mi, "quote").text
    assert "hubo fraude en los votos" in quote and "padding" not in quote and "Radio" not in quote
    core = v.build_state(mi, "core").text
    assert "core text" in core and "padding" not in core
    claim = v.build_state(mi, "claim")
    assert "Radio Prueba" not in claim.text and "2026-11-01" not in claim.text and "KXYZ" not in claim.text
    assert "hubo fraude en los votos" in claim.text and "core text" in claim.text
    assert "Screening note" not in claim.text


def test_state_truncates_head_and_tail_and_records_it():
    mi = model_input(clip())
    mi["input"]["stage1_transcript_excerpt"] = "INICIO " + "x" * 50_000 + " FINAL"
    state = v.build_state(mi, "full", max_tokens=1000)
    assert state.truncated and state.truncated_parts == ("excerpt",)
    assert "INICIO" in state.text and "FINAL" in state.text and "characters omitted" in state.text
    assert state.excerpt_chars > state.excerpt_kept_chars
    assert state.est_tokens <= 1100
    assert not v.build_state(mi, "flag").truncated


def test_state_handles_missing_fields_and_unknown_variant():
    state = v.build_state({"input": {}, "meta": {}}, "full")
    assert "unknown station" in state.text and "(empty)" in state.text and "(none)" in state.text
    assert v.build_state({"input": {"stage1_extra": "bad"}}, "claim").text.count("(empty)") == 2
    with pytest.raises(ValueError):
        v.build_state({}, "nope")
    assert v._join("single") == "single"
    assert v.truncate_middle("abcdef", 3)[1] is True


def test_question_sets():
    with pytest.raises(ValueError):
        v.questions_for("nope")
    neutral = json.dumps(v.questions_for("neutral")).lower()
    for word in ("misinformation", "disinformation", "fact-check"):
        assert word not in neutral
    assert set(v.questions_for("standard")) == set(v.questions_for("neutral"))
    assert v.score_levels(QUESTIONS["stage3_band"]) == 5
    assert v.score_levels({"criteria": {}}) == 0
    assert v.questions_hash(QUESTIONS) == v.questions_hash(v.questions_for("standard"))
    assert v.questions_hash(QUESTIONS) != v.questions_hash(v.questions_for("neutral"))


def test_shuffle_choices_is_deterministic_per_clip():
    a = v.shuffle_choices(QUESTIONS, "clip-a")
    assert a == v.shuffle_choices(QUESTIONS, "clip-a")
    assert set(a["content_type"]["criteria"]) == set(QUESTIONS["content_type"]["criteria"])
    orders = {tuple(v.shuffle_choices(QUESTIONS, f"c{i}")["content_type"]["criteria"]) for i in range(10)}
    assert len(orders) > 1
    assert a["worth_analysis"] == QUESTIONS["worth_analysis"]
    assert QUESTIONS["content_type"]["criteria"] == v.questions_for("standard")["content_type"]["criteria"]


def test_scorer_values_and_stack_features():
    answers = p.normalize_answers(jev_answers()["answers"], QUESTIONS)
    values = v.scorer_values(answers)
    assert values["worth_analysis"] == 0.8
    assert values["stage3_band"] == pytest.approx(0.75)
    assert values["content_type"] == pytest.approx(0.7)
    feats = v.stack_features(answers, QUESTIONS)
    assert len(feats) == 4 + len(v.CONTENT_TYPES)
    refused = p.normalize_answers(jev_answers(refuse=["harm_topic"])["answers"], QUESTIONS)
    assert v.scorer_values(refused)["harm_topic"] is None
    assert v.stack_features(refused, QUESTIONS) is None
    label_only = {"type": "choice", "choice": "religious", "probabilities": {}, "value": None}
    assert v.scorer_values({"c": label_only})["c"] == 0.0
    assert v.scorer_values({"c": {**label_only, "choice": None}})["c"] is None
    assert v.scorer_values({"x": None})["x"] is None
    only_choice = dict(answers, content_type={**label_only, "choice": "news_report", "refused": False})
    feats = v.stack_features(only_choice, QUESTIONS)  # sorted questions; content_type labels sorted, from index 1
    assert feats[1] == 0.0 and feats[1 + sorted(v.CONTENT_TYPES).index("news_report")] == 1.0
    no_choice = dict(answers, content_type={**label_only, "choice": None, "refused": False})
    assert v.stack_features(no_choice, QUESTIONS) is None
    no_value = dict(answers, worth_analysis={"type": "noul", "value": None, "refused": False})
    assert v.stack_features(no_value, QUESTIONS) is None


# ---------------------------------------------------------------- normalization


def test_normalize_answer_types():
    q_noul, q_score, q_choice = QUESTIONS["worth_analysis"], QUESTIONS["stage3_band"], QUESTIONS["content_type"]
    assert p.normalize_answer({"type": "noul", "noul": 1.7}, q_noul)["value"] == 1.0
    assert p.normalize_answer({"type": "noul", "probabilities": {"true": 0.3}}, q_noul)["value"] == 0.3
    assert p.normalize_answer({"type": "noul", "noul": "nan"}, q_noul)["missing"]
    assert p.normalize_answer({"type": "noul", "noul": "x"}, q_noul)["value"] is None
    refusal = p.normalize_answer({"type": "refusal"}, q_noul)
    assert refusal["refused"] and refusal["missing"] and refusal["value"] is None
    assert p.normalize_answer(None, q_noul)["missing"] and not p.normalize_answer(None, q_noul)["refused"]
    score = p.normalize_answer({"type": "score", "probabilities": {"0": 0.5, "4": 0.5}}, q_score)
    assert score["value"] == pytest.approx(0.5)
    assert p.normalize_answer({"type": "score", "probabilities": {"a": 1}}, q_score)["missing"]
    choice = p.normalize_answer({"type": "choice", "choice": "other"}, q_choice)
    assert choice["choice"] == "other" and not choice["missing"]
    assert p.normalize_answer({"type": "choice"}, q_choice)["missing"]


def test_error_message_shapes():
    assert p.error_message({"detail": "bad state"}) == "bad state"
    assert p.error_message({"detail": {"message": "no key"}}) == "no key"
    assert p.error_message({"detail": [{"msg": "a"}, "b"]}) == "a; b"
    assert p.error_message({"errors": [{"message": "route"}, "x"]}) == "route; x"
    assert p.error_message({"message": "No API key"}) == "No API key"
    assert p.error_message(None, "plain text") == "plain text"
    assert p.error_message({"type": "error", "error": {"message": "v"}}).startswith("{")


def test_unwrap_and_parse_payload():
    assert p.unwrap({"result": {"answers": {}}, "success": True, "errors": []}) == ({"answers": {}}, None)
    body, error = p.unwrap({"result": None, "success": False, "errors": [{"message": "No such model"}]})
    assert body is None and error == "No such model"
    assert p.unwrap({"answers": {}}) == ({"answers": {}}, None)
    answers, usage, citations, error = p.parse_payload(
        {"answers": {"worth_analysis": {"type": "noul", "noul": 0.2}}, "usage": {"input_tokens": 5, "cost": 1e-5},
         "citations": [{"url": "u"}]},
        {"worth_analysis": QUESTIONS["worth_analysis"]},
    )
    assert answers["worth_analysis"]["value"] == 0.2 and usage == {"input_tokens": 5, "cost": 1e-5}
    assert citations == [{"url": "u"}] and error is None
    assert p.parse_payload({"x": 1}, QUESTIONS)[3] == "response has no 'answers' object"
    assert p.parse_payload({"result": None, "success": False, "errors": []}, QUESTIONS)[3]
    assert p.parse_usage("x") == {} and p.parse_usage({"prompt_tokens": 3}) == {"input_tokens": 3}


def test_retry_delay():
    assert p.retry_delay(1, "7") == 7.0
    assert p.retry_delay(1, "1000") == 60.0
    rng = __import__("random").Random(0)
    assert 1.0 <= p.retry_delay(1, "soon", rng) <= 2.0
    assert p.retry_delay(10, None, rng) <= 60.0


def test_rate_limiter_spaces_requests():
    now = [0.0]
    slept = []

    async def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    limiter = p.RateLimiter(60, clock=lambda: now[0], sleep=sleep)

    async def go():
        for _ in range(3):
            await limiter.wait()

    asyncio.run(go())
    assert slept == [1.0, 1.0]
    asyncio.run(p.RateLimiter(0).wait())


# ---------------------------------------------------------------- HTTP clients


def run(coro):
    return asyncio.run(coro)


def http_client(provider, handler, env=None, **kwargs):
    env = {"TYPESAFE_API_KEY": "k1", "CLOUDFLARE_API_TOKEN": "k2", "CLOUDFLARE_ACCOUNT_ID": "acct",
           "PARALLEL_API_KEY": "k3", "OPENROUTER_API_KEY": "k4"} if env is None else env
    return p.make_client(provider, env=env, transport=httpx.MockTransport(handler), sleep=_no_sleep, **kwargs)


def test_typesafe_success_and_request_shape():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=jev_answers())

    client = http_client("typesafe", handler)
    result = run(client.decide("state text", QUESTIONS))
    assert result.ok and result.http_status == 200 and result.usage["input_tokens"] == 1200
    assert seen["url"] == "https://api.typesafe.ai/v1/systemone" and seen["auth"] == "Bearer k1"
    assert seen["body"]["model"] == "jev-latest" and seen["body"]["state"] == "state text"
    assert result.answers["stage3_band"]["value"] == pytest.approx(0.75)


def test_cloudflare_wrapped_response_and_url():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"result": jev_answers(), "success": True, "errors": [], "messages": []})

    client = http_client("cloudflare", handler, model="clef-flash")
    result = run(client.decide("s", QUESTIONS))
    assert result.ok and result.answers["worth_analysis"]["value"] == 0.8
    assert seen["url"].endswith("/accounts/acct/ai/run/@cf/cloudflare/clef-flash")
    assert client.build_body("s", QUESTIONS)["model"] == "clef-flash"


def test_parallel_body_refusal_and_citations():
    seen = {}

    def handler(request):
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        payload = jev_answers(refuse=["harm_topic"])
        payload.update(mode="fast", citations=[{"url": "https://x"}], decision_id="d1")
        return httpx.Response(200, json=payload)

    client = http_client("parallel", handler)
    result = run(client.decide("claim", QUESTIONS))
    assert "model" not in seen["body"] and seen["body"]["mode"] == "fast"
    assert seen["headers"]["x-api-key"] == "k3"
    assert result.answers["harm_topic"]["refused"] and result.citations == [{"url": "https://x"}]


def test_retries_429_then_succeeds_with_retry_after():
    calls = []
    slept = []

    async def sleep(seconds):
        slept.append(seconds)

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, json={"detail": "slow down"}, headers={"retry-after": "3"})
        return httpx.Response(200, json=jev_answers())

    client = p.make_client("typesafe", env={"TYPESAFE_API_KEY": "k"}, transport=httpx.MockTransport(handler),
                           sleep=sleep, rpm=600_000)
    result = run(client.decide("s", QUESTIONS))
    assert result.ok and result.attempts == 3 and 3.0 in slept


def test_client_errors_are_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(422, json={"detail": [{"msg": "questions: field required"}]})

    result = run(http_client("typesafe", handler).decide("s", QUESTIONS))
    assert not result.ok and len(calls) == 1 and result.http_status == 422
    assert "field required" in result.error


def test_transport_errors_and_5xx_exhaust_attempts():
    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    result = run(http_client("typesafe", boom, max_attempts=2).decide("s", QUESTIONS))
    assert not result.ok and result.attempts == 2 and result.http_status is None and "ConnectError" in result.error

    result = run(http_client("typesafe", lambda r: httpx.Response(503, text="down"), max_attempts=2).decide(
        "s", QUESTIONS))
    assert result.http_status == 503 and result.raw == "down" and result.attempts == 2


def test_bad_success_body_is_an_error():
    result = run(http_client("typesafe", lambda r: httpx.Response(200, json={"oops": 1})).decide("s", QUESTIONS))
    assert result.error == "response has no 'answers' object"


def test_client_inside_context_manager_reuses_connection():
    async def go():
        client = http_client("typesafe", lambda r: httpx.Response(200, json=jev_answers()))
        async with client:
            first = await client.decide("a", QUESTIONS)
            second = await client.decide("b", QUESTIONS)
        return first, second, client._client

    first, second, inner = run(go())
    assert first.ok and second.ok and inner is None


def test_validate_rejects_bad_questions():
    client = p.make_client("parallel", env={})
    with pytest.raises(ValueError):
        client.validate({})
    with pytest.raises(ValueError):
        client.validate({"bad.name": QUESTIONS["worth_analysis"]})
    p.make_client("cloudflare", env={}).validate({"ok.name": QUESTIONS["worth_analysis"]})


def test_make_client_errors():
    with pytest.raises(ValueError):
        p.make_client("nope")
    with pytest.raises(ValueError):
        p.make_client("typesafe", "gpt")
    with pytest.raises(ValueError):
        p.make_client("fake", "nope")


def test_headers_redaction_and_optional_auth():
    client = p.make_client("typesafe", env={"TYPESAFE_API_KEY": "secret"})
    assert client.build_headers(redact=True)["Authorization"] == "Bearer <redacted>"
    assert "secret" not in json.dumps(client.build_headers(redact=True))
    local = p.make_client("jev_compatible", env={})
    assert "Authorization" not in local.build_headers()
    assert local.build_url() == "http://127.0.0.1:8080/v1/systemone"
    keyed = p.make_client("jev_compatible", env={"DECISION_API_KEY": "x", "DECISION_BASE_URL": "http://h:1/v1/systemone/"})
    assert keyed.build_headers()["Authorization"] == "Bearer x"
    assert keyed.build_url() == "http://h:1/v1/systemone"
    assert keyed.timeout == 600.0 and keyed.spec.concurrency == 1
    assert p.missing_env("cloudflare", {"CLOUDFLARE_API_TOKEN": "t"}) == ["CLOUDFLARE_ACCOUNT_ID"]
    assert p.missing_env("parallel_mcp", {}) == [] and p.missing_env("jev_compatible", {}) == []


def test_openrouter_uses_model_ids_and_reports_cost():
    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "typesafe/jev-1.14"
        payload = jev_answers()
        payload["usage"]["cost"] = 0.00005
        payload.update(id="gen-dec-1", provider="TypeSafe")
        return httpx.Response(200, json=payload)

    client = http_client("openrouter", handler, model="typesafe/jev-1.14")
    result = run(client.decide("s", QUESTIONS))
    assert result.usage["cost"] == 0.00005
    assert client.build_url() == "https://openrouter.ai/api/alpha/decisions"


# ---------------------------------------------------------------- MCP


def sse(message: dict, headers=None) -> httpx.Response:
    body = f"event: message\ndata: {json.dumps(message)}\n\n"
    return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream", **(headers or {})})


def mcp_handler(tool_result=None, rpc_error=None, status=200, init_error=None):
    log = []

    def handler(request):
        message = json.loads(request.content)
        log.append((message.get("method"), dict(request.headers)))
        if message["method"] == "initialize":
            if init_error:
                return sse({"jsonrpc": "2.0", "id": message["id"], "error": {"message": init_error}})
            return sse({"jsonrpc": "2.0", "id": message["id"], "result": {}}, {"mcp-session-id": "sess-1"})
        if message["method"] == "notifications/initialized":
            return httpx.Response(202)
        if status != 200:
            return httpx.Response(status, json={"message": "nope"})
        if rpc_error:
            return sse({"jsonrpc": "2.0", "id": message["id"], "error": {"message": rpc_error}})
        return sse({"jsonrpc": "2.0", "id": message["id"], "result": tool_result})

    return handler, log


def mcp_decide(handler, state="claim"):
    async def go():
        client = p.make_client("parallel_mcp", env={}, transport=httpx.MockTransport(handler), sleep=_no_sleep)
        async with client:
            return await client.decide(state, QUESTIONS)

    return run(go())


def test_mcp_session_and_text_content_result():
    payload = jev_answers(refuse=["harm_topic"])
    payload["citations"] = [{"url": "https://a"}]
    handler, log = mcp_handler({"content": [{"type": "text", "text": json.dumps(payload)}]})
    result = mcp_decide(handler)
    assert result.ok and result.answers["harm_topic"]["refused"] and result.citations
    methods = [m for m, _ in log]
    assert methods == ["initialize", "notifications/initialized", "tools/call"]
    assert log[2][1]["mcp-session-id"] == "sess-1"


def test_mcp_structured_content_is_preferred():
    handler, _ = mcp_handler({"structuredContent": jev_answers(), "content": [{"type": "text", "text": "x"}]})
    assert mcp_decide(handler).answers["worth_analysis"]["value"] == 0.8


def test_mcp_tool_error_and_rpc_error():
    handler, _ = mcp_handler({"isError": True, "content": [{"type": "text", "text": "bad question"}]})
    assert mcp_decide(handler).error == "tool error: bad question"
    handler, _ = mcp_handler(rpc_error="Invalid params")
    assert mcp_decide(handler).error == "MCP error: Invalid params"
    handler, _ = mcp_handler(status=500)
    assert mcp_decide(handler).error.startswith("HTTP 500")
    handler, _ = mcp_handler({"content": [{"type": "text", "text": "not json"}]})
    assert mcp_decide(handler).error == "response has no 'answers' object"


def test_mcp_rate_limits_stop_instead_of_retrying():
    for kwargs in (
        {"status": 429},
        {"rpc_error": "Rate limit exceeded"},
        {"tool_result": {"isError": True, "content": [{"text": "Too many requests, slow down"}]}},
        {"init_error": "rate limited"},
    ):
        handler, _ = mcp_handler(**kwargs)
        with pytest.raises(p.RateLimitStop):
            mcp_decide(handler)


def test_mcp_initialize_failure_and_transport_error():
    handler, _ = mcp_handler(init_error="server broken")
    assert "MCP initialize failed" in mcp_decide(handler).error

    calls = []

    def flaky(request):
        message = json.loads(request.content)
        calls.append(message.get("method"))
        if message["method"] == "tools/call":
            raise httpx.ReadTimeout("slow", request=request)
        return mcp_handler(jev_answers())[0](request)

    assert "ReadTimeout" in mcp_decide(flaky).error


def test_mcp_needs_context_manager_and_parses_plain_json():
    client = p.make_client("parallel_mcp", env={})
    with pytest.raises(RuntimeError):
        run(client._post({}))
    response = httpx.Response(200, json={"jsonrpc": "2.0", "id": 5, "result": {}})
    assert p.parse_mcp_message(response, 5) == {"jsonrpc": "2.0", "id": 5, "result": {}}
    assert p.parse_mcp_message(httpx.Response(200, text="garbage"), 1) is None
    assert p.parse_mcp_message(httpx.Response(200, text=""), 1) is None
    broken = httpx.Response(200, content=b"data: {bad\ndata: {\"id\": 9}\n", headers={"content-type": "text/event-stream"})
    assert p.parse_mcp_message(broken, 1) == {"id": 9}
    assert client.build_headers() == {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


# ---------------------------------------------------------------- fake


def test_fake_is_deterministic_and_signal_follows_the_input():
    client = p.make_client("fake")
    low = run(client.decide("nothing here", QUESTIONS))
    high = run(client.decide(" ".join([p.FAKE_SIGNAL_WORD] * 8), QUESTIONS))
    again = run(client.decide("nothing here", QUESTIONS))
    assert low.answers == again.answers
    assert high.answers["worth_analysis"]["value"] > low.answers["worth_analysis"]["value"]
    assert run(p.make_client("fake", "fake-random").decide("x", QUESTIONS)).http_status in (200, 500)
    assert client.build_url() == "fake://decide" and client.build_headers() == {"Content-Type": "application/json"}
    assert client.validate(QUESTIONS) is None


def test_fake_produces_some_errors_and_refusals():
    client = p.make_client("fake")
    results = [run(client.decide(f"state {i}", QUESTIONS)) for i in range(400)]
    assert any(r.error for r in results)
    assert any(r.answers.get("harm_topic", {}).get("refused") for r in results if r.ok)
    assert run(client.decide({"as": "object"}, QUESTIONS)).http_status in (200, 500)


def test_load_dataset_reads_synthetic_fixture(tmp_path):
    from src.scripts.precheck_eval.synthetic import make_dataset, write_dataset

    assert make_dataset(5, seed=1) == make_dataset(5, seed=1)
    path = tmp_path / "s.jsonl"
    assert write_dataset(str(path), n=20) == 20
    clips, problems = load_dataset(str(path))
    assert len(clips) == 20 and not problems and {c.split for c in clips} == {"dev", "test"}

"""Call one provider for every selected clip, caching each result (errors included)."""

import asyncio
import json
from dataclasses import asdict, dataclass

from .cache import ResponseCache, body_hash, cache_key
from .config import MAX_STATE_TOKENS, estimate_tokens, price_for
from .dataset import Clip, model_input
from .providers import RateLimitStop
from .variants import build_state, questions_hash, shuffle_choices


def run_variant(state_variant: str, question_set: str, max_state_tokens: int = MAX_STATE_TOKENS) -> str:
    """Cache / run label. A non-default state budget is part of the label so runs do not mix."""
    label = f"{state_variant}.{question_set}"
    return label if max_state_tokens == MAX_STATE_TOKENS else f"{label}.t{max_state_tokens}"


@dataclass
class Prepared:
    clip: Clip
    state: object  # variants.State
    body: dict
    questions: dict
    key: str
    repeat: int = 0


def prepare(
    clips: list[Clip],
    client,
    state_variant: str,
    question_set: str,
    questions: dict,
    repeats: int = 1,
    shuffle: bool = True,
    max_state_tokens: int = MAX_STATE_TOKENS,
) -> list[Prepared]:
    variant = run_variant(state_variant, question_set, max_state_tokens)
    out = []
    for clip in clips:
        state = build_state(model_input(clip), state_variant, max_state_tokens)
        clip_questions = shuffle_choices(questions, clip.snippet_id) if shuffle else questions
        body = client.build_body(state.text, clip_questions)
        request_hash = body_hash(body)
        for repeat in range(max(1, repeats)):
            # Repeat 0 keeps the plain key so adding --repeats later reuses the first call.
            key_variant = variant if repeat == 0 else f"{variant}#r{repeat}"
            key = cache_key(client.spec.name, client.model, key_variant, clip.snippet_id, request_hash)
            out.append(Prepared(clip=clip, state=state, body=body, questions=clip_questions, key=key, repeat=repeat))
    return out


def pending(prepared: list[Prepared], cached: dict, retry_errors: bool = False) -> list[Prepared]:
    """Items to call: not cached, cut off by a rate limit earlier, or (with retry_errors) failed."""
    todo = []
    for item in prepared:
        record = cached.get(item.key)
        if record is None or record.get("rate_limited"):
            todo.append(item)
        elif retry_errors and (record.get("result") or {}).get("error") is not None:
            todo.append(item)
    return todo


def dry_run_text(client, prepared: list[Prepared], todo: list[Prepared]) -> str:
    """The request for the first clip plus the estimated number and cost of calls (no network)."""
    lines = []
    if prepared:
        first = prepared[0]
        lines += [
            f"POST {client.build_url()}",
            "Headers: " + json.dumps(client.build_headers(redact=True)),
            f"Body for {first.clip.snippet_id} (state ~{first.state.est_tokens} tokens, "
            f"truncated={first.state.truncated}):",
            json.dumps(first.body, ensure_ascii=False, indent=2),
        ]
    price = price_for(client.spec.name, client.model)
    costs = [price.cost(estimate_tokens(json.dumps(item.body, ensure_ascii=False)), 0) for item in todo]
    known = [c for c in costs if c is not None]
    cost_text = f"${sum(known):.4f}" if len(known) == len(costs) else "unknown (no price in config.py)"
    truncated = sum(1 for item in prepared if item.state.truncated and item.repeat == 0)
    lines += [
        f"Calls selected: {len(prepared)}; already cached: {len(prepared) - len(todo)}; calls to make: {len(todo)}",
        f"States truncated by the harness: {truncated}",
        f"Estimated cost of those calls: {cost_text}",
    ]
    if client.spec.notes:
        lines.append(f"Provider notes: {client.spec.notes}")
    return "\n".join(lines)


async def run_calls(
    client,
    prepared: list[Prepared],
    cache: ResponseCache,
    state_variant: str,
    question_set: str,
    questions: dict,
    concurrency: int | None = None,
    max_calls: int | None = None,
    retry_errors: bool = False,
    max_state_tokens: int = MAX_STATE_TOKENS,
    log=print,
) -> dict:
    variant = run_variant(state_variant, question_set, max_state_tokens)
    cached = cache.load(client.spec.name, client.model, variant)
    todo = pending(prepared, cached, retry_errors)
    summary = {
        "selected": len(prepared),
        "cached": len(prepared) - len(todo),
        "calls": 0,
        "errors": 0,
        "not_called_budget": 0,
        "rate_limited": None,
    }
    semaphore = asyncio.Semaphore(max(1, concurrency or client.spec.concurrency))
    qhash = questions_hash(questions)

    def record_for(item: Prepared, result_dict: dict, rate_limited: bool = False) -> dict:
        state_meta = {k: v for k, v in asdict(item.state).items() if k != "text"}
        state_meta["est_request_tokens"] = estimate_tokens(json.dumps(item.body, ensure_ascii=False))
        return {
            "key": item.key,
            "provider": client.spec.name,
            "model": client.model,
            "variant": variant,
            "state_variant": state_variant,
            "question_set": question_set,
            "questions_hash": qhash,
            "snippet_id": item.clip.snippet_id,
            "repeat": item.repeat,
            "body_hash": body_hash(item.body),
            "rate_limited": rate_limited,
            "state_meta": state_meta,
            "request": item.body,
            "result": result_dict,
        }

    async def one(item: Prepared):
        async with semaphore:
            if summary["rate_limited"]:
                return
            if max_calls is not None and summary["calls"] >= max_calls:
                summary["not_called_budget"] += 1
                return
            summary["calls"] += 1
            try:
                result = await client.decide(item.body["state"], item.questions)
            except RateLimitStop as exc:
                summary["rate_limited"] = str(exc)
                error = {"provider": client.spec.name, "model": client.model, "error": f"rate limited: {exc}"}
                cache.append(record_for(item, error, rate_limited=True))
                return
            cache.append(record_for(item, result.to_dict()))
            if result.error:
                summary["errors"] += 1
                log(f"  {item.clip.snippet_id}: {result.error}")

    async with client:
        await asyncio.gather(*(one(item) for item in todo))
    if summary["not_called_budget"]:
        log(f"--max-calls {max_calls} reached: {summary['not_called_budget']} calls were not made")
    if summary["rate_limited"]:
        log(
            f"Stopped: {client.spec.name} answered with a rate limit ({summary['rate_limited']}). "
            "Nothing was retried; run the same command later to resume."
        )
    return summary

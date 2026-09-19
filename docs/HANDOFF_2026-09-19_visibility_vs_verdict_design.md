# Handoff: separate "is this clip visible" from "is this clip false"

Date: 2026-09-19
Author: Claude (session `session_01RbFdV1RH3zCkU5y5JZ4bnp`), for Rajiv Sinclair
Status: unsolved design problem, no code changes yet. Written for another agent to
think through and propose/implement a fix.

## The one-sentence problem

VERDAD currently uses the same signal — "can we cite a source that contradicts this
claim" — to decide both **what verdict a clip gets** and **whether a journalist can
find the clip at all**. Those should not be the same gate, and conflating them is
actively working against the product's purpose.

## Why this matters right now

A journalist (Carlos Chirinos, writing for a palabra piece publishing next week, via
contacts Martina and Tamoa) searched VERDAD for coverage of a specific claim: that
Fulton County, GA "acknowledged" election violations and 1.7 million Georgia votes
were "violated." He found nothing after July 24, and asked why.

We found the clip. It's real: a September 10 broadcast on Radio Mundo (Florida)
making exactly that claim, bundled with a fabricated Justice Alito quote (confirmed
fabricated — PolitiFact and FactCheck.org have debunked it) and a claim that Maduro
will testify against Whitmer and Benson. Our own pipeline flagged it as a suspect
claim. It still does not appear in search, and by current design, it likely never
will.

Rajiv's framing (verbatim, this is the requirement, not just a symptom to patch):

> the whole point of verdad.app is to help journalists to find examples of snippets
> where misinformation is being broadcast on the air. our system should not hide
> them, but it should analyze them and explain correctly when they are misleading or
> when they contain inaccurate information in their assessment.

## How the current system actually works

Pipeline: Stage 3 (initial analysis + scoring + live web search for corroborating/
contradicting sources) → Stage 4 (review pass; re-reads Stage 3's *already frozen*
`verification_evidence`, does **not** do its own new web search) → if the resulting
confidence score clears the publication threshold, the clip becomes visible in the
app's search/feed.

The evidence gate — `apply_evidence_caps()` in
`src/processing_pipeline/stage_3/models.py` (also invoked from
`src/processing_pipeline/stage_4/tasks.py`) — caps how high a `verified_false` (or
similar debunking) verdict's confidence score can go **unless** at least one search
result in `verification_evidence.search_results[]` is marked
`relevance_to_claim == "contradicts_claim"` and carries a usable http(s) URL (see
`is_http_url` / the admissibility check around `models.py:473-507`). Without that,
the score is capped below the publication threshold, and the clip does not surface.

This gate was added deliberately, in response to earlier, real complaints from
Carlos and Tamoa about the system confidently mislabeling things "false" without
backing. It is doing exactly the job it was built for. The problem is that the same
number it produces is now also being used to decide visibility, and those are
different questions.

**Why this specific clip can never pass the gate as currently wired:** claims like
"Fulton County acknowledged election violations" are hyper-local and largely
uncovered by mainstream fact-checkers. There is often no citable article that
specifically contradicts a claim this narrow — not because the claim is true, but
because nobody writes a fact-check about a claim this obscure. So exactly the kind
of claim a narratives reporter is looking for (a wild, locally-specific assertion) is
structurally the kind least likely to ever get a `contradicts_claim` source. This
was independently confirmed while investigating a related incident (VER-389): across
101 similar Fulton/election-tagged rows we could re-verify, 0 had any
`contradicts_claim` search result. This isn't a bug in the search — it's inherent to
how fact-checking coverage of local radio disinformation actually works.

## What's already tracked

- **VER-358**: the confidence-threshold decision this gate implements. Already open,
  already understood as unresolved. This handoff is evidence that it's not a
  nice-to-have — it's actively blocking a live journalist's search and story.
- **VER-348**: an earlier "absence-of-evidence" hotfix in the same area. Worth
  reading for prior context/tradeoffs before proposing a new fix, to avoid
  re-litigating a decision that was already made once.
- **VER-389** (separate, already fixed in a different PR): an unrelated bug where a
  sweeper job that requeues stuck `Error`-status rows was never scheduled, stranding
  ~3,900 clips in an `Error` queue since August. That bug is being fixed separately
  and is NOT the cause of this problem — even with that queue fully cleared, this
  specific clip and most others like it would still fail the evidence gate and stay
  hidden. Do not conflate the two; a reader of Slack thread `1789491342.759259` may
  see both discussed together.

## The shape of a fix (not a decision, just the outline that seems obviously right)

Separate the two questions the gate currently answers as one:

1. **Should this clip be visible/searchable at all?** — Should be based on whether
   the pipeline identified a genuine suspect claim worth a journalist's attention,
   not on whether we can cite a source refuting it.
2. **What label/verdict does it get, and how confident are we?** — This is where the
   evidence-gate logic (citable contradiction required for a strong "false" verdict)
   correctly belongs. Low/no corroborating evidence should degrade the *label*
   ("unverified," "no corroborating source found," or similar — exact taxonomy TBD),
   not the *visibility*.

If this is right, most flagged clips currently sitting below the publication
threshold should become visible with a softer label instead of invisible with an
inflated one. That reintroduces some of the risk the evidence gate was built to
prevent (a wrong-looking "false" label reaching a journalist) — except the new label
would explicitly say "we could not confirm this independently," which is a different
and more honest claim than "false." Whether that distinction is legible enough to
readers, and whether it fully addresses the original complaint that caused the gate
to be built, needs real thought — that's the actual open design problem, not a
detail to skip past.

## Open questions for the next agent

1. What should the visibility gate check instead, if not "citable contradiction
   exists"? (E.g.: any high-confidence claim extraction at all? A minimum
   plausibility/specificity score? Something else Stage 3 already computes?)
2. What is the full label taxonomy, and how is each label surfaced in the frontend
   (`verdad-frontend` repo) — copy, styling, filtering? Confirm with that repo's
   maintainers/code before assuming search/filter UI needs to change too.
3. Does this change apply retroactively to the ~101,000-clip backlog, or only to
   new clips going forward? Reprocessing at scale has cost and Stage 3 API-quota
   implications worth sizing first.
4. Exact confidence-score / threshold mechanics that gate search visibility today
   live somewhere between Stage 3/4 scoring and the frontend/Supabase query layer —
   this doc has not traced that last hop precisely (i.e., the exact SQL/view/API
   filter verdad-frontend uses to decide what's "in the app"). Confirm that before
   designing the fix, it may be the smallest part to change or the part that
   constrains everything else.
5. Whether relabeling previously-hidden clips as "unverified" (rather than leaving
   them hidden) reopens the original complaint that led to building the gate in the
   first place — re-read VER-348/VER-358 history and, ideally, talk to Tamoa/Carlos
   about what label language they'd find useful versus misleading.

## What NOT to do

- Don't just lower the confidence threshold globally to make more things visible —
  that was tried before (see VER-348) and is exactly what caused the original
  "wrongly labeled false" complaints this gate was built to fix.
- Don't touch `src/processing_pipeline/*/flows.py`, `supabase/migrations/`,
  `fly.*.toml`, or `Dockerfile.*` without plan mode first — see `CLAUDE.md`, these
  affect production topology.
- Don't promise Carlos or any journalist a timeline until a real design is agreed
  and at least prototyped — the letter already sent (or being sent) to
  Martina/Tamoa says this is being worked on, not fixed.

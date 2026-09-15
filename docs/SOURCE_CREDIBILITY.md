# Source credibility tiers and broadcast provenance (VER-360)

Sputnik Mundo used to enter the pipeline with the same prior as a Georgia community station, and the analysis
model could call a true news item "fabricated" on the strength of a single contradicting link. This document
describes the credibility model that fixes both, where the data lives, and how to change it.

## The model: dual phenomenology

Borrowed from nuclear early warning, where a launch is believed only when two independent sensors agree:
**a fabrication or falsity verdict needs two independent lines of contradicting evidence that agree.**

Concretely, `apply_credibility_gate()` (in `src/processing_pipeline/source_credibility.py`) lets a verdict that
asserts falsity keep its score only when the contradicting search results contain either

- two sources of **tier 1 or 2** that are mutually **independent** (different `owner` key, different registrable
  domain, and not two state-controlled outlets of the same country), or
- one **tier-1** source plus an independent **fact-checker** (`category = fact_checker`).

Otherwise `confidence_scores.overall` and every category score are capped at 40 (the same
`EVIDENCE_CAP_MAX_SCORE` as PR #80's evidence gate) and a `[Credibility gate] ...` note is appended to both
explanation languages saying what corroboration is missing. Tier-5 (denylisted) results are dropped before the
test and listed as `excluded`. Scores are never raised, and the station's provenance alone never changes a
score: reputation is not evidence of falsity, and a state outlet can report a real earthquake.

Two axes of provenance are kept separate:

| Axis | Key | Table / CSV | Used by |
|---|---|---|---|
| Web evidence source | domain (bare host) | `source_credibility_domains` / `data/source_credibility/domains.csv` | Stage 3 search results (`source_tier`, `source_category`), credibility gate, Stage 4 `upsert_knowledge_entry` |
| Broadcast source | `audio_files.radio_station_code` | `source_provenance` / `data/source_credibility/stations.csv` | Stage 3 Snippet Data (`source_provenance`), Stage 4 metadata, KB write block |

## Tiers

| Tier | Meaning | Examples |
|---|---|---|
| 1 | Trusted: wire services, IFCN/EFCSN fact-checkers, official primary sources, public broadcasters with statutory independence | reuters.com, bbc.com, politifact.com, maldita.es, cdc.gov |
| 2 | Generally reliable: major national outlets | nytimes.com, elpais.com, univision.com, aljazeera.com |
| 3 | Default / mixed / unrated. **Default for any domain not in the table.** Regional outlets and "watch" rows also sit here. | elnuevodia.com, lapatilla.com |
| 4 | Unreliable (MBFC Low/Questionable, Iffy Index row, RSP generally unreliable). Never counts as corroboration, but stays visible to the model. | breitbart.com, newsmax.com, dailymail.co.uk |
| 5 | Denied: EU-sanctioned state media, RSP deprecated/blacklisted, Pravda network, state-controlled outlets without any reliable rating. Excluded from evidence; blocks KB writes. | rt.com, sputniknews.com, presstv.ir, infowars.com, pravda-es.com |

Only tiers 1-2 can corroborate a falsity verdict.

Categories: `wire`, `public_broadcaster`, `fact_checker`, `official`, `broadsheet`, `broadcaster`, `regional`,
`magazine`, `state_controlled`, `conspiracy`, `hyperpartisan`, `disinformation_network`, `satire`, `other`.

Station provenance values: `state_controlled`, `state_funded_independent`, `public`, `commercial`, `community`,
`religious`, `unknown` (default for stations not listed). Seeded: SPMN and WZHF `state_controlled`
(Rossiya Segodnya), MCD `state_funded_independent` (France Medias Monde).

### Domain matching

`normalize_domain()` lowercases, strips scheme/path/port and a leading `www.`, `m.` or `amp.`, and keeps other
subdomains. Lookup falls back through parent domains up to the registrable domain, so `actualidad.rt.com` uses its
own row when present and `rt.com` otherwise, and `en.m.wikipedia.org` resolves to the `wikipedia.org` row. The
`owner` key defaults to the registrable domain when a row leaves it blank.

**Official domains without a row.** After the table lookup and before the tier-3 default, `official_tier_for()`
gives hosts on government or intergovernmental suffixes tier 1, category `official`: the `.gov`, `.mil` and `.int`
TLDs; a `gov.`, `gob.`, `gouv.`, `go.` or `gc.` second-level label under a two-letter country code (`km.gov.lv`,
`gob.mx`, `service.gov.uk`, `economie.gouv.fr`, `mofa.go.jp`, `canada.gc.ca`); and `europa.eu`. One government is
one voice for the independence test, matching the seeded `us-government` rows: `.gov`/`.mil` hosts get owner
`us-government`, a country-code shape gets `<cc>-government` (`lv-government`, `mx-government`, `ca-government`),
`europa.eu` hosts get `eu-institutions`, and each `.int` body keeps its registrable domain as owner. So state.gov
plus eia.gov do not corroborate each other, while state.gov plus km.gov.lv, or michigan.gov plus an independent
tier-2 outlet, do. These ratings carry `source: "heuristic:official_tld"` in `credibility_gate.evidence_tiers` so an
analyst can tell a heuristic hit from a table row. An explicit row always wins (`vtv.gob.ve` stays denied), so a
captured or propaganda government site is handled by adding a row, never by editing the heuristic. The heuristic
exists because the seed cannot list every ministry: the September 2026 evaluation lost a true positive (Michigan
voting dates contradicted by michigan.gov) and capped several correct verdicts when unlisted official sources
(state.gov, eia.gov, km.gov.lv) defaulted to tier 3.

There is deliberately no regex matching. The Pravda / Portal Kombat network follows two shapes: language
subdomains of one host (`(^|\.)news-pravda\.com$`, e.g. `es.news-pravda.com`), which the parent-domain fallback
already resolves to the `news-pravda.com` row, and separate registrable domains (`^pravda-[a-z]{2,3}\.com$`, e.g.
`pravda-es.com`), which each need their own row because nothing above the registrable domain is consulted.

### Citations

Every row's `rating_sources` is a `;`-separated list of the published ratings that justify it, e.g.
`IFCN:signatory`, `WikipediaRSP:deprecated`, `MBFC:Questionable`, `EU:Reg2022/350`, `Ownership:state`,
`VIGINUM:PortalKombat-2024`, `Lin2023 pc1=0.293`. Tier-4 and tier-5 rows must have at least one citation (enforced
by the CSV test and a table CHECK). Do not add an unreliable or denied row you cannot cite.

### Provenance of the seed list

`data/source_credibility/domains.csv` was assembled in September 2026 from a research pass over public rating
sources; every row's `rating_sources` restates what those sources published, with attribution, so a row can be
contested by checking the citation:

- **Iffy Index of Unreliable Sources** (iffy.news, Barrett Golding), CC BY 4.0. Only rows we have a specific rating
  for were used; the index is not copied wholesale into this repository.
- **IFCN signatory registry** (ifcncodeofprinciples.poynter.org), open JSON; status as of the 2026-09 list
  (`IFCN:signatory`, `IFCN:in-renewal`, `IFCN:expired-YYYY`). EFCSN membership is noted where known.
- **Wikipedia Reliable Sources / Perennial sources list** (WP:RSP), CC BY-SA 4.0 (`WikipediaRSP:deprecated`,
  `blacklisted`, `generally-unreliable`, `no-consensus`, `generally-reliable`).
- **Council Regulation (EU) 2022/350** and its successor sanctions packages suspending RT and Sputnik properties
  (`EU:Reg2022/350`), plus FARA registrations and ownership facts (`Ownership:state`).
- **Media Bias/Fact Check** and **NewsGuard** ratings are proprietary and are quoted only as attributed facts about
  individual domains (e.g. `MBFC:Questionable`, "NewsGuard 20/100 (Press Gazette)"), never bulk-copied.
- **Lin et al. 2023** (PNAS Nexus, domain quality `pc1` scores) cited per domain as supporting evidence.
- **VIGINUM "Portal Kombat" (2024)** and the CheckFirst Pravda-network dataset (MPL-2.0) for the Pravda mirrors.

Mapping from the research pass: high-credibility rows were tiered by category (wire, public broadcaster,
fact-checker, official -> 1; broadsheet, broadcaster, magazine -> 2); low-credibility rows keep the research tier
(3 watch, 4 unreliable, 5 denied).
Owner keys group properties of one network (`rossiya-segodnya` for RT, Sputnik and RIA; `china-state` for CGTN,
Xinhua, China Daily and Global Times; `irib` for Press TV and HispanTV; `cuba-state`; `pravda-network`; and so on)
so the independence test cannot be satisfied by two arms of the same operation.

## Editing the data

The Supabase tables are the runtime source of truth and are admin-editable; the CSVs in git are the seed and the
reviewable history. Keep them in sync with the script:

```bash
# validate the CSVs and show what would change (no credentials needed for --dry-run without SUPABASE_URL)
python src/scripts/import_source_credibility.py import --dry-run

# push CSV -> tables (upsert on domain / station_code; rows only in the table are left alone)
python src/scripts/import_source_credibility.py import --updated-by "$USER"

# pull tables -> CSV after admin edits, then commit the CSV
python src/scripts/import_source_credibility.py export

# report differences without writing anything
python src/scripts/import_source_credibility.py diff
```

The pipeline reads the tables through `SupabaseClient.get_source_credibility_domains()` /
`get_source_provenance()` when a flow has called `configure_source_credibility(supabase_client)` (Stage 3 and
Stage 4 flows do), caches them for 10 minutes and falls back to the CSVs when the client is missing or the query
fails. Tests and local runs therefore need no network. Call `get_source_credibility().reload()` to refresh early.

Migration: `supabase/migrations/20260915120000_source_credibility.sql` creates both tables with CHECK constraints
on tier / provenance / category, RLS enabled, read access for `authenticated` and full access for `service_role`.

## What the pipeline records

Stage 3 stores the gate outcome in `snippets.grounding_metadata.credibility_gate`; Stage 4 re-applies the gate to
the reviewer's output (using the preserved Stage 3 search record) and stores it under the same key:

```json
"credibility_gate": {
  "station_provenance": {"station_code": "SPMN", "provenance": "state_controlled", "owner": "rossiya-segodnya", "country": "RU"},
  "evidence_tiers": [{"domain": "apnews.com", "tier": 1, "category": "wire"}, {"domain": "rt.com", "tier": 5, "category": "state_controlled"}],
  "corroboration": {"satisfied": false, "independent_sources": [], "excluded": ["rt.com"], "reason": "only one contradicting source (apnews.com, tier 1)"},
  "capped": true, "cap": 40, "original_overall": 98, "note": "[Credibility gate] Confidence capped at 40 ..."
}
```

`capped` is false and the cap fields are absent when the analysis does not assert falsity or the corroboration
rule is satisfied. The record is always written so the tiers seen by the model can be audited.

Other touch points:

- `stage_3/web_tools.searxng_web_search` labels each result with `source_tier` (1-5) and `source_category`
  (`denylisted` for tier 5). Nothing is filtered; the model sees everything but knows what it is looking at.
- `stage_3/executors.py` adds `source_provenance` to the Snippet Data metadata; `prompts/stage_3/analysis_prompt.md`
  section C.3 tells the model how to use tiers and provenance.
- `stage_4/tools.upsert_knowledge_entry` rejects tier-5 source URLs and refuses to write any KB entry while
  reviewing a snippet from a `state_controlled` station (station code read from the session's `metadata`).

## Follow-ups

- Move station provenance onto PR #76's `sources` table (`sources.provenance`) and PR #84's `config/stations.yaml`
  (`Station.provenance`) once they land; `source_provenance` is the interim home keyed by station code.
- Admin UI for both tables (Admins' Frontend Interfaces project); until then edit via the Supabase dashboard or the
  CSV + import script.
- Owner keys for research-only rows were derived from the row's notes or default to the registrable domain;
  review them when a new tier 1-2 outlet joins a group that already has a row (the independence test depends on it).
- Draw a dedicated control set for `prompts/eval/state-media-false-positives-2026-09.json` (it reuses the
  fabricated-content control ids) and run PR #71's harness on it.
- Stage 1 does not yet see provenance; add it to `stage_1/tasks.get_audio_file_metadata()` if detection should
  also know the station type.

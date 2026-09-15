"""Source credibility: domain tiers for web evidence and ownership provenance for broadcast stations (VER-360).

Two axes, both admin-editable in Supabase and git-seeded from ``data/source_credibility/*.csv``:

* ``source_credibility_domains``: domain -> tier 1..5 (1 trusted: wires, IFCN fact-checkers, official sources,
  independent public broadcasters; 2 generally reliable; 3 default/mixed/unrated, also for unknown domains;
  4 unreliable, never corroborates; 5 denied, excluded from evidence and blocks KB writes), category, owner, country.
* ``source_provenance``: station code -> provenance (state_controlled, state_funded_independent, public, ...).

The credibility gate implements *dual phenomenology*: an analysis that asserts something is fabricated needs two
mutually independent contradicting sources of tier <= 2 (or one tier-1 source plus an independent fact-checker);
otherwise its scores are capped like PR #80's evidence gate. Reputation alone never changes a score.
"""

import copy
import csv
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from itertools import combinations
from urllib.parse import urlsplit

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")
DOMAINS_CSV = os.path.join(DATA_DIR, "source_credibility", "domains.csv")
STATIONS_CSV = os.path.join(DATA_DIR, "source_credibility", "stations.csv")

VALID_TIERS = (1, 2, 3, 4, 5)
TIER_LABELS = {1: "trusted", 2: "generally_reliable", 3: "default", 4: "unreliable", 5: "denied"}
DEFAULT_TIER = 3
UNRELIABLE_TIER = 4
DENYLIST_TIER = 5
CORROBORATING_MAX_TIER = 2
VALID_CATEGORIES = frozenset(
    {
        "wire",
        "public_broadcaster",
        "fact_checker",
        "official",
        "broadsheet",
        "broadcaster",
        "regional",
        "magazine",
        "state_controlled",
        "conspiracy",
        "hyperpartisan",
        "disinformation_network",
        "satire",
        "other",
    }
)
DEFAULT_CATEGORY = "other"
VALID_PROVENANCES = frozenset(
    {"state_controlled", "state_funded_independent", "public", "commercial", "community", "religious", "unknown"}
)
DEFAULT_PROVENANCE = "unknown"
DOMAIN_COLUMNS = ("domain", "tier", "category", "country", "languages", "owner", "rating_sources", "notes")
STATION_COLUMNS = ("station_code", "provenance", "owner", "country", "rating_sources", "notes")

CREDIBILITY_CACHE_TTL_SECONDS = 600

# Owner keys that legitimately span several registrable domains (parent companies, networks, governments).
# Any other non-state row must use its registrable domain as owner, so the independence test cannot be gamed by
# a mistyped key; state_controlled / disinformation_network rows may group by operator freely.
KNOWN_NETWORKS = {
    "afp": {"afp.com"},
    "al-jazeera-media-network": {"aljazeera.com", "aljazeera.net"},
    "annenberg-public-policy-center": {"factcheck.org"},
    "associated-press": {"apnews.com"},
    "bbc": {"bbc.com", "bbc.co.uk"},
    "comcast": {"telemundo.com", "nbcnews.com"},
    "consejo-de-redaccion": {"colombiacheck.com"},
    "deutsche-welle": {"dw.com"},
    "disney": {"go.com"},
    "epoch-media-group": {"theepochtimes.com", "lagranepoca.com", "ntd.com"},
    "france-medias-monde": {"france24.com", "rfi.fr", "mc-doualiya.com"},
    "free-speech-systems": {"infowars.com"},
    "gannett": {"usatoday.com"},
    "gfr-media": {"elnuevodia.com"},
    "grupo-animal": {"animalpolitico.com"},
    "grupo-clarin": {"clarin.com"},
    "grupo-la-republica": {"larepublica.pe"},
    "grupo-multimedios": {"milenio.com"},
    "grupo-reforma": {"reforma.com"},
    "guardian-media-group": {"theguardian.com"},
    "hearst": {"houstonchronicle.com"},
    "herring-networks": {"oann.com"},
    "impremedia": {"laopinion.com"},
    "maldita": {"maldita.es", "factchequeado.com"},
    "mcclatchy": {"miamiherald.com", "elnuevoherald.com"},
    "nash-holdings": {"washingtonpost.com"},
    "new-york-times-company": {"nytimes.com"},
    "news-corp": {"wsj.com"},
    "newsmax-media": {"newsmax.com"},
    "paramount": {"cbsnews.com"},
    "poynter": {"politifact.com"},
    "prisa": {"elpais.com"},
    "snopes-media-group": {"snopes.com"},
    "srmg": {"aawsat.com"},
    "televisa-univision": {"univision.com"},
    "thomson-reuters": {"reuters.com"},
    "tribune-publishing": {"sun-sentinel.com"},
    "unidad-editorial": {"elmundo.es"},
    "united-nations": {"who.int"},
    "us-government": {"bls.gov", "cdc.gov", "census.gov", "fda.gov", "nih.gov", "usgs.gov"},
    "usagm": {"alhurra.com", "rferl.org", "voanews.com", "martinoticias.com"},
    "warner-bros-discovery": {"cnn.com"},
    "wikimedia": {"wikipedia.org"},
}
OWNER_GROUPED_CATEGORIES = frozenset({"state_controlled", "disinformation_network"})


CREDIBILITY_GATE_NOTE_PREFIX = "[Credibility gate]"
_GATE_NOTE_RE = re.compile(r"\s*" + re.escape(CREDIBILITY_GATE_NOTE_PREFIX) + r"[^\n]*")

# Leading labels that only pick a device/format, not a publication
_STRIP_PREFIXES = ("www.", "m.", "amp.")
# Second-level labels under two-letter ccTLDs (co.uk, com.mx, gob.ve, ...) that are not themselves registrable
_CC_SECOND_LEVEL = frozenset({"co", "com", "org", "net", "gov", "gob", "edu", "ac", "mil", "info"})


def normalize_domain(url_or_host) -> str:
    """Bare lowercase host: no scheme, path, port or leading www./m./amp.; other subdomains are kept."""
    value = (url_or_host or "").strip().lower()
    if not value:
        return ""
    if "//" not in value:
        value = "//" + value
    try:
        host = urlsplit(value).hostname or ""
    except ValueError:
        host = value.split("//", 1)[1].split("/", 1)[0].rsplit("@", 1)[-1].split(":", 1)[0]
    host = host.strip(".")
    stripped = True
    while stripped:
        stripped = False
        for prefix in _STRIP_PREFIXES:
            if host.startswith(prefix) and host.count(".") >= 2:
                host = host[len(prefix) :]
                stripped = True
    return host


def registrable_domain(host: str) -> str:
    """Approximate eTLD+1: ``actualidad.rt.com`` -> ``rt.com``, ``news.bbc.co.uk`` -> ``bbc.co.uk``."""
    labels = normalize_domain(host).split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _CC_SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def domain_candidates(host: str) -> list[str]:
    """Lookup keys from most to least specific, stopping at the registrable domain."""
    host = normalize_domain(host)
    if not host:
        return []
    root = registrable_domain(host)
    candidates = [host]
    while candidates[-1] != root and "." in candidates[-1]:
        candidates.append(candidates[-1].split(".", 1)[1])
    return candidates


def owner_is_plausible(domain: str, owner: str, category: str) -> bool:
    """True when ``owner`` is the registrable domain, a known network covering it, or a state/disinfo operator."""
    root = registrable_domain(domain)
    return owner == root or category in OWNER_GROUPED_CATEGORIES or root in KNOWN_NETWORKS.get(owner, ())


@dataclass(frozen=True)
class DomainRating:
    domain: str
    tier: int = DEFAULT_TIER
    category: str = DEFAULT_CATEGORY
    owner: str = ""
    country: str = ""
    matched_domain: str | None = None  # table row that matched, None when the default applied

    @property
    def denylisted(self) -> bool:
        return self.tier == DENYLIST_TIER

    def as_dict(self) -> dict:
        return {"domain": self.domain, "tier": self.tier, "category": self.category}


@dataclass(frozen=True)
class StationProvenance:
    station_code: str | None
    provenance: str = DEFAULT_PROVENANCE
    owner: str = ""
    country: str = ""

    @property
    def state_controlled(self) -> bool:
        return self.provenance == "state_controlled"

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class CorroborationResult:
    satisfied: bool
    independent_sources: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    reason: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


# --- Row validation (shared by the loader, the import script and the CSV tests) ---------------------------------


def _int_tier(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def validate_domain_row(row: dict) -> list[str]:
    """Return the problems with one domains.csv / source_credibility_domains row (empty when valid)."""
    errors = []
    domain = (row.get("domain") or "").strip()
    if not domain:
        errors.append("domain is required")
    elif domain != normalize_domain(domain):
        errors.append(f"domain '{domain}' is not normalized (expected '{normalize_domain(domain)}')")
    tier = _int_tier(row.get("tier"))
    if tier not in VALID_TIERS:
        errors.append(f"tier '{row.get('tier')}' must be one of {list(VALID_TIERS)}")
    category = (row.get("category") or "").strip()
    if category not in VALID_CATEGORIES:
        errors.append(f"category '{category}' must be one of {sorted(VALID_CATEGORIES)}")
    if tier is not None and tier >= UNRELIABLE_TIER and not (row.get("rating_sources") or "").strip():
        errors.append("rating_sources is required for tier 4 (unreliable) and tier 5 (denied) rows")
    return errors


def validate_station_row(row: dict) -> list[str]:
    errors = []
    if not (row.get("station_code") or "").strip():
        errors.append("station_code is required")
    provenance = (row.get("provenance") or "").strip()
    if provenance not in VALID_PROVENANCES:
        errors.append(f"provenance '{provenance}' must be one of {sorted(VALID_PROVENANCES)}")
    return errors


def read_csv_rows(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as handle:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(handle)]


def _build_domain_index(rows) -> dict[str, DomainRating]:
    index = {}
    for row in rows:
        errors = validate_domain_row(row)
        if errors:
            print(f"[source_credibility] skipping invalid domain row {row.get('domain')!r}: {errors}")
            continue
        domain = normalize_domain(row["domain"])
        index[domain] = DomainRating(
            domain=domain,
            tier=int(row["tier"]),
            category=row["category"].strip(),
            owner=(row.get("owner") or "").strip() or registrable_domain(domain),
            country=(row.get("country") or "").strip(),
            matched_domain=domain,
        )
    return index


def _build_station_index(rows) -> dict[str, StationProvenance]:
    index = {}
    for row in rows:
        errors = validate_station_row(row)
        if errors:
            print(f"[source_credibility] skipping invalid station row {row!r}: {errors}")
            continue
        code = row["station_code"].strip().upper()
        index[code] = StationProvenance(
            station_code=code,
            provenance=row["provenance"].strip(),
            owner=(row.get("owner") or "").strip(),
            country=(row.get("country") or "").strip(),
        )
    return index


# --- Lookup with Supabase-first / CSV-fallback loading -----------------------------------------------------------


class SourceCredibility:
    """Cached domain-tier and station-provenance lookup.

    ``load()`` reads the Supabase tables through ``supabase_client`` when one is configured and falls back to the
    CSV files when it is missing or the query fails, so tests and local runs need no network.
    """

    def __init__(
        self,
        supabase_client=None,
        domains_csv: str = DOMAINS_CSV,
        stations_csv: str = STATIONS_CSV,
        ttl_seconds: float = CREDIBILITY_CACHE_TTL_SECONDS,
    ):
        self.supabase_client = supabase_client
        self.domains_csv = domains_csv
        self.stations_csv = stations_csv
        self.ttl_seconds = ttl_seconds
        self.source: str | None = None  # "supabase" or "csv" after a load
        self._domains: dict[str, DomainRating] = {}
        self._stations: dict[str, StationProvenance] = {}
        self._loaded_at: float | None = None
        self._lock = threading.Lock()

    def load(self) -> "SourceCredibility":
        domain_rows = station_rows = None
        if self.supabase_client is not None:
            try:
                domain_rows = list(self.supabase_client.get_source_credibility_domains())
                station_rows = list(self.supabase_client.get_source_provenance())
                self.source = "supabase"
            except Exception as e:  # any client/transport error: fall back, never block the pipeline
                print(f"[source_credibility] Supabase load failed, falling back to CSV: {type(e).__name__}: {e}")
                domain_rows = station_rows = None
        if domain_rows is None:
            try:
                domain_rows = read_csv_rows(self.domains_csv)
                station_rows = read_csv_rows(self.stations_csv)
                self.source = "csv"
            except OSError as e:  # unreadable seed: run with defaults (tier 3 / unknown) rather than stop the pipeline
                print(f"[source_credibility] CSV load failed, using defaults only: {type(e).__name__}: {e}")
                domain_rows, station_rows = [], []
                self.source = "none"
        with self._lock:
            self._domains = _build_domain_index(domain_rows)
            self._stations = _build_station_index(station_rows or [])
            self._loaded_at = time.monotonic()
        return self

    def reload(self) -> "SourceCredibility":
        return self.load()

    def configure(self, supabase_client) -> "SourceCredibility":
        """Attach a Supabase client (flows call this once) and reload from the tables."""
        self.supabase_client = supabase_client
        return self.load()

    def _ensure_loaded(self):
        if self._loaded_at is None or time.monotonic() - self._loaded_at > self.ttl_seconds:
            self.load()

    def tier_for(self, url_or_host) -> DomainRating:
        """Rating for a URL or host, falling back through parent domains; unknown hosts get the default tier (3)."""
        self._ensure_loaded()
        host = normalize_domain(url_or_host)
        for candidate in domain_candidates(host):
            rating = self._domains.get(candidate)
            if rating is not None:
                return DomainRating(
                    domain=host,
                    tier=rating.tier,
                    category=rating.category,
                    owner=rating.owner,
                    country=rating.country,
                    matched_domain=candidate,
                )
        return DomainRating(domain=host, owner=registrable_domain(host) if host else "")

    def provenance_for(self, station_code) -> StationProvenance:
        self._ensure_loaded()
        code = (station_code or "").strip().upper() or None
        return self._stations.get(code) or StationProvenance(station_code=code)

    def domains(self) -> dict[str, DomainRating]:
        self._ensure_loaded()
        return dict(self._domains)


_singleton: SourceCredibility | None = None
_singleton_lock = threading.Lock()


def get_source_credibility() -> SourceCredibility:
    """Process-wide instance. CSV-backed until a flow calls ``configure_source_credibility(client)``."""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = SourceCredibility()
        return _singleton


def configure_source_credibility(supabase_client) -> SourceCredibility:
    return get_source_credibility().configure(supabase_client)


# --- Dual phenomenology --------------------------------------------------------------------------------------------


def independent(a: DomainRating, b: DomainRating) -> bool:
    """Different owner and different registrable domain; same-country state outlets are one voice."""
    if a.owner and a.owner == b.owner:
        return False
    if registrable_domain(a.domain) == registrable_domain(b.domain):
        return False
    if a.category == "state_controlled" and b.category == "state_controlled" and a.country and a.country == b.country:
        return False
    return True


def contradicting_results(verification_evidence: dict | None) -> list[dict]:
    """Search results marked ``contradicts_claim`` that carry a URL (same fields PR #80's gate reads)."""
    items = []
    if not isinstance(verification_evidence, dict):
        return items
    for search in verification_evidence.get("searches_performed") or []:
        if not isinstance(search, dict):
            continue
        for result in search.get("results") or []:
            if not isinstance(result, dict):
                continue
            url = result.get("url")
            if result.get("relevance_to_claim") == "contradicts_claim" and isinstance(url, str) and url.strip():
                items.append(result)
    return items


def rate_evidence(evidence: list[dict], credibility: SourceCredibility | None = None) -> list[DomainRating]:
    """One rating per distinct domain among the evidence items, in first-seen order (items without a URL dropped)."""
    credibility = credibility or get_source_credibility()
    ratings: dict[str, DomainRating] = {}
    for item in evidence or []:
        rating = credibility.tier_for((item or {}).get("url"))
        if rating.domain:
            ratings.setdefault(rating.domain, rating)
    return list(ratings.values())


def evaluate_corroboration(evidence: list[dict], credibility: SourceCredibility | None = None) -> CorroborationResult:
    """Two independent tier<=2 contradicting sources, or tier-1 plus an independent fact-checker, satisfy the rule."""
    return corroboration_from_ratings(rate_evidence(evidence, credibility))


def corroboration_from_ratings(ratings: list[DomainRating]) -> CorroborationResult:
    excluded = [r.domain for r in ratings if r.denylisted]
    usable = [r for r in ratings if not r.denylisted]
    strong = [r for r in usable if r.tier <= CORROBORATING_MAX_TIER]
    for a, b in combinations(strong, 2):
        if independent(a, b):
            return CorroborationResult(
                True, [a.domain, b.domain], excluded, f"two independent tier<={CORROBORATING_MAX_TIER} sources"
            )
    for a in (r for r in usable if r.tier == 1):
        for b in (r for r in usable if r.category == "fact_checker" and r is not a):
            if independent(a, b):
                return CorroborationResult(True, [a.domain, b.domain], excluded, "tier-1 source plus fact-checker")

    if not usable:
        reason = "no usable contradicting source" + (f" (denylisted: {', '.join(excluded)})" if excluded else "")
    elif len(usable) == 1:
        reason = f"only one contradicting source ({usable[0].domain}, tier {usable[0].tier})"
    elif len(strong) < 2:
        weak = ", ".join(f"{r.domain} (tier {r.tier})" for r in usable if r.tier > CORROBORATING_MAX_TIER)
        reason = f"fewer than two contradicting sources of tier<={CORROBORATING_MAX_TIER}; below tier 2: {weak}"
    else:
        owners = sorted({r.owner for r in strong})
        reason = f"contradicting sources are not mutually independent (owner/network: {', '.join(owners)})"
    return CorroborationResult(False, [], excluded, reason)


def _without_gate_note(text) -> str:
    return _GATE_NOTE_RE.sub("", text if isinstance(text, str) else "").strip()


def apply_credibility_gate(
    analysis: dict,
    station_code: str | None,
    verification_evidence: dict | None = None,
    credibility: SourceCredibility | None = None,
) -> dict:
    """Cap a falsity verdict that lacks independent corroboration; always record the gate.

    Pure like ``apply_evidence_caps``: returns a deep copy with ``credibility_gate`` set to
    ``{station_provenance, evidence_tiers, corroboration, capped, ...}``. Scores are only ever lowered (to
    ``EVIDENCE_CAP_MAX_SCORE``) and station provenance alone never changes a score.
    """
    # Imported here: stage_3/__init__ imports the executor, which imports this module
    from processing_pipeline.stage_3.models import EVIDENCE_CAP_MAX_SCORE, asserts_falsity

    credibility = credibility or get_source_credibility()
    result = copy.deepcopy(analysis)
    if verification_evidence is None:
        verification_evidence = result.get("verification_evidence")

    provenance = credibility.provenance_for(station_code)
    ratings = rate_evidence(contradicting_results(verification_evidence), credibility)
    corroboration = corroboration_from_ratings(ratings)

    explanation = result.get("explanation")
    if isinstance(explanation, dict):
        for language in ("english", "spanish"):
            if language in explanation:
                explanation[language] = _without_gate_note(explanation[language])

    gate = {
        "station_provenance": provenance.as_dict(),
        "evidence_tiers": [r.as_dict() for r in ratings],
        "corroboration": corroboration.as_dict(),
        "capped": False,
    }
    confidence_scores = result.get("confidence_scores")
    if isinstance(confidence_scores, dict) and asserts_falsity(result) and not corroboration.satisfied:
        original_overall = confidence_scores.get("overall")
        if isinstance(original_overall, (int, float)):
            confidence_scores["overall"] = min(original_overall, EVIDENCE_CAP_MAX_SCORE)
        for category in confidence_scores.get("categories") or []:
            if isinstance(category, dict) and isinstance(category.get("score"), (int, float)):
                category["score"] = min(category["score"], EVIDENCE_CAP_MAX_SCORE)
        note_en = (
            f"{CREDIBILITY_GATE_NOTE_PREFIX} Confidence capped at {EVIDENCE_CAP_MAX_SCORE} by the pipeline: a "
            f"fabrication/falsity verdict needs two independent contradicting sources of tier 1-2 (different owners) "
            f"or a tier-1 source plus a fact-checker; {corroboration.reason}."
        )
        note_es = (
            f"{CREDIBILITY_GATE_NOTE_PREFIX} La confianza fue limitada a {EVIDENCE_CAP_MAX_SCORE} por el sistema: un "
            f"veredicto de fabricacion/falsedad requiere dos fuentes independientes de nivel 1-2 que lo contradigan "
            f"(distintos propietarios) o una fuente de nivel 1 mas un verificador; {corroboration.reason}."
        )
        if isinstance(explanation, dict):
            explanation["english"] = f"{explanation.get('english') or ''}\n\n{note_en}".strip()
            explanation["spanish"] = f"{explanation.get('spanish') or ''}\n\n{note_es}".strip()
        gate.update(capped=True, cap=EVIDENCE_CAP_MAX_SCORE, original_overall=original_overall, note=note_en)

    result["credibility_gate"] = gate
    return result

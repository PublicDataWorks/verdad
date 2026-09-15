from unittest.mock import Mock

import pytest

from processing_pipeline import source_credibility as sc
from processing_pipeline.source_credibility import (
    DEFAULT_TIER,
    DENYLIST_TIER,
    DomainRating,
    SourceCredibility,
    domain_candidates,
    evaluate_corroboration,
    independent,
    normalize_domain,
    read_csv_rows,
    registrable_domain,
    validate_domain_row,
    validate_station_row,
)


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


@pytest.fixture
def credibility(tmp_path):
    domains = _write(
        tmp_path,
        "domains.csv",
        "domain,tier,category,country,languages,owner,rating_sources,notes\n"
        "apnews.com,1,wire,US,en,associated-press,WikipediaRSP:generally-reliable,\n"
        "reuters.com,1,wire,GB,en,thomson-reuters,WikipediaRSP:generally-reliable,\n"
        "factuel.afp.com,1,fact_checker,FR,fr,afp,IFCN:signatory,\n"
        "afp.com,1,wire,FR,fr,afp,IFCN:signatory,\n"
        "politifact.com,1,fact_checker,US,en,poynter,IFCN:signatory,\n"
        "chequeado.com,3,fact_checker,AR,es,chequeado,IFCN:signatory,regional-tier fact-checker for the test\n"
        "cdc.gov,1,official,US,en,us-government,Official:government-agency,\n"
        "fda.gov,1,official,US,en,us-government,Official:government-agency,\n"
        "miamiherald.com,2,broadsheet,US,en,mcclatchy,,\n"
        "elnuevoherald.com,2,broadsheet,US,es,mcclatchy,,\n"
        "nytimes.com,2,broadsheet,US,en,nyt,,\n"
        "elnuevodia.com,3,regional,PR,es,gfr-media,,\n"
        "rt.com,5,state_controlled,RU,en,ano-tv-novosti,EU:Reg2022/350,\n"
        "actualidad.rt.com,5,state_controlled,RU,es,ano-tv-novosti,EU:Reg2022/350,\n"
        "ria.ru,5,state_controlled,RU,ru,rossiya-segodnya,Ownership:state,\n"
        "bbc.co.uk,1,public_broadcaster,GB,en,bbc,WikipediaRSP:generally-reliable,\n"
        "vtv.gob.ve,5,state_controlled,VE,es,venezuela-state,Ownership:state,\n"
        "denied.gov,5,state_controlled,XX,en,xx-state,Ownership:state,a .gov row at tier 5 must beat the heuristic\n"
        "tabloid.example,4,other,GB,en,tabloid,WikipediaRSP:deprecated,\n"
        "uncited.example,4,other,,,,,tier 4 without a citation must be skipped\n"
        "badrow.example,9,wire,,,,,invalid tier must be skipped\n",
    )
    stations = _write(
        tmp_path,
        "stations.csv",
        "station_code,provenance,owner,country,rating_sources,notes\n"
        "SPMN,state_controlled,rossiya-segodnya,RU,EU:Reg2022/350,\n"
        "MCD,state_funded_independent,france-medias-monde,FR,,\n",
    )
    return SourceCredibility(domains_csv=domains, stations_csv=stations)


class TestNormalizeDomain:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("https://www.RT.com/news/1", "rt.com"),
            ("http://m.rt.com:8080/x?y=1", "rt.com"),
            ("amp.actualidad.rt.com", "actualidad.rt.com"),
            ("www.m.example.com", "example.com"),
            ("https://user:pw@news.bbc.co.uk./path", "news.bbc.co.uk"),
            ("reuters.com/article", "reuters.com"),
            ("  APNEWS.COM  ", "apnews.com"),
            ("", ""),
            (None, ""),
            ("https://www.com", "www.com"),
        ],
    )
    def test_normalizes(self, raw, expected):
        assert normalize_domain(raw) == expected

    @pytest.mark.parametrize(
        "host, expected",
        [
            ("actualidad.rt.com", "rt.com"),
            ("news.bbc.co.uk", "bbc.co.uk"),
            ("mundo.sputniknews.com", "sputniknews.com"),
            ("vtv.gob.ve", "vtv.gob.ve"),
            ("rt.com", "rt.com"),
            ("https://en.m.wikipedia.org/wiki/x", "wikipedia.org"),
        ],
    )
    def test_registrable_domain(self, host, expected):
        assert registrable_domain(host) == expected

    def test_candidates_walk_up_to_registrable_domain(self):
        assert domain_candidates("https://a.b.rt.com/x") == ["a.b.rt.com", "b.rt.com", "rt.com"]
        assert domain_candidates("news.bbc.co.uk") == ["news.bbc.co.uk", "bbc.co.uk"]
        assert domain_candidates("") == []


class TestLookup:
    def test_exact_and_parent_fallback(self, credibility):
        exact = credibility.tier_for("https://actualidad.rt.com/x")
        assert (exact.tier, exact.matched_domain) == (DENYLIST_TIER, "actualidad.rt.com")
        parent = credibility.tier_for("https://arabic.rt.com/x")
        assert (parent.tier, parent.matched_domain, parent.owner) == (DENYLIST_TIER, "rt.com", "ano-tv-novosti")
        assert credibility.tier_for("https://news.bbc.co.uk/1").matched_domain == "bbc.co.uk"

    def test_subdomain_row_beats_parent_row(self, credibility):
        assert credibility.tier_for("https://factuel.afp.com/x").category == "fact_checker"
        assert credibility.tier_for("https://afp.com/x").category == "wire"

    def test_unknown_defaults_to_tier_3_with_registrable_owner(self, credibility):
        rating = credibility.tier_for("https://www.unknown-blog.example.org/post")
        assert rating == DomainRating(domain="unknown-blog.example.org", tier=DEFAULT_TIER, owner="example.org")
        assert rating.matched_domain is None and not rating.denylisted

    def test_blank_url(self, credibility):
        assert DEFAULT_TIER == 3
        assert credibility.tier_for("").tier == DEFAULT_TIER
        assert credibility.tier_for(None).domain == ""

    def test_invalid_rows_are_skipped(self, credibility):
        assert "badrow.example" not in credibility.domains()
        assert "uncited.example" not in credibility.domains()

    def test_station_provenance(self, credibility):
        assert credibility.provenance_for("spmn").provenance == "state_controlled"
        assert credibility.provenance_for("SPMN").state_controlled
        assert credibility.provenance_for("MCD").provenance == "state_funded_independent"
        unknown = credibility.provenance_for("WLEL")
        assert (unknown.provenance, unknown.state_controlled, unknown.station_code) == ("unknown", False, "WLEL")
        assert credibility.provenance_for(None).provenance == "unknown"
        assert credibility.source == "csv"

    def test_supabase_rows_preferred_and_reload(self, credibility):
        client = Mock()
        client.get_source_credibility_domains.return_value = [
            {"domain": "example.com", "tier": 2, "category": "broadsheet", "owner": "ex", "country": "US"}
        ]
        client.get_source_provenance.return_value = [{"station_code": "WLEL", "provenance": "commercial"}]
        credibility.configure(client)
        assert credibility.source == "supabase"
        assert credibility.tier_for("https://example.com/a").tier == 2
        assert credibility.tier_for("https://rt.com/a").tier == DEFAULT_TIER  # CSV rows are not merged in
        assert credibility.provenance_for("WLEL").provenance == "commercial"

        client.get_source_credibility_domains.side_effect = RuntimeError("PGRST205 table missing")
        credibility.reload()
        assert credibility.source == "csv"
        assert credibility.tier_for("https://rt.com/a").tier == DENYLIST_TIER

    def test_mock_client_that_returns_garbage_falls_back(self, credibility):
        credibility.configure(Mock())  # a bare Mock is not iterable
        assert credibility.source == "csv"

    def test_missing_csv_degrades_to_defaults(self, tmp_path):
        broken = SourceCredibility(domains_csv=str(tmp_path / "nope.csv"), stations_csv=str(tmp_path / "nope2.csv"))
        assert broken.tier_for("https://rt.com/x").tier == DEFAULT_TIER
        assert broken.provenance_for("SPMN").provenance == "unknown"
        assert broken.source == "none"

    def test_ttl_triggers_reload(self, credibility, monkeypatch):
        credibility.ttl_seconds = 0.01
        credibility.load()
        loaded_at = credibility._loaded_at
        monkeypatch.setattr(sc.time, "monotonic", lambda: loaded_at + 1)
        credibility.tier_for("https://rt.com")
        assert credibility._loaded_at == loaded_at + 1

    def test_singleton_is_csv_backed_by_default(self):
        instance = sc.get_source_credibility()
        assert instance is sc.get_source_credibility()
        assert instance.tier_for("https://www.reuters.com/x").tier == 1


class TestOfficialHeuristic:
    """Unlisted government / intergovernmental hosts are tier-1 official; lookalikes and explicit rows are not."""

    @pytest.mark.parametrize(
        "url, expected_domain, expected_owner",
        [
            ("https://www.state.gov/x", "state.gov", "state.gov"),
            ("https://www.eia.gov/outlooks/x", "eia.gov", "eia.gov"),
            ("https://www.michigan.gov/sos/elections", "michigan.gov", "michigan.gov"),
            ("https://www.army.mil/x", "army.mil", "army.mil"),
            ("https://www.nato.int/x", "nato.int", "nato.int"),
            ("https://www.km.gov.lv/lv/x", "km.gov.lv", "km.gov.lv"),
            ("https://www.gob.mx/salud", "gob.mx", "gob.mx"),
            ("https://coronavirus.gob.mx/x", "coronavirus.gob.mx", "coronavirus.gob.mx"),
            ("https://www.service.gov.uk/x", "service.gov.uk", "service.gov.uk"),
            ("https://ec.europa.eu/commission/x", "ec.europa.eu", "europa.eu"),
            ("https://www.economie.gouv.fr/x", "economie.gouv.fr", "gouv.fr"),
            ("https://www.canada.gc.ca/x", "canada.gc.ca", "gc.ca"),
            ("https://www.mofa.go.jp/x", "mofa.go.jp", "go.jp"),
            ("https://www.korea.go.kr/x", "korea.go.kr", "go.kr"),
        ],
    )
    def test_official_hosts_are_tier_1(self, credibility, url, expected_domain, expected_owner):
        rating = credibility.tier_for(url)
        assert (rating.domain, rating.tier, rating.category) == (expected_domain, 1, "official")
        assert (rating.owner, rating.source) == (expected_owner, sc.OFFICIAL_HEURISTIC_SOURCE)
        assert rating.matched_domain is None and not rating.denylisted
        assert rating.as_dict() == {
            "domain": expected_domain,
            "tier": 1,
            "category": "official",
            "source": "heuristic:official_tld",
        }

    @pytest.mark.parametrize(
        "url",
        [
            "https://gov.example.com/x",  # 'gov' label but a generic TLD
            "https://www.go.com/x",  # Disney, not go.<cc>
            "https://mygov.com/x",
            "https://gob.mx.evil.net/x",
            "https://government.org/x",
            "https://europa.eu.example.com/x",
            "https://unknown-blog.example.org/x",
        ],
    )
    def test_lookalikes_keep_the_default_tier(self, credibility, url):
        rating = credibility.tier_for(url)
        assert (rating.tier, rating.category, rating.source) == (DEFAULT_TIER, "other", "")
        assert "source" not in rating.as_dict()

    def test_explicit_row_beats_heuristic(self, credibility):
        denied = credibility.tier_for("https://www.vtv.gob.ve/x")
        assert (denied.tier, denied.matched_domain, denied.source) == (DENYLIST_TIER, "vtv.gob.ve", "")
        assert credibility.tier_for("https://news.denied.gov/x").tier == DENYLIST_TIER
        listed = credibility.tier_for("https://www.cdc.gov/x")
        assert (listed.tier, listed.owner, listed.matched_domain, listed.source) == (1, "us-government", "cdc.gov", "")

    def test_official_tier_for_edge_inputs(self):
        assert sc.official_tier_for("") is None
        assert sc.official_tier_for("gov") is None
        assert sc.official_tier_for(".gov") is None
        assert sc.official_tier_for("https://km.gov.lv/x").domain == "km.gov.lv"
        assert sc.official_tier_for("who.int").owner == "who.int"


class TestIndependence:
    def _r(self, domain, owner, tier=1, category="wire", country=""):
        return DomainRating(domain=domain, tier=tier, category=category, owner=owner, country=country)

    def test_different_owner_and_domain(self):
        assert independent(self._r("apnews.com", "ap"), self._r("reuters.com", "reuters"))

    def test_same_owner(self):
        assert not independent(self._r("miamiherald.com", "mcclatchy"), self._r("elnuevoherald.com", "mcclatchy"))

    def test_same_registrable_domain(self):
        assert not independent(self._r("factuel.afp.com", "afp-fact"), self._r("afp.com", "afp"))

    def test_same_country_is_independent_unless_both_state_controlled(self):
        assert independent(self._r("nytimes.com", "nyt", country="US"), self._r("wsj.com", "newscorp", country="US"))
        rt = self._r("rt.com", "tv-novosti", 5, "state_controlled", "RU")
        ria = self._r("ria.ru", "rossiya-segodnya", 5, "state_controlled", "RU")
        assert not independent(rt, ria)
        cgtn = self._r("cgtn.com", "cmg", 5, "state_controlled", "CN")
        assert independent(rt, cgtn)


def _items(*urls):
    return [{"url": u, "relevance_to_claim": "contradicts_claim"} for u in urls]


class TestCorroboration:
    def test_two_tier1_same_owner_not_satisfied(self, credibility):
        result = evaluate_corroboration(_items("https://cdc.gov/a", "https://fda.gov/b"), credibility)
        assert not result.satisfied and "us-government" in result.reason

    def test_tier1_plus_tier2_different_owners_satisfied(self, credibility):
        result = evaluate_corroboration(_items("https://apnews.com/a", "https://nytimes.com/b"), credibility)
        assert result.satisfied and sorted(result.independent_sources) == ["apnews.com", "nytimes.com"]

    def test_unlisted_official_source_plus_tier2_satisfied(self, credibility):
        # The 2026-09 evaluation lost the Michigan voting-dates true positive to an unlisted .gov at tier 3
        result = evaluate_corroboration(
            _items("https://www.michigan.gov/sos/elections", "https://nytimes.com/b"), credibility
        )
        assert result.satisfied and sorted(result.independent_sources) == ["michigan.gov", "nytimes.com"]
        assert result.reason == "two independent tier<=2 sources"

    def test_two_unlisted_official_sources_of_different_governments_satisfied(self, credibility):
        result = evaluate_corroboration(_items("https://www.km.gov.lv/x", "https://www.state.gov/y"), credibility)
        assert result.satisfied and sorted(result.independent_sources) == ["km.gov.lv", "state.gov"]

    def test_tier1_plus_fact_checker_satisfied(self, credibility):
        # chequeado.com is tier 3 in the fixture, so only the fact-checker rule can satisfy this pair
        result = evaluate_corroboration(_items("https://reuters.com/a", "https://chequeado.com/b"), credibility)
        assert result.satisfied and result.reason == "tier-1 source plus fact-checker"

    def test_tier5_excluded(self, credibility):
        result = evaluate_corroboration(
            _items("https://apnews.com/a", "https://rt.com/b", "https://actualidad.rt.com/c"), credibility
        )
        assert not result.satisfied
        assert result.excluded == ["rt.com", "actualidad.rt.com"]
        assert "only one contradicting source (apnews.com, tier 1)" == result.reason

    def test_one_source_not_satisfied(self, credibility):
        result = evaluate_corroboration(_items("https://apnews.com/a"), credibility)
        assert not result.satisfied and result.independent_sources == []

    def test_two_tier2_different_owners_satisfied(self, credibility):
        result = evaluate_corroboration(_items("https://miamiherald.com/a", "https://nytimes.com/b"), credibility)
        assert result.satisfied

    def test_two_unknown_sources_not_satisfied(self, credibility):
        result = evaluate_corroboration(_items("https://blog-a.example/a", "https://blog-b.example/b"), credibility)
        assert not result.satisfied and "below tier 2" in result.reason

    def test_unreliable_tier4_never_corroborates_but_is_not_excluded(self, credibility):
        result = evaluate_corroboration(_items("https://apnews.com/a", "https://tabloid.example/b"), credibility)
        assert not result.satisfied and result.excluded == [] and "tabloid.example (tier 4)" in result.reason

    def test_no_evidence(self, credibility):
        result = evaluate_corroboration([], credibility)
        assert not result.satisfied and result.reason == "no usable contradicting source"
        only_denylisted = evaluate_corroboration(_items("https://ria.ru/x"), credibility)
        assert only_denylisted.reason == "no usable contradicting source (denylisted: ria.ru)"

    def test_same_domain_twice_counts_once(self, credibility):
        result = evaluate_corroboration(_items("https://apnews.com/a", "https://apnews.com/b"), credibility)
        assert not result.satisfied and "only one" in result.reason

    def test_items_without_url_are_ignored(self, credibility):
        assert not evaluate_corroboration([{"url": ""}, {}, None], credibility).satisfied


class TestSeedCsvValidity:
    """The committed seed files must load cleanly."""

    def test_domains_csv(self):
        rows = read_csv_rows(sc.DOMAINS_CSV)
        assert rows, "domains.csv is empty"
        assert list(rows[0].keys()) == list(sc.DOMAIN_COLUMNS)
        problems = [(r["domain"], validate_domain_row(r)) for r in rows if validate_domain_row(r)]
        assert problems == []
        domains = [r["domain"] for r in rows]
        assert len(domains) == len(set(domains)), "duplicate domains in domains.csv"
        assert all(r["owner"] for r in rows), "every seed row should carry an owner key"
        tiers = {int(r["tier"]) for r in rows}
        assert tiers == {1, 2, 3, 4, 5}
        assert all(r["rating_sources"] for r in rows if int(r["tier"]) >= 4)

    def test_owner_keys_are_registrable_domain_or_known_network(self):
        rows = read_csv_rows(sc.DOMAINS_CSV)
        offenders = [
            (r["domain"], r["owner"]) for r in rows if not sc.owner_is_plausible(r["domain"], r["owner"], r["category"])
        ]
        assert offenders == []
        assert not sc.owner_is_plausible("breitbart.com", "rossiya-segodnya", "hyperpartisan")
        assert sc.owner_is_plausible("elnuevoherald.com", "mcclatchy", "broadsheet")
        assert sc.owner_is_plausible("esrt.online", "rossiya-segodnya", "state_controlled")

    def test_stations_csv(self):
        rows = read_csv_rows(sc.STATIONS_CSV)
        assert list(rows[0].keys()) == list(sc.STATION_COLUMNS)
        assert all(validate_station_row(r) == [] for r in rows)
        by_code = {r["station_code"]: r for r in rows}
        assert by_code["SPMN"]["provenance"] == "state_controlled"
        assert by_code["WZHF"]["provenance"] == "state_controlled"
        assert by_code["MCD"]["provenance"] == "state_funded_independent"

    def test_seed_answers_the_ver_360_cases(self):
        seeded = SourceCredibility()
        assert seeded.tier_for("https://mundo.sputniknews.com/x").denylisted
        assert seeded.tier_for("https://actualidad.rt.com/x").denylisted
        assert seeded.tier_for("https://www.reuters.com/x").tier == 1
        assert seeded.tier_for("https://maldita.es/x").category == "fact_checker"
        assert not independent(seeded.tier_for("https://ria.ru/x"), seeded.tier_for("https://rt.com/x"))
        # Pravda network: language subdomains fall back to the news-pravda.com row; pravda-xx.com need their own rows
        pravda = seeded.tier_for("https://es.news-pravda.com/world/2026/09/15/x.html")
        assert (pravda.tier, pravda.matched_domain, pravda.owner) == (5, "news-pravda.com", "pravda-network")
        assert seeded.tier_for("https://pravda-es.com/x").owner == "pravda-network"
        assert seeded.tier_for("https://breitbart.com/x").tier == 4  # unreliable, not denied

    def test_seed_answers_the_evaluation_report_gaps(self):
        """Sources the 2026-09 evaluation left at tier 3 and thereby capped correct falsity verdicts."""
        seeded = SourceCredibility()
        lsm = seeded.tier_for("https://www.lsm.lv/raksts/x")
        assert (lsm.tier, lsm.category, lsm.owner, lsm.matched_domain) == (1, "public_broadcaster", "lsm.lv", "lsm.lv")
        assert seeded.tier_for("https://eng.lsm.lv/article/x").tier == 1
        jstor = seeded.tier_for("https://www.jstor.org/stable/1")
        assert (jstor.tier, jstor.category, jstor.owner) == (2, "other", "ithaka")
        oec = seeded.tier_for("https://oec.world/en/profile/country/lva")
        assert (oec.tier, oec.category, oec.owner) == (2, "other", "oec.world")
        for url in ("https://www.state.gov/x", "https://www.eia.gov/x", "https://www.km.gov.lv/x"):
            rating = seeded.tier_for(url)
            assert (rating.tier, rating.category, rating.source) == (1, "official", sc.OFFICIAL_HEURISTIC_SOURCE), url
        assert evaluate_corroboration(_items("https://www.eia.gov/x", "https://oec.world/y"), seeded).satisfied
        assert evaluate_corroboration(_items("https://www.km.gov.lv/x", "https://www.lsm.lv/y"), seeded).satisfied
        # Listed federal agencies still share one owner key and so do not corroborate each other
        assert not evaluate_corroboration(_items("https://cdc.gov/a", "https://fda.gov/b"), seeded).satisfied

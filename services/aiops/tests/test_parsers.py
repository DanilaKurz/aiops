"""Tests for ParseResult dataclass and LogParser ABC."""

from dataclasses import asdict

import pytest

from parsers.base import LogParser, ParseResult


class TestParseResult:
    def test_create_parse_result(self):
        r = ParseResult(
            template="GC (Allocation Failure) <*>ms",
            cluster_id=1,
            confidence=0.95,
            parser_name="drain3",
            params={"duration": "15234"},
            metadata={},
        )
        assert r.template == "GC (Allocation Failure) <*>ms"
        assert r.confidence == 0.95
        assert r.cluster_id == 1
        assert r.parser_name == "drain3"
        assert r.params == {"duration": "15234"}
        assert r.metadata == {}

    def test_parse_result_serializable(self):
        r = ParseResult(
            template="test <*>",
            cluster_id=1,
            confidence=0.8,
            parser_name="test",
            params={},
            metadata={"extra": 42},
        )
        d = asdict(r)
        assert d["template"] == "test <*>"
        assert d["metadata"]["extra"] == 42
        assert isinstance(d, dict)

    def test_parse_result_default_metadata(self):
        r = ParseResult(template="t", cluster_id=0, confidence=0.0, parser_name="x")
        assert r.params == {}
        assert r.metadata == {}


class TestLogParserABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            LogParser()  # type: ignore[abstract]

    def test_concrete_parser_must_implement_parse(self):
        """A subclass that only implements reset() but not parse() cannot be instantiated."""

        class IncompleteParser(LogParser):
            name = "incomplete"
            requires_llm = False
            version = "0.0.1"

            def reset(self) -> None:
                pass

        with pytest.raises(TypeError):
            IncompleteParser()

    def test_concrete_parser_works(self):
        """A fully implemented concrete parser can be instantiated and used."""

        class DummyParser(LogParser):
            name = "dummy"
            requires_llm = False
            version = "0.1.0"

            def parse(self, log_line: str) -> ParseResult:
                return ParseResult(
                    template=log_line,
                    cluster_id=0,
                    confidence=1.0,
                    parser_name=self.name,
                )

            def reset(self) -> None:
                pass

        parser = DummyParser()
        result = parser.parse("hello world")
        assert isinstance(result, ParseResult)
        assert result.template == "hello world"
        assert result.parser_name == "dummy"
        assert result.confidence == 1.0

    def test_parse_batch_default_loops(self):
        """The default parse_batch implementation loops over parse()."""

        class CountingParser(LogParser):
            name = "counter"
            requires_llm = False
            version = "0.1.0"

            def __init__(self):
                self._call_count = 0

            def parse(self, log_line: str) -> ParseResult:
                self._call_count += 1
                return ParseResult(
                    template=f"T{self._call_count}",
                    cluster_id=self._call_count,
                    confidence=0.5,
                    parser_name=self.name,
                )

            def reset(self) -> None:
                self._call_count = 0

        parser = CountingParser()
        lines = ["line1", "line2", "line3"]
        results = parser.parse_batch(lines)

        assert len(results) == 3
        assert results[0].template == "T1"
        assert results[1].template == "T2"
        assert results[2].template == "T3"
        assert parser._call_count == 3


# ---------------------------------------------------------------------------
# Drain3Parser tests
# ---------------------------------------------------------------------------
from parsers.drain_parser import Drain3Parser


class TestDrain3Parser:
    def test_is_log_parser(self):
        p = Drain3Parser()
        assert isinstance(p, LogParser)
        assert p.name == "drain3"
        assert p.requires_llm is False

    def test_parse_single_line(self):
        p = Drain3Parser()
        result = p.parse("[GC (Allocation Failure) 15234ms]")
        assert isinstance(result, ParseResult)
        assert result.parser_name == "drain3"
        assert result.cluster_id >= 0
        assert 0.0 <= result.confidence <= 1.0

    def test_parse_batch(self):
        p = Drain3Parser()
        lines = [
            "[GC (Allocation Failure) 15234ms]",
            "[GC (Allocation Failure) 8921ms]",
            "Connection established to 10.0.0.1:6379",
        ]
        results = p.parse_batch(lines)
        assert len(results) == 3
        assert all(isinstance(r, ParseResult) for r in results)
        assert results[0].cluster_id == results[1].cluster_id

    def test_reset_clears_state(self):
        p = Drain3Parser()
        p.parse("[GC (Allocation Failure) 15234ms]")
        assert len(p.get_clusters()) > 0
        p.reset()
        assert len(p.get_clusters()) == 0


# ---------------------------------------------------------------------------
# LogLSHDParser tests
# ---------------------------------------------------------------------------
from parsers.loglshd_parser import LogLSHDParser


class TestLogLSHDParser:
    def test_is_log_parser(self):
        p = LogLSHDParser()
        assert isinstance(p, LogParser)
        assert p.name == "loglshd"
        assert p.requires_llm is False

    def test_parse_single_line(self):
        p = LogLSHDParser()
        result = p.parse("[GC (Allocation Failure) 15234ms]")
        assert isinstance(result, ParseResult)
        assert result.parser_name == "loglshd"
        assert result.cluster_id >= 0
        assert 0.0 <= result.confidence <= 1.0

    def test_parse_batch(self):
        p = LogLSHDParser()
        lines = [
            "[GC (Allocation Failure) 15234ms]",
            "[GC (Allocation Failure) 8921ms]",
            "Connection established to 10.0.0.1:6379",
            "Connection established to 10.0.0.2:6379",
        ]
        results = p.parse_batch(lines)
        assert len(results) == 4
        assert all(isinstance(r, ParseResult) for r in results)
        assert all(r.parser_name == "loglshd" for r in results)

    def test_parse_batch_empty(self):
        p = LogLSHDParser()
        results = p.parse_batch([])
        assert results == []

    def test_parse_batch_single_line(self):
        p = LogLSHDParser()
        results = p.parse_batch(["only one line here"])
        assert len(results) == 1
        assert isinstance(results[0], ParseResult)

    def test_reset(self):
        p = LogLSHDParser()
        p.parse_batch(["test line"])
        p.reset()
        # After reset, internal template dict should be cleared
        assert p._template_dict == {}

    def test_parse_batch_clusters_similar_lines(self):
        """Similar log lines should ideally get the same template."""
        p = LogLSHDParser()
        lines = [
            "Connection established to 10.0.0.1:6379",
            "Connection established to 10.0.0.2:6379",
            "Connection established to 10.0.0.3:6379",
            "Connection established to 192.168.1.1:6379",
        ]
        results = p.parse_batch(lines)
        # All four lines are structurally identical -- they should
        # share the same template (or at worst the same cluster_id).
        templates = set(r.template for r in results)
        # With DTW, these should collapse to 1 or 2 templates
        assert len(templates) <= 2

    def test_version(self):
        p = LogLSHDParser()
        assert p.version == "1.0"


# ---------------------------------------------------------------------------
# LILACParser tests
# ---------------------------------------------------------------------------
from parsers.lilac_parser import LILACParser


class TestLILACParser:
    def test_is_log_parser(self):
        p = LILACParser()
        assert isinstance(p, LogParser)
        assert p.name == "lilac"
        assert p.requires_llm is True

    def test_version(self):
        p = LILACParser()
        assert p.version == "1.0"

    def test_no_api_key_returns_fallback(self):
        p = LILACParser(api_key="")
        result = p.parse("Connection established to 10.0.0.1:6379")
        assert result.confidence == 0.0
        assert result.parser_name == "lilac"
        assert result.metadata["source"] == "fallback"

    def test_no_api_key_fallback_uses_normalisation(self):
        """Without API key the parser still normalises variables via regex."""
        p = LILACParser(api_key="")
        result = p.parse("Connection established to 10.0.0.1:6379")
        assert "<*>" in result.template

    def test_cache_stats_initial(self):
        p = LILACParser()
        assert p.stats["llm_calls"] == 0
        assert p.stats["cache_hits"] == 0
        assert p.stats["cache_rate"] == 0.0

    def test_reset_clears_cache(self):
        p = LILACParser()
        p._template_cache["test"] = "template"
        p._llm_calls = 5
        p._cache_hits = 10
        p.reset()
        assert len(p._template_cache) == 0
        assert p._llm_calls == 0
        assert p._cache_hits == 0

    def test_parse_batch_empty(self):
        p = LILACParser()
        results = p.parse_batch([])
        assert results == []

    def test_parse_batch_returns_list(self):
        p = LILACParser(api_key="")
        lines = ["line one", "line two"]
        results = p.parse_batch(lines)
        assert len(results) == 2
        assert all(isinstance(r, ParseResult) for r in results)

    def test_fallback_cluster_id_is_deterministic(self):
        """Same log line should produce the same cluster_id in fallback."""
        p = LILACParser(api_key="")
        r1 = p.parse("test line 123")
        r2 = p.parse("test line 123")
        assert r1.cluster_id == r2.cluster_id

    def test_cache_eviction(self):
        """When cache_size is exceeded, oldest entries are evicted."""
        p = LILACParser(api_key="", cache_size=2)
        p._template_cache["a"] = "tmpl_a"
        p._template_cache["b"] = "tmpl_b"
        # Inserting a third should evict the first
        p._put_cache("c", "tmpl_c")
        assert "a" not in p._template_cache
        assert "b" in p._template_cache
        assert "c" in p._template_cache


# ---------------------------------------------------------------------------
# LogParserLLMParser tests
# ---------------------------------------------------------------------------
from parsers.logparser_llm_parser import LogParserLLMParser


class TestLogParserLLMParser:
    def test_is_log_parser(self):
        p = LogParserLLMParser()
        assert isinstance(p, LogParser)
        assert p.name == "logparser_llm"
        assert p.requires_llm is True

    def test_version(self):
        p = LogParserLLMParser()
        assert p.version == "1.0"

    def test_no_api_key_still_works(self):
        """Parser must produce valid results even without an API key."""
        p = LogParserLLMParser(api_key="")
        result = p.parse("[GC (Allocation Failure) 15234ms]")
        assert isinstance(result, ParseResult)
        assert result.parser_name == "logparser_llm"
        assert 0.0 <= result.confidence <= 1.0

    def test_prefix_tree_learns(self):
        """Second similar line should be matched by the prefix tree."""
        p = LogParserLLMParser(api_key="")
        p.parse("[GC (Allocation Failure) 15234ms]")
        p.parse("[GC (Allocation Failure) 8921ms]")
        assert p.stats["tree_matches"] >= 1

    def test_prefix_tree_same_template(self):
        """Similar lines should produce the same template after learning."""
        p = LogParserLLMParser(api_key="")
        r1 = p.parse("Connection established to 10.0.0.1:6379")
        r2 = p.parse("Connection established to 10.0.0.2:6379")
        assert r1.template == r2.template
        assert r1.cluster_id == r2.cluster_id

    def test_different_patterns_get_different_clusters(self):
        """Structurally different lines should get different cluster IDs."""
        p = LogParserLLMParser(api_key="")
        r1 = p.parse("[GC (Allocation Failure) 15234ms]")
        r2 = p.parse("Connection established to 10.0.0.1:6379")
        assert r1.cluster_id != r2.cluster_id

    def test_reset(self):
        """Reset must clear all internal state."""
        p = LogParserLLMParser()
        p.parse("test line 123")
        p.parse("test line 456")
        p.reset()
        assert p.stats["tree_matches"] == 0
        assert p.stats["llm_calls"] == 0
        assert p.stats["tree_hit_rate"] == 0.0

    def test_stats_initial(self):
        p = LogParserLLMParser()
        assert p.stats["tree_matches"] == 0
        assert p.stats["llm_calls"] == 0
        assert p.stats["tree_hit_rate"] == 0.0

    def test_parse_batch(self):
        p = LogParserLLMParser(api_key="")
        lines = [
            "[GC (Allocation Failure) 15234ms]",
            "[GC (Allocation Failure) 8921ms]",
            "Connection established to 10.0.0.1:6379",
        ]
        results = p.parse_batch(lines)
        assert len(results) == 3
        assert all(isinstance(r, ParseResult) for r in results)
        # First two lines should share a template
        assert results[0].template == results[1].template

    def test_parse_batch_empty(self):
        p = LogParserLLMParser()
        results = p.parse_batch([])
        assert results == []

    def test_heuristic_replaces_numbers(self):
        """Heuristic template extraction should replace numbers with <*>."""
        p = LogParserLLMParser(api_key="")
        result = p.parse("Request processed in 1234 ms with code 200")
        assert "<*>" in result.template
        assert "Request" in result.template

    def test_metadata_source_field(self):
        """Metadata should indicate the source (prefix_tree or heuristic)."""
        p = LogParserLLMParser(api_key="")
        r1 = p.parse("Error code 500 on server 10.0.0.1")
        assert r1.metadata["source"] in ("heuristic", "llm")
        # Parse again -- should come from prefix tree
        r2 = p.parse("Error code 404 on server 10.0.0.2")
        assert r2.metadata["source"] == "prefix_tree"

    def test_tree_hit_rate_increases(self):
        """Tree hit rate should increase as more similar lines are parsed."""
        p = LogParserLLMParser(api_key="")
        p.parse("User login from 192.168.1.1")
        for i in range(10):
            p.parse(f"User login from 192.168.1.{i + 2}")
        assert p.stats["tree_hit_rate"] > 0.5


# ---------------------------------------------------------------------------
# DivLogParser tests
# ---------------------------------------------------------------------------
from parsers.divlog_parser import DivLogParser


class TestDivLogParser:
    def test_is_log_parser(self):
        p = DivLogParser()
        assert isinstance(p, LogParser)
        assert p.name == "divlog"
        assert p.requires_llm is True

    def test_sample_size_config(self):
        p = DivLogParser(sample_size=50)
        assert p._sample_size == 50

    def test_no_api_key_uses_heuristic(self):
        p = DivLogParser(api_key="")
        result = p.parse("[GC 15234ms from 10.0.0.1]")
        assert result.confidence == 0.3
        assert "<*>" in result.template
        assert result.metadata["source"] == "heuristic"

    def test_cache_works(self):
        p = DivLogParser(api_key="")
        p.parse("[GC 100ms]")
        r2 = p.parse("[GC 200ms]")
        assert r2.metadata["source"] == "cache"

    def test_reset(self):
        p = DivLogParser()
        p.parse("test")
        p.reset()
        assert p.stats["llm_calls"] == 0
        assert p.stats["cache_size"] == 0

    def test_stats(self):
        p = DivLogParser(sample_size=10)
        assert p.stats["sample_size"] == 10
        assert p.stats["llm_calls"] == 0


# ---------------------------------------------------------------------------
# LemurParser tests
# ---------------------------------------------------------------------------
from parsers.lemur_parser import LemurParser


class TestLemurParser:
    def test_is_log_parser(self):
        p = LemurParser()
        assert isinstance(p, LogParser)
        assert p.name == "lemur"

    def test_parse_batch_entropy(self):
        p = LemurParser()
        lines = [
            "[GC (Allocation Failure) 15234ms]",
            "[GC (Allocation Failure) 8921ms]",
            "[GC (Allocation Failure) 3456ms]",
            "Connection to 10.0.0.1 established",
            "Connection to 10.0.0.2 established",
        ]
        results = p.parse_batch(lines)
        assert len(results) == 5
        # GC lines should get same template (numbers are high entropy)
        gc_templates = set(r.template for r in results[:3])
        assert len(gc_templates) == 1  # all same template
        # Connection lines should differ from GC
        conn_template = results[3].template
        assert conn_template != results[0].template

    def test_consolidate_without_api(self):
        p = LemurParser(api_key="")
        templates = [
            "GC (Allocation Failure) <*>ms",
            "GC (<*> Failure) <*>",
            "GC (Allocation Failure) <DURATION>ms",
        ]
        merged = p.consolidate(templates)
        assert len(merged) <= len(templates)

    def test_consolidate_empty(self):
        p = LemurParser()
        assert p.consolidate([]) == []

    def test_reset(self):
        p = LemurParser()
        p.parse_batch(["test line 1", "test line 2"])
        p.reset()
        assert p.stats["line_count"] == 0
        assert p.stats["template_count"] == 0

    def test_stats(self):
        p = LemurParser()
        p.parse_batch(["line one", "line two"])
        assert p.stats["line_count"] == 2
        assert p.stats["template_count"] > 0

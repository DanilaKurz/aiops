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

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

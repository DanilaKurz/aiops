import pytest
from parsers.base import LogParser, ParseResult
from parsers.ensemble import EnsembleParser, EnsembleResult


class FakeParser(LogParser):
    requires_llm = False
    version = "test"

    def __init__(self, name: str, template_map: dict[str, str]):
        self.name = name
        self._map = template_map

    def parse(self, log_line: str) -> ParseResult:
        tmpl = self._map.get(log_line, log_line)
        return ParseResult(template=tmpl, cluster_id=hash(tmpl) % 10000,
                           confidence=0.9, parser_name=self.name)

    def reset(self):
        pass


class TestEnsembleParserParallel:
    def _make_ensemble(self):
        p1 = FakeParser("p1", {"gc log 15s": "GC <*>s"})
        p2 = FakeParser("p2", {"gc log 15s": "GC <*>s"})
        p3 = FakeParser("p3", {"gc log 15s": "gc log <*>"})
        return EnsembleParser(parsers=[p1, p2, p3], mode="parallel", voting="majority")

    def test_parallel_majority_vote(self):
        e = self._make_ensemble()
        result = e.parse("gc log 15s")
        assert isinstance(result, EnsembleResult)
        assert result.consensus_template == "GC <*>s"
        assert result.agreement_ratio == pytest.approx(2/3, abs=0.01)

    def test_per_parser_results_preserved(self):
        e = self._make_ensemble()
        result = e.parse("gc log 15s")
        assert "p1" in result.per_parser
        assert "p2" in result.per_parser
        assert "p3" in result.per_parser

    def test_full_agreement(self):
        p1 = FakeParser("p1", {"x": "T"})
        p2 = FakeParser("p2", {"x": "T"})
        e = EnsembleParser(parsers=[p1, p2], mode="parallel", voting="majority")
        result = e.parse("x")
        assert result.agreement_ratio == 1.0

    def test_single_mode(self):
        p1 = FakeParser("p1", {"x": "T1"})
        p2 = FakeParser("p2", {"x": "T2"})
        e = EnsembleParser(parsers=[p1, p2], mode="single", voting="majority")
        result = e.parse("x")
        assert result.consensus_template == "T1"
        assert len(result.per_parser) == 1

    def test_cascade_stops_at_confident(self):
        p1 = FakeParser("p1", {"x": "T1"})
        p2 = FakeParser("p2", {"x": "T2"})
        e = EnsembleParser(parsers=[p1, p2], mode="cascade", cascade_threshold=0.8)
        result = e.parse("x")
        # p1 confidence=0.9 >= 0.8, so cascade stops at p1
        assert result.consensus_template == "T1"
        assert result.vote_details["stopped_at"] == "p1"

    def test_parse_batch(self):
        e = self._make_ensemble()
        results = e.parse_batch(["gc log 15s", "other line"])
        assert len(results) == 2
        assert all(isinstance(r, EnsembleResult) for r in results)

    def test_best_confidence_voting(self):
        p1 = FakeParser("p1", {"x": "T1"})
        p2 = FakeParser("p2", {"x": "T2"})
        # Override p2 to have higher confidence
        class HighConfParser(FakeParser):
            def parse(self, log_line):
                r = super().parse(log_line)
                return ParseResult(template=r.template, cluster_id=r.cluster_id,
                                   confidence=0.99, parser_name=self.name)
        p2_high = HighConfParser("p2", {"x": "T2"})
        e = EnsembleParser(parsers=[p1, p2_high], mode="parallel", voting="best_confidence")
        result = e.parse("x")
        assert result.consensus_template == "T2"

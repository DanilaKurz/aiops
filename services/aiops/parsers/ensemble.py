"""EnsembleParser -- combines multiple LogParsers with voting strategies."""
from collections import Counter
from dataclasses import dataclass, field
from parsers.base import LogParser, ParseResult


@dataclass
class EnsembleResult:
    consensus_template: str
    consensus_confidence: float
    per_parser: dict[str, ParseResult]
    agreement_ratio: float
    vote_details: dict = field(default_factory=dict)


class EnsembleParser:
    def __init__(self, parsers: list[LogParser], mode: str = "parallel",
                 voting: str = "majority", consolidator: LogParser | None = None,
                 cascade_threshold: float = 0.7):
        self.parsers = parsers
        self.mode = mode  # parallel | cascade | single
        self.voting = voting  # majority | weighted | best_confidence
        self.consolidator = consolidator
        self.cascade_threshold = cascade_threshold

    def parse(self, log_line: str) -> EnsembleResult:
        if self.mode == "single":
            return self._parse_single(log_line)
        elif self.mode == "cascade":
            return self._parse_cascade(log_line)
        else:
            return self._parse_parallel(log_line)

    def parse_batch(self, lines: list[str]) -> list[EnsembleResult]:
        return [self.parse(line) for line in lines]

    def _parse_parallel(self, log_line: str) -> EnsembleResult:
        per_parser = {}
        for parser in self.parsers:
            result = parser.parse(log_line)
            per_parser[parser.name] = result
        consensus, confidence, agreement, details = self._vote(per_parser)
        return EnsembleResult(consensus_template=consensus, consensus_confidence=confidence,
                              per_parser=per_parser, agreement_ratio=agreement, vote_details=details)

    def _parse_single(self, log_line: str) -> EnsembleResult:
        parser = self.parsers[0]
        result = parser.parse(log_line)
        return EnsembleResult(consensus_template=result.template, consensus_confidence=result.confidence,
                              per_parser={parser.name: result}, agreement_ratio=1.0,
                              vote_details={"mode": "single", "parser": parser.name})

    def _parse_cascade(self, log_line: str) -> EnsembleResult:
        per_parser = {}
        for parser in self.parsers:
            result = parser.parse(log_line)
            per_parser[parser.name] = result
            if result.confidence >= self.cascade_threshold:
                return EnsembleResult(consensus_template=result.template, consensus_confidence=result.confidence,
                                      per_parser=per_parser, agreement_ratio=1.0,
                                      vote_details={"mode": "cascade", "stopped_at": parser.name})
        consensus, confidence, agreement, details = self._vote(per_parser)
        details["mode"] = "cascade_fallback"
        return EnsembleResult(consensus_template=consensus, consensus_confidence=confidence,
                              per_parser=per_parser, agreement_ratio=agreement, vote_details=details)

    def _vote(self, per_parser: dict[str, ParseResult]) -> tuple:
        templates = [r.template for r in per_parser.values()]
        counter = Counter(templates)
        if self.voting == "best_confidence":
            best = max(per_parser.values(), key=lambda r: r.confidence)
            winner = best.template
        else:
            winner = counter.most_common(1)[0][0]
        agree_count = counter[winner]
        total = len(templates)
        agreement = agree_count / total if total > 0 else 0.0
        matching = [r for r in per_parser.values() if r.template == winner]
        avg_conf = sum(r.confidence for r in matching) / len(matching) if matching else 0
        consensus_confidence = avg_conf * agreement
        details = {"mode": "parallel", "voting": self.voting, "winner": winner,
                   "votes": dict(counter), "agree_count": agree_count, "total_parsers": total}
        return winner, consensus_confidence, agreement, details

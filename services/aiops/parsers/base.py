"""Base classes for log parsers in the Ensemble Pipeline.

ParseResult is the universal output format for all parsers.
LogParser is the abstract base class that every parser adapter must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ParseResult:
    """Universal output format for all log parsers.

    Attributes:
        template: Extracted log template, e.g. "GC (Allocation Failure) <*>ms"
        cluster_id: Unique identifier for the template cluster.
        confidence: Parser confidence score in range [0.0, 1.0].
        parser_name: Name of the parser that produced this result.
        params: Extracted parameters from the log line.
        metadata: Arbitrary extra data (parser-specific).
    """

    template: str
    cluster_id: int
    confidence: float
    parser_name: str
    params: dict[str, str] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


class LogParser(ABC):
    """Abstract base class for all log parsers.

    Every parser adapter (Drain3, LogLSHD, LILAC, DivLog,
    LogParser-LLM, Lemur) must subclass this and implement
    parse() and reset().

    Class attributes:
        name: Short identifier for the parser (e.g. "drain3").
        requires_llm: Whether this parser needs an LLM backend.
        version: Semantic version string for the adapter.
    """

    name: str
    requires_llm: bool
    version: str

    @abstractmethod
    def parse(self, log_line: str) -> ParseResult:
        """Parse a single log line and return a ParseResult."""

    def parse_batch(self, lines: list[str]) -> list[ParseResult]:
        """Parse multiple log lines. Default: loops over parse().

        LLM-based parsers should override this for batched API calls.
        """
        return [self.parse(line) for line in lines]

    @abstractmethod
    def reset(self) -> None:
        """Clear all learned state for fair benchmark runs."""

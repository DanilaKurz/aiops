"""LILAC adapter -- LLM with Adaptive Parsing Cache.

LILAC (Log parsing with LLM, Adaptive parsing Cache) uses an LLM
(OpenAI) for log template extraction with an adaptive cache that
minimises API calls.  When a log line is similar to a previously
seen pattern, the cached template is reused instead of calling the
LLM again.

This adapter provides a self-contained implementation of the LILAC
approach:
  1. Normalise the log line (collapse obvious variables).
  2. Look up the normalised form in a local template cache.
  3. On cache miss, call the LLM to extract a template.
  4. Store the result in the cache for future hits.

When no ``api_key`` is supplied the parser returns a graceful
fallback result with ``confidence=0``.
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional

from parsers.base import LogParser, ParseResult

# ---------------------------------------------------------------------------
# Optional OpenAI import
# ---------------------------------------------------------------------------
_OPENAI_AVAILABLE = True
try:
    from openai import OpenAI  # type: ignore[import-untyped]
except ImportError:
    _OPENAI_AVAILABLE = False

# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------
_VAR_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # IPv4 addresses
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<*>"),
    # Hex sequences (8+ chars)
    (re.compile(r"\b0x[0-9a-fA-F]+\b"), "<*>"),
    (re.compile(r"\b[0-9a-fA-F]{8,}\b"), "<*>"),
    # Pure numbers (int / float)
    (re.compile(r"(?<![a-zA-Z])\d+(?:\.\d+)?(?![a-zA-Z])"), "<*>"),
    # File paths
    (re.compile(r"(?:/[\w.\-]+){2,}"), "<*>"),
]

_PROMPT_TEMPLATE = (
    "You are a log template extractor. Given the following log message, "
    "extract the static template by replacing all variable parts "
    "(IP addresses, numbers, file paths, hex values, timestamps, UUIDs, "
    "hostnames, etc.) with the placeholder <*>. "
    "Return ONLY the template string, nothing else.\n\n"
    "Log message: {log_line}\n\n"
    "Template:"
)


def _normalise(line: str) -> str:
    """Quick regex-based normalisation to create a cache key."""
    result = line
    for pattern, replacement in _VAR_PATTERNS:
        result = pattern.sub(replacement, result)
    # Collapse consecutive <*> tokens
    result = re.sub(r"(<\*>\s*){2,}", "<*> ", result)
    return result.strip()


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class LILACParser(LogParser):
    """LILAC-style log parser: LLM template extraction with adaptive cache."""

    name = "lilac"
    requires_llm = True
    version = "1.0"

    def __init__(
        self,
        api_key: str = "",
        cache_size: int = 10000,
        model: str = "gpt-4o-mini",
    ):
        self._api_key = api_key
        self._cache_size = cache_size
        self._model = model

        # Stats counters
        self._llm_calls: int = 0
        self._cache_hits: int = 0

        # Adaptive cache: normalised_pattern -> template
        self._template_cache: dict[str, str] = {}

        # Initialise OpenAI client if possible
        self._client: Optional[object] = None
        if _OPENAI_AVAILABLE and api_key:
            try:
                self._client = OpenAI(api_key=api_key)
            except Exception:
                self._client = None

    # ------------------------------------------------------------------
    # LogParser ABC
    # ------------------------------------------------------------------

    def parse(self, log_line: str) -> ParseResult:
        """Parse a single log line using LLM with adaptive cache."""
        # If no client available, return fallback
        if self._client is None:
            return self._fallback_result(log_line)

        # Step 1: normalise to build cache key
        cache_key = _normalise(log_line)

        # Step 2: check cache
        if cache_key in self._template_cache:
            self._cache_hits += 1
            template = self._template_cache[cache_key]
            return self._build_result(
                log_line, template, source="cache",
            )

        # Step 3: cache miss -- call LLM
        template = self._call_llm(log_line)
        if template is None:
            # LLM call failed -- return fallback
            return self._fallback_result(log_line)

        self._llm_calls += 1

        # Step 4: store in cache (with eviction if needed)
        self._put_cache(cache_key, template)

        return self._build_result(log_line, template, source="llm")

    def parse_batch(self, lines: list[str]) -> list[ParseResult]:
        """Parse multiple log lines.

        Processes sequentially so that earlier lines populate the cache
        for later identical patterns.
        """
        return [self.parse(line) for line in lines]

    def reset(self) -> None:
        """Clear all learned state and statistics."""
        self._llm_calls = 0
        self._cache_hits = 0
        self._template_cache.clear()

    # ------------------------------------------------------------------
    # Stats property
    # ------------------------------------------------------------------

    @property
    def stats(self) -> dict:
        """Return cache / LLM usage statistics."""
        total = self._llm_calls + self._cache_hits
        return {
            "llm_calls": self._llm_calls,
            "cache_hits": self._cache_hits,
            "cache_rate": self._cache_hits / max(1, total),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_llm(self, log_line: str) -> Optional[str]:
        """Call OpenAI to extract a log template."""
        if self._client is None:
            return None
        try:
            response = self._client.chat.completions.create(  # type: ignore[union-attr]
                model=self._model,
                messages=[
                    {
                        "role": "user",
                        "content": _PROMPT_TEMPLATE.format(log_line=log_line),
                    },
                ],
                temperature=0.0,
                max_tokens=256,
            )
            template = response.choices[0].message.content.strip()
            return template
        except Exception:
            return None

    def _put_cache(self, key: str, template: str) -> None:
        """Insert into cache with simple size-based eviction."""
        if len(self._template_cache) >= self._cache_size:
            # Evict the oldest entry (FIFO)
            oldest_key = next(iter(self._template_cache))
            del self._template_cache[oldest_key]
        self._template_cache[key] = template

    def _build_result(
        self,
        log_line: str,
        template: str,
        source: str,
    ) -> ParseResult:
        """Build a ParseResult from a template."""
        event_id = hashlib.md5(template.encode("utf-8")).hexdigest()[:8]
        cluster_id = int(event_id, 16) % (2**31)
        # Confidence: LLM-derived templates get high confidence
        confidence = 0.9 if source == "llm" else 0.85
        return ParseResult(
            template=template,
            cluster_id=cluster_id,
            confidence=confidence,
            parser_name=self.name,
            params={},
            metadata={
                "source": source,
                "stats": self.stats,
            },
        )

    def _fallback_result(self, log_line: str) -> ParseResult:
        """Return a degraded result when no API key / LLM is available."""
        # Use regex-based normalisation as a best-effort template
        template = _normalise(log_line)
        event_id = hashlib.md5(template.encode("utf-8")).hexdigest()[:8]
        cluster_id = int(event_id, 16) % (2**31)
        return ParseResult(
            template=template,
            cluster_id=cluster_id,
            confidence=0.0,
            parser_name=self.name,
            params={},
            metadata={
                "source": "fallback",
                "reason": "no_api_key" if not self._api_key else "client_init_failed",
            },
        )

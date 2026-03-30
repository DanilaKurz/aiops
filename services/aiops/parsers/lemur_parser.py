"""Lemur adapter -- Entropy-based clustering + CoT template merging.

Dual role:
  - Parser: entropy clustering to extract templates
  - Consolidator: merge templates from multiple parsers via LLM CoT
"""
import re
import math
from collections import Counter, defaultdict

from parsers.base import LogParser, ParseResult


class LemurParser(LogParser):
    """Log parser using information entropy + optional LLM consolidation."""

    name = "lemur"
    requires_llm = True  # for consolidation; parsing works without LLM
    version = "1.0"

    def __init__(
        self,
        api_key: str = "",
        model: str = "gpt-4o-mini",
        merge_threshold: float = 0.85,
    ):
        self._api_key = api_key
        self._model = model
        self._merge_threshold = merge_threshold
        self._token_stats: dict[int, Counter] = defaultdict(Counter)
        self._line_count = 0
        self._templates: dict[str, int] = {}  # template -> cluster_id
        self._next_id = 0

    # ------------------------------------------------------------------
    # LogParser interface
    # ------------------------------------------------------------------

    def parse(self, log_line: str) -> ParseResult:
        tokens = log_line.split()
        self._line_count += 1

        # Update token statistics per position
        for i, token in enumerate(tokens):
            self._token_stats[i][token] += 1

        # Generate template based on entropy
        template_tokens = []
        for i, token in enumerate(tokens):
            entropy = self._position_entropy(i)
            if entropy > 1.0:  # high entropy = likely parameter
                template_tokens.append("<*>")
            else:
                template_tokens.append(token)

        template = " ".join(template_tokens)
        # Collapse consecutive <*>
        template = re.sub(r"(<\*>\s*)+", "<*> ", template).strip()

        if template not in self._templates:
            self._templates[template] = self._next_id
            self._next_id += 1

        return ParseResult(
            template=template,
            cluster_id=self._templates[template],
            confidence=min(1.0, self._line_count / 20),
            parser_name=self.name,
            metadata={"line_count": self._line_count},
        )

    def parse_batch(self, lines: list[str]) -> list[ParseResult]:
        """Two-pass: first pass collects stats, second generates templates."""
        # Pass 1: collect token statistics
        for line in lines:
            tokens = line.split()
            self._line_count += 1
            for i, token in enumerate(tokens):
                self._token_stats[i][token] += 1

        # Pass 2: generate templates using collected entropy
        results = []
        for line in lines:
            tokens = line.split()
            template_tokens = []
            for i, token in enumerate(tokens):
                entropy = self._position_entropy(i)
                if entropy > 1.0:
                    template_tokens.append("<*>")
                else:
                    template_tokens.append(token)
            template = " ".join(template_tokens)
            template = re.sub(r"(<\*>\s*)+", "<*> ", template).strip()

            if template not in self._templates:
                self._templates[template] = self._next_id
                self._next_id += 1

            results.append(
                ParseResult(
                    template=template,
                    cluster_id=self._templates[template],
                    confidence=min(1.0, self._line_count / 20),
                    parser_name=self.name,
                )
            )
        return results

    def reset(self) -> None:
        self._token_stats.clear()
        self._line_count = 0
        self._templates.clear()
        self._next_id = 0

    # ------------------------------------------------------------------
    # Consolidator role
    # ------------------------------------------------------------------

    def consolidate(self, templates: list[str]) -> list[str]:
        """Merge similar templates from different parsers using LLM CoT.

        This is Lemur's consolidator role. If no API key, uses simple
        string similarity to merge obvious duplicates.
        """
        if not templates:
            return []

        if self._api_key:
            return self._llm_consolidate(templates)
        return self._simple_consolidate(templates)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _position_entropy(self, position: int) -> float:
        """Calculate information entropy at a token position."""
        counter = self._token_stats.get(position)
        if not counter:
            return 0.0
        total = sum(counter.values())
        if total <= 1:
            return 0.0
        entropy = 0.0
        for count in counter.values():
            p = count / total
            if p > 0:
                entropy -= p * math.log2(p)
        return entropy

    def _llm_consolidate(self, templates: list[str]) -> list[str]:
        """Use LLM with Chain-of-Thought to merge similar templates."""
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self._api_key)

            template_list = "\n".join(
                f"{i + 1}. {t}" for i, t in enumerate(templates)
            )
            prompt = (
                "You are merging log templates from multiple parsers.\n\n"
                f"Templates:\n{template_list}\n\n"
                "Think step by step:\n"
                "1. Identify templates that describe the same log pattern\n"
                "2. For each group, pick the most specific template\n"
                "3. Merge groups into unified templates\n\n"
                "Output ONLY the merged templates, one per line. "
                "No numbering, no explanation."
            )

            response = client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0,
            )
            merged = [
                t.strip()
                for t in response.choices[0].message.content.strip().split("\n")
                if t.strip()
            ]
            return merged if merged else templates
        except Exception:
            return self._simple_consolidate(templates)

    def _simple_consolidate(self, templates: list[str]) -> list[str]:
        """Simple merge: group templates by normalized form."""
        normalized: dict[str, str] = {}
        for t in templates:
            key = re.sub(r"<[^>]+>", "<*>", t.lower().strip())
            if key not in normalized:
                normalized[key] = t  # keep first (most specific)
        return list(normalized.values())

    @property
    def stats(self) -> dict:
        return {
            "line_count": self._line_count,
            "template_count": len(self._templates),
            "positions_tracked": len(self._token_stats),
        }

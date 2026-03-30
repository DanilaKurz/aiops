"""LogParser-LLM adapter -- Prefix Tree + LLM fallback.

Implements the LogParser-LLM approach: a prefix parse tree for fast
syntactic matching of known log patterns, with LLM fallback for truly
novel patterns.  In production benchmarks, the prefix tree handles
~99.99% of 3.6M logs, requiring only ~272 LLM calls.

When no API key is provided the parser still works using prefix-tree
matching only -- novel patterns are assigned low-confidence templates
derived from token-level heuristics.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from typing import Any, Optional

from parsers.base import LogParser, ParseResult

# ---------------------------------------------------------------------------
# Vendor path -- attempt to import LogParser-LLM from the vendored copy
# ---------------------------------------------------------------------------
_VENDOR_PATH = os.path.join(
    os.path.dirname(__file__), "..", "vendor", "llmparser",
)
_LLMPARSER_AVAILABLE = False
_IMPORT_ERROR: Optional[str] = None

try:
    if os.path.isdir(_VENDOR_PATH) and _VENDOR_PATH not in sys.path:
        sys.path.insert(0, _VENDOR_PATH)
    # Try importing the vendored LogParser-LLM module
    from LLMParser import LLMParser as _VendorLLMParser  # type: ignore[import-untyped]

    _LLMPARSER_AVAILABLE = True
except ImportError as exc:
    _IMPORT_ERROR = str(exc)

# ---------------------------------------------------------------------------
# Variable-detection regexes (common log variables -> <*>)
# Applied to each *token* individually in order.
# ---------------------------------------------------------------------------
_TOKEN_VAR_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?"),   # IPv4 + optional port
    re.compile(r"[0-9a-fA-F]{8,}"),                      # long hex strings
    re.compile(r"\d+"),                                   # any digit sequence
]


# ===================================================================
# Prefix Tree Node
# ===================================================================
class _PrefixTreeNode:
    """A node in the prefix parse tree.

    Each node stores a token (or ``None`` for root), child nodes keyed
    by token text, a wildcard child (``<*>``), and -- if this node is a
    leaf -- the template string and cluster ID it represents.
    """

    __slots__ = ("token", "children", "wildcard_child",
                 "template", "cluster_id", "count")

    def __init__(self, token: Optional[str] = None):
        self.token = token
        self.children: dict[str, _PrefixTreeNode] = {}
        self.wildcard_child: Optional[_PrefixTreeNode] = None
        self.template: Optional[str] = None
        self.cluster_id: Optional[int] = None
        self.count: int = 0


# ===================================================================
# Prefix Parse Tree
# ===================================================================
class PrefixParseTree:
    """Prefix tree (trie) over tokenised log templates.

    Insert templates (token sequences containing ``<*>`` wildcards) into
    the tree, then look up new log lines to find a matching template.
    """

    def __init__(self, sim_threshold: float = 0.5):
        self.root = _PrefixTreeNode()
        self._sim_threshold = sim_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def insert(self, template_tokens: list[str], cluster_id: int) -> None:
        """Insert a template (list of tokens) into the tree.

        Any token containing ``<*>`` (either the token IS ``<*>`` or it
        contains the wildcard, e.g. ``<*>ms]``) is stored under the
        wildcard branch so it can match variable tokens during lookup.
        """
        node = self.root
        for token in template_tokens:
            if "<*>" in token:
                if node.wildcard_child is None:
                    node.wildcard_child = _PrefixTreeNode("<*>")
                node = node.wildcard_child
            else:
                if token not in node.children:
                    node.children[token] = _PrefixTreeNode(token)
                node = node.children[token]
        node.template = " ".join(template_tokens)
        node.cluster_id = cluster_id
        node.count += 1

    def match(self, tokens: list[str]) -> Optional[tuple[str, int]]:
        """Try to match a tokenised log line against the tree.

        Returns ``(template, cluster_id)`` on match, else ``None``.
        Uses a BFS-like approach: at each position we try both the
        exact-token child and the wildcard child, keeping the best
        (deepest) match.
        """
        candidates: list[tuple[_PrefixTreeNode, int]] = [(self.root, 0)]
        best_match: Optional[tuple[str, int]] = None
        best_depth = -1

        while candidates:
            next_candidates: list[tuple[_PrefixTreeNode, int]] = []
            for node, depth in candidates:
                if depth == len(tokens):
                    # Reached the end of the token sequence
                    if node.template is not None and depth > best_depth:
                        best_match = (node.template, node.cluster_id)  # type: ignore[assignment]
                        best_depth = depth
                        node.count += 1
                    continue

                current_token = tokens[depth]

                # Try exact match
                if current_token in node.children:
                    next_candidates.append((node.children[current_token], depth + 1))

                # Try wildcard match
                if node.wildcard_child is not None:
                    next_candidates.append((node.wildcard_child, depth + 1))

            candidates = next_candidates

        return best_match

    def clear(self) -> None:
        """Remove all entries from the tree."""
        self.root = _PrefixTreeNode()


# ===================================================================
# LogParserLLMParser
# ===================================================================
class LogParserLLMParser(LogParser):
    """Adapter for LogParser-LLM: prefix tree + optional LLM fallback.

    The prefix tree handles known log patterns with confidence=1.0 and
    zero LLM cost.  Unknown patterns are sent to the LLM for template
    extraction, and the resulting template is inserted back into the
    tree for future matches.

    Without an API key the parser still functions: novel patterns are
    handled by a heuristic tokeniser that replaces variable-like tokens
    with ``<*>``, producing a lower-confidence result.
    """

    name = "logparser_llm"
    requires_llm = True
    version = "1.0"

    def __init__(
        self,
        api_key: str = "",
        model: str = "gpt-4o-mini",
        sim_threshold: float = 0.5,
    ):
        self._api_key = api_key
        self._model = model
        self._tree = PrefixParseTree(sim_threshold=sim_threshold)
        self._tree_matches = 0
        self._llm_calls = 0
        self._template_pool: dict[str, int] = {}  # template -> cluster_id
        self._next_cluster_id = 0

        # Attempt to create a real OpenAI client if key is available
        self._llm_client: Any = None
        if self._api_key:
            try:
                from openai import OpenAI
                self._llm_client = OpenAI(api_key=self._api_key)
            except ImportError:
                pass

    # ------------------------------------------------------------------
    # LogParser ABC
    # ------------------------------------------------------------------

    def parse(self, log_line: str) -> ParseResult:
        """Parse a single log line.

        1. Tokenise and preprocess the line.
        2. Try prefix tree match -- if hit, return with confidence=1.0.
        3. If miss and LLM is available, call LLM for template extraction.
        4. Otherwise, apply heuristic template extraction.
        5. Insert the resulting template back into the prefix tree.
        """
        tokens = self._tokenise(log_line)

        # Step 1: prefix tree lookup
        tree_result = self._tree.match(tokens)
        if tree_result is not None:
            template, cluster_id = tree_result
            self._tree_matches += 1
            return ParseResult(
                template=template,
                cluster_id=cluster_id,
                confidence=1.0,
                parser_name=self.name,
                params={},
                metadata={"source": "prefix_tree"},
            )

        # Step 2: LLM fallback (if available)
        if self._llm_client is not None:
            template = self._call_llm(log_line)
            self._llm_calls += 1
            confidence = 0.9
            source = "llm"
        else:
            # Step 3: Heuristic fallback
            template = self._heuristic_template(tokens)
            confidence = 0.4
            source = "heuristic"

        # Register template
        cluster_id = self._register_template(template)

        # Insert into prefix tree for future matches
        template_tokens = template.split()
        self._tree.insert(template_tokens, cluster_id)

        return ParseResult(
            template=template,
            cluster_id=cluster_id,
            confidence=confidence,
            parser_name=self.name,
            params={},
            metadata={"source": source},
        )

    def parse_batch(self, lines: list[str]) -> list[ParseResult]:
        """Parse multiple log lines.

        Processes lines sequentially so the prefix tree learns
        progressively -- later lines benefit from earlier discoveries.
        """
        return [self.parse(line) for line in lines]

    def reset(self) -> None:
        """Clear all learned state for fair benchmark runs."""
        self._tree_matches = 0
        self._llm_calls = 0
        self._tree.clear()
        self._template_pool.clear()
        self._next_cluster_id = 0

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @property
    def stats(self) -> dict[str, Any]:
        """Return parsing statistics."""
        total = self._tree_matches + self._llm_calls
        return {
            "tree_matches": self._tree_matches,
            "llm_calls": self._llm_calls,
            "tree_hit_rate": self._tree_matches / max(1, total),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _tokenise(self, log_line: str) -> list[str]:
        """Split a log line into tokens."""
        return log_line.strip().split()

    def _heuristic_template(self, tokens: list[str]) -> str:
        """Apply heuristic variable detection to produce a template.

        Replaces tokens that look like variables (numbers, hex strings,
        IP addresses, paths with digits) with ``<*>``.  Consecutive
        wildcards are merged.
        """
        result: list[str] = []
        for token in tokens:
            replaced = token
            for pat in _TOKEN_VAR_PATTERNS:
                replaced = pat.sub("<*>", replaced)
            # If the entire token became only wildcards/punctuation
            stripped = replaced.replace("<*>", "").strip()
            if not stripped and token != replaced:
                replaced = "<*>"
            result.append(replaced)

        # Merge consecutive <*>
        merged: list[str] = []
        for tok in result:
            if tok == "<*>" and merged and merged[-1] == "<*>":
                continue
            merged.append(tok)

        return " ".join(merged)

    def _call_llm(self, log_line: str) -> str:
        """Call the LLM to extract a log template.

        The prompt follows the LogParser-LLM approach: ask the model to
        replace variable parts with ``<*>`` while keeping the static
        structure.
        """
        prompt = (
            "You are a log template extractor. Given the following log "
            "message, replace all variable parts (timestamps, IDs, IP "
            "addresses, numbers, file paths, etc.) with the placeholder "
            "`<*>`. Keep the static structure intact. Return ONLY the "
            "template, nothing else.\n\n"
            f"Log: {log_line}\n"
            "Template:"
        )
        try:
            response = self._llm_client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=256,
                temperature=0.0,
            )
            template = response.choices[0].message.content.strip()
            return template if template else self._heuristic_template(
                self._tokenise(log_line)
            )
        except Exception:
            # On any LLM error, fall back to heuristic
            return self._heuristic_template(self._tokenise(log_line))

    def _register_template(self, template: str) -> int:
        """Register a template and return its cluster ID."""
        if template in self._template_pool:
            return self._template_pool[template]
        cluster_id = self._next_cluster_id
        self._template_pool[template] = cluster_id
        self._next_cluster_id += 1
        return cluster_id

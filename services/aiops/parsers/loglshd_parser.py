"""LogLSHD adapter -- LSH + Dynamic Time Warping log parser.

Wraps the LogLSHD algorithm (Locality-Sensitive Hashing with DTW-based
template extraction) into the LogParser ABC.  LogLSHD is inherently
batch-oriented: it needs a collection of log lines to cluster.

The adapter re-implements the core algorithmic pipeline in-memory,
reusing the vendor DTW_TemplateGenerator where possible.
"""

from __future__ import annotations

import hashlib
import os
import sys
from typing import Optional

import numpy as np
import pandas as pd

from parsers.base import LogParser, ParseResult

# ---------------------------------------------------------------------------
# Vendor path -- attempt to import LogLSHD's DTW module from the vendored copy
# ---------------------------------------------------------------------------
_VENDOR_PATH = os.path.join(
    os.path.dirname(__file__), "..", "vendor", "loglshd",
    "benchmark", "logparser", "LogLSHD",
)
_LOGLSHD_AVAILABLE = False
_IMPORT_ERROR: Optional[str] = None

try:
    import regex as re
    from datasketch import MinHash, MinHashLSH
    from fastdtw import fastdtw  # noqa: F401 -- used inside DTW module

    # Try importing the vendored DTW helper
    if os.path.isdir(_VENDOR_PATH) and _VENDOR_PATH not in sys.path:
        sys.path.insert(0, _VENDOR_PATH)
    from DTW import DTW_TemplateGenerator  # type: ignore[import-untyped]

    _LOGLSHD_AVAILABLE = True
except ImportError as exc:
    _IMPORT_ERROR = str(exc)
    # Provide a no-op re if regex is missing (only used in fallback path)
    try:
        import regex as re  # type: ignore[no-redef]
    except ImportError:
        import re as re  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class LogLSHDParser(LogParser):
    """Adapter that wraps the LogLSHD algorithm into the LogParser ABC.

    LogLSHD is batch-oriented.  ``parse_batch()`` is the primary entry
    point -- it groups log lines using heuristic features, applies LSH
    to merge similar groups, and extracts templates via DTW.

    ``parse()`` still works for single lines but produces lower-quality
    results (each line is its own cluster).
    """

    name = "loglshd"
    requires_llm = False
    version = "1.0"

    def __init__(
        self,
        k: int = 1,
        sig_len: int = 20,
        jaccard_t: float = 0.7,
        rex: Optional[list[str]] = None,
    ):
        """
        Args:
            k:         k-token shingle size.
            sig_len:   MinHash signature length (num_perm).
            jaccard_t: Jaccard similarity threshold for LSH.
            rex:       List of regex patterns for preprocessing
                       (variables -> ``<*>``).
        """
        self.k = k
        self.sig_len = sig_len
        self.jaccard_t = jaccard_t
        self.rex = rex or []

        self._word_pattern = re.compile(r"^[a-zA-Z]+[.,]*$")

        if _LOGLSHD_AVAILABLE:
            self._dtw = DTW_TemplateGenerator()
        else:
            self._dtw = None

        # Accumulated state across calls
        self._template_dict: dict[str, str] = {}

    # ------------------------------------------------------------------
    # LogParser ABC
    # ------------------------------------------------------------------

    def parse(self, log_line: str) -> ParseResult:
        """Parse a single log line.

        For a single line, the template is just the preprocessed line
        itself (no clustering context).  Confidence is low because
        LogLSHD is designed for batch operation.
        """
        if not _LOGLSHD_AVAILABLE:
            return self._fallback_result(log_line)

        preprocessed = self._preprocess(log_line)
        template = preprocessed
        event_id = hashlib.md5(template.encode("utf-8")).hexdigest()[:8]

        if template not in self._template_dict:
            self._template_dict[template] = event_id

        return ParseResult(
            template=template,
            cluster_id=int(event_id, 16) % (2**31),
            confidence=0.3,  # low -- single-line mode
            parser_name=self.name,
            params={},
            metadata={"mode": "single"},
        )

    def parse_batch(self, lines: list[str]) -> list[ParseResult]:
        """Parse a batch of log lines using the full LogLSHD pipeline.

        This is where LogLSHD shines -- it groups, clusters via LSH,
        and extracts templates using DTW across similar log groups.
        """
        if not lines:
            return []

        if not _LOGLSHD_AVAILABLE:
            return [self._fallback_result(line) for line in lines]

        # Build a DataFrame mirroring LogLSHD's internal structure
        df = pd.DataFrame({"Content": lines})
        df["TokenCount"] = df["Content"].apply(lambda x: x.count(" "))
        df["ContentLength"] = df["Content"].apply(len)
        df["Char1"] = df["Content"].apply(
            lambda x: x[0] if len(x) > 0 else ""
        )
        df["Char2"] = df["Content"].apply(
            lambda x: x[max(0, len(x) // 4 - 1)] if len(x) >= 4 else ""
        )
        df["Char3"] = df["Content"].apply(
            lambda x: x[max(0, len(x) // 2 - 1)] if len(x) >= 2 else ""
        )
        df["Char4"] = df["Content"].apply(
            lambda x: x[max(0, 3 * len(x) // 4 - 1)] if len(x) >= 4 else ""
        )
        df["Char5"] = df["Content"].apply(
            lambda x: x[-1] if len(x) > 0 else ""
        )

        # Group by heuristic features
        group_cols = [
            "TokenCount", "ContentLength",
            "Char1", "Char2", "Char3", "Char4", "Char5",
        ]
        grouped = df.groupby(group_cols)
        grouped_keys = list(grouped.groups.keys())

        # Allocate output arrays
        templates: list[Optional[str]] = [None] * len(lines)
        event_ids: list[Optional[str]] = [None] * len(lines)

        if self.jaccard_t >= 1.0:
            # No LSH needed -- each heuristic group is a final cluster
            for _, group in grouped:
                group_idxs = group.index.tolist()
                template = self._find_template(df, group_idxs)
                eid = self._get_event_id(template)
                for idx in group_idxs:
                    templates[idx] = template
                    event_ids[idx] = eid
        else:
            # Use MinHash LSH to merge similar groups
            lsh = MinHashLSH(threshold=self.jaccard_t, num_perm=self.sig_len)
            minhashes: list[MinHash] = []

            for i, (_, group) in enumerate(grouped):
                repr_content = group.iloc[0]["Content"]
                shingle = self._build_token_shingle(repr_content, self.k)
                mh = MinHash(num_perm=self.sig_len)
                for element in shingle:
                    mh.update(str(element).encode("utf8"))
                try:
                    lsh.insert(str(i), mh)
                except ValueError:
                    # Duplicate key -- skip (already inserted)
                    pass
                minhashes.append(mh)

            visited: set[int] = set()
            for i, mh in enumerate(minhashes):
                if i in visited:
                    continue

                similar = lsh.query(mh)
                merged_idxs: list[int] = []
                for idx_str in similar:
                    gidx = int(idx_str)
                    grp = grouped.get_group(grouped_keys[gidx])
                    merged_idxs.extend(grp.index.tolist())
                    visited.add(gidx)

                template = self._find_template(df, merged_idxs)
                eid = self._get_event_id(template)
                for idx in merged_idxs:
                    templates[idx] = template
                    event_ids[idx] = eid

        # Build results
        results: list[ParseResult] = []
        for i, line in enumerate(lines):
            tmpl = templates[i] if templates[i] is not None else line
            eid = event_ids[i] if event_ids[i] is not None else "00000000"
            cluster_id = int(eid, 16) % (2**31)

            # Confidence heuristic: higher if the template covers multiple
            # lines (i.e., template != the raw line itself).
            confidence = 0.8 if tmpl != self._preprocess(line) else 0.5

            results.append(
                ParseResult(
                    template=tmpl,
                    cluster_id=cluster_id,
                    confidence=confidence,
                    parser_name=self.name,
                    params={},
                    metadata={"mode": "batch"},
                )
            )

        return results

    def reset(self) -> None:
        """Clear all learned state."""
        self._template_dict.clear()

    # ------------------------------------------------------------------
    # Internal helpers (mirroring LogLSHD's core logic)
    # ------------------------------------------------------------------

    def _preprocess(self, line: str) -> str:
        """Replace known variable patterns with ``<*>``."""
        for pattern in self.rex:
            line = re.sub(pattern, "<*>", line)
        return line

    def _build_token_shingle(self, log: str, k: int) -> set[str]:
        """Build k-token shingles from a log message."""
        tokens = [t for t in log.split() if self._word_pattern.match(t)]
        if not tokens:
            return {log}
        shingles = []
        for i in range(len(tokens) - k + 1):
            shingles.append(" ".join(tokens[i : i + k]))
        if not shingles:
            shingles.append(" ".join(tokens))
        return set(shingles)

    def _find_template(
        self, df: pd.DataFrame, log_idxs: list[int], sample_size: int = 10
    ) -> str:
        """Extract a template from a cluster of log indices using DTW."""
        if len(log_idxs) <= sample_size:
            selected = log_idxs
        else:
            selected = list(
                np.random.choice(log_idxs, sample_size, replace=False)
            )

        selected_logs = [
            self._preprocess(df.iloc[idx]["Content"]) for idx in selected
        ]

        if self._dtw is not None and len(selected_logs) > 1:
            common_part = self._dtw.dynamic_time_warping(selected_logs)
            substituted = self._dtw.combine_consecutive_star(common_part)
            template = self._dtw.postprocess(substituted)
            return template

        # Fallback for single-element clusters or missing DTW
        if len(selected_logs) == 1:
            return selected_logs[0]

        # Simple token-based template extraction (no DTW)
        base = selected_logs[0].split()
        final = list(base)
        for tokens_str in selected_logs[1:]:
            tokens = tokens_str.split()
            for ti in range(len(final)):
                if ti < len(tokens):
                    if tokens[ti] != final[ti]:
                        final[ti] = "<*>"
                else:
                    final[ti] = "<*>"
        # Merge consecutive <*>
        merged = []
        for token in final:
            if token == "<*>":
                if not merged or merged[-1] != "<*>":
                    merged.append(token)
            else:
                merged.append(token)
        return " ".join(merged)

    def _get_event_id(self, template: str) -> str:
        """Get or create an MD5-based event ID for a template."""
        if template not in self._template_dict:
            eid = hashlib.md5(template.encode("utf-8")).hexdigest()[:8]
            self._template_dict[template] = eid
        return self._template_dict[template]

    def _fallback_result(self, log_line: str) -> ParseResult:
        """Return a degraded result when LogLSHD deps are missing."""
        return ParseResult(
            template=log_line,
            cluster_id=0,
            confidence=0.0,
            parser_name=self.name,
            params={},
            metadata={
                "mode": "fallback",
                "error": _IMPORT_ERROR or "LogLSHD not available",
            },
        )

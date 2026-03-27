"""Drain3 adapter -- wraps existing Drain3 library into LogParser ABC."""

from __future__ import annotations

import os
from typing import Optional

from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig

from parsers.base import LogParser, ParseResult


class Drain3Parser(LogParser):
    """Adapter that wraps the drain3 library into the LogParser ABC."""

    name = "drain3"
    requires_llm = False
    version = "0.9"

    def __init__(
        self,
        sim_th: float = 0.4,
        depth: int = 4,
        max_clusters: int = 1024,
        config_path: Optional[str] = None,
    ):
        config = TemplateMinerConfig()
        if config_path and os.path.exists(config_path):
            config.load(config_path)
        else:
            config.drain_sim_th = sim_th
            config.drain_depth = depth
            config.drain_max_clusters = max_clusters
        self._config = config
        self.miner = TemplateMiner(config=config)

    def parse(self, log_line: str) -> ParseResult:
        result = self.miner.add_log_message(log_line)
        cluster_id: int = result["cluster_id"]
        template: str = result["template_mined"]

        # Look up cluster size for confidence scoring.
        size = 1
        for c in self.miner.drain.clusters:
            if c.cluster_id == cluster_id:
                size = c.size
                break

        confidence = min(1.0, size / 10.0)

        return ParseResult(
            template=template,
            cluster_id=cluster_id,
            confidence=confidence,
            parser_name=self.name,
            params={},
            metadata={"change_type": result["change_type"]},
        )

    def reset(self) -> None:
        """Clear all learned state (re-create the miner)."""
        self.miner = TemplateMiner(config=self._config)

    def get_clusters(self) -> list[dict]:
        """Return a list of all discovered clusters with their templates."""
        return [
            {"id": c.cluster_id, "template": c.get_template(), "count": c.size}
            for c in self.miner.drain.clusters
        ]

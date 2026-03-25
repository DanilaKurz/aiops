from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig
from typing import Optional
import os


class DrainParser:
    def __init__(self, config_path: Optional[str] = None):
        config = TemplateMinerConfig()
        if config_path and os.path.exists(config_path):
            config.load(config_path)
        self.miner = TemplateMiner(config=config)

    def parse(self, log_line: str) -> dict:
        result = self.miner.add_log_message(log_line)
        return {
            "cluster_id": result["cluster_id"],
            "template": result["template_mined"],
            "change_type": result["change_type"],
        }

    def batch_parse(self, lines: list[str]) -> list[dict]:
        return [self.parse(line) for line in lines]

    def get_clusters(self) -> list[dict]:
        clusters = []
        for cluster in self.miner.drain.clusters:
            clusters.append({
                "id": cluster.cluster_id,
                "template": cluster.get_template(),
                "count": cluster.size,
            })
        return clusters

    def get_cluster(self, cluster_id: int) -> Optional[dict]:
        for c in self.miner.drain.clusters:
            if c.cluster_id == cluster_id:
                return {
                    "id": c.cluster_id,
                    "template": c.get_template(),
                    "count": c.size,
                }
        return None

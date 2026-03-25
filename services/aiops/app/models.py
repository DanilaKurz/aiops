from pydantic import BaseModel
from typing import Optional


class LogEntry(BaseModel):
    timestamp: str
    service: str
    message: str


class ClusterInfo(BaseModel):
    id: int
    template: str
    count: int
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None


class AnomalyInfo(BaseModel):
    id: int
    window_start: str
    window_end: str
    score: float
    anomaly_type: str
    service: Optional[str] = None
    details: Optional[dict] = None


class IngestRequest(BaseModel):
    dataset: str
    date: str


class InvestigateRequest(BaseModel):
    incident_id: str
    dataset: str
    date: str
    time_range: Optional[dict] = None


class RCAReport(BaseModel):
    id: int
    incident_id: Optional[str] = None
    created_at: str
    root_cause: dict
    causal_chain: list
    evidence: list
    data_coverage: dict
    quality: dict
    correct: Optional[int] = None


class StatsResponse(BaseModel):
    total_logs: int
    unique_templates: int
    anomaly_count: int
    anomaly_rate: float
    last_ingest: Optional[str] = None

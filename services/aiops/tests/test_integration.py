"""Integration test: runs the full pipeline with real Drain + SQLite, mocked externals."""
import json
import os
import sys
import tempfile
import importlib
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

# Pre-inject mock modules so rag.py can be imported without real chromadb/openai
if "chromadb" not in sys.modules:
    sys.modules["chromadb"] = MagicMock()
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()


@pytest.fixture
def test_app(sample_openrca_dir):
    """Create test app with real Drain + SQLite, mocked ChromaDB + OpenAI."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")

        # Set environment BEFORE importing app
        os.environ["OPENAI_API_KEY"] = "test-key"
        os.environ["SQLITE_PATH"] = db_path
        os.environ["OPENRCA_DATA_DIR"] = sample_openrca_dir
        os.environ["CHROMA_URL"] = "http://localhost:8000"
        os.environ["KEEP_API_URL"] = "http://localhost:8080"
        os.environ["KEEP_API_KEY"] = ""

        # Clear settings cache
        from app.config import get_settings
        get_settings.cache_clear()

        # Force-import rag module so patch targets exist
        import app.agent.rag

        # Mock ChromaDB and OpenAI at import time
        mock_chroma = MagicMock()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 0
        mock_collection.add = MagicMock()
        mock_collection.query.return_value = {
            "documents": [["test doc"]],
            "metadatas": [[{"source": "test.md"}]],
            "distances": [[0.5]],
        }
        mock_chroma.HttpClient.return_value.get_or_create_collection.return_value = mock_collection

        mock_openai = MagicMock()
        mock_embed = MagicMock()
        mock_embed.data = [MagicMock(embedding=[0.1] * 10)]
        mock_openai.return_value.embeddings.create.return_value = mock_embed

        with patch("app.agent.rag.chromadb", mock_chroma), \
             patch("app.agent.rag.OpenAI", mock_openai):
            # Need to reimport to pick up new settings
            import app.main
            importlib.reload(app.main)

            with TestClient(app.main.app) as client:
                yield client

        # Clean up settings cache
        get_settings.cache_clear()


def test_ingest_and_clusters(test_app):
    """Test: ingest OpenRCA data -> check clusters created."""
    # 1. Ingest
    response = test_app.post("/ingest/openrca", json={
        "dataset": "Bank",
        "date": "2024_01_15"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["logs_processed"] == 3
    assert data["clusters"] > 0

    # 2. Check clusters
    response = test_app.get("/clusters")
    assert response.status_code == 200
    clusters = response.json()
    assert len(clusters) > 0

    # 3. Check stats
    response = test_app.get("/stats")
    assert response.status_code == 200
    stats = response.json()
    assert stats["total_logs"] == 3
    assert stats["unique_templates"] > 0


def test_anomalies_endpoint(test_app):
    """Test: anomalies endpoint returns list."""
    # First ingest some data
    test_app.post("/ingest/openrca", json={
        "dataset": "Bank",
        "date": "2024_01_15"
    })

    response = test_app.get("/anomalies")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_reports_endpoint(test_app):
    """Test: reports endpoint returns empty list initially."""
    response = test_app.get("/reports")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_ingest_logs_endpoint(test_app):
    """Test: direct log ingestion via /ingest/logs."""
    response = test_app.post("/ingest/logs", json=[
        "Connection timeout to db-master after 30s",
        "Request processed in 150ms",
    ])
    assert response.status_code == 200
    data = response.json()
    assert data["processed"] == 2
    assert len(data["results"]) == 2


def test_benchmark_results_endpoint(test_app):
    """Test: benchmark results returns default structure."""
    response = test_app.get("/benchmark/results")
    assert response.status_code == 200
    data = response.json()
    assert "total_incidents" in data
    assert "accuracy" in data
    assert "baseline_openrca" in data

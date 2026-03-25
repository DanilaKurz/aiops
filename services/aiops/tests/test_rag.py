import os
import sys
import json
import pytest
from unittest.mock import MagicMock, patch

# Pre-inject mock modules so rag.py can be imported without real chromadb/openai
if "chromadb" not in sys.modules:
    sys.modules["chromadb"] = MagicMock()
if "openai" not in sys.modules:
    mock_openai_mod = MagicMock()
    sys.modules["openai"] = mock_openai_mod


def test_read_knowledge_files():
    """Test that knowledge files can be found and read."""
    from app.agent.rag import RAGManager
    knowledge_dir = os.path.join(os.path.dirname(__file__), "..", "knowledge")
    if not os.path.exists(knowledge_dir):
        pytest.skip("knowledge dir not found")
    rag = RAGManager.__new__(RAGManager)
    rag.knowledge_dir = knowledge_dir
    docs = rag._read_knowledge_files()
    assert len(docs) >= 4  # 3 runbooks + 1 incident


def test_search_returns_results():
    """Test search with mocked ChromaDB."""
    from app.agent.rag import RAGManager
    with patch("app.agent.rag.chromadb") as mock_chroma:
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "documents": [["CPU high runbook content"]],
            "metadatas": [[{"source": "cpu_high.md"}]],
            "distances": [[0.3]],
        }
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chroma.HttpClient.return_value = mock_client

        with patch("app.agent.rag.OpenAI") as mock_openai:
            mock_embed_response = MagicMock()
            mock_embed_response.data = [MagicMock(embedding=[0.1]*384)]
            mock_openai_client = MagicMock()
            mock_openai_client.embeddings.create.return_value = mock_embed_response
            mock_openai.return_value = mock_openai_client

            rag = RAGManager(
                chroma_url="http://localhost:8000",
                collection_name="test",
                knowledge_dir=os.path.join(os.path.dirname(__file__), "..", "knowledge"),
                openai_api_key="test-key",
            )
            results = rag.search("CPU spike investigation")
            assert len(results) > 0

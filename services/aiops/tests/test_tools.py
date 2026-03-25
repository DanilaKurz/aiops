from app.agent.tools import TOOL_DEFINITIONS, get_tool_registry


def test_tool_definitions_valid():
    assert len(TOOL_DEFINITIONS) == 6
    for tool in TOOL_DEFINITIONS:
        assert tool["type"] == "function"
        assert "name" in tool
        assert "parameters" in tool
        assert tool["parameters"].get("additionalProperties") is False


def test_tool_registry_has_all_tools():
    registry = get_tool_registry(
        openrca_adapter=None,
        db_path=None,
        rag_manager=None,
    )
    expected = {"query_metrics", "query_logs", "query_traces",
                "get_topology", "get_recent_changes", "search_knowledge_base"}
    assert set(registry.keys()) == expected

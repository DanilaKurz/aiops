import json
import pytest
from unittest.mock import MagicMock, patch


def test_investigate_returns_report():
    from app.agent.investigator import Investigator

    mock_response = MagicMock()
    mock_output_item = MagicMock()
    mock_output_item.type = "text"
    mock_response.output = [mock_output_item]
    mock_response.output_text = json.dumps({
        "root_cause": {"component": "db-master", "reason": "test", "onset_time": "2024-01-15T10:11:45Z", "confidence": 0.9},
        "causal_chain": ["db-master -> payment-api"],
        "evidence": ["test evidence"],
        "data_coverage": {"metrics_checked": [], "logs_checked": [], "traces_checked": []},
        "investigation_quality": {"total_tool_calls": 0, "all_data_types_checked": False, "upstream_followed": False},
    })

    with patch("app.agent.investigator.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        mock_client.responses.create.return_value = mock_response
        MockOpenAI.return_value = mock_client

        investigator = Investigator(
            api_key="test-key",
            model="gpt-5.4",
            tool_registry={},
            tool_definitions=[],
            max_iterations=5,
        )
        report = investigator.investigate("Test incident context")
        assert report["root_cause"]["component"] == "db-master"


def test_investigate_executes_tool_calls():
    from app.agent.investigator import Investigator

    tool_call = MagicMock()
    tool_call.type = "function_call"
    tool_call.name = "get_topology"
    tool_call.arguments = '{"dataset": "Bank"}'
    tool_call.call_id = "call_1"

    response1 = MagicMock()
    response1.output = [tool_call]

    response2 = MagicMock()
    text_item = MagicMock()
    text_item.type = "text"
    response2.output = [text_item]
    response2.output_text = json.dumps({
        "root_cause": {"component": "db-master", "reason": "test", "onset_time": "2024-01-15T10:11:45Z", "confidence": 0.9},
        "causal_chain": [],
        "evidence": [],
        "data_coverage": {"metrics_checked": [], "logs_checked": [], "traces_checked": []},
        "investigation_quality": {"total_tool_calls": 1, "all_data_types_checked": False, "upstream_followed": False},
    })

    with patch("app.agent.investigator.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        mock_client.responses.create.side_effect = [response1, response2]
        MockOpenAI.return_value = mock_client

        mock_tool = MagicMock(return_value={"nodes": ["gateway"], "edges": []})

        investigator = Investigator(
            api_key="test-key",
            model="gpt-5.4",
            tool_registry={"get_topology": mock_tool},
            tool_definitions=[],
            max_iterations=5,
        )
        report = investigator.investigate("Test incident")
        mock_tool.assert_called_once()
        assert report is not None

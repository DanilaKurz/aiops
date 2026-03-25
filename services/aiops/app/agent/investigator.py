import json
import time
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)


class Investigator:
    def __init__(self, api_key: str, model: str, tool_registry: dict,
                 tool_definitions: list, max_iterations: int = 20,
                 fallback_model: str = "gpt-4.1"):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.fallback_model = fallback_model
        self.tool_registry = tool_registry
        self.tool_definitions = tool_definitions
        self.max_iterations = max_iterations

    def investigate(self, context: str, system_prompt: str = "") -> dict:
        """Run agentic investigation loop using OpenAI Responses API.

        Returns structured RCA report dict.
        """
        input_list = [
            {"role": "user", "content": context}
        ]

        model = self.model

        for iteration in range(self.max_iterations):
            try:
                kwargs = {
                    "model": model,
                    "input": input_list,
                }
                if system_prompt:
                    kwargs["instructions"] = system_prompt
                if self.tool_definitions:
                    kwargs["tools"] = self.tool_definitions
                    kwargs["parallel_tool_calls"] = True

                response = self.client.responses.create(**kwargs)

            except Exception as e:
                # If model not found, try fallback
                if "model" in str(e).lower() and model != self.fallback_model:
                    logger.warning(f"Model {model} failed, trying {self.fallback_model}")
                    model = self.fallback_model
                    continue

                # Retry with exponential backoff (3 attempts)
                retries = 3
                for attempt in range(retries):
                    wait = 2 ** (attempt + 1)
                    logger.warning(f"OpenAI error (attempt {attempt+1}/{retries}): {e}")
                    time.sleep(wait)
                    try:
                        response = self.client.responses.create(**kwargs)
                        break
                    except Exception:
                        if attempt == retries - 1:
                            return {
                                "root_cause": {"component": "unknown", "reason": f"Investigation failed: {e}", "onset_time": "", "confidence": 0},
                                "causal_chain": [],
                                "evidence": [],
                                "data_coverage": {"metrics_checked": [], "logs_checked": [], "traces_checked": []},
                                "investigation_quality": {"total_tool_calls": iteration, "all_data_types_checked": False, "upstream_followed": False},
                                "error": str(e),
                            }

            # Check for tool calls
            tool_calls = [item for item in response.output if item.type == "function_call"]

            if not tool_calls:
                # Model returned final answer
                try:
                    return json.loads(response.output_text)
                except (json.JSONDecodeError, TypeError):
                    return {
                        "root_cause": {"component": "unknown", "reason": response.output_text or "No response", "onset_time": "", "confidence": 0},
                        "causal_chain": [],
                        "evidence": [],
                        "data_coverage": {"metrics_checked": [], "logs_checked": [], "traces_checked": []},
                        "investigation_quality": {"total_tool_calls": iteration, "all_data_types_checked": False, "upstream_followed": False},
                    }

            # Execute tool calls and append results
            input_list += response.output

            for tc in tool_calls:
                try:
                    args = json.loads(tc.arguments)
                    if tc.name in self.tool_registry:
                        result = self.tool_registry[tc.name](**args)
                    else:
                        result = {"error": f"Unknown tool: {tc.name}"}
                except Exception as e:
                    result = {"error": f"Tool {tc.name} failed: {e}"}

                input_list.append({
                    "type": "function_call_output",
                    "call_id": tc.call_id,
                    "output": json.dumps(result),
                })

        # Max iterations reached
        return {
            "root_cause": {"component": "unknown", "reason": "Max iterations reached", "onset_time": "", "confidence": 0},
            "causal_chain": [],
            "evidence": [],
            "data_coverage": {"metrics_checked": [], "logs_checked": [], "traces_checked": []},
            "investigation_quality": {"total_tool_calls": self.max_iterations, "all_data_types_checked": False, "upstream_followed": False},
        }

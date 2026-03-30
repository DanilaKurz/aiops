"""DivLog adapter -- In-Context Learning log parser with diversity sampling."""
import re
import hashlib
from parsers.base import LogParser, ParseResult


class DivLogParser(LogParser):
    """Log parser using diversity-maximizing ICL (In-Context Learning).

    Most expensive parser -- every line goes through LLM.
    Use sample_size to limit API calls.
    """
    name = "divlog"
    requires_llm = True
    version = "1.0"

    def __init__(self, api_key: str = "", model: str = "gpt-4o-mini",
                 sample_size: int = 100):
        self._api_key = api_key
        self._model = model
        self._sample_size = sample_size
        self._llm_calls = 0
        self._demo_pool: list[tuple[str, str]] = []  # (log, template) pairs for ICL
        self._template_cache: dict[str, str] = {}

    def parse(self, log_line: str) -> ParseResult:
        # Normalize for cache lookup
        cache_key = self._normalize(log_line)
        if cache_key in self._template_cache:
            template = self._template_cache[cache_key]
            return ParseResult(
                template=template,
                cluster_id=self._hash_id(template),
                confidence=0.95,
                parser_name=self.name,
                metadata={"source": "cache"},
            )

        if self._api_key and self._llm_calls < self._sample_size:
            template = self._call_llm(log_line)
            self._llm_calls += 1
        else:
            template = self._heuristic_parse(log_line)

        self._template_cache[cache_key] = template
        # Add to demo pool for ICL
        if len(self._demo_pool) < 50:
            self._demo_pool.append((log_line, template))

        return ParseResult(
            template=template,
            cluster_id=self._hash_id(template),
            confidence=0.9 if self._api_key else 0.3,
            parser_name=self.name,
            metadata={"source": "llm" if self._api_key else "heuristic",
                       "llm_calls": self._llm_calls},
        )

    def parse_batch(self, lines: list[str]) -> list[ParseResult]:
        return [self.parse(line) for line in lines]

    def reset(self) -> None:
        self._llm_calls = 0
        self._demo_pool.clear()
        self._template_cache.clear()

    def _call_llm(self, log_line: str) -> str:
        """Call LLM with ICL demos to extract template."""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self._api_key)

            # Build ICL prompt with diversity samples
            demos = ""
            for log, tmpl in self._demo_pool[-5:]:  # last 5 demos
                demos += f"Log: {log}\nTemplate: {tmpl}\n\n"

            prompt = f"""{demos}Extract the log template by replacing variable parts with <*>.
Keep static text unchanged. Only output the template, nothing else.

Log: {log_line}
Template:"""

            response = client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            return self._heuristic_parse(log_line)

    def _heuristic_parse(self, log_line: str) -> str:
        """Fallback: regex-based template extraction."""
        result = log_line
        result = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?\b', '<*>', result)
        result = re.sub(r'\b0x[0-9a-fA-F]+\b', '<*>', result)
        result = re.sub(r'(?<=[^a-zA-Z])\d+(?=[^a-zA-Z]|$)', '<*>', result)
        return result

    def _normalize(self, log_line: str) -> str:
        """Normalize for cache key."""
        return re.sub(r'\d+', 'N', log_line.strip())

    def _hash_id(self, template: str) -> int:
        return int(hashlib.md5(template.encode()).hexdigest()[:8], 16) % 100000

    @property
    def stats(self) -> dict:
        return {
            "llm_calls": self._llm_calls,
            "sample_size": self._sample_size,
            "demo_pool_size": len(self._demo_pool),
            "cache_size": len(self._template_cache),
        }

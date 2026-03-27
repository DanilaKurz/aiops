# Ensemble Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configurable ensemble log parsing pipeline с 6 парсерами, pipeline trace, benchmark runner и самодостаточным agent context.

**Architecture:** Модульная структура parsers/ + pipeline/ + benchmark/ рядом с существующими app/, detection/, agent/. Каждый парсер реализует LogParser ABC. EnsembleParser оркестрирует через YAML config. PipelineTrace записывает полный прогон. BenchmarkRunner сравнивает конфигурации.

**Tech Stack:** Python 3.12, drain3, LogLSHD, LILAC, logparser (DivLog), LLMparser, Lemur, PyYAML, scikit-learn, pandas, OpenAI API, pytest.

**Spec:** `docs/superpowers/specs/2026-03-27-ensemble-pipeline-design.md`

**Verification dataset:** Bank, 2021_03_04, Hour 7 (Redis02 CPU incident)

---

## File Map

### Новые файлы

| Файл | Назначение |
|------|------------|
| `services/aiops/parsers/__init__.py` | Package init, экспорт парсеров |
| `services/aiops/parsers/base.py` | LogParser ABC, ParseResult, EnsembleResult |
| `services/aiops/parsers/drain_parser.py` | Drain3 adapter |
| `services/aiops/parsers/loglshd_parser.py` | LogLSHD adapter |
| `services/aiops/parsers/lilac_parser.py` | LILAC adapter |
| `services/aiops/parsers/logparser_llm_parser.py` | LogParser-LLM adapter |
| `services/aiops/parsers/divlog_parser.py` | DivLog adapter |
| `services/aiops/parsers/lemur_parser.py` | Lemur adapter (parser + consolidator) |
| `services/aiops/parsers/ensemble.py` | EnsembleParser: voting, cascade, single |
| `services/aiops/pipeline/__init__.py` | Package init |
| `services/aiops/pipeline/config.py` | YAML config loader + Pydantic validation |
| `services/aiops/pipeline/trace.py` | PipelineTrace dataclass + save/load |
| `services/aiops/pipeline/runner.py` | Pipeline orchestration |
| `services/aiops/pipeline/context_formatter.py` | JSON + Narrative agent context |
| `services/aiops/benchmark/__init__.py` | Package init |
| `services/aiops/benchmark/runner.py` | Batch experiments, compare, ablation |
| `services/aiops/benchmark/scoring.py` | Per-incident, per-parser, cross-config metrics |
| `services/aiops/tests/test_parsers.py` | Тесты парсеров |
| `services/aiops/tests/test_ensemble.py` | Тесты ансамбля |
| `services/aiops/tests/test_pipeline.py` | Тесты pipeline runner + trace |
| `services/aiops/tests/test_context_formatter.py` | Тесты форматирования контекста |
| `services/aiops/tests/test_benchmark.py` | Тесты benchmark |
| `services/aiops/pipeline_config.yaml` | Default YAML config |
| `services/aiops/run_pipeline.py` | CLI entrypoint для pipeline |

### Модифицируемые файлы

| Файл | Изменение |
|------|-----------|
| `services/aiops/requirements.txt` | Добавить PyYAML, зависимости парсеров |
| `services/aiops/app/agent/tools.py` | Добавить 2 новых tool, улучшить query_logs |
| `README.md` | Переписать на русском, лаконично |
| `tasks.md` | Обновить task board |

---

## Task 1: LogParser ABC + ParseResult + project structure

**Files:**
- Create: `services/aiops/parsers/__init__.py`
- Create: `services/aiops/parsers/base.py`
- Create: `services/aiops/pipeline/__init__.py`
- Create: `services/aiops/benchmark/__init__.py`
- Create: `services/aiops/tests/test_parsers.py`
- Modify: `services/aiops/requirements.txt`

- [ ] **Step 1: Создать директории и __init__.py**

```bash
cd services/aiops
mkdir -p parsers pipeline benchmark
touch parsers/__init__.py pipeline/__init__.py benchmark/__init__.py
```

- [ ] **Step 2: Добавить PyYAML в requirements.txt**

Добавить строку в `services/aiops/requirements.txt`:
```
pyyaml==6.0.*
```

- [ ] **Step 3: Написать failing test для ParseResult и LogParser ABC**

Создать `services/aiops/tests/test_parsers.py`:
```python
"""Tests for LogParser ABC and ParseResult."""
import pytest
from dataclasses import asdict
from parsers.base import ParseResult, LogParser


class TestParseResult:
    def test_create_parse_result(self):
        r = ParseResult(
            template="GC (Allocation Failure) <*>ms",
            cluster_id=1,
            confidence=0.95,
            parser_name="drain3",
            params={"duration": "15234"},
            metadata={},
        )
        assert r.template == "GC (Allocation Failure) <*>ms"
        assert r.confidence == 0.95
        assert r.parser_name == "drain3"

    def test_parse_result_serializable(self):
        r = ParseResult(
            template="test <*>",
            cluster_id=1,
            confidence=0.8,
            parser_name="test",
            params={},
            metadata={"extra": 42},
        )
        d = asdict(r)
        assert d["template"] == "test <*>"
        assert d["metadata"]["extra"] == 42

    def test_parse_result_default_metadata(self):
        r = ParseResult(
            template="t",
            cluster_id=0,
            confidence=0.0,
            parser_name="x",
        )
        assert r.params == {}
        assert r.metadata == {}


class TestLogParserABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            LogParser()

    def test_concrete_parser_must_implement_parse(self):
        class BadParser(LogParser):
            name = "bad"
            requires_llm = False
            version = "0.1"

            def reset(self):
                pass

        with pytest.raises(TypeError):
            BadParser()

    def test_concrete_parser_works(self):
        class GoodParser(LogParser):
            name = "good"
            requires_llm = False
            version = "0.1"

            def parse(self, log_line: str) -> ParseResult:
                return ParseResult(
                    template=log_line,
                    cluster_id=0,
                    confidence=1.0,
                    parser_name=self.name,
                )

            def reset(self):
                pass

        p = GoodParser()
        result = p.parse("test line")
        assert result.template == "test line"
        assert result.parser_name == "good"

    def test_parse_batch_default_loops(self):
        class SimpleParser(LogParser):
            name = "simple"
            requires_llm = False
            version = "0.1"

            def parse(self, log_line: str) -> ParseResult:
                return ParseResult(
                    template=log_line.upper(),
                    cluster_id=0,
                    confidence=1.0,
                    parser_name=self.name,
                )

            def reset(self):
                pass

        p = SimpleParser()
        results = p.parse_batch(["a", "b", "c"])
        assert len(results) == 3
        assert results[0].template == "A"
        assert results[2].template == "C"
```

- [ ] **Step 4: Запустить тест, убедиться что fails**

```bash
cd services/aiops && py -m pytest tests/test_parsers.py -v
```
Expected: FAIL -- `ModuleNotFoundError: No module named 'parsers'`

- [ ] **Step 5: Реализовать base.py**

Создать `services/aiops/parsers/base.py`:
```python
"""LogParser ABC and ParseResult -- common interface for all log parsers."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ParseResult:
    """Result of parsing a single log line."""
    template: str
    cluster_id: int
    confidence: float
    parser_name: str
    params: dict[str, str] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


class LogParser(ABC):
    """Abstract base class for log parsers.

    Every parser implements parse() and reset().
    parse_batch() has a default loop implementation;
    LLM-based parsers should override it for efficiency.
    """
    name: str
    requires_llm: bool
    version: str

    @abstractmethod
    def parse(self, log_line: str) -> ParseResult:
        """Parse a single log line into a template."""
        ...

    def parse_batch(self, lines: list[str]) -> list[ParseResult]:
        """Parse multiple log lines. Override for batch-optimized parsers."""
        return [self.parse(line) for line in lines]

    @abstractmethod
    def reset(self) -> None:
        """Clear learned state for fair benchmark runs."""
        ...
```

- [ ] **Step 6: Запустить тесты, убедиться что pass**

```bash
cd services/aiops && py -m pytest tests/test_parsers.py -v
```
Expected: 6 passed

- [ ] **Step 7: Commit**

```bash
git add services/aiops/parsers/ services/aiops/pipeline/ services/aiops/benchmark/ services/aiops/tests/test_parsers.py services/aiops/requirements.txt
git commit -m "feat: LogParser ABC + ParseResult + project structure for ensemble pipeline"
```

---

## Task 2: Drain3 Adapter

**Files:**
- Create: `services/aiops/parsers/drain_parser.py`
- Modify: `services/aiops/tests/test_parsers.py`

- [ ] **Step 1: Написать failing test для Drain3 adapter**

Добавить в `services/aiops/tests/test_parsers.py`:
```python
from parsers.drain_parser import Drain3Parser


class TestDrain3Parser:
    def test_is_log_parser(self):
        p = Drain3Parser()
        assert isinstance(p, LogParser)
        assert p.name == "drain3"
        assert p.requires_llm is False

    def test_parse_single_line(self):
        p = Drain3Parser()
        result = p.parse("[GC (Allocation Failure) 15234ms]")
        assert isinstance(result, ParseResult)
        assert result.parser_name == "drain3"
        assert result.cluster_id >= 0
        assert 0.0 <= result.confidence <= 1.0
        assert "<*>" in result.template or "Allocation" in result.template

    def test_parse_batch(self):
        p = Drain3Parser()
        lines = [
            "[GC (Allocation Failure) 15234ms]",
            "[GC (Allocation Failure) 8921ms]",
            "Connection established to 10.0.0.1:6379",
        ]
        results = p.parse_batch(lines)
        assert len(results) == 3
        assert all(isinstance(r, ParseResult) for r in results)
        # first two should get same template
        assert results[0].cluster_id == results[1].cluster_id

    def test_reset_clears_state(self):
        p = Drain3Parser()
        p.parse("[GC (Allocation Failure) 15234ms]")
        assert len(p.get_clusters()) > 0
        p.reset()
        assert len(p.get_clusters()) == 0

    def test_parse_real_bank_log_line(self):
        """Verify on a real Bank dataset log format."""
        p = Drain3Parser()
        line = "2021-03-04T07:01:15.123+0800 [GC (Allocation Failure)  DefNew: 157248K->157248K(157248K), 15.234 secs]"
        result = p.parse(line)
        assert result.template != ""
        assert result.confidence > 0
```

- [ ] **Step 2: Запустить тест, убедиться что fails**

```bash
cd services/aiops && py -m pytest tests/test_parsers.py::TestDrain3Parser -v
```
Expected: FAIL -- `ModuleNotFoundError: No module named 'parsers.drain_parser'`

- [ ] **Step 3: Реализовать Drain3 adapter**

Создать `services/aiops/parsers/drain_parser.py`:
```python
"""Drain3 adapter -- wraps existing Drain3 library into LogParser ABC."""
from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig
from typing import Optional
import os

from parsers.base import LogParser, ParseResult


class Drain3Parser(LogParser):
    """Log parser using Drain3 (fixed-depth tree clustering)."""
    name = "drain3"
    requires_llm = False
    version = "0.9"

    def __init__(self, sim_th: float = 0.4, depth: int = 4,
                 max_clusters: int = 1024, config_path: Optional[str] = None):
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
        cluster = result["cluster_id"]
        template = result["template_mined"]
        # confidence: Drain3 similarity threshold as proxy
        # higher cluster size = more confidence
        size = 1
        for c in self.miner.drain.clusters:
            if c.cluster_id == cluster:
                size = c.size
                break
        confidence = min(1.0, size / 10.0)  # scale: 10+ matches = 1.0
        return ParseResult(
            template=template,
            cluster_id=cluster,
            confidence=confidence,
            parser_name=self.name,
            params={},
            metadata={"change_type": result["change_type"]},
        )

    def reset(self) -> None:
        self.miner = TemplateMiner(config=self._config)

    def get_clusters(self) -> list[dict]:
        """Get all current template clusters (for compatibility)."""
        return [
            {"id": c.cluster_id, "template": c.get_template(), "count": c.size}
            for c in self.miner.drain.clusters
        ]
```

- [ ] **Step 4: Запустить тесты, убедиться что pass**

```bash
cd services/aiops && py -m pytest tests/test_parsers.py -v
```
Expected: 11 passed

- [ ] **Step 5: Проверить на реальных данных Bank Hour 7**

```bash
cd services/aiops && py -c "
from parsers.drain_parser import Drain3Parser
import pandas as pd
df = pd.read_csv('../../Bank/telemetry/2021_03_04/log/log_service.csv', nrows=100)
p = Drain3Parser()
for _, row in df.iterrows():
    r = p.parse(str(row.get('value', '')))
    if r.cluster_id <= 3:
        print(f'cluster={r.cluster_id} conf={r.confidence:.2f} tmpl={r.template[:80]}')
print(f'Total clusters: {len(p.get_clusters())}')
"
```
Expected: вывод кластеров из реальных GC логов, без ошибок типов.

- [ ] **Step 6: Commit**

```bash
git add services/aiops/parsers/drain_parser.py services/aiops/tests/test_parsers.py
git commit -m "feat: Drain3 adapter for LogParser ABC, verified on Bank data"
```

---

## Task 3: LogLSHD Integration

**Files:**
- Create: `services/aiops/parsers/loglshd_parser.py`
- Modify: `services/aiops/tests/test_parsers.py`
- Modify: `services/aiops/requirements.txt`

- [ ] **Step 1: Установить LogLSHD**

```bash
cd services/aiops && pip install git+https://github.com/mooselab/LogLSHD.git
```
Если pip install не работает (нет setup.py), клонировать и добавить как local:
```bash
git clone https://github.com/mooselab/LogLSHD.git services/aiops/vendor/loglshd
```

- [ ] **Step 2: Изучить API LogLSHD**

```bash
cd services/aiops && py -c "
import os, sys
# check what's available after install/clone
try:
    import loglshd
    print(dir(loglshd))
except ImportError:
    sys.path.insert(0, 'vendor/loglshd')
    # find main module
    for f in os.listdir('vendor/loglshd'):
        print(f)
"
```
Записать фактический API для адаптера.

- [ ] **Step 3: Написать failing test**

Добавить в `services/aiops/tests/test_parsers.py`:
```python
from parsers.loglshd_parser import LogLSHDParser


class TestLogLSHDParser:
    def test_is_log_parser(self):
        p = LogLSHDParser()
        assert isinstance(p, LogParser)
        assert p.name == "loglshd"
        assert p.requires_llm is False

    def test_parse_batch_returns_results(self):
        p = LogLSHDParser()
        lines = [
            "[GC (Allocation Failure) 15234ms]",
            "[GC (Allocation Failure) 8921ms]",
            "Connection established to 10.0.0.1:6379",
            "Connection established to 10.0.0.2:6379",
        ]
        results = p.parse_batch(lines)
        assert len(results) == 4
        assert all(isinstance(r, ParseResult) for r in results)
        assert all(r.parser_name == "loglshd" for r in results)
        # GC lines should cluster together
        assert results[0].cluster_id == results[1].cluster_id

    def test_reset(self):
        p = LogLSHDParser()
        p.parse_batch(["test line 1", "test line 2"])
        p.reset()
        # after reset, parser should have no state
```

- [ ] **Step 4: Реализовать LogLSHD adapter**

Создать `services/aiops/parsers/loglshd_parser.py`:
```python
"""LogLSHD adapter -- LSH + Dynamic Time Warping log parser.

LogLSHD is batch-oriented: it needs all logs at once to cluster.
parse() accumulates lines; parse_batch() runs the actual algorithm.
"""
import sys
import os
from parsers.base import LogParser, ParseResult

# LogLSHD may be installed as package or vendored
try:
    from loglshd import LogLSHD
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vendor", "loglshd"))
    from loglshd import LogLSHD


class LogLSHDParser(LogParser):
    """Log parser using Locality-Sensitive Hashing + Dynamic Time Warping."""
    name = "loglshd"
    requires_llm = False
    version = "1.0"

    def __init__(self):
        self._buffer: list[str] = []
        self._results: dict[str, ParseResult] = {}

    def parse(self, log_line: str) -> ParseResult:
        # LogLSHD is batch-oriented; single-line returns basic result
        self._buffer.append(log_line)
        return ParseResult(
            template=log_line,
            cluster_id=-1,  # will be assigned in parse_batch
            confidence=0.0,
            parser_name=self.name,
            metadata={"note": "use parse_batch for real results"},
        )

    def parse_batch(self, lines: list[str]) -> list[ParseResult]:
        # Actual implementation depends on LogLSHD's API
        # This will be adapted after Step 2 (studying actual API)
        parser = LogLSHD()
        templates = parser.parse(lines)  # API to be verified
        results = []
        for i, (line, tmpl) in enumerate(zip(lines, templates)):
            results.append(ParseResult(
                template=tmpl,
                cluster_id=hash(tmpl) % 100000,
                confidence=0.8,  # LogLSHD doesn't provide confidence natively
                parser_name=self.name,
            ))
        return results

    def reset(self) -> None:
        self._buffer.clear()
        self._results.clear()
```

**NOTE:** Фактическая реализация `parse_batch` будет адаптирована в Step 2 после изучения реального API LogLSHD. Класс `LogLSHD` и метод `parse()` -- placeholder'ы, заменить на реальный API.

- [ ] **Step 5: Тесты + проверка на Bank данных**

```bash
cd services/aiops && py -m pytest tests/test_parsers.py::TestLogLSHDParser -v
```

Затем на реальных данных:
```bash
cd services/aiops && py -c "
from parsers.loglshd_parser import LogLSHDParser
import pandas as pd
df = pd.read_csv('../../Bank/telemetry/2021_03_04/log/log_service.csv', nrows=100)
lines = [str(row.get('value', '')) for _, row in df.iterrows()]
p = LogLSHDParser()
results = p.parse_batch(lines)
templates = set(r.template for r in results)
print(f'Lines: {len(lines)}, Templates: {len(templates)}')
for t in list(templates)[:5]:
    print(f'  {t[:80]}')
"
```

- [ ] **Step 6: Commit**

```bash
git add services/aiops/parsers/loglshd_parser.py services/aiops/tests/test_parsers.py
git commit -m "feat: LogLSHD adapter for ensemble pipeline"
```

---

## Task 4: LILAC Integration

**Files:**
- Create: `services/aiops/parsers/lilac_parser.py`
- Modify: `services/aiops/tests/test_parsers.py`

- [ ] **Step 1: Установить LILAC**

```bash
pip install git+https://github.com/logpai/LILAC.git
```
Или clone:
```bash
git clone https://github.com/logpai/LILAC.git services/aiops/vendor/lilac
```

- [ ] **Step 2: Изучить API и написать failing test**

Добавить в `tests/test_parsers.py`:
```python
from parsers.lilac_parser import LILACParser


class TestLILACParser:
    def test_is_log_parser(self):
        p = LILACParser(api_key="test-key")
        assert isinstance(p, LogParser)
        assert p.name == "lilac"
        assert p.requires_llm is True

    def test_parse_batch_without_api_skips(self):
        """Without valid API key, parser should handle gracefully."""
        p = LILACParser(api_key="")
        results = p.parse_batch(["test line"])
        assert len(results) == 1
        assert results[0].confidence == 0.0
```

- [ ] **Step 3: Реализовать LILAC adapter**

Создать `services/aiops/parsers/lilac_parser.py`:
```python
"""LILAC adapter -- LLM + Adaptive Parsing Cache.

Uses OpenAI API for template extraction with intelligent caching.
Cache hits bypass LLM entirely, reducing API costs.
"""
import sys
import os
from parsers.base import LogParser, ParseResult

try:
    from lilac import LILACParser as _LILAC
except ImportError:
    _LILAC = None


class LILACParser(LogParser):
    """Log parser using LILAC (LLM with Adaptive Cache)."""
    name = "lilac"
    requires_llm = True
    version = "1.0"

    def __init__(self, api_key: str = "", cache_size: int = 10000):
        self._api_key = api_key
        self._cache_size = cache_size
        self._llm_calls = 0
        self._cache_hits = 0
        self._parser = None
        if _LILAC and api_key:
            self._parser = _LILAC(api_key=api_key, cache_size=cache_size)

    def parse(self, log_line: str) -> ParseResult:
        if not self._parser:
            return ParseResult(
                template=log_line,
                cluster_id=-1,
                confidence=0.0,
                parser_name=self.name,
                metadata={"error": "LILAC not available or no API key"},
            )
        # Actual API call -- to be adapted after studying LILAC API
        result = self._parser.parse(log_line)
        is_cache_hit = result.get("from_cache", False)
        if is_cache_hit:
            self._cache_hits += 1
        else:
            self._llm_calls += 1
        return ParseResult(
            template=result["template"],
            cluster_id=hash(result["template"]) % 100000,
            confidence=1.0 if is_cache_hit else 0.9,
            parser_name=self.name,
            metadata={
                "cache_hit": is_cache_hit,
                "llm_calls_total": self._llm_calls,
                "cache_hits_total": self._cache_hits,
            },
        )

    def parse_batch(self, lines: list[str]) -> list[ParseResult]:
        return [self.parse(line) for line in lines]

    def reset(self) -> None:
        self._llm_calls = 0
        self._cache_hits = 0
        if self._parser:
            self._parser = type(self._parser)(
                api_key=self._api_key, cache_size=self._cache_size
            )

    @property
    def stats(self) -> dict:
        return {
            "llm_calls": self._llm_calls,
            "cache_hits": self._cache_hits,
            "cache_rate": self._cache_hits / max(1, self._cache_hits + self._llm_calls),
        }
```

- [ ] **Step 4: Тесты + commit**

```bash
cd services/aiops && py -m pytest tests/test_parsers.py::TestLILACParser -v
git add services/aiops/parsers/lilac_parser.py services/aiops/tests/test_parsers.py
git commit -m "feat: LILAC adapter (LLM + adaptive cache parser)"
```

---

## Task 5: LogParser-LLM Integration

**Files:**
- Create: `services/aiops/parsers/logparser_llm_parser.py`
- Modify: `services/aiops/tests/test_parsers.py`

Структура аналогична Task 4. Ключевое отличие: prefix tree для быстрого match, LLM только для незнакомых шаблонов (~272 вызова на 3.6M логов).

- [ ] **Step 1: Установить LogParser-LLM**

```bash
git clone https://github.com/LLMparser/LLMparser.git services/aiops/vendor/llmparser
```

- [ ] **Step 2: Изучить API, написать failing test**

```python
from parsers.logparser_llm_parser import LogParserLLMParser

class TestLogParserLLMParser:
    def test_is_log_parser(self):
        p = LogParserLLMParser(api_key="test-key")
        assert isinstance(p, LogParser)
        assert p.name == "logparser_llm"
        assert p.requires_llm is True

    def test_parse_without_api_key(self):
        p = LogParserLLMParser(api_key="")
        result = p.parse("test line")
        assert result.confidence == 0.0
```

- [ ] **Step 3: Реализовать adapter (prefix tree + LLM fallback)**

Создать `services/aiops/parsers/logparser_llm_parser.py` -- аналогичная структура: import vendor, wrap в LogParser ABC, track LLM calls vs tree matches.

- [ ] **Step 4: Тесты + проверка на Bank данных + commit**

---

## Task 6: DivLog Integration

**Files:**
- Create: `services/aiops/parsers/divlog_parser.py`
- Modify: `services/aiops/tests/test_parsers.py`

DivLog -- самый дорогой парсер (каждая строка через LLM). В конфиге по умолчанию `enabled: false`.

- [ ] **Step 1: Установить из logpai/logparser**

```bash
pip install git+https://github.com/logpai/logparser.git
```

- [ ] **Step 2: Написать test + adapter**

```python
from parsers.divlog_parser import DivLogParser

class TestDivLogParser:
    def test_is_log_parser(self):
        p = DivLogParser(api_key="test-key", sample_size=10)
        assert isinstance(p, LogParser)
        assert p.name == "divlog"
        assert p.requires_llm is True

    def test_sample_size_limits_calls(self):
        p = DivLogParser(api_key="", sample_size=5)
        assert p._sample_size == 5
```

Adapter: `services/aiops/parsers/divlog_parser.py` -- diversity sampling + kNN ICL prompt.

- [ ] **Step 3: Тесты + commit**

---

## Task 7: Lemur Integration

**Files:**
- Create: `services/aiops/parsers/lemur_parser.py`
- Modify: `services/aiops/tests/test_parsers.py`

Lemur имеет двойную роль: и парсер (entropy clustering), и консолидатор (CoT merging шаблонов от других парсеров).

- [ ] **Step 1: Установить**

```bash
git clone https://github.com/zwpride/lemur.git services/aiops/vendor/lemur
```

- [ ] **Step 2: Написать test + adapter**

```python
from parsers.lemur_parser import LemurParser

class TestLemurParser:
    def test_is_log_parser(self):
        p = LemurParser(api_key="test-key")
        assert isinstance(p, LogParser)
        assert p.name == "lemur"

    def test_consolidate_templates(self):
        """Test Lemur's template merging capability."""
        p = LemurParser(api_key="")
        templates = [
            "GC (Allocation Failure) <*>ms",
            "GC (<*> Failure) <*>",
            "GC (Allocation Failure) <DURATION>ms",
        ]
        merged = p.consolidate(templates)
        # Should produce fewer templates than input
        assert len(merged) <= len(templates)
```

Adapter: и `parse()`, и `consolidate(templates)` для post-processing роли.

- [ ] **Step 3: Тесты + commit**

---

## Task 8: EnsembleParser

**Files:**
- Create: `services/aiops/parsers/ensemble.py`
- Create: `services/aiops/tests/test_ensemble.py`

- [ ] **Step 1: Написать failing test**

Создать `services/aiops/tests/test_ensemble.py`:
```python
"""Tests for EnsembleParser -- voting, agreement, consensus."""
import pytest
from parsers.base import LogParser, ParseResult
from parsers.ensemble import EnsembleParser, EnsembleResult


class FakeParser(LogParser):
    """Test parser that returns predetermined templates."""
    requires_llm = False
    version = "test"

    def __init__(self, name: str, template_map: dict[str, str]):
        self.name = name
        self._map = template_map

    def parse(self, log_line: str) -> ParseResult:
        tmpl = self._map.get(log_line, log_line)
        return ParseResult(
            template=tmpl,
            cluster_id=hash(tmpl) % 10000,
            confidence=0.9,
            parser_name=self.name,
        )

    def reset(self):
        pass


class TestEnsembleParserParallel:
    def _make_ensemble(self):
        p1 = FakeParser("p1", {"gc log 15s": "GC <*>s"})
        p2 = FakeParser("p2", {"gc log 15s": "GC <*>s"})
        p3 = FakeParser("p3", {"gc log 15s": "gc log <*>"})
        return EnsembleParser(
            parsers=[p1, p2, p3],
            mode="parallel",
            voting="majority",
        )

    def test_parallel_majority_vote(self):
        e = self._make_ensemble()
        result = e.parse("gc log 15s")
        assert isinstance(result, EnsembleResult)
        assert result.consensus_template == "GC <*>s"  # 2/3 agree
        assert result.agreement_ratio == pytest.approx(2 / 3, abs=0.01)

    def test_per_parser_results_preserved(self):
        e = self._make_ensemble()
        result = e.parse("gc log 15s")
        assert "p1" in result.per_parser
        assert "p2" in result.per_parser
        assert "p3" in result.per_parser

    def test_full_agreement(self):
        p1 = FakeParser("p1", {"x": "T"})
        p2 = FakeParser("p2", {"x": "T"})
        e = EnsembleParser(parsers=[p1, p2], mode="parallel", voting="majority")
        result = e.parse("x")
        assert result.agreement_ratio == 1.0
        assert result.consensus_confidence > 0.9

    def test_single_mode(self):
        p1 = FakeParser("p1", {"x": "T1"})
        p2 = FakeParser("p2", {"x": "T2"})
        e = EnsembleParser(parsers=[p1, p2], mode="single", voting="majority")
        result = e.parse("x")
        # single mode uses first parser only
        assert result.consensus_template == "T1"
        assert len(result.per_parser) == 1

    def test_parse_batch(self):
        e = self._make_ensemble()
        results = e.parse_batch(["gc log 15s", "other line"])
        assert len(results) == 2
        assert all(isinstance(r, EnsembleResult) for r in results)
```

- [ ] **Step 2: Запустить, verify fails**

```bash
cd services/aiops && py -m pytest tests/test_ensemble.py -v
```

- [ ] **Step 3: Реализовать EnsembleParser**

Создать `services/aiops/parsers/ensemble.py`:
```python
"""EnsembleParser -- combines multiple LogParsers with voting strategies."""
from collections import Counter
from dataclasses import dataclass, field
from parsers.base import LogParser, ParseResult


@dataclass
class EnsembleResult:
    """Result from ensemble parsing with consensus and per-parser breakdown."""
    consensus_template: str
    consensus_confidence: float
    per_parser: dict[str, ParseResult]
    agreement_ratio: float
    vote_details: dict = field(default_factory=dict)


class EnsembleParser:
    """Orchestrates multiple LogParsers with configurable strategy."""

    def __init__(
        self,
        parsers: list[LogParser],
        mode: str = "parallel",
        voting: str = "majority",
        consolidator: LogParser | None = None,
        cascade_threshold: float = 0.7,
    ):
        self.parsers = parsers
        self.mode = mode
        self.voting = voting
        self.consolidator = consolidator
        self.cascade_threshold = cascade_threshold

    def parse(self, log_line: str) -> EnsembleResult:
        if self.mode == "single":
            return self._parse_single(log_line)
        elif self.mode == "cascade":
            return self._parse_cascade(log_line)
        else:
            return self._parse_parallel(log_line)

    def parse_batch(self, lines: list[str]) -> list[EnsembleResult]:
        return [self.parse(line) for line in lines]

    def _parse_parallel(self, log_line: str) -> EnsembleResult:
        per_parser = {}
        for parser in self.parsers:
            result = parser.parse(log_line)
            per_parser[parser.name] = result

        consensus, confidence, agreement, details = self._vote(per_parser)
        return EnsembleResult(
            consensus_template=consensus,
            consensus_confidence=confidence,
            per_parser=per_parser,
            agreement_ratio=agreement,
            vote_details=details,
        )

    def _parse_single(self, log_line: str) -> EnsembleResult:
        parser = self.parsers[0]
        result = parser.parse(log_line)
        return EnsembleResult(
            consensus_template=result.template,
            consensus_confidence=result.confidence,
            per_parser={parser.name: result},
            agreement_ratio=1.0,
            vote_details={"mode": "single", "parser": parser.name},
        )

    def _parse_cascade(self, log_line: str) -> EnsembleResult:
        per_parser = {}
        for parser in self.parsers:
            result = parser.parse(log_line)
            per_parser[parser.name] = result
            if result.confidence >= self.cascade_threshold:
                return EnsembleResult(
                    consensus_template=result.template,
                    consensus_confidence=result.confidence,
                    per_parser=per_parser,
                    agreement_ratio=1.0,
                    vote_details={"mode": "cascade", "stopped_at": parser.name},
                )
        # no parser was confident enough, use last result
        consensus, confidence, agreement, details = self._vote(per_parser)
        details["mode"] = "cascade_fallback"
        return EnsembleResult(
            consensus_template=consensus,
            consensus_confidence=confidence,
            per_parser=per_parser,
            agreement_ratio=agreement,
            vote_details=details,
        )

    def _vote(self, per_parser: dict[str, ParseResult]) -> tuple:
        templates = [r.template for r in per_parser.values()]
        counter = Counter(templates)

        if self.voting == "best_confidence":
            best = max(per_parser.values(), key=lambda r: r.confidence)
            winner = best.template
        else:
            # majority (and weighted for now)
            winner = counter.most_common(1)[0][0]

        agree_count = counter[winner]
        total = len(templates)
        agreement = agree_count / total if total > 0 else 0.0

        # confidence: weighted by agreement
        matching = [r for r in per_parser.values() if r.template == winner]
        avg_conf = sum(r.confidence for r in matching) / len(matching) if matching else 0
        consensus_confidence = avg_conf * agreement

        details = {
            "mode": "parallel",
            "voting": self.voting,
            "winner": winner,
            "votes": dict(counter),
            "agree_count": agree_count,
            "total_parsers": total,
        }
        return winner, consensus_confidence, agreement, details
```

- [ ] **Step 4: Тесты pass + commit**

```bash
cd services/aiops && py -m pytest tests/test_ensemble.py -v
git add services/aiops/parsers/ensemble.py services/aiops/tests/test_ensemble.py
git commit -m "feat: EnsembleParser with parallel voting, cascade, single modes"
```

---

## Task 9: Pipeline Config (YAML)

**Files:**
- Create: `services/aiops/pipeline/config.py`
- Create: `services/aiops/pipeline_config.yaml`
- Create: `services/aiops/tests/test_pipeline.py`

- [ ] **Step 1: Написать failing test**

Создать `services/aiops/tests/test_pipeline.py`:
```python
"""Tests for pipeline config, trace, runner."""
import pytest
import yaml
import tempfile
import os
from pipeline.config import PipelineConfig, load_config


class TestPipelineConfig:
    def test_load_from_yaml(self, tmp_path):
        cfg = {
            "parsing": {
                "mode": "parallel",
                "voting": "majority",
                "parsers": [
                    {"name": "drain3", "enabled": True, "params": {"sim_th": 0.4}},
                    {"name": "loglshd", "enabled": True},
                ],
                "consolidator": {"name": "lemur", "enabled": False},
            },
            "context": {"formats": ["json", "narrative"]},
            "agent": {"model": "gpt-5.4", "max_iterations": 20},
            "benchmark": {"datasets": ["Bank"], "dates": ["2021_03_04"], "save_traces": True},
        }
        path = tmp_path / "config.yaml"
        path.write_text(yaml.dump(cfg))
        config = load_config(str(path))
        assert config.parsing.mode == "parallel"
        assert len(config.parsing.parsers) == 2
        assert config.parsing.parsers[0].name == "drain3"
        assert config.context.formats == ["json", "narrative"]
        assert config.agent.model == "gpt-5.4"

    def test_default_config_valid(self):
        config = load_config("pipeline_config.yaml")
        assert config.parsing.mode in ("parallel", "cascade", "single")
        assert len(config.parsing.parsers) > 0
```

- [ ] **Step 2: Реализовать config.py + default YAML**

Создать `services/aiops/pipeline/config.py`:
```python
"""Pipeline configuration -- YAML loader with Pydantic validation."""
import yaml
from pydantic import BaseModel
from typing import Optional


class ParserConfig(BaseModel):
    name: str
    enabled: bool = True
    params: dict = {}


class ConsolidatorConfig(BaseModel):
    name: str
    enabled: bool = False
    params: dict = {}


class ParsingConfig(BaseModel):
    mode: str = "parallel"
    voting: str = "majority"
    cascade_threshold: float = 0.7
    parsers: list[ParserConfig] = []
    consolidator: Optional[ConsolidatorConfig] = None


class ContextConfig(BaseModel):
    formats: list[str] = ["json", "narrative"]


class AgentConfig(BaseModel):
    model: str = "gpt-5.4"
    fallback_model: str = "gpt-4.1"
    max_iterations: int = 20


class BenchmarkConfig(BaseModel):
    datasets: list[str] = ["Bank"]
    dates: list[str] = ["2021_03_04"]
    hours: list[int] = [7]
    save_traces: bool = True


class PipelineConfig(BaseModel):
    parsing: ParsingConfig = ParsingConfig()
    context: ContextConfig = ContextConfig()
    agent: AgentConfig = AgentConfig()
    benchmark: BenchmarkConfig = BenchmarkConfig()


def load_config(path: str) -> PipelineConfig:
    with open(path) as f:
        raw = yaml.safe_load(f)
    return PipelineConfig(**raw)
```

Создать `services/aiops/pipeline_config.yaml` -- default config из spec.

- [ ] **Step 3: Тесты + commit**

---

## Task 10: Pipeline Trace

**Files:**
- Create: `services/aiops/pipeline/trace.py`
- Modify: `services/aiops/tests/test_pipeline.py`

- [ ] **Step 1: Тест для PipelineTrace save/load**

Добавить в `tests/test_pipeline.py`:
```python
from pipeline.trace import PipelineTrace, save_trace, load_trace


class TestPipelineTrace:
    def test_create_trace(self):
        t = PipelineTrace(
            dataset="Bank", date="2021_03_04", hour=7,
            config_snapshot={"parsing": {"mode": "parallel"}},
        )
        assert t.trace_id  # auto-generated UUID
        assert t.dataset == "Bank"

    def test_save_and_load(self, tmp_path):
        t = PipelineTrace(
            dataset="Bank", date="2021_03_04", hour=7,
            config_snapshot={"test": True},
        )
        save_trace(t, str(tmp_path))
        loaded = load_trace(str(tmp_path / t.trace_id))
        assert loaded.dataset == "Bank"
        assert loaded.config_snapshot == {"test": True}
```

- [ ] **Step 2: Реализовать trace.py**

```python
"""PipelineTrace -- full record of a pipeline run."""
import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class PipelineTrace:
    dataset: str
    date: str
    hour: int
    config_snapshot: dict

    trace_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    # Parsing
    raw_log_count: int = 0
    parse_results: dict = field(default_factory=dict)
    ensemble_results: list = field(default_factory=list)
    template_summary: dict = field(default_factory=dict)

    # Detection
    anomalies: list = field(default_factory=list)
    golden_signals: list = field(default_factory=list)
    infra_alerts: list = field(default_factory=list)
    incidents: list = field(default_factory=list)

    # Context
    agent_contexts: dict = field(default_factory=dict)
    context_token_counts: dict = field(default_factory=dict)

    # Investigation
    agent_results: dict = field(default_factory=dict)
    tool_call_log: list = field(default_factory=list)

    # Evaluation
    ground_truth: dict = field(default_factory=dict)
    scores: dict = field(default_factory=dict)

    # Performance
    timing: dict = field(default_factory=dict)


def save_trace(trace: PipelineTrace, base_dir: str) -> str:
    trace_dir = os.path.join(base_dir, trace.trace_id)
    os.makedirs(trace_dir, exist_ok=True)
    with open(os.path.join(trace_dir, "trace.json"), "w") as f:
        json.dump(asdict(trace), f, indent=2, default=str)
    return trace_dir


def load_trace(trace_dir: str) -> PipelineTrace:
    with open(os.path.join(trace_dir, "trace.json")) as f:
        data = json.load(f)
    return PipelineTrace(**data)
```

- [ ] **Step 3: Тесты + commit**

---

## Task 11: Context Formatter (JSON + Narrative)

**Files:**
- Create: `services/aiops/pipeline/context_formatter.py`
- Create: `services/aiops/tests/test_context_formatter.py`

- [ ] **Step 1: Тест для самодостаточного формата**

```python
"""Tests for context formatter -- JSON and Narrative formats."""
from pipeline.context_formatter import ContextFormatter


class TestContextFormatterJSON:
    def test_json_has_required_fields(self):
        fmt = ContextFormatter()
        ctx = fmt.format_json(
            dataset="Bank", date="2021_03_04", hour=7,
            golden_signals=[{"service": "ServiceTest3", "sr_min": 88.7, "mrt_max": 13950}],
            components=[{
                "name": "Redis02",
                "role": "cache server",
                "severity": "critical",
                "is_new": True,
                "onset": "07:01:00",
                "metrics": [{"name": "CPU utilization", "value": 91.9, "normal": "1-3%"}],
            }],
            topology={"nodes": [], "edges": []},
        )
        import json
        data = json.loads(ctx)
        assert "incident" in data
        assert "user_impact" in data
        assert "suspicious_components" in data
        # self-documenting: each metric has normal_range
        comp = data["suspicious_components"][0]
        assert "role" in comp
        assert "why_suspicious" in comp or "onset" in comp

class TestContextFormatterNarrative:
    def test_narrative_has_sections(self):
        fmt = ContextFormatter()
        ctx = fmt.format_narrative(
            dataset="Bank", date="2021_03_04", hour=7,
            golden_signals=[{"service": "ServiceTest3", "sr_min": 88.7}],
            components=[{"name": "Redis02", "severity": "critical"}],
            topology={"nodes": [], "edges": []},
        )
        assert "INCIDENT CONTEXT" in ctx
        assert "WHAT USERS SEE" in ctx or "Golden Signals" in ctx
        assert "SUSPICIOUS COMPONENTS" in ctx
        assert "Redis02" in ctx
```

- [ ] **Step 2: Реализовать context_formatter.py**

Два метода: `format_json()` и `format_narrative()`. Каждое значение сопровождается: что это, нормальный диапазон, почему подозрительно.

- [ ] **Step 3: Тесты + проверка на Bank Hour 7 + commit**

---

## Task 12: Pipeline Runner

**Files:**
- Create: `services/aiops/pipeline/runner.py`
- Create: `services/aiops/run_pipeline.py`
- Modify: `services/aiops/tests/test_pipeline.py`

- [ ] **Step 1: Тест для PipelineRunner**

```python
from pipeline.runner import PipelineRunner


class TestPipelineRunner:
    def test_create_runner(self):
        runner = PipelineRunner(config_path="pipeline_config.yaml")
        assert runner.config.parsing.mode == "parallel"

    def test_run_returns_trace(self):
        runner = PipelineRunner(config_path="pipeline_config.yaml")
        # Run with only drain3 enabled for speed
        trace = runner.run(dataset="Bank", date="2021_03_04", hour=7)
        assert trace.dataset == "Bank"
        assert trace.raw_log_count > 0
        assert "drain3" in trace.parse_results
        assert len(trace.template_summary) > 0
```

- [ ] **Step 2: Реализовать runner.py**

Оркестрация: load config -> init parsers -> load data via OpenRCAAdapter -> run parsing -> run detection -> format context -> run agent -> save trace.

- [ ] **Step 3: Реализовать run_pipeline.py (CLI entrypoint)**

```python
"""CLI entrypoint for running the ensemble pipeline."""
import argparse
from pipeline.runner import PipelineRunner


def main():
    parser = argparse.ArgumentParser(description="AIOps Ensemble Pipeline")
    parser.add_argument("--config", default="pipeline_config.yaml")
    parser.add_argument("--dataset", default="Bank")
    parser.add_argument("--date", default="2021_03_04")
    parser.add_argument("--hour", type=int, default=7)
    parser.add_argument("--traces-dir", default="traces")
    args = parser.parse_args()

    runner = PipelineRunner(config_path=args.config)
    trace = runner.run(
        dataset=args.dataset,
        date=args.date,
        hour=args.hour,
        traces_dir=args.traces_dir,
    )
    print(f"Pipeline complete. Trace: {trace.trace_id}")
    print(f"  Logs parsed: {trace.raw_log_count}")
    print(f"  Templates: {trace.template_summary}")
    print(f"  Anomalies: {len(trace.anomalies)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: End-to-end тест на Bank Hour 7 + commit**

---

## Task 13: Agent Tools (2 новых + улучшенный query_logs)

**Files:**
- Modify: `services/aiops/app/agent/tools.py`

- [ ] **Step 1: Добавить query_parser_details tool definition**

```python
{
    "type": "function",
    "name": "query_parser_details",
    "description": "Get detailed log parsing results per parser for a service. Shows which templates each parser found, their agreement ratio, and confidence scores. Use to assess how reliable the log analysis is.",
    "parameters": {
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "Service/component name"},
            "hour": {"type": ["integer", "null"], "description": "Hour 0-23 to filter"},
        },
        "required": ["service"],
        "additionalProperties": False,
    },
},
```

- [ ] **Step 2: Добавить get_baseline_comparison tool definition**

```python
{
    "type": "function",
    "name": "get_baseline_comparison",
    "description": "Compare current metric value against historical baseline. Returns values for previous N hours, trend (stable/rising/spike/falling), and percentile rank. Use instead of hardcoded thresholds.",
    "parameters": {
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "Service/component name"},
            "metric": {"type": "string", "description": "Metric/KPI name"},
            "hours_back": {"type": "integer", "description": "Hours of history (default 6)", "default": 6},
        },
        "required": ["service", "metric"],
        "additionalProperties": False,
    },
},
```

- [ ] **Step 3: Улучшить query_logs -- ensemble-aware response**

Модифицировать handler query_logs чтобы возвращал templates с confidence и agreement вместо raw samples.

- [ ] **Step 4: Commit**

---

## Task 14: Benchmark Runner + Scoring

**Files:**
- Create: `services/aiops/benchmark/runner.py`
- Create: `services/aiops/benchmark/scoring.py`
- Create: `services/aiops/tests/test_benchmark.py`

- [ ] **Step 1: Тесты для scoring**

```python
from benchmark.scoring import score_incident, score_parser, compare_configs


class TestScoring:
    def test_score_incident_correct(self):
        score = score_incident(
            predicted={"component": "Redis02", "reason": "high CPU"},
            ground_truth={"component": "Redis02", "reason": "high CPU usage"},
        )
        assert score["component_match"] is True
        assert score["reason_similarity"] > 0.8

    def test_score_incident_wrong(self):
        score = score_incident(
            predicted={"component": "Tomcat01"},
            ground_truth={"component": "Redis02"},
        )
        assert score["component_match"] is False

    def test_score_parser(self):
        result = score_parser(
            template_count=47,
            parsing_time=12.3,
            llm_calls=0,
        )
        assert "template_count" in result
        assert "parsing_time" in result
```

- [ ] **Step 2: Реализовать scoring.py + runner.py**

- [ ] **Step 3: Тесты + commit**

---

## Task 15: README.md (русский, лаконичный)

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Переписать README.md**

Структура:
- Название + одно предложение
- Архитектура (ASCII диаграмма)
- Парсеры (таблица)
- Конфигурация (YAML пример)
- Быстрый старт
- Структура проекта

Всё на русском, лаконично.

- [ ] **Step 2: Commit**

---

## Task 16: Integration Test (end-to-end)

**Files:**
- Modify: `services/aiops/tests/test_pipeline.py`

- [ ] **Step 1: End-to-end тест**

```python
class TestIntegration:
    def test_full_pipeline_bank_h7(self):
        """Full pipeline run on Bank Hour 7 with Drain3 only (no LLM cost)."""
        runner = PipelineRunner(config_path="pipeline_config.yaml")
        # Override to only use drain3 for fast test
        runner.config.parsing.parsers = [
            ParserConfig(name="drain3", enabled=True)
        ]
        trace = runner.run(dataset="Bank", date="2021_03_04", hour=7)

        # Parsing worked
        assert trace.raw_log_count > 0
        assert "drain3" in trace.parse_results
        assert trace.template_summary["drain3"] > 0

        # Detection worked
        assert len(trace.golden_signals) > 0 or len(trace.infra_alerts) > 0

        # Context generated
        assert "json" in trace.agent_contexts or "narrative" in trace.agent_contexts

        # Trace saved
        assert trace.trace_id
        assert trace.timing.get("parsing", 0) > 0
```

- [ ] **Step 2: Запустить, убедиться что pass**

- [ ] **Step 3: Commit**

---

## Task 17: Обновить tasks.md

**Files:**
- Modify: `tasks.md`

- [ ] **Step 1: Добавить все новые задачи в tasks.md**

Обновить формат с батчами для параллельного выполнения.

- [ ] **Step 2: Commit**

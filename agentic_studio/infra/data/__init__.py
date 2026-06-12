"""结构化数据访问（安全中介层 + 证据源抽象）。

agent **不直接操作数据库**：只暴露具名、只读、参数化的取数原语（MetricStore），
经 EvidenceProvider 抽象喂给能力层。见 docs/engineering.md「安全 DB 访问」。
"""

from agentic_studio.infra.data.metric_store import MetricSourceConfig, MetricStore
from agentic_studio.infra.data.providers import (
    EvidenceProvider,
    ProviderSet,
    build_provider_set,
)

__all__ = [
    "MetricStore",
    "MetricSourceConfig",
    "EvidenceProvider",
    "ProviderSet",
    "build_provider_set",
]

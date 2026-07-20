"""Synchronous pipeline orchestration boundary."""

from backend.app.collector.source_collector import SourceCollector
from backend.app.normalizer import DiscussionNormalizer
from backend.app.pipeline.result import PipelineResult
from backend.app.pipeline.synchronous import (
    Extractor,
    StageStorage,
    SynchronousPipeline,
    Validator,
)
from backend.app.pipeline.trace import (
    PipelineTrace,
    PipelineTracer,
    StageTrace,
    StageStatus,
)

# Backward-compatible aliases for composition roots that have not migrated imports.
Collector = SourceCollector
Normalizer = DiscussionNormalizer

__all__ = [
    "Collector",
    "DiscussionNormalizer",
    "Extractor",
    "Normalizer",
    "PipelineResult",
    "PipelineTrace",
    "PipelineTracer",
    "SourceCollector",
    "StageStatus",
    "StageStorage",
    "StageTrace",
    "SynchronousPipeline",
    "Validator",
]

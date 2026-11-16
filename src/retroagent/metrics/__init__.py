"""Metrics, exit criteria and the release decision (docs/reference/metrics.md). Code decides, never a model."""

from retroagent.metrics.compute import NotEvaluable, Ratio
from retroagent.metrics.criteria import OpenDefectLimits, Thresholds
from retroagent.metrics.evaluation import EvaluationError, evaluate, load_inputs

__all__ = [
    "EvaluationError",
    "NotEvaluable",
    "OpenDefectLimits",
    "Ratio",
    "Thresholds",
    "evaluate",
    "load_inputs",
]

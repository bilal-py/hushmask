"""hushmask: hide PII before text goes to an AI, put it back after."""

from .detectors import Detector, KnownValue, KnownValuesDetector, PatternDetector, default_detectors
from .entities import Entity, EntityType
from .masker import LeakError, Masker, MaskResult, RestoreResult
from .policy import PRESETS, Policy

__all__ = [
    "PRESETS",
    "Detector",
    "Entity",
    "EntityType",
    "KnownValue",
    "KnownValuesDetector",
    "LeakError",
    "MaskResult",
    "Masker",
    "PatternDetector",
    "Policy",
    "RestoreResult",
    "default_detectors",
]

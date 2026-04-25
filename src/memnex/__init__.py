"""Memnex — cross-channel memory infrastructure for conversational AI agents."""
from memnex.client import Memnex
from memnex.config import MemnexConfig
from memnex.identity.models import Customer, Match
from memnex.memory.models import Conflict, Fact, Memory

__version__ = "0.1.0"

__all__ = [
    "Memnex",
    "MemnexConfig",
    "Customer",
    "Match",
    "Memory",
    "Fact",
    "Conflict",
    "__version__",
]

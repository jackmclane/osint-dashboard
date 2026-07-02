"""The interface every source implements.

Phase 3 (prediction markets, AIS) just adds new files here that return the
same Event list. The collector doesn't need to know the difference.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Event


class Source(ABC):
    name: str = "source"
    source_type: str = "generic"

    @abstractmethod
    def collect(self) -> list[Event]:
        """Fetch from the source and return normalized Events."""
        raise NotImplementedError

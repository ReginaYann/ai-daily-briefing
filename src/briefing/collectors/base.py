"""BaseCollector — every source implements this."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import AppConfig, Secrets
from ..models import Item


class BaseCollector(ABC):
    """A collector pulls items from one source.

    Subclasses must set ``name`` and implement ``collect``. ``collect`` is async
    so collectors can run concurrently in the pipeline.
    """

    name: str = ""

    def __init__(self, config: AppConfig, secrets: Secrets) -> None:
        self.config = config
        self.secrets = secrets

    @abstractmethod
    async def collect(self) -> list[Item]:
        """Return a list of normalized Items. Should not raise on empty."""
        ...

    def is_enabled(self) -> bool:
        """Default: look up `collectors.<name>.enabled`. Override if needed."""
        node = getattr(self.config.collectors, self.name, None)
        return bool(getattr(node, "enabled", False))

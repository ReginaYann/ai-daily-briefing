"""Registry for collector classes — discover via decorator."""
from __future__ import annotations

from typing import Type

from .base import BaseCollector


_REGISTRY: dict[str, Type[BaseCollector]] = {}


def register_collector(cls: Type[BaseCollector]) -> Type[BaseCollector]:
    """Class decorator. Requires the class to set a non-empty ``name`` attribute."""
    if not getattr(cls, "name", ""):
        raise ValueError(f"{cls.__name__} must set a `name` class attribute to register")
    if cls.name in _REGISTRY:
        raise ValueError(f"collector name '{cls.name}' already registered")
    _REGISTRY[cls.name] = cls
    return cls


def get_registry() -> dict[str, Type[BaseCollector]]:
    return dict(_REGISTRY)


def all_collector_names() -> list[str]:
    return sorted(_REGISTRY.keys())

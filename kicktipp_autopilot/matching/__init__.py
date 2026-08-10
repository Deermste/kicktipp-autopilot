"""Zuordnung von Vorhersagen zu Kicktipp-Spielen."""

from .matcher import TeamMatcher, load_aliases
from .normalize import normalize

__all__ = ["TeamMatcher", "load_aliases", "normalize"]

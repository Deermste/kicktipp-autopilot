"""Zielplattformen, bei denen Tipps abgegeben werden."""

from .base import TippTarget
from .kicktipp import KicktippBrowser
from .kicktipp_http import KicktippHttp
from .kicktipp_parse import TippabgabePage

__all__ = ["TippTarget", "KicktippBrowser", "KicktippHttp", "TippabgabePage"]

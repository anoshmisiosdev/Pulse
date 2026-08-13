"""Visitor identity provider adapters."""

from app.visitor_intelligence.providers.base import NormalizedVisitorSignal
from app.visitor_intelligence.providers.rb2b import Rb2bAdapter

__all__ = ["NormalizedVisitorSignal", "Rb2bAdapter"]

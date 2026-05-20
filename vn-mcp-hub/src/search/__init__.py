"""Federated multi-search backends — reusable direct functions.

Each backend exports a single function taking (query, limit) -> list[dict].
Backends that fail (no API key, network error, rate limit) return [] silently
so the orchestrator can continue with other sources.
"""

# Re-export direct search functions for the orchestrator
from src.search.semantic_scholar import semantic_scholar_search
from src.search.crossref import crossref_search

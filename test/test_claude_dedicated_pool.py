"""Regression guard for the dedicated Claude route's pool failover binding.

The local fallback test interpreter is Python 3.9 while the application targets
3.10+, so this intentionally inspects the route AST instead of importing its
Pydantic model (which uses ``X | None`` annotations).
"""

from __future__ import annotations

import ast
from pathlib import Path


_SOURCE = (Path(__file__).resolve().parents[1] / "api" / "claude.py").read_text(encoding="utf-8")


def _calls(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for item in ast.walk(node):
        if not isinstance(item, ast.Call):
            continue
        if isinstance(item.func, ast.Name):
            out.add(item.func.id)
        elif isinstance(item.func, ast.Attribute) and isinstance(item.func.value, ast.Name):
            out.add(f"{item.func.value.id}.{item.func.attr}")
    return out


def test_dedicated_claude_route_uses_pool_handler_not_single_backend() -> None:
    tree = ast.parse(_SOURCE)
    factory = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_router")
    endpoint = next(n for n in ast.walk(factory)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name == "claude_chat_completions")
    calls = _calls(endpoint)
    assert "handle_claude_chat" in calls
    assert "_backend.chat" not in calls

"""Multi-signal lexical ranking for HA local intent (inspired by assist-canonicalizer).

Lightweight pure-Python ensemble (no rapidfuzz dependency):
  - token Jaccard (word overlap)
  - character 3-gram Jaccard
  - sequence ratio (order-aware rough similarity)
  - intent-action affinity (on/off opposing safety)

Used when entity name is ambiguous (multiple entities share a name without area).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


# Weights sum ≈ 1.0 (assist-canonicalizer style ensemble)
W_TOKEN = 0.40
W_CHAR = 0.30
W_SEQ = 0.20
W_INTENT = 0.10

DEFAULT_MIN_CONFIDENCE = 0.55
DEFAULT_MIN_MARGIN = 0.08

_OPPOSING = {
    frozenset({"HassTurnOn", "HassTurnOff"}),
    frozenset({"HassMediaUnpause", "HassMediaPause"}),
    frozenset({"HassOpenCover", "HassCloseCover"}),
}


def _tokens(s: str) -> list[str]:
    return [t for t in (s or "").lower().split() if t]


def _char_ngrams(s: str, n: int = 3) -> set[str]:
    s = (s or "").lower().replace(" ", "")
    if len(s) < n:
        return {s} if s else set()
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _seq_ratio(a: str, b: str) -> float:
    """Rough order-aware similarity (Difflib-style ratio without import)."""
    a, b = (a or "").lower(), (b or "").lower()
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    # longest common subsequence length / max len
    la, lb = len(a), len(b)
    dp = [0] * (lb + 1)
    for i in range(1, la + 1):
        prev = 0
        for j in range(1, lb + 1):
            cur = dp[j]
            if a[i - 1] == b[j - 1]:
                dp[j] = prev + 1
            else:
                dp[j] = max(dp[j], dp[j - 1])
            prev = cur
    lcs = dp[lb]
    return (2.0 * lcs) / (la + lb)


def _intent_affinity(service: str, query: str) -> float:
    q = (query or "").lower()
    on_words = ("bat", "bật", "mo", "mở", "on", "turn on", "enable")
    off_words = ("tat", "tắt", "dong", "đóng", "off", "turn off", "disable")
    if service == "HassTurnOn":
        return 1.0 if any(w in q for w in on_words) else 0.5
    if service == "HassTurnOff":
        return 1.0 if any(w in q for w in off_words) else 0.5
    return 0.6


@dataclass(frozen=True, slots=True)
class RankedHit:
    key: str
    score: float
    token: float
    char: float
    seq: float
    intent: float
    payload: Any = None


def score_candidate(
    query: str,
    candidate: str,
    *,
    service: str = "",
) -> RankedHit:
    qt, ct = _tokens(query), _tokens(candidate)
    t = _jaccard(set(qt), set(ct))
    c = _jaccard(_char_ngrams(query), _char_ngrams(candidate))
    s = _seq_ratio(query, candidate)
    i = _intent_affinity(service, query) if service else 0.6
    final = W_TOKEN * t + W_CHAR * c + W_SEQ * s + W_INTENT * i
    return RankedHit(
        key=candidate, score=final, token=t, char=c, seq=s, intent=i,
    )


def rank_candidates(
    query: str,
    candidates: Sequence[tuple[str, Any]],
    *,
    service: str = "",
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    min_margin: float = DEFAULT_MIN_MARGIN,
) -> RankedHit | None:
    """candidates: list of (label, payload). Return best if passes gates."""
    if not candidates:
        return None
    scored: list[RankedHit] = []
    for label, payload in candidates:
        h = score_candidate(query, label, service=service)
        scored.append(RankedHit(
            key=h.key, score=h.score, token=h.token, char=h.char,
            seq=h.seq, intent=h.intent, payload=payload,
        ))
    scored.sort(key=lambda x: x.score, reverse=True)
    best = scored[0]
    if best.score < min_confidence:
        return None
    # margin vs next different payload
    for other in scored[1:]:
        if other.payload != best.payload:
            if (best.score - other.score) < min_margin:
                return None
            break
    return best


def pick_entity_among(
    query_tokens: list[str],
    candidates: list[tuple[str, str, str]],
    *,
    service: str = "",
    area_hint: str = "",
) -> tuple[str, str, str] | None:
    """Pick (eid, domain, orig_name) from ambiguous candidates.

    candidates: list of (eid, domain, orig_friendly_name)
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    q = " ".join(query_tokens)
    if area_hint:
        q = f"{q} {area_hint}"
    labeled = [(c[2], c) for c in candidates]  # friendly name as label
    hit = rank_candidates(q, labeled, service=service)
    if not hit or not hit.payload:
        return None
    return hit.payload  # type: ignore[return-value]


def services_are_opposing(a: str, b: str) -> bool:
    return frozenset({a, b}) in _OPPOSING

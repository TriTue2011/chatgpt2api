"""Multi-signal lexical ranking for HA local intent (inspired by assist-canonicalizer).

Lightweight pure-Python ensemble (no rapidfuzz dependency):
  - word similarity  (char LCS + token-sort LCS + token-set overlap, cả ba bị
    phạt theo chênh lệch độ dài — cùng bộ ba mà rapidfuzz dùng)
  - character 3-gram Jaccard
  - BM25 keyword relevance chấm trên chính tập ứng viên (token hiếm — tên riêng
    của thiết bị — nặng hơn token phổ biến như "đèn", "phòng")
  - intent-action affinity (on/off opposing safety)

Mọi chuỗi được chuẩn hoá NFKC → bỏ dấu → bỏ dấu câu ở NGAY TRONG module này,
nên nơi gọi có thể trộn tên gốc ("Đèn ngủ") với câu đã bỏ dấu ("den phong ngu")
mà vẫn so đúng.

Dùng khi tên thiết bị nhập nhằng (nhiều entity trùng tên) và khi câu nói không
khớp chính xác tên nào (lỗi nhận dạng giọng nói, gọi tắt).

Điểm tổng CAO chưa đủ để điều khiển: đường khớp mờ còn phải qua cổng CĂN TỪ
(_tokens_aligned) — mỗi từ trong câu phải có một từ tương ứng riêng ở ứng viên.
Đó là chỗ phân biệt "nói sai chính tả" (nhận) với "nói thiết bị khác" (loại).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from math import log
from typing import Any, Sequence


# Weights sum = 1.0 (assist-canonicalizer style ensemble)
W_WORD = 0.33
W_CHAR = 0.32
W_BM25 = 0.20
W_INTENT = 1.0 - (W_WORD + W_CHAR + W_BM25)

DEFAULT_MIN_CONFIDENCE = 0.55
DEFAULT_MIN_MARGIN = 0.08

# Cổng cho đường KHỚP MỜ (pick_entity_fuzzy) — cao hơn mặc định vì ở đó không
# có tên nào khớp chính xác để neo vào. Đo 11/08 trên bộ 20 thiết bị mô phỏng:
# 11/12 câu lỗi-ASR nhận đúng, 0 chọn sai, 0/10 câu vu vơ bị nhận nhầm.
FUZZY_MIN_CONFIDENCE = 0.62
FUZZY_MIN_MARGIN = 0.10
FUZZY_MAX_TOKENS = 6  # dài hơn = cả câu, để model xử lý

# Chỉ chấm điểm đầy đủ cho ngần này ứng viên tốt nhất theo sàng lọc n-gram (rẻ).
# LCS là O(n·m) nên quét thẳng vài trăm thiết bị sẽ chậm thấy rõ.
PREFILTER_TOP = 24

_BM25_K1 = 1.5
_BM25_B = 0.75

_OPPOSING = {
    frozenset({"HassTurnOn", "HassTurnOff"}),
    frozenset({"HassMediaUnpause", "HassMediaPause"}),
    frozenset({"HassOpenCover", "HassCloseCover"}),
}

_NON_WORD_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


@lru_cache(maxsize=8192)
def normalize(text: str) -> str:
    """NFKC + thường hoá + bỏ dấu Latin + bỏ dấu câu + gộp khoảng trắng.

    "Đèn ngủ, Phòng ngủ!" và "den ngu phong ngu" cho ra cùng một chuỗi.
    """
    s = unicodedata.normalize("NFKC", text or "").casefold().replace("đ", "d")
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if not unicodedata.combining(c))
    return _WS_RE.sub(" ", _NON_WORD_RE.sub(" ", s)).strip()


def _tokens(s: str) -> list[str]:
    return [t for t in s.split() if t]


def _char_ngrams(s: str, n: int = 3) -> set[str]:
    s = s.replace(" ", "")
    if len(s) < n:
        return {s} if s else set()
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def _seq_ratio(a: str, b: str) -> float:
    """Order-aware similarity: 2·LCS / (len a + len b)."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    la, lb = len(a), len(b)
    dp = [0] * (lb + 1)
    for i in range(1, la + 1):
        prev = 0
        ai = a[i - 1]
        for j in range(1, lb + 1):
            cur = dp[j]
            if ai == b[j - 1]:
                dp[j] = prev + 1
            elif dp[j - 1] > dp[j]:
                dp[j] = dp[j - 1]
            prev = cur
    return (2.0 * dp[lb]) / (la + lb)


def _word_sim(q: str, c: str, qt: list[str], ct: list[str]) -> float:
    """Bộ ba của rapidfuzz, viết bằng Python thuần.

    - LCS trên chuỗi thô: bắt lỗi chính tả / thiếu chữ.
    - LCS trên token đã sắp xếp: bỏ qua thứ tự từ.
    - Độ phủ tập token, nhân với tỉ lệ độ dài: phạt ứng viên tên ngắn cụt
      ("đèn") khi câu nói dài ("đèn ngủ phòng ngủ").
    """
    if not q or not c:
        return 0.0
    char_lcs = _seq_ratio(q, c)
    sort_lcs = _seq_ratio(" ".join(sorted(qt)), " ".join(sorted(ct)))
    qs, cs = set(qt), set(ct)
    overlap = len(qs & cs) / min(len(qs), len(cs)) if qs and cs else 0.0
    len_ratio = min(len(qt), len(ct)) / max(len(qt), len(ct)) if qt and ct else 0.0
    return (char_lcs + sort_lcs + overlap * len_ratio) / 3.0


def _bm25_scores(query_tokens: list[str], docs: list[list[str]]) -> list[float]:
    """BM25 trên chính tập ứng viên, chuẩn hoá về [0,1] theo điểm cao nhất.

    IDF tính trong phạm vi `docs` được truyền vào (tức tập đã sàng lọc), không
    phải toàn kho thiết bị: ở đây chỉ cần biết từ nào PHÂN BIỆT được các ứng
    viên đang chung kết với nhau.
    """
    n = len(docs)
    if not n or not query_tokens:
        return [0.0] * n
    lengths = [len(d) for d in docs]
    total = sum(lengths)
    if not total:
        return [0.0] * n
    avg = total / n
    df: dict[str, int] = {}
    for d in docs:
        for tok in set(d):
            df[tok] = df.get(tok, 0) + 1
    raw = [0.0] * n
    for tok in set(query_tokens):
        freq_docs = df.get(tok)
        if not freq_docs:
            continue
        idf = log(1 + (n - freq_docs + 0.5) / (freq_docs + 0.5))
        for i, d in enumerate(docs):
            tf = d.count(tok)
            if not tf:
                continue
            denom = tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * lengths[i] / avg)
            raw[i] += idf * (_BM25_K1 + 1) * tf / denom
    top = max(raw)
    return [r / top for r in raw] if top > 0 else raw


_ON_WORDS = frozenset({"bat", "mo", "on", "enable"})
_OFF_WORDS = frozenset({"tat", "dong", "off", "disable"})


def _intent_affinity(service: str, query: str) -> float:
    """So theo TỪ, không theo chuỗi con: "phòng" chứa "on" nhưng không phải
    động từ bật. Câu đưa vào thường đã cắt bỏ động từ (đoạn sau động từ), khi
    đó tín hiệu này là hằng số cho mọi ứng viên và chỉ dịch thang điểm."""
    toks = set(query.split())
    if service == "HassTurnOn":
        return 1.0 if (toks & _ON_WORDS or "turn on" in query) else 0.5
    if service == "HassTurnOff":
        return 1.0 if (toks & _OFF_WORDS or "turn off" in query) else 0.5
    return 0.6


# Từ đệm cuối câu tiếng Việt — không chỉ thiết bị nào ("bật đèn ngủ cho anh
# nhé"). Bỏ khi so khớp, nếu không chúng luôn là từ "không căn được".
_FILLER = frozenset({
    "cho", "toi", "minh", "anh", "em", "giup", "gium", "dum",
    "di", "nhe", "luon", "the", "voi", "day",
})

# Ngưỡng CĂN TỪ theo độ dài từ (assist-canonicalizer: từ càng ngắn càng phải
# giống, vì một chữ sai trên từ 2 chữ là sai hẳn).
_ALIGN_THRESHOLDS = ((2, 0.75), (3, 0.66), (5, 0.60))
_ALIGN_BASE = 0.50


def _tokens_aligned(query_tokens: Sequence[str], cand_tokens: Sequence[str]) -> bool:
    """Mọi từ nội dung trong câu phải tìm được một từ TƯƠNG ỨNG ở ứng viên.

    Đây là chốt chặn phân biệt "sai chính tả" với "sai thiết bị":
      "đèn trần phòng khác" ~ "Đèn trần Phòng khách" → "khac"↔"khach" = 0.89, nhận.
      "quạt trần phòng ngủ" ~ "Đèn trần Phòng ngủ"  → "quat" không có từ nào
      giống (max 0.29), loại — dù tổng điểm vẫn cao vì 3/4 từ trùng.

    Ghép MỘT–MỘT (mỗi từ ứng viên chỉ đỡ được một từ của câu): không thế thì
    "máy sấy nhà tắm" mượn luôn chữ "máy" của "Máy sưởi" mà lọt.
    """
    if not cand_tokens:
        return False
    pairs = sorted(
        (_seq_ratio(q, c), qi, ci)
        for qi, q in enumerate(query_tokens)
        for ci, c in enumerate(cand_tokens)
    )
    matched: dict[int, float] = {}
    used_c: set[int] = set()
    for score, qi, ci in reversed(pairs):
        if qi in matched or ci in used_c:
            continue
        matched[qi] = score
        used_c.add(ci)
    for qi, qt in enumerate(query_tokens):
        limit = _ALIGN_BASE
        for max_len, threshold in _ALIGN_THRESHOLDS:
            if len(qt) <= max_len:
                limit = threshold
                break
        if matched.get(qi, 0.0) < limit:
            return False
    return True


@dataclass(frozen=True, slots=True)
class RankedHit:
    key: str
    score: float
    word: float
    char: float
    bm25: float
    intent: float
    payload: Any = None


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
    q = normalize(query)
    qt = _tokens(q)
    q_grams = _char_ngrams(q)
    norm = [(normalize(label), payload) for label, payload in candidates]

    # Sàng lọc bằng n-gram (chỉ phép tập hợp) trước khi chạy LCS.
    pool = list(range(len(norm)))
    char_scores = [_jaccard(q_grams, _char_ngrams(c)) for c, _ in norm]
    if len(pool) > PREFILTER_TOP:
        pool.sort(key=lambda i: char_scores[i], reverse=True)
        pool = pool[:PREFILTER_TOP]

    docs = [_tokens(norm[i][0]) for i in pool]
    bm25 = _bm25_scores(qt, docs)
    intent = _intent_affinity(service, q) if service else 0.6

    scored: list[RankedHit] = []
    for slot, i in enumerate(pool):
        c, payload = norm[i]
        ct = docs[slot]
        w = _word_sim(q, c, qt, ct)
        ch = char_scores[i]
        final = W_WORD * w + W_CHAR * ch + W_BM25 * bm25[slot] + W_INTENT * intent
        scored.append(RankedHit(
            key=candidates[i][0], score=final, word=w, char=ch,
            bm25=bm25[slot], intent=intent, payload=payload,
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


def pick_entity_fuzzy(
    seg_tokens: Sequence[str],
    ent_by_name: dict[str, list[tuple[str, str, str]]],
    area_of: dict[str, str],
    *,
    service: str = "",
    skip_tokens: frozenset[str] | set[str] = frozenset(),
) -> tuple[str, str, str] | None:
    """Đoạn nói KHÔNG khớp chính xác tên thiết bị nào → chọn thiết bị gần nhất.

    Bắt lỗi nhận dạng giọng nói ("đèn trần phòng khác"), tên dính chữ, gọi
    thiếu chữ. Nhãn xếp hạng = tên thiết bị + tên khu vực, nên "phòng khác"
    vẫn kéo được về đúng "Đèn trần / Phòng khách".

    ent_by_name: {tên đã gấp dấu: [(entity_id, domain, tên gốc)…]} — gồm cả alias.
    area_of:     {entity_id: tên khu vực} (tên gốc, module tự chuẩn hoá).

    Cổng CHẶT hơn mặc định: chọn nhầm ở đây là điều khiển nhầm thiết bị, mà
    không qua cổng thì vẫn còn model đỡ. Trả None nghĩa là "không đủ chắc".
    """
    words = [t for t in seg_tokens
             if len(t) > 1 and t not in skip_tokens and t not in _FILLER]
    if not words or len(words) > FUZZY_MAX_TOKENS:
        return None
    labeled: list[tuple[str, tuple[str, str, str]]] = []
    for name, cands in ent_by_name.items():
        for ent in cands:
            area = normalize(area_of.get(ent[0]) or "")
            labeled.append((f"{name} {area}".strip(), ent))
    if not labeled:
        return None
    query = " ".join(words)
    hit = rank_candidates(
        query, labeled, service=service,
        min_confidence=FUZZY_MIN_CONFIDENCE, min_margin=FUZZY_MIN_MARGIN,
    )
    # Căn từ phải so trên CÙNG một dạng chuẩn hoá: "đèn" gấp dấu ra "đen" còn
    # nhãn chuẩn hoá ra "den", để nguyên thì chính chữ đúng lại bị coi là lệch.
    if not hit or not _tokens_aligned(
        _tokens(normalize(query)), _tokens(normalize(hit.key))
    ):
        return None
    return hit.payload  # type: ignore[return-value]


def services_are_opposing(a: str, b: str) -> bool:
    return frozenset({a, b}) in _OPPOSING

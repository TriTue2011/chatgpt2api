"""Hạn mức thật của tài khoản Codex — đọc từ chính lưu lượng đang chạy.

VÌ SAO CÓ FILE NÀY
------------------
Màn hình Tài khoản vẽ bốn thanh `limits_progress` (nghiên cứu sâu, tải tệp, dán
văn bản, tạo ảnh). Với tài khoản **free** thì đó đúng là hạn mức của họ. Với tài
khoản **codex** thì không: thứ khiến chúng thành `limited` là hạn mức chữ của
Codex — cửa sổ chính và cửa sổ phụ. Hai đồng hồ khác nhau, và
`services/account_service.py::giu_han_nghi` đã phải sinh ra chỉ để chúng không
xoá kết quả của nhau.

Bản trước (`usage_snapshot_poller`) cứ 15 giây gọi
`/backend-api/sentinel/chat-requirements` — endpoint chống bot, không phải
endpoint hạn mức. Đo trên máy chủ 08/08/2026: 0/3 tài khoản có phần trăm, 0/3 có
email hoặc gói, 2/3 trả `unauthorized`, và **6 tài khoản codex bị gộp còn 3** vì
nó lấy `access_token[:40]` làm khoá — 40 ký tự đầu của một JWT là phần header,
giống hệt nhau giữa các tài khoản cùng nguồn phát.

Ở đây không thăm dò nữa. Mỗi phản hồi Codex mà c2a vốn đã nhận đều mang sẵn họ
header `x-codex-*`; đọc chúng không tốn thêm request nào và luôn tươi hơn mọi
chu kỳ 15 giây. `/backend-api/wham/usage` chỉ dùng khi cần bức tranh đầy đủ
(email, gói, credit reset) mà lưu lượng không mang theo.

ĐO THẬT 08/08/2026 — phản hồi 429 của `/backend-api/codex/responses`:

    x-codex-plan-type: go              x-codex-active-limit: premium
    x-codex-primary-used-percent: 100  x-codex-secondary-used-percent: 0
    x-codex-primary-window-minutes: 43200
    x-codex-primary-reset-at: 1788148926
    x-codex-credits-has-credits: False x-codex-credits-unlimited: False

Không có `x-codex-account-email` — email chỉ lấy được từ claim của JWT hoặc từ
`/wham/usage`. Bản cũ đọc header đó nên trường email luôn rỗng.

Tên header theo `codex-rs/codex-api/src/rate_limits.rs` của openai/codex.
"""
from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
from typing import Any

from utils.log import logger

# Endpoint hạn mức chính thức của Codex. `/backend-api` là dạng đường dẫn
# ChatGPT (`PathStyle::ChatGptApi`); bản Codex API dùng `/api/codex/usage`.
WHAM_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"

# Gọi `/wham/usage` là một request thật. Trong khoảng này thì dùng lại bản đã có
# thay vì hỏi lại — màn hình Tài khoản mở đi mở lại không nhân lên thành tải.
TTL_WHAM_GIAY = 120

TIMEOUT_GIAY = 20


def _bam(token: str) -> str:
    """Khoá kho: băm TOÀN BỘ token.

    Bản cũ dùng `token[:40]`, và vì 40 ký tự đầu của một JWT chỉ là phần header
    đã base64 nên nhiều tài khoản khác nhau ra cùng một khoá — bản ghi của tài
    khoản này ghi đè bản ghi của tài khoản kia, im lặng.
    """
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def claims_tu_token(token: str) -> dict[str, Any]:
    """Giải phần payload của JWT. Trả `{}` nếu không phải JWT.

    Không xác thực chữ ký: ta chỉ đọc claim của chính token mình đang giữ để
    biết email/gói, không dùng nó để cấp quyền cho ai.
    """
    try:
        phan = (token or "").split(".")
        if len(phan) < 2:
            return {}
        p = phan[1]
        p += "=" * (-len(p) % 4)
        ra = json.loads(base64.urlsafe_b64decode(p))
        return ra if isinstance(ra, dict) else {}
    except Exception:
        return {}


def thong_tin_token(token: str) -> dict[str, Any]:
    """Email, gói và account_id lấy từ claim của access token.

    `chatgpt_account_id` là thứ phải gửi lại dưới dạng header
    `ChatGPT-Account-Id`; thiếu nó thì tài khoản thuộc workspace gọi đâu hỏng đó.
    """
    c = claims_tu_token(token)
    if not c:
        return {"la_jwt": False, "email": "", "plan": "", "account_id": ""}
    auth = c.get("https://api.openai.com/auth") or {}
    profile = c.get("https://api.openai.com/profile") or {}
    return {
        "la_jwt": True,
        "email": str(c.get("email") or profile.get("email") or ""),
        "plan": str(auth.get("chatgpt_plan_type") or ""),
        "account_id": str(auth.get("chatgpt_account_id") or ""),
    }


def nhan_cua_so(phut: int | None) -> str:
    """Đổi số phút thành nhãn người đọc được. 43200 phút là '30 ngày'."""
    if not phut or phut <= 0:
        return ""
    if phut % (24 * 60) == 0:
        ngay = phut // (24 * 60)
        return f"{ngay} ngày"
    if phut % 60 == 0:
        return f"{phut // 60} giờ"
    return f"{phut} phút"


def _so(gia_tri: Any) -> float | None:
    try:
        s = str(gia_tri).strip()
        return float(s) if s else None
    except Exception:
        return None


def _nguyen(gia_tri: Any) -> int | None:
    v = _so(gia_tri)
    return int(v) if v is not None else None


def _bool_header(gia_tri: Any) -> bool:
    return str(gia_tri).strip().lower() in {"true", "1", "yes"}


def _cua_so(headers: dict, vai: str) -> dict[str, Any] | None:
    """Dựng một cửa sổ hạn mức từ ba header của nó.

    Không có phần trăm thì coi như cửa sổ đó không tồn tại — Codex vẫn gửi
    `x-codex-secondary-window-minutes: 0` cho tài khoản chỉ có một cửa sổ, nên
    không thể lấy sự hiện diện của header làm căn cứ.
    """
    pct = _so(headers.get(f"x-codex-{vai}-used-percent"))
    if pct is None:
        return None
    phut = _nguyen(headers.get(f"x-codex-{vai}-window-minutes"))
    reset_at = _nguyen(headers.get(f"x-codex-{vai}-reset-at"))
    con_lai = _nguyen(headers.get(f"x-codex-{vai}-reset-after-seconds"))
    if not pct and not phut and not reset_at:
        return None      # toàn số 0 — cửa sổ này không dùng
    return {
        "da_dung_pct": pct,
        "con_lai_pct": max(0.0, round(100.0 - pct, 1)),
        "cua_so_phut": phut,
        "nhan": nhan_cua_so(phut),
        "reset_at": reset_at,
        "con_bao_lau_giay": con_lai,
    }


def doc_header(headers: dict[str, Any]) -> dict[str, Any] | None:
    """Đọc họ header `x-codex-*` thành một bản ghi hạn mức.

    Trả `None` khi phản hồi không mang header nào — phần lớn phản hồi 4xx sớm
    (400 sai model, 401 hết hạn) rơi vào nhóm này.
    """
    if not headers:
        return None
    h = {str(k).lower(): v for k, v in headers.items()}
    chinh = _cua_so(h, "primary")
    phu = _cua_so(h, "secondary")
    plan = str(h.get("x-codex-plan-type") or "").strip()
    if chinh is None and phu is None and not plan:
        return None
    return {
        "nguon": "header",
        "plan": plan,
        "gioi_han_dang_ap": str(h.get("x-codex-active-limit") or "").strip(),
        "chinh": chinh,
        "phu": phu,
        "cham_tran": bool(chinh and chinh["da_dung_pct"] >= 100),
        "credit_du": _bool_header(h.get("x-codex-credits-has-credits")),
        "credit_khong_gioi_han": _bool_header(h.get("x-codex-credits-unlimited")),
        "luc_do": time.time(),
    }


def _cua_so_tu_json(w: Any) -> dict[str, Any] | None:
    """Cùng hình dạng cửa sổ, nhưng dựng từ thân JSON của `/wham/usage`.

    JSON đo bằng GIÂY (`limit_window_seconds`) còn header đo bằng PHÚT — đổi về
    phút để hai nguồn ra cùng một hình dạng, nếu không giao diện phải biết dữ
    liệu đến từ đâu mới vẽ được.
    """
    if not isinstance(w, dict):
        return None
    pct = _so(w.get("used_percent"))
    if pct is None:
        return None
    giay = _nguyen(w.get("limit_window_seconds"))
    phut = giay // 60 if giay else None
    return {
        "da_dung_pct": pct,
        "con_lai_pct": max(0.0, round(100.0 - pct, 1)),
        "cua_so_phut": phut,
        "nhan": nhan_cua_so(phut),
        "reset_at": _nguyen(w.get("reset_at")),
        "con_bao_lau_giay": _nguyen(w.get("reset_after_seconds")),
    }


def doc_wham(payload: dict[str, Any]) -> dict[str, Any]:
    """Đọc thân JSON `/wham/usage`. Giàu hơn header: có email và credit reset."""
    rl = payload.get("rate_limit") or {}
    credits = payload.get("credits") or {}
    reset_credits = payload.get("rate_limit_reset_credits") or {}
    loai = payload.get("rate_limit_reached_type") or {}
    return {
        "nguon": "wham",
        "email": str(payload.get("email") or ""),
        "plan": str(payload.get("plan_type") or ""),
        "gioi_han_dang_ap": "",
        "chinh": _cua_so_tu_json(rl.get("primary_window")),
        "phu": _cua_so_tu_json(rl.get("secondary_window")),
        "cham_tran": bool(rl.get("limit_reached")),
        "credit_du": bool(credits.get("has_credits")),
        "credit_khong_gioi_han": bool(credits.get("unlimited")),
        # Credit reset hạn mức là thứ KHÁC với `credits` ở trên: nó cho phép xoá
        # sạch cửa sổ hiện tại ngay lập tức, mỗi credit dùng được một lần.
        "credit_reset": _nguyen(reset_credits.get("available_count")) or 0,
        "ly_do_cham_tran": str(loai.get("type") or ""),
        "luc_do": time.time(),
    }


class KhoHanMuc:
    """Kho trong bộ nhớ, khoá bằng băm đầy đủ của token."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ban_ghi: dict[str, dict[str, Any]] = {}

    def ghi(self, token: str, ban_ghi: dict[str, Any] | None) -> None:
        if not token or not ban_ghi:
            return
        khoa = _bam(token)
        with self._lock:
            cu = self._ban_ghi.get(khoa) or {}
            # `/wham/usage` mang email + credit mà header không có. Ghi đè bằng
            # bản header sẽ xoá mất chúng, nên chỉ bổ sung những trường bản mới
            # thật sự nói tới.
            gop = dict(cu)
            gop.update({k: v for k, v in ban_ghi.items() if v not in (None, "")})
            gop["luc_do"] = ban_ghi.get("luc_do") or time.time()
            gop["nguon"] = ban_ghi.get("nguon") or cu.get("nguon") or ""
            self._ban_ghi[khoa] = gop

    def lay(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        with self._lock:
            ban = self._ban_ghi.get(_bam(token))
            return dict(ban) if ban else None

    def qua_cu(self, token: str, ttl: float = TTL_WHAM_GIAY) -> bool:
        ban = self.lay(token)
        if not ban or ban.get("nguon") != "wham":
            return True
        return (time.time() - float(ban.get("luc_do") or 0)) > ttl

    def xoa_ngoai(self, tokens: list[str]) -> None:
        """Bỏ bản ghi của tài khoản đã xoá khỏi pool."""
        giu = {_bam(t) for t in tokens if t}
        with self._lock:
            for khoa in list(self._ban_ghi):
                if khoa not in giu:
                    self._ban_ghi.pop(khoa, None)

    def tat_ca(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {k: dict(v) for k, v in self._ban_ghi.items()}


kho_han_muc = KhoHanMuc()


def ghi_nhan_tu_header(token: str, headers: Any) -> None:
    """Cắm vào mọi phản hồi Codex. Không bao giờ được ném ra ngoài.

    Đây nằm trên đường đi của một cú chat thật; một lỗi đọc header không được
    phép làm hỏng câu trả lời của người dùng.
    """
    try:
        ban = doc_header(dict(headers) if headers else {})
        if ban:
            kho_han_muc.ghi(token, ban)
    except Exception:
        pass


def doc_tu_mang(token: str) -> dict[str, Any] | None:
    """Gọi `/wham/usage` một lần. Chỉ dùng khi cần email/credit hoặc chưa có gì.

    Trả `None` nếu token không phải JWT — ba tài khoản codex trên máy chủ đang
    giữ token phiên (JWE / blob đăng nhập) chứ không phải access token, và mọi
    lời gọi bằng chúng chỉ đổi lấy 401.
    """
    tt = thong_tin_token(token)
    if not tt["la_jwt"]:
        return None
    try:
        from curl_cffi import requests
    except Exception:
        return None
    h = {"Authorization": f"Bearer {token}", "User-Agent": "codex-cli"}
    if tt["account_id"]:
        # Tài khoản thuộc workspace bắt buộc có header này.
        h["ChatGPT-Account-Id"] = tt["account_id"]
    try:
        r = requests.get(WHAM_USAGE_URL, headers=h, timeout=TIMEOUT_GIAY,
                         impersonate="chrome110")
    except Exception as exc:
        logger.debug({"event": "codex_usage_loi_mang", "loi": str(exc)[:120]})
        return None
    if r.status_code != 200:
        logger.info({"event": "codex_usage_khong_200", "status": r.status_code,
                     "email": tt["email"][:80]})
        return None
    try:
        ban = doc_wham(r.json())
    except Exception:
        return None
    kho_han_muc.ghi(token, ban)
    return ban


def lam_moi(token: str, ttl: float = TTL_WHAM_GIAY) -> dict[str, Any] | None:
    """Bản ghi mới nhất; chỉ ra mạng khi bản đang có đã quá hạn TTL."""
    if kho_han_muc.qua_cu(token, ttl):
        moi = doc_tu_mang(token)
        if moi:
            return moi
    return kho_han_muc.lay(token)

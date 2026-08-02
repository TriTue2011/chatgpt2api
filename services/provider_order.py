"""Thứ tự provider trong combo — cạn tài khoản thì xuống cuối, hồi thì về chỗ cũ.

Yêu cầu của chủ máy 02/08: "khi 1 provider cạn hết các tài khoản thì tạm thời cho
xuống dưới nhưng chỉ cần nó khôi phục là đưa về vị trí đầu vì thường đó là
provider tốt nhất".

KHÁC GÌ HAI TẦNG ĐÃ CÓ:

  · `provider_circuit` — provider fail LIÊN TIẾP thì **bỏ qua hẳn** trong 60s.
    Bỏ qua khác với xếp cuối: provider bị bỏ qua không còn là đường thoát nữa,
    nên nó phải chừa route cuối ra để combo khỏi chết cứng.
  · `model_cooldown` khoá `combo:<tên>` — nghỉ theo từng cặp provider+model,
    cũng là **bỏ qua**, và bậc nghỉ cho 429 bắt đầu từ 1 giây.

Tầng này không bỏ qua gì cả: nó chỉ **đổi thứ tự**. Provider cạn tụt xuống cuối
danh sách (vẫn được thử nếu mọi thứ trên nó chết), và vì thứ tự luôn tính lại từ
cấu hình gốc nên lúc nó hồi là nó tự về đúng vị trí cũ — thường là số 1.

CHỈ HẠ KHI CẠN CẢ POOL, KHÔNG HẠ VÌ MỘT CÚ 429
Một cú 429 nghĩa là MỘT tài khoản cạn, và provider tự xoay tài khoản khác
(`_handle_openai_oauth_chat` thử tới 8 tài khoản một lượt). Hạ provider ở đó là
hạ oan. Dấu hiệu cạn cả pool là lúc provider không còn credential nào để lấy —
những câu lỗi thật trong kho code:

    "No Codex OAuth tokens available. Add via OAuth login or import 9router backup."
    "All Gemini API keys rate limited. Try again later."          (gemini_free)
    "All NVIDIA NIM API keys rate limited"                        (nvidia_nim)
    "Agnes AI key not configured"                                 (agnes)
    "[tokenrouter] chưa có API key trong cấu hình"                (tokenrouter)
    "no available image quota"                                    (account_service)

HAI ĐƯỜNG VỀ VỊ TRÍ CŨ
  1. Provider có pool tài khoản (codex, chatgpt free, claude, gemini web): hỏi
     thẳng pool. Có một tài khoản dùng được là hết hạ NGAY — không chờ hết giờ.
  2. Provider dùng API key (gemini_free, nvidia_nim, agnes, tokenrouter): không
     có pool để hỏi, nên hết cửa sổ `provider_demote_seconds` thì thử lại.

Tắt bằng `smart_pool.enabled=false` → `reorder()` trả nguyên thứ tự cấu hình.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from services.config import config
from utils.log import logger

# Cửa sổ hạ mặc định cho provider KHÔNG hỏi được pool (dùng API key).
_MAC_DINH_GIAY = 900

# Câu lỗi nghĩa là "provider này không còn credential nào" — xem docstring cho
# nguyên văn từng provider. Chỉ những câu này mới hạ, 429 lẻ thì không.
_CAN_POOL = (
    # "No Codex OAuth tokens available" và cả thứ tự ngược "no available image quota"
    re.compile(r"\bno\b[^.]{0,40}\b(token|key|account|credential|quota)s?\b[^.]{0,20}\bavailable\b", re.I),
    re.compile(r"\bno available\b[^.]{0,40}\b(token|key|account|credential|quota)s?\b", re.I),
    re.compile(r"\ball\b[^.]{0,40}\b(key|token|account)s?\b[^.]{0,30}"
               r"(rate.?limit|limited|exhaust|failed)", re.I),
    re.compile(r"\bno usable\b", re.I),
    re.compile(r"\bkey not configured\b", re.I),
    re.compile(r"chưa có api key", re.I),
    re.compile(r"key bị giới hạn", re.I),
)

# provider (BackendRoute.provider) → nhóm tài khoản trong account_service.
# Provider nào không có ở đây thì không hỏi được pool → chỉ dùng cửa sổ thời gian.
_NHOM_POOL = {
    "openai_oauth": "codex",
    "codex": "codex",
    "chatgpt": "free",
    "chatgpt_free": "free",
    "claude": "claude",
    "gemini_web_api": "gemini_web_api",
    "antigravity": "antigravity",
}

_TRANG_THAI_CHET = {"disabled", "error", "limited"}


def _bat() -> bool:
    sp = config.data.get("smart_pool")
    if isinstance(sp, dict):
        return bool(sp.get("enabled", True))
    return True


def _cua_so_giay() -> int:
    try:
        sp = config.data.get("smart_pool") or {}
        if isinstance(sp, dict):
            return max(30, int(sp.get("provider_demote_seconds", _MAC_DINH_GIAY)))
    except Exception:
        pass
    return _MAC_DINH_GIAY


def can_pool(error: str = "") -> bool:
    """True khi câu lỗi nói provider hết credential (không phải một tài khoản).

    Chỉ đọc CÂU LỖI, không đọc mã HTTP: 429 là dấu hiệu một tài khoản cạn, mà
    provider tự xoay sang tài khoản khác — mã đó không nói được gì về cả pool.
    """
    text = str(error or "")
    if not text:
        return False
    return any(p.search(text) for p in _CAN_POOL)


def _pool_con_song(provider: str) -> bool | None:
    """Pool của provider còn tài khoản dùng được không?

    None = provider này không có pool để hỏi (dùng API key) → caller dựa vào
    cửa sổ thời gian.
    """
    nhom = _NHOM_POOL.get(str(provider or "").strip())
    if not nhom:
        return None
    try:
        from services.account_service import account_group, account_service
        for acc in list(account_service._accounts.values()):
            if str(acc.get("status") or "") in _TRANG_THAI_CHET:
                continue
            if account_group(acc) == nhom:
                return True
        return False
    except Exception as exc:
        logger.warning({"event": "provider_order_pool_loi", "provider": provider,
                        "error": str(exc)[:120]})
        return None


@dataclass
class TrangThaiHa:
    provider: str
    den_luc: float = 0.0
    ly_do: str = ""
    so_lan: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "con_lai_giay": max(0, round(self.den_luc - time.time())),
            "ly_do": self.ly_do[:120],
            "so_lan_ha": self.so_lan,
        }


class ProviderOrder:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ha: dict[str, TrangThaiHa] = {}

    # ── Ghi nhận ────────────────────────────────────────────────────────────
    def record_failure(self, provider: str, status_code: int = 0, error: str = "") -> None:
        """Hạ provider xuống cuối NẾU lỗi là cạn cả pool. 429 lẻ thì bỏ qua.

        `status_code` nhận vào cho khớp chỗ gọi (đứng ngay cạnh
        `provider_circuit.record_failure`) nhưng CỐ Ý không dùng — xem `can_pool`.
        """
        provider = str(provider or "").strip()
        if not provider or not _bat() or not can_pool(error):
            return
        with self._lock:
            st = self._ha.get(provider) or TrangThaiHa(provider=provider)
            moi = st.den_luc <= time.time()
            st.den_luc = time.time() + _cua_so_giay()
            st.ly_do = str(error or "")[:200]
            if moi:
                st.so_lan += 1
            self._ha[provider] = st
            if moi:
                logger.warning({
                    "event": "provider_ha_xuong_cuoi",
                    "provider": provider,
                    "giay": _cua_so_giay(),
                    "error": st.ly_do[:120],
                })

    def record_success(self, provider: str) -> None:
        """Provider chạy được → về đúng vị trí cấu hình NGAY."""
        provider = str(provider or "").strip()
        if not provider:
            return
        with self._lock:
            if self._ha.pop(provider, None) is not None:
                logger.info({"event": "provider_ve_cho_cu", "provider": provider,
                             "ly_do": "thanh_cong"})

    # ── Tra cứu ─────────────────────────────────────────────────────────────
    def is_demoted(self, provider: str) -> bool:
        provider = str(provider or "").strip()
        if not provider or not _bat():
            return False
        with self._lock:
            st = self._ha.get(provider)
            if st is None:
                return False
            het_gio = time.time() >= st.den_luc
        if het_gio:
            with self._lock:
                self._ha.pop(provider, None)
            logger.info({"event": "provider_ve_cho_cu", "provider": provider,
                         "ly_do": "het_cua_so"})
            return False
        # Pool đã có tài khoản sống lại → về chỗ cũ ngay, không chờ hết cửa sổ.
        if _pool_con_song(provider) is True:
            with self._lock:
                self._ha.pop(provider, None)
            logger.info({"event": "provider_ve_cho_cu", "provider": provider,
                         "ly_do": "pool_hoi"})
            return False
        return True

    def reorder(self, routes: list[Any]) -> list[Any]:
        """Giữ nguyên thứ tự cấu hình cho provider khoẻ, dồn provider bị hạ xuống
        cuối (thứ tự tương đối trong mỗi nhóm không đổi).

        KHÔNG bỏ route nào — combo vẫn còn đủ đường thoát như trước.
        """
        if not _bat() or len(routes) < 2:
            return list(routes)
        try:
            bi_ha = {p for p in {str(getattr(r, "provider", "")) for r in routes}
                     if self.is_demoted(p)}
        except Exception as exc:
            logger.warning({"event": "provider_order_reorder_loi", "error": str(exc)[:120]})
            return list(routes)
        if not bi_ha:
            return list(routes)
        khoe = [r for r in routes if str(getattr(r, "provider", "")) not in bi_ha]
        cuoi = [r for r in routes if str(getattr(r, "provider", "")) in bi_ha]
        logger.info({"event": "provider_doi_thu_tu", "ha": sorted(bi_ha),
                     "dau_moi": str(getattr(khoe[0], "model", "")) if khoe else ""})
        return khoe + cuoi

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            con = {p: st.to_dict() for p, st in self._ha.items()
                   if st.den_luc > time.time()}
        return {
            "enabled": _bat(),
            "cua_so_giay": _cua_so_giay(),
            "so_provider_bi_ha": len(con),
            "providers": con,
        }


# Singleton
provider_order = ProviderOrder()

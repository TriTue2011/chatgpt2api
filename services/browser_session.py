"""Phiên đăng nhập cho TRÌNH DUYỆT — tách khỏi khoá API máy-với-máy.

Vì sao cần: hiện web admin giữ chính `CHATGPT2API_AUTH_KEY` trong
localStorage. Khoá đó mở được MỌI endpoint, sống vĩnh viễn, và bất kỳ đoạn
script nào chạy trong trang cũng đọc được — một lỗ XSS là mất trọn quyền quản
trị, không thu hồi lại được vì khoá còn nằm trong config của HA, Zalo và mọi
script khác.

Phiên trình duyệt sửa đúng ba điểm đó: cookie ``HttpOnly`` nên JavaScript
không đọc được, có hạn dùng, và thu hồi được từng phiên một mà không đụng tới
khoá API.

**Chỉ lưu HASH.** Kho này không giữ session id lẫn CSRF secret ở dạng gốc —
đọc được file cũng không mạo danh được ai. Giá trị gốc chỉ tồn tại một lần,
trong phản hồi của lần đăng nhập.

Khoá Bearer KHÔNG bị đụng tới. Home Assistant, Zalo, script và API ngoài vẫn
đi đường cũ; chỉ trình duyệt admin mới chuyển sang cookie.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

COOKIE_NAME = "c2a_session"
CSRF_HEADER = "X-CSRF-Token"

# 14 ngày: đủ dài để không bắt đăng nhập lại mỗi ngày, đủ ngắn để một máy bị
# bỏ quên không mở cửa mãi mãi.
THOI_HAN_GIAY = 14 * 24 * 3600
# Không hoạt động 3 ngày thì coi như bỏ, kể cả chưa hết hạn tuyệt đối.
IDLE_GIAY = 3 * 24 * 3600
GIOI_HAN_PHIEN = 200          # chặn kho phình vô hạn nếu ai đó gọi login liên tục


def _duong_dan() -> Path:
    goc = os.getenv("DATA_DIR") or str(Path(__file__).resolve().parents[1] / "data")
    return Path(goc) / "browser_sessions.json"


def _bam(gia_tri: str) -> str:
    return hashlib.sha256(gia_tri.encode("utf-8")).hexdigest()


class KhoPhienTrinhDuyet:
    """Kho phiên, lưu ra đĩa để redeploy không đá mọi người ra ngoài."""

    def __init__(self) -> None:
        self._khoa = threading.Lock()
        self._phien: dict[str, dict[str, Any]] = {}
        self._da_nap = False

    # ── đĩa ────────────────────────────────────────────────────────────────
    def _nap(self) -> None:
        if self._da_nap:
            return
        self._da_nap = True
        p = _duong_dan()
        try:
            if p.exists():
                raw = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._phien = {k: v for k, v in raw.items() if isinstance(v, dict)}
        except Exception as exc:
            # Hỏng file phiên KHÔNG được làm chết tiến trình — mất phiên thì
            # đăng nhập lại, còn crash lúc khởi động là mất luôn đường vào.
            logger.warning({"event": "phien_trinh_duyet_nap_loi", "error": str(exc)})
            self._phien = {}

    def _ghi(self) -> None:
        p = _duong_dan()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tam = p.with_suffix(".tmp")
            tam.write_text(json.dumps(self._phien, ensure_ascii=False), encoding="utf-8")
            os.chmod(tam, 0o600)
            tam.replace(p)          # thay nguyên tử, không để lại file nửa vời
        except Exception as exc:
            logger.warning({"event": "phien_trinh_duyet_ghi_loi", "error": str(exc)})

    # ── nghiệp vụ ──────────────────────────────────────────────────────────
    def _con_han(self, ban_ghi: dict[str, Any], bay_gio: float) -> bool:
        return (float(ban_ghi.get("het_han") or 0) > bay_gio
                and bay_gio - float(ban_ghi.get("lan_cuoi") or 0) < IDLE_GIAY)

    def don_het_han(self) -> int:
        with self._khoa:
            self._nap()
            bay_gio = time.time()
            cu = len(self._phien)
            self._phien = {k: v for k, v in self._phien.items()
                           if self._con_han(v, bay_gio)}
            bo = cu - len(self._phien)
            if bo:
                self._ghi()
            return bo

    def tao(self, identity: dict[str, Any]) -> tuple[str, str]:
        """Tạo phiên mới. Trả (session_id, csrf_token) DẠNG GỐC — lần duy nhất."""
        sid = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        bay_gio = time.time()
        with self._khoa:
            self._nap()
            self._phien = {k: v for k, v in self._phien.items()
                           if self._con_han(v, bay_gio)}
            if len(self._phien) >= GIOI_HAN_PHIEN:
                # Bỏ phiên cũ nhất theo lần dùng cuối.
                cu_nhat = min(self._phien, key=lambda k: self._phien[k].get("lan_cuoi") or 0)
                self._phien.pop(cu_nhat, None)
            self._phien[_bam(sid)] = {
                "chu_the": str(identity.get("id") or ""),
                "ten": str(identity.get("name") or ""),
                "vai_tro": str(identity.get("role") or ""),
                "csrf_bam": _bam(csrf),
                "tao_luc": bay_gio,
                "het_han": bay_gio + THOI_HAN_GIAY,
                "lan_cuoi": bay_gio,
            }
            self._ghi()
        return sid, csrf

    def tra_cuu(self, sid: str) -> dict[str, Any] | None:
        """Bản ghi phiên nếu còn hạn. Cập nhật ``lan_cuoi``."""
        if not sid:
            return None
        khoa = _bam(sid)
        bay_gio = time.time()
        with self._khoa:
            self._nap()
            ban_ghi = self._phien.get(khoa)
            if not ban_ghi or not self._con_han(ban_ghi, bay_gio):
                if ban_ghi:
                    self._phien.pop(khoa, None)
                    self._ghi()
                return None
            # Chỉ ghi đĩa khi mốc đã cũ hơn 5 phút — tránh ghi file mỗi request.
            if bay_gio - float(ban_ghi.get("lan_cuoi") or 0) > 300:
                ban_ghi["lan_cuoi"] = bay_gio
                self._ghi()
            else:
                ban_ghi["lan_cuoi"] = bay_gio
            return dict(ban_ghi)

    def kiem_csrf(self, sid: str, csrf: str) -> bool:
        """So HẰNG THỜI GIAN trên bytes.

        Trên bytes vì ``compare_digest`` ném TypeError với chuỗi ngoài ASCII —
        token do ta sinh thì luôn ASCII, nhưng giá trị header là do CLIENT gửi
        và họ gửi được bất cứ thứ gì.
        """
        ban_ghi = self.tra_cuu(sid)
        if not ban_ghi or not csrf:
            return False
        return hmac.compare_digest(_bam(csrf).encode(),
                                   str(ban_ghi.get("csrf_bam") or "").encode())

    def thu_hoi(self, sid: str) -> bool:
        if not sid:
            return False
        with self._khoa:
            self._nap()
            if self._phien.pop(_bam(sid), None) is None:
                return False
            self._ghi()
            return True

    def thu_hoi_het(self) -> int:
        with self._khoa:
            self._nap()
            n = len(self._phien)
            self._phien = {}
            self._ghi()
            return n

    def so_phien(self) -> int:
        with self._khoa:
            self._nap()
            return len(self._phien)


kho_phien = KhoPhienTrinhDuyet()

__all__ = ["COOKIE_NAME", "CSRF_HEADER", "KhoPhienTrinhDuyet", "kho_phien",
           "THOI_HAN_GIAY", "IDLE_GIAY"]

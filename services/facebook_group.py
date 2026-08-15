"""Đăng bài vào NHÓM Facebook — client gọi captcha-solver, cấu hình, hàng đợi nền.

Meta gỡ Groups API từ 22/04/2024 nên KHÔNG có đường chính thức; phần thao tác
trình duyệt nằm ở captcha-solver (`/v1/facebook/group-post`, profile
"facebook" giữ phiên đăng nhập thật qua noVNC). Chủ máy đã nghe rõ rủi ro
checkpoint/khoá tài khoản và chọn làm bằng tài khoản chính (13/08).

File này giữ phần KHÔNG đụng trình duyệt:
  · cấu hình `config.json["facebook"]`: groups=[{id,name}], auto_share_groups
  · nhớ bài Page vừa đăng theo user (để «chia sẻ bài vừa rồi vào nhóm»)
  · hàng đợi nền: đăng lần lượt từng nhóm, giãn cách như người, không giữ
    lượt chat của người dùng trong lúc chạy
"""

from __future__ import annotations

import logging
import random
import re
import threading
import time
from typing import Any

import requests

from services.config import config

logger = logging.getLogger(__name__)

# Giãn cách giữa hai nhóm liên tiếp: người thật không bắn 5 nhóm trong 10 giây.
_GIAN_CACH_S = (90, 240)
_HTTP_TIMEOUT = 180  # trình duyệt mở trang + gõ + chờ preview, chậm là thường

_lock = threading.RLock()
_bai_cuoi: dict[str, dict[str, Any]] = {}   # user_id -> {message, link, ts}
_BAI_TTL = 24 * 3600
_ket_qua: list[str] = []                    # dòng kết quả lần chia sẻ gần nhất
_dang_chay = threading.Event()


def _solver_cfg() -> tuple[str, str]:
    """(url, api_key) captcha-solver — cùng nguồn config với account_recovery."""
    prov = config.data.get("providers") or {}
    for n in ("flow", "gemini_web_api", "gemini_web"):
        c = prov.get(n) or {}
        raw = str(c.get("captcha_solver_url") or "").strip()
        if raw:
            from services.captcha import captcha_base
            return captcha_base(raw), str(c.get("captcha_solver_api_key") or "")
    return "http://127.0.0.1:8010", ""


def _headers() -> dict[str, str]:
    _, key = _solver_cfg()
    h = {"Content-Type": "application/json"}
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


# ── Cấu hình nhóm ────────────────────────────────────────────────────────────

def _fb_cfg() -> dict:
    cfg = (config.get() or {}).get("facebook")
    return dict(cfg) if isinstance(cfg, dict) else {}


def _luu_fb(cap_nhat: dict) -> None:
    config.update({"facebook": {**_fb_cfg(), **cap_nhat}})


def nap_nhom() -> list[dict]:
    ra = []
    for g in _fb_cfg().get("groups") or []:
        if isinstance(g, dict) and str(g.get("id") or "").strip():
            ra.append({"id": str(g["id"]), "name": str(g.get("name") or g["id"])})
    return ra


_NHOM_RE = re.compile(r"facebook\.com/groups/([^/?\s#]+)", re.I)


def them_nhom(text: str) -> list[dict]:
    """Nhặt mọi link nhóm trong `text`, lưu vào config. Trả danh sách vừa thêm.

    Nhận cả id/slug trần (không phải URL) khi cả chuỗi chỉ là một token.
    """
    thay = [m.group(1) for m in _NHOM_RE.finditer(text or "")]
    if not thay:
        t = (text or "").strip()
        if t and re.fullmatch(r"[\w.\-]+", t):
            thay = [t]
    cu = nap_nhom()
    da_co = {g["id"] for g in cu}
    moi = [{"id": gid, "name": gid} for gid in dict.fromkeys(thay)
           if gid not in da_co]
    if moi:
        _luu_fb({"groups": cu + moi})
    return moi


def go_het_nhom() -> int:
    n = len(nap_nhom())
    _luu_fb({"groups": []})
    return n


def auto_share_bat() -> bool:
    return bool(_fb_cfg().get("auto_share_groups"))


def doi_auto_share() -> bool:
    moi = not auto_share_bat()
    _luu_fb({"auto_share_groups": moi})
    return moi


# ── Nhớ bài Page vừa đăng (mỗi user) ─────────────────────────────────────────

def ghi_bai_cuoi(user_id: str, message: str, link: str = "", url: str = "") -> None:
    with _lock:
        _bai_cuoi[str(user_id)] = {"message": message, "link": link,
                                   "url": url, "ts": time.time()}


def bai_cuoi(user_id: str) -> dict | None:
    with _lock:
        p = _bai_cuoi.get(str(user_id))
        if not p or time.time() - float(p.get("ts") or 0) > _BAI_TTL:
            return None
        return dict(p)


# ── Gọi captcha-solver ───────────────────────────────────────────────────────

def dang_mot_nhom(group_id: str, message: str) -> dict:
    """Một lần đăng, đồng bộ. Trả body JSON của solver ({status: ...})."""
    base, _ = _solver_cfg()
    try:
        r = requests.post(f"{base}/v1/facebook/group-post", headers=_headers(),
                          json={"group_id": group_id, "message": message},
                          timeout=_HTTP_TIMEOUT)
        try:
            return r.json() if r.content else {"status": "loi", "detail": f"HTTP {r.status_code}"}
        finally:
            try:
                r.close()
            except Exception:
                pass
    except Exception as exc:
        return {"status": "loi", "detail": str(exc)}


def mo_dang_nhap() -> str:
    """Bật cửa sổ đăng nhập Facebook trên noVNC. Trả hướng dẫn cho người dùng."""
    base, _ = _solver_cfg()
    try:
        r = requests.post(f"{base}/v1/session/manual-login", headers=_headers(),
                          json={"url": "https://www.facebook.com",
                                "profile": "facebook", "force": True},
                          timeout=60)
        try:
            body = r.json()
        finally:
            try:
                r.close()
            except Exception:
                pass
        novnc = str(body.get("open_in_browser") or "http://<máy-chủ>:6080")
        return (f"🔑 Em đã mở sẵn trang Facebook trong trình duyệt của bot.\n"
                f"Anh/chị mở {novnc} , đăng nhập Facebook trong cửa sổ đó MỘT "
                f"lần (phiên được giữ lại cho các lần sau), xong quay lại đây "
                f"chọn «Đăng vào nhóm» lại nhé.")
    except Exception as exc:
        return f"❌ Không gọi được trình duyệt của bot: {exc}"


# ── Hàng đợi nền ─────────────────────────────────────────────────────────────

def dang_chay() -> bool:
    return _dang_chay.is_set()


def ket_qua_gan_nhat() -> list[str]:
    with _lock:
        return list(_ket_qua)


def _ghep_bai(p: dict) -> str:
    """Nội dung đăng nhóm = bài + link (link Page mở rộng tầm với của Page)."""
    phan = [str(p.get("message") or "").strip()]
    link = str(p.get("link") or "").strip()
    if link and link not in phan[0]:
        phan.append(link)
    return "\n\n".join(x for x in phan if x)


def chia_se_nen(user_id: str, bai: dict, nhom: list[dict] | None = None) -> str:
    """Đăng `bai` vào các nhóm trong nền, giãn cách như người. Trả lời NGAY —
    kết quả từng nhóm xem lại ở menu «Đăng vào nhóm» (ket_qua_gan_nhat).

    Một hàng đợi tại một thời điểm: đang chạy mà gọi tiếp thì từ chối, tránh
    hai luồng cùng bắn một tài khoản — kiểu hoạt động dễ ăn checkpoint nhất.
    """
    ds = nhom if nhom is not None else nap_nhom()
    if not ds:
        return "Chưa có nhóm nào được lưu ạ."
    if _dang_chay.is_set():
        return "Em đang chia sẻ đợt trước, xong đợt đó em mới nhận thêm ạ."
    noi_dung = _ghep_bai(bai)
    if not noi_dung:
        return "Bài trống, không có gì để chia sẻ ạ."
    _dang_chay.set()
    with _lock:
        _ket_qua.clear()
        _ket_qua.append("⏳ đang chạy…")

    def _chay() -> None:
        dong: list[str] = []
        try:
            for i, g in enumerate(ds):
                if i:
                    time.sleep(random.uniform(*_GIAN_CACH_S))
                kq = dang_mot_nhom(g["id"], noi_dung)
                st = str(kq.get("status") or "loi")
                if st == "ok":
                    dong.append(f"✅ {g['name']}")
                elif st == "chua_dang_nhap":
                    dong.append(f"🔑 {g['name']} — chưa đăng nhập, dừng cả đợt")
                    break
                else:
                    dong.append(f"❌ {g['name']} — {str(kq.get('detail') or '')[:120]}")
                logger.info("fb nhóm %s: %s", g["id"], st)
        finally:
            with _lock:
                _ket_qua.clear()
                _ket_qua.extend(dong or ["(không có kết quả)"])
            _dang_chay.clear()

    threading.Thread(target=_chay, daemon=True, name="fb-group-share").start()
    phut = len(ds) * (sum(_GIAN_CACH_S) / 2) / 60
    return (f"📤 Em bắt đầu chia sẻ vào {len(ds)} nhóm, mỗi nhóm cách nhau vài "
            f"phút cho giống người (ước chừng {max(1, round(phut))} phút). Xem "
            f"kết quả ở menu /facebook ▸ Đăng vào nhóm nhé.")

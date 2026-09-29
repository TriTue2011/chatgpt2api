"""Đăng nhập HÀNG LOẠT tài khoản OpenAI gốc — xong một tài khoản mới sang tài khoản kế.

Chủ máy 29/09/2026: "Login trực tiếp qua open ai, có cách nào gán list rồi tự đăng nhập dần
được không" → "C2a đăng nhập thành công 1 tài khoản rồi sang tài khoản khác"; tài khoản có TOTP.

Mỗi tài khoản đi ĐÚNG đường của thẻ "OpenAI gốc" (một tài khoản một lần): solver
`/v1/openai-native/onboard` (điền form của OpenAI, tự sinh mã từ hạt giống TOTP, lưu mật khẩu vào
kho `openai` của solver để lần sau tự đăng nhập lại) → chờ `onboard-status` → lấy token → đưa vào
pool như `POST /api/accounts`.

Chạy trên MÁY CHỦ, không trong trình duyệt như nút hàng loạt của Codex: đóng trang là vòng lặp
trình duyệt chết giữa chừng. Mật khẩu chỉ nằm trong bộ nhớ lúc chạy, không trả về trạng thái.

LẦN LƯỢT và có khoảng nghỉ: một chùm đăng nhập tự động từ cùng một IP máy chủ là cách chắc nhất
để bị bắt captcha (nhánh Google đã gặp — xem `account_recovery._glogin_serial`). Gặp captcha /
OpenAI chặn thì DỪNG cả hàng: thử tiếp chỉ đẻ thêm thử thách.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any

from utils.log import logger

#: Nghỉ giữa hai tài khoản.
NGHI_GIAY = 30.0
#: Trần một lượt đăng nhập — solver tự bỏ sau ~300 s; thêm biên cho mở Chrome.
TRAN_GIAY = 420.0
_NHIP_GIAY = 3.0
#: Ngần này tài khoản LIỀN NHAU hỏng thì dừng cả hàng. Lỗi riêng một tài khoản (sai mật khẩu,
#: hạt giống TOTP) hiếm khi đứng liền nhau; máy chủ bị thử thách (captcha, chặn IP) thì tài khoản
#: nào cũng hỏng. Đếm theo KẾT QUẢ thay vì khớp chữ trong lỗi — lời lỗi OpenAI đổi theo bản dựng.
HONG_LIEN_DUNG = 2
#: Trạng thái dòng pool còn dùng được — đã có thì bỏ qua, khỏi đăng nhập lại.
_CON_SONG = ("active", "limited")

_khoa = threading.Lock()
_hang: list[dict[str, Any]] = []
_dung = threading.Event()
_luong: threading.Thread | None = None


def doc_danh_sach(van_ban: str) -> list[dict[str, str]]:
    """Mỗi dòng ``email|mật khẩu|hạt giống TOTP``. Dấu ``|`` vì mật khẩu hay có ``:``.
    Dòng CHỈ có email = đăng nhập lại tài khoản đã lưu: solver tự lấy mật khẩu + hạt giống trong kho
    `openai` (`bu_credential`), mật khẩu không phải gõ lại.
    Dòng sai khuôn → ValueError nêu số dòng; email trùng chỉ giữ lần đầu."""
    ra: list[dict[str, str]] = []
    thay: set[str] = set()
    for i, dong in enumerate(str(van_ban or "").splitlines(), 1):
        dong = dong.strip()
        if not dong or dong.startswith("#"):
            continue
        phan = [p.strip() for p in dong.split("|")]
        phan = [p for p in phan if p] if len(phan) > 1 and not any(phan[1:]) else phan
        if "@" not in phan[0] or (len(phan) > 1 and not phan[1]):
            raise ValueError(f"Dòng {i}: cần «email|mật khẩu|TOTP» hoặc chỉ email (đã lưu mật khẩu).")
        email = phan[0].lower()
        if email in thay:
            continue
        thay.add(email)
        ra.append({"email": email, "mat_khau": phan[1] if len(phan) > 1 else "",
                   "totp": re.sub(r"\s+", "", phan[2]) if len(phan) > 2 else ""})
    if not ra:
        raise ValueError("Danh sách trống.")
    return ra


def _profile(email: str) -> str:
    """Cùng quy ước với thẻ "OpenAI gốc" (`_profileTu`) và `account_recovery._ho_so_openai`."""
    local = email.split("@", 1)[0] or "default"
    return "openai-" + re.sub(r"[^a-z0-9-]", "-", local, flags=re.IGNORECASE)


def bat_dau(van_ban: str) -> dict[str, Any]:
    global _luong
    ds = doc_danh_sach(van_ban)
    with _khoa:
        if _luong is not None and _luong.is_alive():
            raise ValueError("Đang chạy một danh sách — dừng nó trước.")
        _hang[:] = [{**x, "state": "cho", "message": "Chờ tới lượt", "luc": 0.0} for x in ds]
        _dung.clear()
        _luong = threading.Thread(target=_chay, name="openai-hang-loat", daemon=True)
        _luong.start()
    logger.info({"event": "openai_hang_loat_bat_dau", "so": len(ds)})
    return trang_thai()


def dung() -> dict[str, Any]:
    _dung.set()
    return trang_thai()


def trang_thai() -> dict[str, Any]:
    with _khoa:
        return {"dang_chay": _luong is not None and _luong.is_alive(),
                "ds": [{k: x[k] for k in ("email", "state", "message", "luc")} for x in _hang]}


def _dat(x: dict[str, Any], state: str, message: str) -> None:
    with _khoa:
        x.update(state=state, message=message[:200], luc=time.time())


def _chay() -> None:
    try:
        _chay_hang()
    finally:
        with _khoa:
            for y in _hang:             # mật khẩu không ở lại trong bộ nhớ sau lượt
                y["mat_khau"] = y["totp"] = ""


def _chay_hang() -> None:
    lan_truoc = 0.0
    hong_lien = 0
    for x in list(_hang):
        if _dung.is_set():
            _dat(x, "bo", "Đã dừng")
            continue
        try:
            song = _con_song(x["email"])
        except Exception:  # noqa: BLE001 — không đọc được pool thì cứ đăng nhập
            song = False
        if song:
            _dat(x, "da_co", "Đã có trong pool, còn dùng được — bỏ qua")
            continue
        cho = lan_truoc + NGHI_GIAY - time.time()
        if lan_truoc and cho > 0:
            _dat(x, "cho", f"Nghỉ {cho:.0f} s trước khi đăng nhập")
            if _dung.wait(cho):
                _dat(x, "bo", "Đã dừng")
                continue
        try:
            _mot(x)
        except Exception as exc:  # noqa: BLE001 — một tài khoản hỏng không giết cả hàng
            _dat(x, "loi", f"{type(exc).__name__}: {exc}")
        lan_truoc = time.time()
        logger.info({"event": "openai_hang_loat_mot", "email": x["email"], "state": x["state"]})
        hong_lien = hong_lien + 1 if x["state"] == "loi" else 0
        if hong_lien >= HONG_LIEN_DUNG:
            _dung.set()
            with _khoa:
                for y in _hang:
                    if y["state"] == "cho":
                        y.update(state="bo", message=f"Dừng cả hàng: {hong_lien} tài khoản liền nhau "
                                                     "hỏng — có thể OpenAI đang chặn máy chủ; xem lỗi rồi chạy lại")


def _con_song(email: str) -> bool:
    from services.account_service import account_service
    acc = account_service.find_free_by_email(email)
    return bool(acc) and str(acc.get("status") or "") in _CON_SONG


def _mot(x: dict[str, Any]) -> None:
    """Một tài khoản: onboard → chờ → token → pool."""
    import requests
    from services.account_recovery import _solver_cfg
    from services.account_service import account_service

    url, api_key = _solver_cfg()
    goc = url.rstrip("/")
    H = {"Authorization": f"Bearer {api_key}"}
    p = _profile(x["email"])
    _dat(x, "dang_nhap", "Đang mở Chrome")
    r = requests.post(f"{goc}/v1/openai-native/onboard", headers=H, timeout=60,
                      json={"profile": p, "email": x["email"], "password": x["mat_khau"],
                            "totp_secret": x["totp"]})
    r.raise_for_status()
    het = time.time() + TRAN_GIAY
    while True:
        if _dung.wait(_NHIP_GIAY):
            _dat(x, "bo", "Đã dừng giữa lượt (Chrome tự đóng khi solver xong)")
            return
        s = requests.get(f"{goc}/v1/openai-native/{p}/onboard-status", headers=H, timeout=30).json()
        st = str(s.get("state") or "")
        if st == "success":
            break
        if st == "failed":
            loi = str(s.get("error") or s.get("message") or "Đăng nhập thất bại")
            # Mã lỗi `account_*` do CHÍNH OpenAI đặt tên là lỗi của riêng tài khoản (vd account_deactivated —
            # bị xoá / vô hiệu hoá): không phải máy chủ bị chặn, nên không tính vào HONG_LIEN_DUNG.
            m = re.search(r"error_code=(account_[A-Za-z0-9_]+)", loi)
            _dat(x, "khoa" if m else "loi", f"OpenAI báo tài khoản lỗi {m.group(1)}: {loi}" if m else loi)
            return
        if st == "need_code":
            _dat(x, "loi", "OpenAI hỏi mã mà không sinh được từ TOTP — kiểm hạt giống")
            return
        if time.time() > het:
            _dat(x, "loi", f"Quá {TRAN_GIAY:.0f} s chưa xong: {s.get('message') or st}")
            return
        _dat(x, "dang_nhap", str(s.get("message") or st))
    d = requests.get(f"{goc}/v1/openai-native/{p}/token", headers=H, timeout=30).json()
    token = str(d.get("access_token") or "")
    # KIỂM KẾT QUẢ trước khi báo xong. Đo 29/09/2026: 17 tài khoản hotmail báo «xong» mà solver trả
    # cookie phiên mã hoá thay cho access token — không đọc được email, làm mới đánh lỗi, bước gộp
    # trùng xoá dòng không email: mất cả 17 mà không ai hay.
    email_token = account_service._email_from_token_or_account(token)
    if email_token != x["email"]:
        _dat(x, "loi", "Solver trả token không dùng được (không phải access token ChatGPT"
                       + (f" của {x['email']}" if email_token else "") + ") — thử lại tài khoản này")
        return
    account_service.add_accounts([token])
    account_service.refresh_accounts([token])
    acc = account_service.find_free_by_email(x["email"]) or {}
    if str(acc.get("status") or "") not in _CON_SONG:
        _dat(x, "loi", f"Đã thêm nhưng kiểm lại thì tài khoản ở trạng thái «{acc.get('status') or 'không thấy'}»")
        return
    _dat(x, "xong", f"Đã thêm {x['email']} vào pool (kiểm lại: {acc.get('status')})")

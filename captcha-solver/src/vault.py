"""Mã hoá tại chỗ cho mật khẩu Google và hạt giống TOTP.

`accounts.db` đang giữ `password` và `totp_secret` dạng CHỮ THƯỜNG. Hai thứ đó
cộng lại là toàn quyền vào tài khoản Google — hạt giống TOTP không phải "mã 6
số", nó sinh ra mọi mã 6 số từ nay về sau, nên lộ nó là mất luôn yếu tố thứ
hai chứ không chỉ một lần đăng nhập. File đó nằm trên volume, đi theo mọi bản
sao lưu, và ai đọc được đĩa là đọc được hết.

Thiết kế:

  - **AES-256-GCM**, nonce 12 byte RIÊNG cho từng lần ghi.
  - **AAD** gồm `email` và TÊN TRƯỜNG. Nhờ vậy không thể bê nguyên khối
    ciphertext của tài khoản A sang tài khoản B, cũng không thể đổi chỗ
    `password` với `totp_secret` — đổi chỗ là giải mã hỏng, không phải giải mã
    ra giá trị sai.
  - **Định dạng có tiền tố phiên bản**: `v1:<nonce b64>:<ct b64>`. Chuỗi không
    mang tiền tố = dữ liệu cũ chưa mã hoá, đọc thẳng và tự mã hoá ở lần ghi
    kế tiếp. Di trú không cần bước thủ công nào.

**Chưa đặt `VAULT_MASTER_KEY` thì KHÔNG mã hoá, và ghi log cảnh báo.** Bắt buộc
biến này sẽ khiến container không lên được sau khi cập nhật — đúng kiểu hỏng
đã gặp với bốn biến của zalo-server, và mất cả hệ thống thì tệ hơn nhiều so
với thứ nó định bảo vệ. Việc bảo vệ quan trọng hơn được làm vô điều kiện:
`list_accounts()` không trả `totp_secret` ra nữa, dù có khoá hay không.

Sinh khoá:  `python3 -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"`
"""

from __future__ import annotations

import base64
import logging
import os
import secrets

logger = logging.getLogger(__name__)

TIEN_TO = "v1:"
_da_canh_bao = False


def _khoa() -> bytes | None:
    """32 byte khoá chính, hoặc None nếu chưa cấu hình."""
    global _da_canh_bao
    raw = os.environ.get("VAULT_MASTER_KEY", "").strip()
    if not raw:
        if not _da_canh_bao:
            _da_canh_bao = True
            logger.warning({
                "event": "vault_chua_co_khoa",
                "msg": "VAULT_MASTER_KEY chưa đặt — mật khẩu và TOTP lưu dạng chữ "
                       "thường trong accounts.db. Sinh khoá: "
                       "python3 -c \"import base64,os;print(base64.b64encode(os.urandom(32)).decode())\"",
            })
        return None
    try:
        k = base64.b64decode(raw, validate=True)
    except Exception:
        logger.error({"event": "vault_khoa_khong_hop_le",
                      "msg": "VAULT_MASTER_KEY không phải base64 hợp lệ"})
        return None
    if len(k) != 32:
        logger.error({"event": "vault_khoa_sai_do_dai",
                      "msg": f"VAULT_MASTER_KEY giải ra {len(k)} byte, cần đúng 32"})
        return None
    return k


def dang_bat() -> bool:
    return _khoa() is not None


def _aad(email: str, truong: str) -> bytes:
    return f"{str(email or '').strip().lower()}|{str(truong or '').strip()}".encode("utf-8")


def ma_hoa(gia_tri: str, email: str, truong: str) -> str:
    """Trả chuỗi để lưu vào DB. Chưa có khoá → trả nguyên giá trị."""
    gt = str(gia_tri or "")
    if not gt:
        return ""
    k = _khoa()
    if k is None:
        return gt
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = secrets.token_bytes(12)
    ct = AESGCM(k).encrypt(nonce, gt.encode("utf-8"), _aad(email, truong))
    return TIEN_TO + base64.b64encode(nonce).decode() + ":" + base64.b64encode(ct).decode()


def giai_ma(luu_tru: str, email: str, truong: str) -> str:
    """Đọc giá trị. Chuỗi không có tiền tố = dữ liệu cũ, trả thẳng."""
    s = str(luu_tru or "")
    if not s or not s.startswith(TIEN_TO):
        return s
    k = _khoa()
    if k is None:
        # Có ciphertext mà mất khoá: KHÔNG trả chuỗi rác ra ngoài. Trả rỗng để
        # nơi gọi thấy "không có mật khẩu" và báo lỗi rõ, thay vì đem chuỗi vô
        # nghĩa đi đăng nhập rồi nhận một lỗi chẳng liên quan.
        logger.error({"event": "vault_mat_khoa",
                      "msg": "accounts.db có dữ liệu đã mã hoá nhưng VAULT_MASTER_KEY "
                             "trống hoặc sai — không đọc được"})
        return ""
    try:
        _, nonce_b64, ct_b64 = s.split(":", 2)
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        thuong = AESGCM(k).decrypt(base64.b64decode(nonce_b64),
                                   base64.b64decode(ct_b64), _aad(email, truong))
        return thuong.decode("utf-8")
    except Exception as exc:
        logger.error({"event": "vault_giai_ma_hong", "error": type(exc).__name__})
        return ""


def da_ma_hoa(luu_tru: str) -> bool:
    return str(luu_tru or "").startswith(TIEN_TO)


__all__ = ["TIEN_TO", "da_ma_hoa", "dang_bat", "giai_ma", "ma_hoa"]

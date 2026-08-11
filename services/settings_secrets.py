"""Không trả giá trị bí mật ra `/api/settings`, và không để UI ghi đè mất chúng.

Hiện `GET /api/settings` trả nguyên `config.get()` — gồm mọi khoá API, token
bot, cookie, khoá R2, sessionKey. Ai mở được trang admin, hoặc bất kỳ script
nào chạy trong trang đó, đều đọc trọn bộ. Khoá không hiện ra màn hình vẫn nằm
trong phản hồi HTTP.

**Vì sao che ĐỌC bắt buộc phải đi kèm sửa GHI.** `web/src/app/combos/page.tsx`
GET config rồi POST NGUYÊN CẢ config trở lại. Nếu chỉ che đường đọc, lần lưu
đầu tiên sẽ ghi cái nhãn che vào đúng chỗ khoá thật — mất sạch, và mất im
lặng. Hai hàm ở đây là một cặp, đừng dùng lẻ:

    che_giau()  → giá trị bí mật thành {"is_set": true}
    loc_ghi()   → bỏ mọi nhãn che và chuỗi rỗng khỏi dữ liệu client gửi lên

Quy ước ghi (khớp đặc tả chủ dự án):

    trường bí mật KHÔNG gửi   → giữ nguyên
    gửi nhãn che {"is_set":…} → giữ nguyên
    gửi chuỗi rỗng            → giữ nguyên
    gửi giá trị mới           → ghi đè
    xoá hẳn                   → `clear_secret_fields: ["backup.secret_access_key"]`

Cố ý KHÔNG có đường nào để "xoá bằng cách gửi rỗng": một ô input trống do
trang chưa nạp xong là chuyện thường, và nó không được phép đồng nghĩa với
"xoá khoá R2".
"""
from __future__ import annotations

from typing import Any

# Tên trường bị coi là bí mật. So sau khi hạ chữ thường và đổi '-' thành '_',
# theo hai luật: BẰNG một mục dưới đây, hoặc KẾT THÚC bằng '_' + mục đó.
#
# Dùng luật theo tên chứ không phải danh sách đường dẫn cố định vì provider là
# mở — người dùng thêm `custom_providers.<tên tự đặt>` lúc nào cũng được, và
# một danh sách cứng sẽ bỏ sót đúng những chỗ mới thêm.
_TEN_BI_MAT: frozenset[str] = frozenset({
    "api_key", "api_keys", "apikey", "apikeys",
    "auth_key", "authkey",
    "secret", "secret_key", "client_secret", "webhook_secret",
    "access_key_id", "secret_access_key",
    "session_key", "sessionkey", "sessionid",
    "password", "passwd", "pass",
    "token", "refresh_token", "access_token", "bot_token", "tunnel_token",
    # token_long: luật đuôi chỉ khớp "_token" nên "user_token_long" từng LỌT
    # LƯỚI — token dài hạn Facebook trả về web UI dạng thô (đo thật 11/08).
    # Thêm "token_long" để bắt cả tên đúng lẫn mọi "*_token_long" sau này.
    "token_long", "user_token_long",
    "cookie", "cookies",
    "credential", "credentials",
    "private_key", "totp_secret", "totp_seed", "seed",
})

# Tên TRÔNG giống bí mật nhưng không phải. Không có danh sách này thì
# `max_tokens` hay `token_limit` bị che, và UI mất một ô cấu hình bình thường
# mà chẳng ai hiểu vì sao.
_KHONG_PHAI_BI_MAT: frozenset[str] = frozenset({
    "max_tokens", "token_limit", "tokens", "max_output_tokens",
    "token_count", "cookie_secure", "cookie_domain", "cookie_name",
})


def _chuan(ten: str) -> str:
    return str(ten or "").strip().lower().replace("-", "_")


def la_truong_bi_mat(ten: str) -> bool:
    t = _chuan(ten)
    if not t or t in _KHONG_PHAI_BI_MAT:
        return False
    if t in _TEN_BI_MAT:
        return True
    return any(t.endswith("_" + m) for m in _TEN_BI_MAT)


def _co_gia_tri(v: Any) -> bool:
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, (list, tuple, dict)):
        return bool(v)
    return v is not None and v is not False


def _nhan_che(v: Any) -> dict[str, Any]:
    if isinstance(v, (list, tuple)):
        # Danh sách nhiều khoá: UI cần biết CÓ MẤY cái, không thì không hiển
        # thị được gì có nghĩa. Số lượng không phải bí mật.
        thuc = [x for x in v if _co_gia_tri(x)]
        return {"is_set": bool(thuc), "count": len(thuc)}
    return {"is_set": _co_gia_tri(v)}


def la_nhan_che(v: Any) -> bool:
    """Có phải cái nhãn do `che_giau` sinh ra không (client gửi ngược lên)."""
    return (isinstance(v, dict) and bool(v)
            and set(v.keys()) <= {"is_set", "count"})


def che_giau(data: Any) -> Any:
    """Bản sao của `data` với mọi giá trị bí mật thay bằng nhãn `is_set`."""
    if isinstance(data, dict):
        ra: dict[str, Any] = {}
        for k, v in data.items():
            ra[k] = _nhan_che(v) if la_truong_bi_mat(k) else che_giau(v)
        return ra
    if isinstance(data, list):
        return [che_giau(x) for x in data]
    return data


def _gia_tri_moi(v: Any) -> Any | None:
    """Giá trị bí mật THẬT SỰ mới, hoặc None nếu client không gửi gì mới."""
    if la_nhan_che(v) or not _co_gia_tri(v):
        return None
    if isinstance(v, (list, tuple)):
        thuc = [x for x in v if _co_gia_tri(x) and not la_nhan_che(x)]
        return thuc or None
    return v


def loc_ghi(den: Any, hien_tai: Any = None) -> Any:
    """Thay mọi trường bí mật KHÔNG mang giá trị mới bằng giá trị đang chạy.

    **Vì sao phải CHÉP LẠI giá trị cũ chứ không chỉ bỏ trường đi.** Bản đầu chỉ
    bỏ, dựa trên lập luận "config.update chỉ ghi khoá có mặt, nên vắng mặt =
    giữ nguyên". Lập luận đó chỉ đúng ở TẦNG NGOÀI CÙNG. `config.update` làm
    ``next_data.update(incoming)`` — một dict top-level như ``backup`` bị thay
    NGUYÊN KHỐI, nên bỏ ``backup.secret_access_key`` khỏi payload không phải là
    giữ nguyên mà là xoá; ``_normalize_backup_settings`` sau đó điền lại thành
    chuỗi rỗng, im lặng.

    Hai mươi test đơn vị không thấy điều này. Test chạy qua ``config.update``
    thật thì thấy ngay ở lần đầu.

    ``hien_tai`` nên là ``config.data`` (bản đang lưu), không phải
    ``config.get()``: ``get()`` tự điền vài trường từ biến môi trường, chép lại
    là ghi giá trị của môi trường vào file cấu hình.
    """
    if isinstance(den, dict):
        ra: dict[str, Any] = {}
        for k, v in den.items():
            cu = hien_tai.get(k) if isinstance(hien_tai, dict) else None
            if la_truong_bi_mat(k):
                moi = _gia_tri_moi(v)
                if moi is not None:
                    ra[k] = moi
                elif _co_gia_tri(cu):
                    ra[k] = cu
                # không có cả mới lẫn cũ → bỏ hẳn, đừng ghi rỗng đè lên
            else:
                ra[k] = loc_ghi(v, cu)
        return ra
    if isinstance(den, list):
        # Danh sách không bí mật: không có cách khớp phần tử với bản hiện tại.
        return [loc_ghi(x) for x in den]
    return den


def xoa_theo_duong_dan(data: dict[str, Any], duong_dan: list[str]) -> list[str]:
    """Xoá hẳn các trường bí mật theo `clear_secret_fields`. Trả danh sách đã xoá.

    CHỈ xoá được trường bí mật. Cho phép xoá trường bất kỳ là biến một endpoint
    lưu cài đặt thành một endpoint xoá cấu hình tuỳ ý.
    """
    da_xoa: list[str] = []
    for duong in duong_dan or []:
        phan = [p for p in str(duong or "").split(".") if p]
        if not phan or not la_truong_bi_mat(phan[-1]):
            continue
        nut: Any = data
        for p in phan[:-1]:
            if not isinstance(nut, dict) or p not in nut:
                nut = None
                break
            nut = nut[p]
        if not isinstance(nut, dict) or phan[-1] not in nut:
            continue
        cu = nut[phan[-1]]
        nut[phan[-1]] = [] if isinstance(cu, (list, tuple)) else ""
        da_xoa.append(".".join(phan))
    return da_xoa


__all__ = ["che_giau", "la_nhan_che", "la_truong_bi_mat", "loc_ghi",
           "xoa_theo_duong_dan"]

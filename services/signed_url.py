"""URL media có chữ ký HMAC — cho những đường KHÔNG gửi được header.

Loa Cast/DLNA, Zalo và Telegram kéo file bằng cách đưa URL cho một tiến trình
khác (chromecast, máy chủ Zalo, bot API). Những chỗ đó không gửi được
`Authorization`, nên `/media/voice/{name}` và mount `/images` hiện đang mở
hoàn toàn: ai đoán hoặc dò được tên file là tải được, và tên file thì nằm sẵn
trong log, trong lịch sử chat, trong URL đã chia sẻ.

Chữ ký giải quyết đúng chỗ đó: URL vẫn không cần header, nhưng nó tự chứng
minh là do máy chủ này phát ra, cho đúng một đường dẫn, và chỉ trong một
khoảng thời gian.

Ba thứ nằm TRONG chữ ký, cố ý:

  - **phương thức** — chữ ký của một GET không dùng lại cho thao tác khác.
  - **đường dẫn đã chuẩn hoá** — không thì `/media/voice/a/../../etc/passwd`
    ký một đằng, đọc một nẻo.
  - **hạn dùng** — link rò ra ngoài thì cũng tự chết.

Khoá ký lấy từ `CHATGPT2API_AUTH_KEY`. Không phải lựa chọn đẹp nhất (lý tưởng
là khoá riêng), nhưng nó có sẵn ở mọi triển khai và không thêm một biến môi
trường bắt buộc nữa — thêm biến bắt buộc là container không lên được sau khi
cập nhật, đúng kiểu hỏng đã gặp với 4 biến zalo-server.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import quote

HAN_MAC_DINH_GIAY = 600.0


def _khoa_ky() -> bytes:
    from services.config import config
    goc = str(config.auth_key or "").strip()
    # Tách khỏi khoá gốc bằng một nhãn: chữ ký rò ra cũng không suy ngược được
    # `CHATGPT2API_AUTH_KEY`, và khoá này không dùng lại được cho mục đích khác.
    return hashlib.sha256(("c2a-signed-url:" + goc).encode("utf-8")).digest()


def _chuan_hoa(duong: str) -> str:
    """Bỏ `.`/`..` và gộp dấu gạch — ký và kiểm phải nhìn cùng một chuỗi."""
    phan: list[str] = []
    for p in str(duong or "").split("/"):
        if not p or p == ".":
            continue
        if p == "..":
            if phan:
                phan.pop()
            continue
        phan.append(p)
    return "/" + "/".join(phan)


def _chu_ky(phuong_thuc: str, duong: str, han: int, pham_vi: str) -> str:
    thong_diep = "\n".join([
        str(phuong_thuc or "GET").upper(),
        _chuan_hoa(duong),
        str(han),
        str(pham_vi or ""),
    ]).encode("utf-8")
    return hmac.new(_khoa_ky(), thong_diep, hashlib.sha256).hexdigest()


def ky_duong_dan(duong: str, *, pham_vi: str = "media",
                 song_giay: float = HAN_MAC_DINH_GIAY,
                 phuong_thuc: str = "GET") -> str:
    """Trả phần query `?exp=…&sig=…` để nối vào sau đường dẫn."""
    han = int(time.time() + max(1.0, float(song_giay)))
    sig = _chu_ky(phuong_thuc, duong, han, pham_vi)
    return f"exp={han}&sig={sig}&scope={quote(pham_vi)}"


def ky_url(url: str, *, pham_vi: str = "images",
           song_giay: float = HAN_MAC_DINH_GIAY) -> str:
    """Ký một URL ĐẦY ĐỦ (đã có scheme/host), trả lại URL kèm chữ ký.

    Dùng cho nơi phát URL ra ngoài — Zalo và Telegram nhận URL rồi TỰ đi tải,
    nên chúng không gửi được cookie lẫn header nào. Không ký thì khi bật
    `security.signed_media_required`, ảnh gửi đi sẽ 403 ở phía họ.
    """
    from urllib.parse import urlsplit
    u = urlsplit(str(url or ""))
    if not u.path:
        return url
    noi = "&" if u.query else "?"
    return f"{url}{noi}{ky_duong_dan(u.path, pham_vi=pham_vi, song_giay=song_giay)}"


def kiem_chu_ky(duong: str, exp: str, sig: str, *, pham_vi: str = "media",
                phuong_thuc: str = "GET") -> bool:
    """True nếu chữ ký đúng và chưa hết hạn."""
    if not exp or not sig:
        return False
    try:
        han = int(str(exp).strip())
    except (TypeError, ValueError):
        return False
    if han <= time.time():
        return False
    mong_doi = _chu_ky(phuong_thuc, duong, han, pham_vi)
    # So HẰNG THỜI GIAN, trên bytes: `sig` do client gửi nên có thể chứa ký tự
    # ngoài ASCII, mà `compare_digest` trên chuỗi sẽ ném TypeError với chúng.
    return hmac.compare_digest(mong_doi.encode(), str(sig).strip().encode())


__all__ = ["HAN_MAC_DINH_GIAY", "kiem_chu_ky", "ky_duong_dan", "ky_url"]

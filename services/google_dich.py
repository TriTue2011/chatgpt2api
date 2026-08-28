"""Google Dịch làm Ý KIẾN THỨ HAI — tuỳ chọn, mặc định TẮT.

Đường dịch chính của dự án vẫn là ``vn-translate`` trong stack: tự chủ, không
gì rời máy. Module này là thứ khác hẳn về bản chất, nên đọc kỹ trước khi bật:

* Nó gọi ``translate.googleapis.com/translate_a/single?client=gtx`` — endpoint
  mà chính trang translate.google.com dùng, **không có khoá, không có tài liệu,
  không có cam kết nào**. Đo thật 28/08/2026: trả đúng ``stroke → đột quỵ`` cho
  cả từ đứng lẻ, và tự nhận tiếng nguồn. Cùng nếp với cách repo accuweather của
  chủ máy lấy dữ liệu từ trang web thay vì API — khác ở chỗ đây là JSON sẵn nên
  không cần giả dấu vân tay TLS, gọi thẳng là ra.
* Google **thấy toàn bộ chữ** gửi lên. Đó là lý do mặc định TẮT và phải bật tay
  trong tab Dịch: bật hay không là quyết định về dữ liệu, không phải về kỹ thuật.
* Endpoint không công bố thì có ngày đổi hoặc chặn theo IP. Vì vậy mọi lỗi ở
  đây đều NUỐT vào trong: hỏng thì ô Google trống, đường dịch chính không hề
  hấn gì. Hỏng một lần là CẦU DAO ngắt 5 phút, khỏi mỗi lượt lại chờ hết giờ.

Bật bằng config ``dich_google``: ``{"bat": true}`` (đặt ở tab Dịch).
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from services.config import config

logger = logging.getLogger(__name__)

URL = "https://translate.googleapis.com/translate_a/single"

#: Trần chữ gửi một lượt. Endpoint không công bố giới hạn; cắt ở đây để một cú
#: dán nhầm cả quyển sách không thành một request khổng lồ rồi ăn chặn IP.
TRAN_KY_TU = 5000

#: Hỏng một lần thì nghỉ ngần này giây. Bị chặn IP mà vẫn gọi tiếp là kéo dài
#: thời gian bị chặn, và mỗi lượt người dùng phải chờ hết timeout vô ích.
NGHI_SAU_LOI = 300.0

#: Trình duyệt thật. Endpoint trả 403 cho User-Agent mặc định của urllib.
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

_nghi_toi = 0.0
_khoa = threading.Lock()


class LoiGoogle(Exception):
    """Không gọi được Google (tắt, mạng lỗi, bị chặn, trả dạng lạ)."""


def dang_bat() -> bool:
    """Chủ máy đã bật Google Dịch trong tab Dịch hay chưa. Mặc định chưa."""
    return bool(((config.get() or {}).get("dich_google") or {}).get("bat"))


def _phan_tich(raw: str) -> tuple[str, str]:
    """``[[["dịch","gốc",…],…], null, "en", …]`` → (bản dịch, tiếng nhận ra).

    Mảng ngoài cùng chia câu dài thành nhiều mảnh; nối lại đúng thứ tự. Dạng
    này không có tài liệu nên chỉ đọc những ô đã tự tay xác minh, gặp dạng lạ
    thì báo lỗi chứ không đoán.
    """
    try:
        goi = json.loads(raw)
    except ValueError as exc:
        raise LoiGoogle(f"Google trả thứ không phải JSON: {str(exc)[:120]}") from exc
    # Kiểm dạng bằng isinstance chứ không bắt lỗi khi đánh chỉ số: một object
    # JSON (``{"error": …}``) vẫn cho ``goi[0]`` chạy tới KeyError, mà bắt tất
    # cả lỗi thì che luôn cả lỗi lập trình thật.
    manh = goi[0] if isinstance(goi, list) and goi else None
    if not isinstance(manh, list) or not manh:
        raise LoiGoogle("Google trả dạng lạ: không có danh sách mảnh dịch")
    ban = "".join(str(m[0]) for m in manh
                  if isinstance(m, list) and m and m[0] is not None)
    nhan = goi[2] if len(goi) > 2 and isinstance(goi[2], str) else ""
    return ban, str(nhan)


def dich(text: str, target: str, source: str = "auto") -> tuple[str, str]:
    """Dịch qua Google → (bản dịch, mã tiếng nguồn Google nhận ra).

    Ném ``LoiGoogle`` khi chưa bật, đang trong thời gian nghỉ của cầu dao, hoặc
    gọi không được — nơi gọi chịu trách nhiệm nuốt lỗi và để trống ô Google.
    """
    global _nghi_toi
    if not dang_bat():
        raise LoiGoogle("chưa bật Google Dịch trong tab Dịch")
    nd = str(text or "").strip()
    if not nd:
        return "", ""
    if len(nd) > TRAN_KY_TU:
        nd = nd[:TRAN_KY_TU]
    with _khoa:
        if time.time() < _nghi_toi:
            raise LoiGoogle("Google vừa lỗi, đang nghỉ vài phút")
    tham_so = urllib.parse.urlencode({
        "client": "gtx", "dt": "t",
        "sl": str(source or "auto").lower() or "auto",
        "tl": str(target or "").lower(),
    })
    req = urllib.request.Request(
        f"{URL}?{tham_so}",
        data=urllib.parse.urlencode({"q": nd}).encode("utf-8"),
        headers={"User-Agent": _UA,
                 "Content-Type": "application/x-www-form-urlencoded"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=config.google_dich_timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        with _khoa:
            _nghi_toi = time.time() + NGHI_SAU_LOI
        logger.warning("Google Dịch lỗi (%s) — nghỉ %.0f giây",
                       str(exc)[:160], NGHI_SAU_LOI)
        raise LoiGoogle(f"không gọi được Google: {str(exc)[:160]}") from exc
    return _phan_tich(raw)

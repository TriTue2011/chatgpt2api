"""Hộp thư hai chiều giữa phiên Claude giám sát và chủ máy qua Zalo.

Claude chạy trên máy chủ (ngoài container) cần HỎI chủ máy trước khi làm việc
khó đảo — sửa file nhạy cảm, đẩy bản vá lúc nửa đêm. Nhưng nó không nằm trong
luồng chat của bot, nên câu trả lời của chủ máy không tự về tới nó.

Không dùng long-poll `getUpdates` được: Zalo nói thẳng "getUpdates sẽ không hoạt
động nếu bạn đã thiết lập Webhook trước đó" (xem chú thích dài ở
``zalo_bot.py`` quanh dòng 482). Bot đang chạy webhook thật; bật poll song song
là một trong hai đường im lặng mất tin, mà im lặng kiểu đó rất khó truy.

Nên đường về đi qua CHÍNH webhook đang chạy: ``zalo_bot`` gọi ``tra_loi()`` cho
mọi tin từ thread admin, y như cách nó gọi ``admin_workspace.handle_admin_text``
ngay trước đó. Trả chuỗi = đã xử lý, gửi lại rồi dừng; trả ``None`` = không
phải việc của module này, tin đi tiếp như thường.

Hộp thư là một tệp JSON, không phải DB: mỗi lần chỉ có một câu hỏi đang chờ,
mất tệp thì chỉ lỡ một lượt hỏi chứ không hỏng dữ liệu nào.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from utils.log import logger

#: Câu hỏi quá hạn thì thôi, đừng để chủ máy trả lời một câu từ hôm kia rồi
#: Claude hành động theo bối cảnh đã cũ.
_HAN = 6 * 3600.0

#: Tiền tố để chủ máy trả lời mà không lẫn với câu chat thường. Chọn "cl" cho
#: ngắn: chủ máy gõ trên điện thoại.
_TIEN_TO = ("cl ", "claude ")


def _duong() -> Path:
    from services.config import DATA_DIR
    return Path(DATA_DIR) / "agent" / "hoi_giam_sat.json"


def _doc() -> dict[str, Any]:
    try:
        p = _duong()
        if p.is_file():
            d = json.loads(p.read_text("utf-8") or "{}")
            return d if isinstance(d, dict) else {}
    except Exception as exc:
        logger.warning({"event": "hoi_giam_sat_doc_loi", "loi": str(exc)})
    return {}


def _ghi(d: dict) -> bool:
    """Ghi nguyên tử: nửa chừng mất điện không để lại tệp JSON hỏng."""
    tmp: Path | None = None
    try:
        p = _duong()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), "utf-8")
        os.replace(tmp, p)
        return True
    except Exception as exc:
        logger.warning({"event": "hoi_giam_sat_ghi_loi", "loi": str(exc)})
        return False
    finally:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def dat_cau_hoi(cau_hoi: str, lua_chon: list[str]) -> str:
    """Claude đặt một câu hỏi. Trả về đoạn text đã đánh số để gửi qua Zalo.

    Ghi đè câu hỏi cũ nếu có: mỗi lúc chỉ một câu chờ, để chủ máy trả lời "1"
    thì không mơ hồ là "1" của câu nào.
    """
    ch = (cau_hoi or "").strip()
    ds = [str(x).strip() for x in (lua_chon or []) if str(x).strip()]
    if not ch or not ds:
        return ""
    _ghi({
        "cau_hoi": ch,
        "lua_chon": ds,
        "ts": time.time(),
        "tra_loi": "",
        "tra_loi_ts": 0.0,
    })
    dong = [ch, ""]
    dong += [f"{i}. {x}" for i, x in enumerate(ds, 1)]
    dong += ["", f'Trả lời: nhắn "cl 1" (hoặc số tương ứng).']
    return "\n".join(dong)


def tra_loi(text: str) -> Optional[str]:
    """Chủ máy trả lời qua Zalo. Trả chuỗi xác nhận, hoặc None nếu không phải.

    Gọi từ `zalo_bot` cho tin từ thread admin, đặt cạnh
    `admin_workspace.handle_admin_text` và theo cùng hợp đồng: None thì tin đi
    tiếp như một câu chat bình thường.
    """
    t = (text or "").strip()
    low = t.lower()
    if not any(low.startswith(p) for p in _TIEN_TO):
        return None
    for p in _TIEN_TO:
        if low.startswith(p):
            t = t[len(p):].strip()
            break

    d = _doc()
    ds = [str(x) for x in (d.get("lua_chon") or [])]
    if not ds:
        return "Hiện không có câu hỏi nào của Claude đang chờ."
    if time.time() - float(d.get("ts") or 0) > _HAN:
        return ("Câu hỏi đã quá hạn (hơn 6 giờ) nên em bỏ rồi — "
                "Claude sẽ hỏi lại nếu còn cần.")

    chon = ""
    if t.isdigit():
        i = int(t)
        if 1 <= i <= len(ds):
            chon = ds[i - 1]
    if not chon:
        # Cho gõ thẳng nội dung lựa chọn, khỏi phải đếm số.
        for x in ds:
            if x.lower() == t.lower():
                chon = x
                break
    if not chon:
        return ("Em chưa hiểu. Câu hỏi đang chờ:\n"
                + "\n".join(f"{i}. {x}" for i, x in enumerate(ds, 1)))

    d["tra_loi"] = chon
    d["tra_loi_ts"] = time.time()
    _ghi(d)
    logger.info({"event": "hoi_giam_sat_tra_loi", "chon": chon})
    return f"Đã ghi nhận: **{chon}**. Claude sẽ theo ý này ở lượt tới."


def doc_tra_loi() -> dict[str, Any]:
    """Claude đọc câu trả lời. Rỗng nghĩa là chủ máy chưa trả lời."""
    d = _doc()
    if not d.get("tra_loi"):
        return {}
    if time.time() - float(d.get("ts") or 0) > _HAN:
        return {}
    return {
        "cau_hoi": d.get("cau_hoi") or "",
        "tra_loi": d.get("tra_loi") or "",
        "tra_loi_ts": float(d.get("tra_loi_ts") or 0),
    }


def xoa() -> None:
    """Claude dọn hộp thư sau khi đã hành động theo câu trả lời."""
    _ghi({})


def _reset_for_tests() -> None:
    _ghi({})

"""Nghe phụ đề bằng faster-whisper trên máy GPU, có đường lui về model tại chỗ.

**Vì sao cần.** Đo trên bộ FLEURS (tiếng người kèm bản chữ đúng, 150 bản thu mỗi
tiếng, 14/08/2026) thì model tại chỗ **bỏ trắng** 7% đoạn tiếng Anh và 45% đoạn
tiếng Hàn — không trả chữ nào mà cũng không báo lỗi, nên phụ đề mất dòng một cách
im lặng. Xem `scripts/kiem_nghe.py` để đo lại, `docs/NGHE_GPU.md` để bật.

**Nguyên tắc: thêm GPU không bao giờ làm đứt dịch vụ.** Giống đường máy dịch GPU
(`services/translate_service.py`): lỗi thì rơi ngay về model tại chỗ, và có CẦU
DAO nghỉ 5 phút. Cầu dao là thứ bắt buộc, không phải cho đẹp: máy GPU **treo mà
không tắt hẳn** thì mỗi lượt gọi phải chờ trọn timeout mới rơi về đường tại chỗ,
một phim chia trăm lượt là cộng dồn hàng giờ.

**Hợp đồng trả về** là `(tokens, moc)` — danh sách chữ và mốc giây TUYỆT ĐỐI của
từng chữ, đúng hình dạng mà `services/video_asr.py::gom_khung` đang nhận từ
transducer tại chỗ. Nhờ vậy toàn bộ phần cắt khung phụ đề (tách ở khoảng nghỉ,
chặn khung quá dài) dùng lại y nguyên, không có bộ cắt khung thứ hai để lệch nhau.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

#: Cầu dao — mốc thời gian được phép thử lại máy GPU.
_nghi_toi = 0.0
NGHI_GIAY = 300.0

#: Lô nhỏ để không tràn VRAM: card 8 GB còn gánh camera và máy dịch. Đo trên
#: 2060S: batch 8 và 4 đều CUDA OOM với video 10 phút, batch 2 chạy được.
BATCH = 2


class LoiNgheGpu(RuntimeError):
    """Máy GPU không nghe được — caller phải rơi về đường tại chỗ."""


def dung_duoc(lang: str) -> bool:
    """Có nên gửi tiếng này sang máy GPU không (đã khai URL, chưa bị cầu dao)."""
    from services.voice import config as vcfg

    if not vcfg.stt_gpu_url():
        return False
    if str(lang or "").lower() not in vcfg.stt_gpu_tieng():
        return False
    return time.time() >= _nghi_toi


def _ngat_cau_dao(ly_do: str) -> None:
    global _nghi_toi
    _nghi_toi = time.time() + NGHI_GIAY
    logger.warning("máy nghe GPU lỗi (%s) — rơi về model tại chỗ, nghỉ GPU %.0f phút",
                   ly_do[:160], NGHI_GIAY / 60)


def nghe(duong_wav: str, lang: str, tran_giay: float = 1800.0
         ) -> tuple[list[str], list[float]]:
    """Gửi cả tệp wav sang máy GPU → (tokens, mốc giây tuyệt đối từng token).

    Ném ``LoiNgheGpu`` khi máy GPU không dùng được; caller nghe lại bằng model
    tại chỗ. Mọi lỗi đều ngắt cầu dao trước khi ném.
    """
    from services.voice import config as vcfg

    url = vcfg.stt_gpu_url()
    if not url:
        raise LoiNgheGpu("chưa khai địa chỉ máy nghe GPU")
    import requests

    tep = Path(duong_wav)
    try:
        # Mở tệp NGOÀI khối ngắt cầu dao: tệp wav hỏng là lỗi phía mình, phạt
        # máy GPU nghỉ 5 phút vì chuyện đó là oan. Đọc theo dòng chảy chứ không
        # nạp cả tệp: một phim 150 phút là 288 MB wav 16 kHz.
        f = tep.open("rb")
    except OSError as exc:
        raise LoiNgheGpu(f"không đọc được tệp wav: {exc}") from exc
    try:
        with f:
            r = requests.post(
                f"{url}/nghe",
                files={"tep": (tep.name, f, "audio/wav")},
                data={"lang": str(lang or ""), "batch": str(BATCH)},
                timeout=tran_giay)
        r.raise_for_status()
        body = r.json()
    except Exception as exc:
        _ngat_cau_dao(f"{type(exc).__name__}: {exc}")
        raise LoiNgheGpu(str(exc)[:200]) from exc

    doan = body.get("doan")
    if not isinstance(doan, list):
        _ngat_cau_dao("máy GPU trả thiếu trường 'doan'")
        raise LoiNgheGpu("máy GPU trả thiếu trường 'doan'")

    tokens: list[str] = []
    moc: list[float] = []
    for d in doan:
        if not isinstance(d, dict):
            continue
        tu = d.get("tu")
        if isinstance(tu, list) and tu:
            for w in tu:
                chu = str((w or {}).get("chu") or "")
                if not chu.strip():
                    continue
                tokens.append(chu)
                moc.append(float(w.get("t") or 0.0))
            continue
        # Đoạn không có mốc từng chữ (word_timestamps hụt): coi cả đoạn là MỘT
        # token đặt ở đầu đoạn. Thà khung dài hơn mong muốn còn hơn mất chữ.
        chu = str(d.get("chu") or "")
        if chu.strip():
            tokens.append(chu)
            moc.append(float(d.get("bat_dau") or 0.0))
    if not tokens:
        # KHÔNG ngắt cầu dao: máy chạy tốt, chỉ là tệp này không có tiếng nói.
        raise LoiNgheGpu("máy GPU không nghe ra chữ nào")
    return tokens, moc

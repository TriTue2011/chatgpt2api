"""Nghe tệp video/âm thanh ra chữ KÈM dấu thời gian — cho tệp không có phụ đề.

Toàn bộ bằng đồ có sẵn trong image, không tải thêm gì: ffmpeg bóc tiếng, bộ
nghe sherpa-onnx của phần giọng nói (model Việt Zipformer + Anh Parakeet — cả
hai là transducer nên trả mốc thời gian theo từng token, đo thật 13/08).

Đường đi: tệp → wav 16 kHz mono → cắt ĐOẠN CÓ TIẾNG bằng năng lượng (model
transducer suy giảm khi nghe cả phút liền, và khoảng lặng dài là chỗ mọi bộ
nghe hay bịa chữ) → nghe từng đoạn → ghép mốc token thành khung phụ đề.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: Đuôi tệp nhận nghe. Nhận cả tệp thuần âm thanh — cùng một đường.
DUOI_VIDEO = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".3gp")
DUOI_TIENG = (".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac", ".wma")

#: Một đoạn đưa vào bộ nghe dài nhất ngần này giây. Zipformer huấn luyện trên
#: câu ngắn; đoạn quá dài vừa tốn RAM vừa giảm chất lượng.
DOAN_TOI_DA = 28.0
#: Lặng ngắn hơn ngưỡng này thì coi như vẫn đang nói (nghỉ lấy hơi).
LANG_NOI_LIEN = 0.4
#: Đệm hai đầu mỗi đoạn để không cắt cụt phụ âm đầu/cuối.
DEM = 0.15

#: Trong một đoạn, hai token cách nhau quá ngưỡng này thì tách khung phụ đề —
#: ranh giới tự nhiên giữa hai ý.
KHE_TACH_KHUNG = 0.7
KHUNG_TOI_DA_GIAY = 10.0


class LoiNghe(RuntimeError):
    """Không nghe được tệp — thông điệp đưa thẳng cho người dùng."""


@dataclass
class Cau:
    bat_dau: float
    ket_thuc: float
    chu: str


def la_tep_nghe_duoc(ten: str) -> bool:
    t = str(ten or "").lower()
    return t.endswith(DUOI_VIDEO) or t.endswith(DUOI_TIENG)


def _boc_tieng(duong: str) -> str:
    """Tệp video/âm thanh → wav 16 kHz mono, trả đường dẫn wav tạm."""
    ra = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    try:
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-i", duong, "-vn", "-ac", "1", "-ar", "16000",
             "-f", "wav", ra],
            capture_output=True, timeout=600,
        )
    except FileNotFoundError as exc:
        raise LoiNghe("thiếu ffmpeg trong image") from exc
    except subprocess.TimeoutExpired as exc:
        raise LoiNghe("bóc tiếng quá 10 phút — tệp quá lớn hoặc hỏng") from exc
    if p.returncode != 0 or not Path(ra).is_file() or Path(ra).stat().st_size < 100:
        loi = (p.stderr or b"").decode("utf-8", "ignore")[:150]
        raise LoiNghe(f"không đọc được tiếng trong tệp ({loi or 'ffmpeg lỗi'})")
    return ra


def _doc_wav(duong: str):
    """wav 16k mono s16 → (mảng float32, tần số)."""
    import wave

    import numpy as np

    with wave.open(duong, "rb") as w:
        rate = w.getframerate()
        pcm = w.readframes(w.getnframes())
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0, rate


def cat_doan_tieng(mau, rate: int) -> list[tuple[float, float]]:
    """Tìm các đoạn CÓ TIẾNG theo năng lượng → [(bắt đầu, kết thúc)] giây.

    Ngưỡng đặt TƯƠNG ĐỐI theo chính tệp (gấp 3 lần nền ồn phân vị 10) chứ không
    tuyệt đối: video quay điện thoại nền ồn to, video studio nền gần im — một
    ngưỡng cứng sẽ hỏng một trong hai.
    """
    import numpy as np

    khung = int(rate * 0.1)
    if len(mau) < khung:
        return []
    n = len(mau) // khung
    rms = np.sqrt((mau[: n * khung].reshape(n, khung) ** 2).mean(axis=1))
    # Hai chốt chặn cho hai kiểu tệp cực đoan: "nhân 3 nền ồn" chết ở tệp NÓI
    # LIÊN TỤC không nghỉ (phân vị 10 đã là tiếng nói, nhân 3 vượt mọi khung —
    # test lòi ra); nên kẹp trần bằng 30% phân vị 90 (mức "đang nói" điển
    # hình). Sàn 0.008 cho tệp im lặng hoàn toàn khỏi nhận nhiễu làm tiếng.
    nen = float(np.percentile(rms, 10))
    dinh = float(np.percentile(rms, 90))
    nguong = max(0.008, min(nen * 3.0, dinh * 0.3))
    noi = rms > nguong
    if not bool(noi.any()):
        return []

    ra: list[tuple[float, float]] = []
    bat: float | None = None
    lang = 0
    cho_lang = int(LANG_NOI_LIEN / 0.1)
    for i, co in enumerate(noi):
        t = i * 0.1
        if co:
            if bat is None:
                bat = t
            lang = 0
        elif bat is not None:
            lang += 1
            if lang >= cho_lang:
                ra.append((bat, t - (lang - 1) * 0.1))
                bat, lang = None, 0
    if bat is not None:
        ra.append((bat, n * 0.1))

    # Đệm biên, bỏ mẩu quá ngắn, và CẮT đoạn dài quá sức model.
    dai_tep = len(mau) / rate
    sach: list[tuple[float, float]] = []
    for b, k in ra:
        b, k = max(0.0, b - DEM), min(dai_tep, k + DEM)
        if k - b < 0.3:
            continue
        while k - b > DOAN_TOI_DA:
            sach.append((b, b + DOAN_TOI_DA))
            b += DOAN_TOI_DA
        sach.append((b, k))
    return sach


def _nghe_mot_doan(rec, mau, rate: int) -> tuple[list[str], list[float]]:
    """Một đoạn tiếng → (tokens, mốc giây từng token). Gọi khi ĐÃ giữ khoá STT."""
    stream = rec.create_stream()
    stream.accept_waveform(rate, mau)
    rec.decode_stream(stream)
    r = stream.result
    return list(r.tokens or []), [float(x) for x in (r.timestamps or [])]


def gom_khung(tokens: list[str], moc: list[float], goc: float) -> list[Cau]:
    """Token + mốc → các khung phụ đề, tách ở khoảng nghỉ dài giữa hai token.

    ``goc`` = mốc bắt đầu của đoạn trong cả tệp — mốc token tính từ đầu ĐOẠN.
    """
    if not tokens or len(tokens) != len(moc):
        return []
    ra: list[Cau] = []
    dau = 0
    for i in range(1, len(tokens) + 1):
        het = i == len(tokens)
        if not het and moc[i] - moc[i - 1] < KHE_TACH_KHUNG \
                and moc[i] - moc[dau] < KHUNG_TOI_DA_GIAY:
            continue
        chu = "".join(tokens[dau:i]).strip()
        if chu:
            ra.append(Cau(goc + moc[dau], goc + moc[i - 1] + 0.35, chu))
        dau = i
    return ra


#: Mỗi cửa sổ dò tối đa ngần này giây, gom đủ ~8 giây quanh mỗi mốc lấy mẫu.
_DO_CUA_SO = 10.0
_DO_MOI_MOC = 8.0
#: Dưới ngần này token coi như model không nghe ra gì (nhạc nền, im lặng).
_TOKEN_TOI_THIEU = 5
#: Model en phải tự tin hơn model vi quá mức này mới thắng — máy ưu tiên tiếng
#: Việt, và video Việt chêm từ tiếng Anh là chuyện thường.
_CHENH_THANG = 0.1


def _chon_ngon_ngu(mau, rate: int, doan: list[tuple[float, float]]) -> str:
    """Video nói tiếng gì — vi hay en.

    Nghe THỬ vài mẫu bằng CẢ HAI model rồi so độ tự tin giải mã
    (``ys_log_probs`` của transducer): model đúng ngôn ngữ tự tin ~-0.04,
    model sai ~-0.5÷-0.6, nhạc nền ~-1.7 hoặc im lặng — đo thật 13/08 trên
    video tiếng Anh (Zootopia) và giọng TTS tiếng Việt, hai phía cách nhau
    hơn 10 lần nên không cần thư viện đoán ngôn ngữ nào nữa. Bản trước dùng
    langdetect chết từ trứng nước: thư viện không có trong image, cộng với
    mẫu "20 giây đầu" dính ngay nhạc mở màn → mọi tệp rơi về mặc định vi
    (video Zootopia 25 phút bị nghe bằng model Việt, đo thật 13/08).

    Mẫu lấy RẢI ở 1/4, 1/2 và 3/4 danh sách đoạn tiếng — video hay mở màn
    bằng nhạc, giữa thân video mới chắc là lời nói.
    """
    from services.voice import engines as eng

    cua_so: list = []
    da_lay: set[int] = set()
    for phan in (0.25, 0.5, 0.75):
        i = min(len(doan) - 1, int(len(doan) * phan))
        tong = 0.0
        while i < len(doan) and tong < _DO_MOI_MOC:
            if i not in da_lay:
                da_lay.add(i)
                b, k = doan[i]
                k = min(k, b + _DO_CUA_SO)
                cua_so.append(mau[int(b * rate):int(k * rate)])
                tong += k - b
            i += 1

    def _tu_tin(lang: str) -> tuple[float, int]:
        """(trung bình log-prob, số token) khi nghe các cửa sổ mẫu."""
        du: list[float] = []
        try:
            # Lấy recognizer TRƯỚC khi giữ khoá: _get_recognizer tự xin
            # _stt_lock bên trong, mà khoá này không tái nhập — gọi lồng là
            # tự khoá chết mình (treo thật 13/08, đúng 10 phút timeout).
            rec = eng._get_recognizer(lang)
            for thu in cua_so:
                with eng._stt_lock:
                    stream = rec.create_stream()
                    stream.accept_waveform(rate, thu)
                    rec.decode_stream(stream)
                    du.extend(float(x) for x in
                              (getattr(stream.result, "ys_log_probs", None) or []))
        except Exception as exc:
            logger.info("dò ngôn ngữ bằng model %s lỗi: %s", lang, str(exc)[:120])
            return -9.9, 0
        if not du:
            return -9.9, 0
        return sum(du) / len(du), len(du)

    vi_tb, vi_n = _tu_tin("vi")
    en_tb, en_n = _tu_tin("en")
    if en_n < _TOKEN_TOI_THIEU:
        ra = "vi"
    elif vi_n < _TOKEN_TOI_THIEU:
        ra = "en"
    else:
        ra = "en" if en_tb > vi_tb + _CHENH_THANG else "vi"
    logger.info("dò ngôn ngữ: vi %.3f (%d token) / en %.3f (%d token) → %s",
                vi_tb, vi_n, en_tb, en_n, ra)
    return ra


def nghe_tep(duong: str, tran_giay: float = 0) -> tuple[list[Cau], str, float]:
    """Tệp video/âm thanh → (các khung chữ có mốc, ngôn ngữ, số giây tiếng).

    ``tran_giay`` > 0 thì từ chối tệp dài hơn — kiểm SAU khi bóc tiếng (rẻ)
    và TRƯỚC khi nghe (đắt). Raise ``LoiNghe`` với thông điệp đưa thẳng được
    cho người dùng.
    """
    from services.voice import engines as eng

    wav = _boc_tieng(duong)
    try:
        mau, rate = _doc_wav(wav)
        if tran_giay and len(mau) / rate > tran_giay:
            raise LoiNghe(
                f"tệp dài {len(mau) / rate / 60:.0f} phút, quá mức "
                f"{tran_giay / 60:.0f} phút mà em nghe được — video YouTube "
                f"thì gửi em link sẽ nhanh hơn nhiều")
        doan = cat_doan_tieng(mau, rate)
        if not doan:
            raise LoiNghe("không thấy tiếng nói nào trong tệp")
        lang = _chon_ngon_ngu(mau, rate, doan)
        rec = eng._get_recognizer(lang)

        ra: list[Cau] = []
        for b, k in doan:
            # Khoá theo TỪNG đoạn chứ không cả vòng lặp: bộ nghe dùng chung với
            # voice note của bot, giữ khoá suốt một video 30 phút là chặn mọi
            # tin nhắn thoại ngần ấy thời gian.
            with eng._stt_lock:
                tokens, moc = _nghe_mot_doan(rec, mau[int(b * rate):int(k * rate)], rate)
            ra.extend(gom_khung(tokens, moc, b))

        sach = [Cau(c.bat_dau, c.ket_thuc, eng._normalize_stt(c.chu)) for c in ra]
        sach = [c for c in sach if c.chu]
        if not sach:
            raise LoiNghe("không nghe ra chữ nào trong tệp")
        return sach, lang, sum(k - b for b, k in doan)
    finally:
        try:
            Path(wav).unlink()
        except OSError:
            pass

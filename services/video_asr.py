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
#: Hai đoạn local kế tiếp chồng lên nhau một nhịp lấy hơi. Whisper nghe cả tệp
#: nên không cần nó, còn model local phải thấy cả từ ở biên 28 giây để không
#: nuốt mất lúc GPU bỏ sót và đường bù được kích hoạt.
DOAN_CHONG_GIAY = 0.4

#: GPU đôi lúc trả được một phần tệp nhưng VAD bỏ trắng hẳn một cụm thoại.
#: Nếu khe trong đoạn năng lượng vượt ngưỡng này, nghe bù RIÊNG khe đó bằng
#: model tại chỗ. ``cat_doan_tieng`` đã tách khoảng lặng >= 0,4 s thành đoạn
#: khác, nên 1 giây còn lại không phải là nhịp lấy hơi bình thường; giữ 4 giây
#: khiến câu thoại ngắn (dạng lỗi 1:30/2:23) biến mất im lặng.
KHE_BO_SOT_GIAY = 1.0

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


@dataclass
class KetQuaNghe:
    """Kết quả nghe kèm nguồn STT thực tế đã dùng.

    API cũ của :func:`nghe_tep` trả đúng bộ ba ``(câu, tiếng, giây)``. Chi tiết
    này chỉ được trả khi caller chủ động xin, để các lối dùng cũ không đổi hợp
    đồng. Nó rất quan trọng với phụ đề tiếng Anh: GPU tắt từng bị rơi im lặng
    về model tại chỗ, đến khi người dùng mở SRT sai mới biết.
    """

    cau: list[Cau]
    ngon_ngu: str
    giay_tieng: float
    engine: str                     # gpu | gpu_recovered | gpu_incomplete | local | local_fallback
    canh_bao: str = ""

    def __iter__(self):
        """Tương thích với chỗ gọi vẫn unpack ba giá trị như trước."""
        yield self.cau
        yield self.ngon_ngu
        yield self.giay_tieng


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


def _khung_co_tieng(mau, rate: int):
    """Mặt nạ năng lượng 100 ms dùng chung cho nghe và soát độ phủ GPU."""
    import numpy as np

    khung = int(rate * 0.1)
    if len(mau) < khung:
        return None, khung
    n = len(mau) // khung
    rms = np.sqrt((mau[: n * khung].reshape(n, khung) ** 2).mean(axis=1))
    # Hai chốt chặn cho hai kiểu tệp cực đoan: "nhân 3 nền ồn" chết ở tệp NÓI
    # LIÊN TỤC không nghỉ (phân vị 10 đã là tiếng nói, nhân 3 vượt mọi khung —
    # test lòi ra); nên kẹp trần bằng 30% phân vị 90 (mức "đang nói" điển
    # hình). Sàn 0.008 cũ lại bỏ trắng hẳn tệp quay nhỏ tiếng (RMS ~0.004),
    # nên chỉ giữ sàn đó khi đỉnh đủ lớn; tệp rất nhỏ dùng sàn 0.0005 và để STT
    # quyết định thay vì mất lời thoại ngay từ VAD.
    nen = float(np.percentile(rms, 10))
    dinh = float(np.percentile(rms, 90))
    nguong_tuong_doi = min(nen * 3.0, dinh * 0.3)
    nguong = max(0.008 if dinh >= 0.008 else 0.0005, nguong_tuong_doi)
    noi = rms > nguong
    return (noi if bool(noi.any()) else None), khung


def cat_doan_tieng(mau, rate: int) -> list[tuple[float, float]]:
    """Tìm các đoạn CÓ TIẾNG theo năng lượng → [(bắt đầu, kết thúc)] giây.

    Ngưỡng đặt TƯƠNG ĐỐI theo chính tệp (gấp 3 lần nền ồn phân vị 10) chứ không
    tuyệt đối: video quay điện thoại nền ồn to, video studio nền gần im — một
    ngưỡng cứng sẽ hỏng một trong hai.
    """
    noi, khung = _khung_co_tieng(mau, rate)
    if noi is None:
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
        ra.append((bat, len(noi) * 0.1))

    # Đệm biên, bỏ mẩu quá ngắn, và CẮT đoạn dài quá sức model.
    dai_tep = len(mau) / rate
    sach: list[tuple[float, float]] = []
    for b, k in ra:
        b, k = max(0.0, b - DEM), min(dai_tep, k + DEM)
        if k - b < 0.3:
            continue
        while k - b > DOAN_TOI_DA:
            cat = b + DOAN_TOI_DA
            sach.append((b, cat))
            b = cat - DOAN_CHONG_GIAY
        sach.append((b, k))
    return sach


def doan_nang_luong_chi_tiet(mau, rate: int) -> list[tuple[float, float]]:
    """Các dải năng lượng đang có tiếng, không nối qua khoảng lặng.

    Đây không phải đơn vị đưa vào recognizer: nhận dạng local vẫn dùng
    :func:`cat_doan_tieng` dài và có đệm. Dải chi tiết chỉ trả lời đúng câu hỏi
    audit: GPU bỏ phụ đề tại chính thời điểm âm thanh còn có năng lượng hay chỉ
    là khoảng lặng cuối câu? Nhờ đó ngưỡng 1 giây không tạo lượt nghe bù giả.
    """
    noi, _khung = _khung_co_tieng(mau, rate)
    if noi is None:
        return []
    ra: list[tuple[float, float]] = []
    bat: float | None = None
    for i, co in enumerate(noi):
        t = i * 0.1
        if co and bat is None:
            bat = t
        elif not co and bat is not None:
            ra.append((bat, t))
            bat = None
    if bat is not None:
        ra.append((bat, len(noi) * 0.1))
    return ra


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


def doan_tieng_bi_bo_sot(doan: list[tuple[float, float]], cau: list[Cau]
                          ) -> list[tuple[float, float]]:
    """Trả các khoảng có tiếng nhưng GPU chưa tạo phụ đề.

    Không chỉ kiểm ``ra == []``: một kết quả Whisper không rỗng vẫn có thể bỏ
    cả một câu vì VAD. Cắt theo đoạn năng lượng đã dùng cho local rồi tìm khe
    phụ đề đủ dài; như vậy không phải nghe lại cả phim và không lẫn khoảng im
    giữa các cảnh với lời thoại bị mất.
    """
    ra: list[tuple[float, float]] = []
    for b, k in doan:
        khung = sorted((c for c in cau if c.ket_thuc > b and c.bat_dau < k),
                       key=lambda c: c.bat_dau)
        if not khung:
            ra.append((b, k))
            continue
        den = b
        for c in khung:
            bat = max(b, c.bat_dau)
            if bat - den > KHE_BO_SOT_GIAY:
                ra.append((den, bat))
            den = max(den, min(k, c.ket_thuc))
        if k - den > KHE_BO_SOT_GIAY:
            ra.append((den, k))
    # Các dải audit là khung 100 ms nên một từ có thể rơi vào vài dải kề nhau.
    # Gộp rồi đệm một nhịp ở hai biên để recognizer local không nuốt phụ âm
    # đầu/cuối, đồng thời không xin khoá STT hàng chục lần cho một câu.
    if not ra:
        return []
    ra.sort()
    gom: list[tuple[float, float]] = []
    for b, k in ra:
        if gom and b - gom[-1][1] <= LANG_NOI_LIEN:
            truoc_b, truoc_k = gom[-1]
            gom[-1] = (truoc_b, max(truoc_k, k))
        else:
            gom.append((b, k))
    return [(max(0.0, b - DEM), k + DEM) for b, k in gom]


#: Mỗi cửa sổ dò tối đa ngần này giây, gom đủ ~8 giây quanh mỗi mốc lấy mẫu.
_DO_CUA_SO = 10.0
_DO_MOI_MOC = 8.0
#: Dưới ngần này token coi như model không nghe ra gì (nhạc nền, im lặng).
_TOKEN_TOI_THIEU = 5
#: Model en phải tự tin hơn model vi quá mức này mới thắng — máy ưu tiên tiếng
#: Việt, và video Việt chêm từ tiếng Anh là chuyện thường.
_CHENH_THANG = 0.1


def _chon_ngon_ngu(mau, rate: int, doan: list[tuple[float, float]],
                   ung_vien: tuple[str, ...] = ("vi", "en")) -> str:
    """Video nói tiếng gì — so độ tự tin giữa CÁC model ứng viên.

    ``ung_vien``: nhóm tiếng đem so (theo tính năng + thread — xem
    ``vcfg.stt_nhom_tieng``). Một tiếng = khoá cứng, không đo gì. Hai tiếng =
    phép so đã đo chắc (đúng ~-0,04 vs sai ~-0,5). Ba tiếng trở lên vẫn chạy
    nhưng mỗi tiếng thêm là thêm một lượt nghe: chậm gấp N và biên an toàn hẹp
    lại — UI phải nói rõ điều đó cho người chọn.

    Tiếng Việt (nếu có trong nhóm) được cộng biên ``_CHENH_THANG``: máy này ưu
    tiên tiếng Việt và video Việt chêm từ ngoại là chuyện thường. Model chưa
    tải trên đĩa thì phía đó câm → không thắng được.

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
        """(trung bình log-prob, số token) khi nghe các cửa sổ mẫu.

        Model SenseVoice (zh/ja/ko) KHÔNG trả ``ys_log_probs``, nên nhánh dưới
        chấm nó bằng thứ nó có: chính nó khai tiếng nghe được (``<|ja|>``).
        Không có nhánh này thì mọi tiếng dùng SenseVoice đều bị chấm -9,9 và
        thua trắng, tức video tiếng Nhật bị nghe bằng model tiếng Việt mà
        không ai báo — đúng kiểu hỏng im lặng nguy nhất ở đường phụ đề.
        """
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
                    kq = stream.result
                    diem_lp = [float(x) for x in
                               (getattr(kq, "ys_log_probs", None) or [])]
                    if diem_lp:
                        du.extend(diem_lp)
                        continue
                    # Quy về CÙNG THANG với log-prob của transducer để hai loại
                    # model so được với nhau: model đúng tiếng ~-0,04, model sai
                    # ~-0,5÷-0,6 (đo 13/08). Khai đúng tiếng thì cho -0,04; khai
                    # tiếng khác thì -0,9, tức thua chắc nhưng vẫn hơn "câm".
                    khai = str(getattr(kq, "lang", "") or "").strip("<|> ")
                    if khai and (kq.tokens or []):
                        du.extend([-0.04 if khai == lang else -0.9]
                                  * len(kq.tokens))
        except Exception as exc:
            logger.info("dò ngôn ngữ bằng model %s lỗi: %s", lang, str(exc)[:120])
            return -9.9, 0
        if not du:
            return -9.9, 0
        return sum(du) / len(du), len(du)

    nhom = [x for x in dict.fromkeys(ung_vien) if x] or ["vi"]
    if len(nhom) == 1:
        return nhom[0]          # khoá cứng: không tốn lượt nghe nào để dò
    diem: dict[str, tuple[float, int]] = {}
    for lang in nhom:
        diem[lang] = _tu_tin(lang)
    # Điểm so sánh: tiếng Việt được cộng biên ưu tiên.
    def _xep(lang: str) -> float:
        tb, n = diem[lang]
        if n < _TOKEN_TOI_THIEU:
            return -99.0        # câm (chưa tải model / nhạc nền) → không thắng
        return tb + (_CHENH_THANG if lang == "vi" else 0.0)

    ra = max(nhom, key=_xep)
    if _xep(ra) <= -99.0:       # mọi model đều câm → về mặc định
        ra = "vi" if "vi" in nhom else nhom[0]
    logger.info("dò ngôn ngữ trong %s: %s → %s", nhom,
                {k: (round(v[0], 3), v[1]) for k, v in diem.items()}, ra)
    return ra


def nghe_tep(duong: str, tran_giay: float = 0,
             ung_vien: tuple[str, ...] = ("vi", "en"), *,
             chi_tiet: bool = False) -> tuple[list[Cau], str, float] | KetQuaNghe:
    """Tệp video/âm thanh → (các khung chữ có mốc, ngôn ngữ, số giây tiếng).

    ``ung_vien``: cặp ngôn ngữ đem dò (xem ``_chon_ngon_ngu``) — người dùng
    chọn cặp Việt↔Trung thì so vi với zh thay vì en.

    ``chi_tiet`` chỉ dành cho đường phụ đề: trả thêm engine thực tế và cảnh
    báo khi tiếng Anh rơi về local. Mặc định vẫn là bộ ba cũ để không làm gãy
    các caller đã có.

    ``tran_giay`` > 0 thì từ chối tệp dài hơn — kiểm SAU khi bóc tiếng (rẻ)
    và TRƯỚC khi nghe (đắt). Raise ``LoiNghe`` với thông điệp đưa thẳng được
    cho người dùng.
    """
    from services import nghe_gpu
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
        # Đơn vị dài/đệm dùng để local STT và dò ngôn ngữ; mặt nạ năng lượng
        # chi tiết chỉ dùng để soát Whisper GPU bỏ một câu NGẮN trong cùng câu.
        doan_audit = doan_nang_luong_chi_tiet(mau, rate)
        if not doan:
            raise LoiNghe("không thấy tiếng nói nào trong tệp")
        lang = _chon_ngon_ngu(mau, rate, doan, ung_vien)

        # Nghe bằng máy GPU trước NẾU tiếng này đã đo là tại chỗ nghe kém (mặc
        # định en và ko — model tại chỗ bỏ trắng 7% và 45% đoạn). Nhận diện
        # ngôn ngữ vẫn làm tại chỗ: nó rẻ và đã chạy đúng. Lỗi thì rơi xuống
        # đường tại chỗ ngay bên dưới, phụ đề không bao giờ vì thế mà đứt.
        ra: list[Cau] = []
        engine = "local"
        canh_bao = ""
        doan_tin_thap: list[tuple[float, float]] = []
        if nghe_gpu.dung_duoc(lang):
            try:
                ket_qua_gpu = nghe_gpu.nghe(wav, lang)
                tokens, moc = ket_qua_gpu
                doan_tin_thap = list(getattr(ket_qua_gpu, "doan_tin_thap", []) or [])
                ra = gom_khung(tokens, moc, 0.0)   # mốc GPU đã là tuyệt đối
                if ra:
                    engine = "gpu"
                    if doan_tin_thap:
                        canh_bao = (f"Whisper GPU có {len(doan_tin_thap)} đoạn độ tin cậy "
                                     "thấp; nên đối chiếu lại lời thoại ở các mốc đó.")
                    logger.info("phụ đề: nghe %s bằng máy GPU — %d khung", lang, len(ra))
            except nghe_gpu.LoiNgheGpu as exc:
                engine = "local_fallback"
                # Không ghép chi tiết exception vào tin bot: URL nội bộ và lỗi
                # requests không giúp người xem SRT, còn log đã giữ để admin dò.
                canh_bao = ("Whisper GPU không dùng được nên đã nghe lại bằng "
                             "model tại chỗ.")
                logger.info("phụ đề: máy GPU không nghe được (%s) — nghe tại chỗ",
                            str(exc)[:120])

        bo_sot = doan_tieng_bi_bo_sot(doan_audit, ra) if ra else doan
        if bo_sot:
            ra_bu: list[Cau] = []
            co_gpu = bool(ra)
            loi_nghe_bu = False
            try:
                rec = eng._get_recognizer(lang)
                for b, k in bo_sot:
                    # Khoá theo TỪNG đoạn chứ không cả vòng lặp: bộ nghe dùng chung
                    # với voice note của bot, giữ khoá suốt một video 30 phút là
                    # chặn mọi tin nhắn thoại ngần ấy thời gian.
                    with eng._stt_lock:
                        tokens, moc = _nghe_mot_doan(
                            rec, mau[int(b * rate):int(k * rate)], rate)
                    ra_bu.extend(gom_khung(tokens, moc, b))
            except Exception as exc:
                if not co_gpu:
                    raise
                loi_nghe_bu = True
                engine = "gpu_incomplete"
                canh_bao = " ".join(x for x in (
                    canh_bao,
                    f"Whisper GPU bỏ sót {len(bo_sot)} đoạn tiếng; STT local "
                    "không nghe bù được, cần kiểm tra lại.") if x)
                logger.warning("phụ đề: STT local không bù được %d đoạn GPU bỏ sót: %s",
                               len(bo_sot), str(exc)[:120])
            if co_gpu and not loi_nghe_bu:
                ra.extend(ra_bu)
                ra.sort(key=lambda c: (c.bat_dau, c.ket_thuc))
                con_sot = doan_tieng_bi_bo_sot(doan_audit, ra)
                da_bu = len(bo_sot) - len(con_sot)
                if con_sot:
                    engine = "gpu_incomplete"
                    canh_bao = " ".join(x for x in (
                        canh_bao,
                        f"Whisper GPU bỏ sót {len(bo_sot)} đoạn tiếng; STT local chỉ "
                        f"bù được {da_bu}, còn {len(con_sot)} đoạn cần kiểm tra lại.") if x)
                else:
                    engine = "gpu_recovered"
                    canh_bao = " ".join(x for x in (
                        canh_bao,
                        f"Whisper GPU bỏ sót {len(bo_sot)} đoạn tiếng; đã nghe bù "
                        "bằng model tại chỗ.") if x)
                    logger.warning("phụ đề: Whisper GPU bỏ sót %d đoạn tiếng, đã bù local",
                                   len(bo_sot))
            elif not co_gpu:
                ra.extend(ra_bu)

        sach = [Cau(c.bat_dau, c.ket_thuc, eng._normalize_stt(c.chu)) for c in ra]
        sach = [c for c in sach if c.chu]
        if not sach:
            raise LoiNghe("không nghe ra chữ nào trong tệp")
        # FLEURS cho thấy tiếng Anh local có WER cao hơn hẳn Whisper GPU. Báo
        # rõ ở kết quả thay vì để rơi im lặng — đây là thông tin vận hành, không
        # phải kết luận rằng mọi phụ đề local đều sai.
        if lang == "en" and engine == "local":
            canh_bao = ("Tiếng Anh được nghe bằng model tại chỗ, không phải "
                         "Whisper GPU; tên riêng và thoại có thể kém chính xác hơn.")
        ket = KetQuaNghe(sach, lang, sum(k - b for b, k in doan), engine, canh_bao)
        return ket if chi_tiet else (ket.cau, ket.ngon_ngu, ket.giay_tieng)
    finally:
        try:
            Path(wav).unlink()
        except OSError:
            pass

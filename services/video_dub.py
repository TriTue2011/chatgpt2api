"""Lồng tiếng video bằng các engine TTS đã có, kèm ``prosody.json``.

Đường này cố ý độc lập với việc tạo phụ đề: caller đưa SRT đã dịch và video
gốc vào, nhận một video trong đó lời thoại gốc được thay bằng TTS nhưng nhạc và
hiệu ứng vẫn giữ. Muốn làm đúng phải source-separation trước; không được trộn
âm gốc nhỏ đi vì lời cũ sẽ lọt, cũng không được bỏ cả track khiến phim mất nền.

Prosody đo từ track gốc ở đúng mốc từng cue. Khi chưa có diarization, trường
``speaker`` là ``UNKNOWN`` — thà nói chưa biết còn hơn gán nhầm giới tính.
"""
from __future__ import annotations

import json
import logging
import math
import re
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, Callable

logger = logging.getLogger(__name__)

RATE_GOC = 16000
RATE_DUB = 24000
#: Hệ số đọc chậm nhất cho phép. Dưới mức này giọng bị kéo nhoè phụ âm và nghe
#: như máy hỏng; phần khung còn thừa để im lặng thì tự nhiên hơn hẳn.
TEMPO_CHAM_NHAT = 0.7
#: Trần dịch cao độ theo cue, tính bằng nửa cung. ĐANG TẮT (0.0).
#:
#: Đo trên một video thật (53 câu, một giọng) cho thấy vì sao. ``pitch_relative``
#: đo được trải từ -9,65 đến +4,56 nửa cung — vô lý với một người dẫn duy nhất,
#: vì nó đo trên track còn lẫn nhạc và tiếng máy. Kẹp một dãy số nhiễu như thế
#: vào ±2 thì phép kẹp BÃO HOÀ: độ lệch chuẩn của lượng dịch thực áp là 1,81
#: trên biên 2,0, tức gần như câu nào cũng bị đẩy hẳn về một trong hai đầu.
#: Kết quả không phải biến hoá nhẹ mà là các câu liên tiếp nhảy qua lại giữa hai
#: mức cách nhau 4 nửa cung — nghe thành hai người thay phiên.
#:
#: Cao độ đầu ra bám lượng dịch với hệ số tương quan +0,83, nên đây là nguyên
#: nhân chứ không phải trùng hợp. Bỏ hẳn thì trải rộng giảm từ 7,1 xuống 4,4 nửa
#: cung, phần còn lại là ngữ điệu tự nhiên của chính TTS.
#:
#: Chỉ bật lại khi đo được F0 trên stem giọng đã tách; đo trên bản trộn thì con
#: số không dùng được. Vẫn giữ ``pitch_relative`` trong JSON làm dữ liệu.
PITCH_TOI_DA = 0.0
#: Mức to mục tiêu của track lồng tiếng, tính bằng LUFS tích hợp (chuẩn EBU
#: R128). Video web thường nằm khoảng -16 đến -14. Cả đường ống trước đây không
#: có bước chuẩn hoá nào: nền lấy từ máy tách âm ở mức nào giữ nguyên mức đó,
#: TTS ở mức engine trả về, ``amix`` chỉ cộng lại còn ``alimiter`` chỉ chặn đỉnh
#: chứ không bù lên. Đo bản chạy thật 17/08 được -21,3 LUFS trong khi đỉnh thật
#: mới -4,1 dBFS — nhỏ hơn thông lệ 5 dB mà vẫn còn thừa 4 dB chưa dùng.
DO_TO_MUC_TIEU = -16.0
#: Chặn hai đầu lượng bù. Một phim gần như im lặng đo ra -70 LUFS mà bù thẳng
#: +54 dB thì tiếng nền nhỏ cũng thành tiếng gào.
BU_AM_TOI_DA = 12.0
#: Trần đỉnh sau khi bù, và PHẢI tắt tự cân mức của ``alimiter``. Mặc định bộ
#: lọc này tự kéo tín hiệu lên sát trần, nên lượng bù tính ra không còn đúng.
#: Đo thật 17/08 trên cùng một tệp, cùng bù +5,30 dB: để mặc định ra -15,6 LUFS
#: với đỉnh thật chạm 0,0 dBFS (sát méo), còn tắt tự cân thì ra đúng -16,0 LUFS
#: với đỉnh -0,9 dBFS — vừa đúng mức vừa còn khoảng an toàn.
TRAN_DINH = 0.89
#: Dải F0 tiếng người. Dưới 70 Hz gần như chỉ còn tiếng trầm của nhạc/máy móc,
#: trên 350 Hz là hoạ âm chứ hiếm khi là tần số cơ bản của lời thoại.
F0_THAP = 70.0
F0_CAO = 350.0
#: Khung phân tích F0: 64 ms chứa được vài chu kỳ của giọng trầm nhất mà vẫn
#: ngắn hơn một âm tiết, nên không gộp nhiều cao độ vào một phép đo.
F0_KHUNG_GIAY = 0.064
#: Đỉnh tự tương quan chuẩn hoá nằm trong khoảng 0..1 và chính là thước đo mức
#: tuần hoàn. Dưới ngưỡng này là khung không tuần hoàn — nhiễu, tiếng va đập,
#: khoảng lặng — nên bỏ hẳn thay vì gán cho nó một cao độ bịa. Lưu ý phép đo này
#: KHÔNG phân biệt được giọng người với một nốt nhạc ngân đều: cả hai đều tuần
#: hoàn. Muốn loại nốt nhạc thì phải đo trên stem giọng đã tách.
F0_NGUONG_TUAN_HOAN = 0.35
#: Cần vài khung cùng đồng ý thì trung vị mới có nghĩa.
F0_KHUNG_TOI_THIEU = 3
#: Một lần thử lại ngay tại cue lỗi: giữ nguyên track đã tổng hợp trước đó,
#: đủ cứu lỗi engine thoáng qua mà không nhân đôi thời gian của mọi câu.
TTS_SO_LAN_TOI_DA = 2
TTS_CHO_THU_LAI_GIAY = 0.5
Progress = Callable[[int, int, str], None]


class LoiLongTieng(RuntimeError):
    """Đầu vào, giọng hoặc ffmpeg không đủ để tạo bản lồng tiếng."""


class LoiLongTiengTamThoi(LoiLongTieng):
    """Lỗi có khả năng TỰ HẾT (quá giờ vì máy đang tải), đáng thử lại một lần.

    Là lớp con nên mọi ``except LoiLongTieng`` sẵn có vẫn bắt được như cũ; chỉ
    thêm cho chỗ nào muốn phân biệt "hỏng hẳn" với "lúc này đang bận".
    """


@dataclass(frozen=True)
class KetQuaLongTieng:
    video_path: str
    prosody_path: str
    voice: str
    so_cau: int
    so_cau_loi: int = 0
    canh_bao: str = ""


def _hop_tieng(row: dict[str, Any], lang: str) -> bool:
    ngon_ngu = str(row.get("language") or "").lower()
    ma = str(lang or "").lower().split("-", 1)[0]
    if ma == "vi":
        return ngon_ngu == "vi" or ngon_ngu.startswith("vi-") or ngon_ngu == "vi-en"
    if ma == "en":
        return ngon_ngu == "en" or ngon_ngu == "vi-en"
    return False


def _diem_giong(row: dict[str, Any], lang: str) -> tuple[int, str]:
    vid = str(row.get("id") or "")
    ma = str(lang or "").lower().split("-", 1)[0]
    diem = 0
    if row.get("downloaded"):
        diem += 1000
    # Bảng phát âm hiện chỉ đo bằng câu TIẾNG VIỆT; không được lấy điểm đó để
    # xếp VieNeu cao hơn Kokoro bản ngữ khi đích là tiếng Anh.
    if ma == "vi" and bool((row.get("phat_am") or {}).get("dat")):
        diem += 100
    if ma == "vi":
        uu_tien = ["vieneu:Mai Anh", "vieneu:Thái Sơn", "vieneu:Thục Đoan",
                   "ngochuyen", "ngochuyennew"]
        if vid.startswith("vieneu:"):
            diem += 50                 # 48 kHz, có style kể chuyện
    else:
        uu_tien = ["kokoro:af_sky", "kokoro:af_bella"]
        if vid.startswith("kokoro:"):
            diem += 50                 # giọng Anh bản ngữ
    if vid in uu_tien:
        diem += len(uu_tien) - uu_tien.index(vid)
    return diem, vid


def danh_sach_giong(lang: str) -> list[dict[str, Any]]:
    """Danh sách giọng WebUI dùng được cho tiếng đích, có đúng một khuyến nghị."""
    from services.voice import config as vcfg

    ma = str(lang or "").lower().split("-", 1)[0]
    if ma in ("vi", "en"):
        rows = []
        for row in vcfg.voice_catalog():
            if not _hop_tieng(row, ma):
                continue
            vid = str(row.get("id") or "")
            rows.append({
                "id": vid,
                "label": f"{vid} · {row.get('language_label') or ma}",
                "downloaded": bool(row.get("downloaded")),
                "recommended": False,
                "phat_am": row.get("phat_am"),
            })
    elif ma in ("zh", "ja", "ko"):
        try:
            st = vcfg.status()
            so = int((st.get("so_giong_them") or {}).get(ma) or 0)
        except Exception:
            so = 0
        ten = {"zh": "Kokoro Trung", "ja": "Supertonic Nhật",
               "ko": "Supertonic Hàn"}[ma]
        rows = [{"id": f"dangu:{ma}:{i}", "label": f"{ten} · giọng {i + 1}",
                 "downloaded": so > 0, "recommended": False}
                for i in range(max(so, 1))]
    else:
        return []

    da_tai = [r for r in rows if r["downloaded"]]
    if da_tai:
        goi_y = None
        if ma in ("zh", "ja", "ko"):
            try:
                sid = (vcfg.kokoro_zh_sid() if ma == "zh"
                       else vcfg.supertonic_sid(ma))
                goi_y = next((r for r in da_tai
                              if r["id"] == f"dangu:{ma}:{sid}"), None)
            except Exception:
                pass
        goi_y = goi_y or max(da_tai, key=lambda r: _diem_giong(r, ma))
        goi_y["recommended"] = True
        goi_y["label"] += " · Khuyến nghị"
    return rows


def chon_giong(lang: str, voice: str = "") -> str:
    """Kiểm tra lựa chọn hoặc tự lấy giọng khuyến nghị đã tải."""
    rows = danh_sach_giong(lang)
    if voice:
        row = next((r for r in rows if r["id"] == voice), None)
        if row is None:
            raise LoiLongTieng(f"Giọng '{voice}' không phù hợp tiếng {lang}.")
        if not row["downloaded"]:
            raise LoiLongTieng(f"Giọng '{voice}' chưa được tải trên máy.")
        return voice
    row = next((r for r in rows if r.get("recommended")), None)
    if row is None:
        raise LoiLongTieng(f"Chưa có giọng TTS tiếng {lang} đã tải trên máy.")
    return str(row["id"])


def _chay(cmd: list[str], *, input_data: bytes | None = None,
          timeout: float = 600) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, input=input_data, capture_output=True,
                              timeout=timeout)
    except FileNotFoundError as exc:
        raise LoiLongTieng("Thiếu ffmpeg/ffprobe trong image.") from exc
    except subprocess.TimeoutExpired as exc:
        # Quá giờ thường là máy đang tải chứ không phải tệp hỏng — phân loại
        # riêng để bước căn thời lượng được thử lại thay vì bỏ cả phim.
        raise LoiLongTiengTamThoi("Xử lý âm thanh quá thời gian cho phép.") from exc


def _thoi_luong(duong: str, fallback: float) -> float:
    p = _chay(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "default=noprint_wrappers=1:nokey=1", duong], timeout=60)
    try:
        return max(float(p.stdout.decode().strip()), fallback)
    except (TypeError, ValueError):
        return fallback


def _kiem_tra_nen_du_dai(duong_nen: str, dai_video: float) -> float:
    """Chặn track separator bị cụt trước khi mux thành phim mất nền đoạn cuối."""
    dai_nen = _thoi_luong(duong_nen, 0.0)
    dung_sai = max(1.0, min(3.0, dai_video * 0.001))
    if dai_nen <= 0 or abs(dai_nen - dai_video) > dung_sai:
        raise LoiLongTieng(
            f"Track nhạc/hiệu ứng sai thời lượng ({dai_nen:.2f}s; video "
            f"{dai_video:.2f}s), nên không xuất MP4 thiếu âm thanh.")
    return dai_nen


def _boc_pcm_goc(duong: str) -> str:
    out = tempfile.NamedTemporaryFile(suffix=".s16le", delete=False).name
    try:
        p = _chay(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                  "-i", duong, "-vn", "-ac", "1", "-ar", str(RATE_GOC),
                  "-f", "s16le", out], timeout=900)
    except Exception:
        Path(out).unlink(missing_ok=True)
        raise
    if p.returncode or not Path(out).is_file() or Path(out).stat().st_size < 2:
        Path(out).unlink(missing_ok=True)
        loi = p.stderr.decode("utf-8", "ignore")[:180]
        raise LoiLongTieng(f"Không bóc được âm thanh gốc: {loi or 'ffmpeg lỗi'}")
    return out


def _f0_mot_khung(khung, rate: int) -> tuple[float, float] | None:
    """F0 và mức tuần hoàn của một khung, bằng tự tương quan chuẩn hoá."""
    import numpy as np

    tau_min = max(1, int(rate / F0_CAO))
    tau_max = int(rate / F0_THAP)
    if len(khung) <= tau_max + 1:
        return None
    x = khung - float(khung.mean())
    # Tự tương quan qua FFT: rẻ hơn hẳn vòng lặp trên từng độ trễ.
    n = 1
    while n < 2 * len(x):
        n *= 2
    pho = np.fft.rfft(x, n)
    acf = np.fft.irfft(pho * np.conj(pho), n)[:tau_max + 1]
    if float(acf[0]) <= 0.0:
        return None
    # Chia cho acf[0] khiến độ trễ càng lớn càng bị thiệt, nên đỉnh ở BỘI của
    # chu kỳ thật khó thắng — đúng thứ ta cần để khỏi báo thấp đi một quãng tám.
    r = acf / float(acf[0])
    vung = r[tau_min:tau_max + 1]
    j = int(np.argmax(vung))
    manh = float(vung[j])
    tau = tau_min + j
    # Vẫn còn khả năng bắt trúng chu kỳ gấp đôi. Nếu nửa chu kỳ gần mạnh ngang
    # thì nó mới là chu kỳ thật.
    nua = tau // 2
    if nua >= tau_min and float(r[nua]) > 0.85 * manh:
        tau, manh = nua, float(r[nua])
    return rate / float(tau), manh


def _pitch_acf(mau, rate: int) -> float | None:
    """F0 của cue: đo từng khung rồi lấy trung vị các khung có tiếng người.

    Bản trước lấy vạch phổ to nhất trong dải 70-350 Hz của MỘT phép biến đổi dài
    1,5 giây. Hỏng ba chỗ: hoạ âm bậc hai của giọng thường to hơn tần số cơ bản
    nên hay báo cao gấp đôi; 1,5 giây gộp cả lên giọng, xuống giọng lẫn khoảng
    lặng vào một phép tính; và cue chỉ có nhạc hay tiếng máy vẫn được gán một
    con số vì phép lọc duy nhất là ngưỡng âm lượng.
    """
    import numpy as np

    x = np.asarray(mau, dtype=np.float32)
    if len(x) < int(rate * 0.08):
        return None
    # Vẫn giới hạn 1,5 s giữa cue để phim dài không kéo dài thời gian phân tích.
    n = min(len(x), int(rate * 1.5))
    bat = max(0, (len(x) - n) // 2)
    x = x[bat:bat + n]
    win = int(rate * F0_KHUNG_GIAY)
    hop = max(1, win // 2)
    if len(x) < win:
        return None
    f0s: list[float] = []
    for i in range(0, len(x) - win + 1, hop):
        khung = x[i:i + win]
        if float(np.sqrt(np.mean(khung * khung))) < 0.003:
            continue
        ket = _f0_mot_khung(khung, rate)
        if ket is None:
            continue
        f0, manh = ket
        if manh < F0_NGUONG_TUAN_HOAN or not (F0_THAP <= f0 <= F0_CAO):
            continue
        f0s.append(f0)
    if len(f0s) < F0_KHUNG_TOI_THIEU:
        return None
    return float(median(f0s))


def _dac_trung(mau, rate: int, bat: float, ket: float) -> tuple[float, float | None]:
    import numpy as np

    a = max(0, min(len(mau), round(bat * rate)))
    b = max(a, min(len(mau), round(ket * rate)))
    if b <= a:
        return 0.0, None
    x = np.asarray(mau[a:b], dtype=np.float32) / 32768.0
    nang_luong = float(np.sqrt(np.mean(x * x))) if len(x) else 0.0
    return nang_luong, _pitch_acf(x, rate)


def _tao_meta(duong_video: str, doan: list[Any], lang: str,
              voice: str) -> tuple[dict[str, Any], str]:
    import numpy as np

    raw = _boc_pcm_goc(duong_video)
    try:
        mau = np.memmap(raw, dtype="<i2", mode="r")
        tam: list[dict[str, Any]] = []
        for i, d in enumerate(doan):
            bat, ket = float(d.bat_dau), float(d.ket_thuc)
            energy, pitch = _dac_trung(mau, RATE_GOC, bat, ket)
            truoc = float(doan[i - 1].ket_thuc) if i else 0.0
            sau = float(doan[i + 1].bat_dau) if i + 1 < len(doan) else ket
            chu = str(d.chu or "").strip()
            don_vi = len(re.findall(r"\w+", chu, flags=re.UNICODE))
            tam.append({
                "index": i + 1,
                "start": round(bat, 3),
                "end": round(ket, 3),
                "text": chu,
                "speaker": "UNKNOWN",
                "rate": round(don_vi / max(0.1, ket - bat), 3),
                "rate_unit": "words_per_second",
                "rate_source": "translated_text_per_subtitle_slot",
                "_pitch_hz": pitch,
                "energy": round(energy, 5),
                "pause_before": round(max(0.0, bat - truoc), 3),
                "pause_after": round(max(0.0, sau - ket), 3),
                "emphasis": [],
                "emphasis_source": "unavailable",
            })
        pitches = [float(x["_pitch_hz"]) for x in tam if x["_pitch_hz"]]
        energies = [float(x["energy"]) for x in tam if x["energy"] > 0]
        rates = [float(x["rate"]) for x in tam if x["rate"] > 0]
        pitch_med = median(pitches) if pitches else 0.0
        energy_med = median(energies) if energies else 0.0
        rate_med = median(rates) if rates else 0.0
        for cue in tam:
            pitch = cue.pop("_pitch_hz")
            cue["pitch_relative"] = (round(12.0 * math.log2(pitch / pitch_med), 2)
                                      if pitch and pitch_med else None)
            energy_db = (20.0 * math.log10(max(cue["energy"], 1e-6)
                                           / max(energy_med, 1e-6))
                         if energy_med else 0.0)
            cue["energy_relative_db"] = round(energy_db, 2)
            if energy_db > 4.0 or (rate_med and cue["rate"] > rate_med * 1.25):
                cue["emotion"] = "energetic"
            elif energy_db < -4.0 and (not rate_med or cue["rate"] < rate_med * 0.9):
                cue["emotion"] = "calm"
            else:
                cue["emotion"] = "neutral"
        return ({
            "version": 1,
            "language": lang,
            "voice": voice,
            "original_audio": "dialogue_replaced_background_preserved",
            "original_dialogue": "pending_source_separation",
            "background_audio": "pending_source_separation",
            "separation_quality": "model_estimate_not_lossless",
            "separation_note": (
                "Source separation có thể còn rò giọng hoặc làm mờ phần giọng hát "
                "nằm trong nhạc; track âm thanh gốc không được đưa vào bản mux."),
            "speaker_detection": "unavailable",
            "speaker_note": "one selected voice is used for every cue",
            "analysis_source": "mixed_original_audio",
            "created_at": int(time.time()),
            "cues": tam,
        }, raw)
    except Exception:
        Path(raw).unlink(missing_ok=True)
        raise


def _doc_wav_info(wav_bytes: bytes) -> tuple[float, int]:
    from io import BytesIO

    try:
        with wave.open(BytesIO(wav_bytes), "rb") as w:
            rate = max(1, w.getframerate())
            return w.getnframes() / rate, rate
    except Exception as exc:
        raise LoiLongTieng(f"TTS trả WAV không hợp lệ: {exc}") from exc


def _bo_loc_tts(giay_goc: float, giay_dich: float, *,
                pitch_relative: float | None = None,
                energy_relative_db: float = 0.0) -> tuple[str, float]:
    """Tạo filter ffmpeg thuần để test được mà không phải giả subprocess."""
    # Khung phụ đề dài KHÔNG có nghĩa là câu phải đọc chậm hết khung: cat_khung
    # ép mỗi khung tối thiểu 1 giây và cho tới 7 giây, nên "Vâng." đọc hết 0,5
    # giây rơi vào khung 7 giây sẽ ra tempo 0,07× — nghe thành tiếng rên kéo dài
    # chứ không còn là lời thoại. Chậm nhất TEMPO_CHAM_NHAT rồi để phần dư im
    # lặng; mốc bắt đầu của khung sau vẫn đúng vì _pcm_vua_khung đệm cho đủ.
    tempo = max(TEMPO_CHAM_NHAT, giay_goc / max(0.08, giay_dich))
    # Cao độ để CÙNG MỘT giọng nói cao lên hay trầm xuống, không phải để đổi
    # người. asetrate kéo giãn cả phổ nên dịch luôn formant — thứ mã hoá chiều
    # dài đường thanh, tức tai người nghe ra vóc người khác. rubberband dịch F0
    # riêng và formant=preserved giữ nguyên danh tính giọng đã chọn; nó cũng lo
    # luôn thời lượng nên không cần chuỗi atempo bù qua bù lại nữa.
    nua_cung = max(-PITCH_TOI_DA, min(PITCH_TOI_DA, float(pitch_relative or 0.0)))
    he_so_pitch = 2.0 ** (nua_cung / 12.0)
    gain = max(-6.0, min(6.0, float(energy_relative_db or 0.0)))
    loc = (f"aresample={RATE_DUB},"
           f"rubberband=tempo={tempo:.6f}:pitch={he_so_pitch:.6f}"
           f":formant=preserved:pitchq=quality,"
           f"volume={gain:.3f}dB")
    return loc, tempo


def _pcm_vua_khung(wav_bytes: bytes, giay_dich: float, *,
                   pitch_relative: float | None = None,
                   energy_relative_db: float = 0.0) -> tuple[bytes, float]:
    """Khớp thời lượng đồng thời tái tạo cao độ/năng lượng tương đối của cue."""
    giay_goc, _ = _doc_wav_info(wav_bytes)
    loc, tempo = _bo_loc_tts(
        giay_goc, giay_dich,
        pitch_relative=pitch_relative, energy_relative_db=energy_relative_db)
    p = _chay(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
              "-af", loc, "-ac", "1", "-ar", str(RATE_DUB),
              "-f", "s16le", "pipe:1"], input_data=wav_bytes, timeout=120)
    if p.returncode or not p.stdout:
        raise LoiLongTieng("Không khớp được thời lượng câu TTS: "
                           + p.stderr.decode("utf-8", "ignore")[:150])
    can = max(2, round(giay_dich * RATE_DUB) * 2)
    pcm = p.stdout[:can]
    if len(pcm) < can:
        pcm += b"\0" * (can - len(pcm))
    return pcm, tempo


def _tong_hop(chu: str, voice: str, emotion: str) -> bytes:
    from services.voice import engines

    if voice.startswith("dangu:"):
        phan = voice.split(":")
        lang = phan[1] if len(phan) > 1 else ""
        sid = int(phan[2]) if len(phan) > 2 and phan[2].isdigit() else -1
        return engines.synthesize_da_ngu(chu, lang, sid)
    style = {"calm": "doc_truyen", "energetic": "tin_tuc"}.get(
        emotion, "tu_nhien")
    return engines.synthesize(chu, voice, style=style)


def _loi_tts_tam_thoi(exc: Exception) -> bool:
    """Chỉ retry lỗi có khả năng tự hết; cấu hình/media/OOM phải dừng ngay."""
    if isinstance(exc, (subprocess.TimeoutExpired, TimeoutError,
                        ConnectionError, LoiLongTiengTamThoi)):
        return True
    if isinstance(exc, (FileNotFoundError, ValueError, LoiLongTieng)):
        return False
    text = str(exc).casefold()
    vinh_vien = (
        "không có nội dung", "đang tắt", "chưa cài", "chưa tải", "thiếu ",
        "không có giọng", "không hợp lệ", "invalid", "not found", "cuda",
        "out of memory", "oom",
    )
    if any(x in text for x in vinh_vien):
        return False
    # KHÔNG nhận ra thì THỬ LẠI. Hai hướng sai không ngang giá nhau: thử thừa
    # tốn 0,5 giây và một lần tổng hợp, còn dừng nhầm thì vứt cả buổi — đúng
    # thứ đường retry này sinh ra để tránh. Danh sách "vĩnh viễn" ở trên đã
    # chặn sẵn các lỗi chắc chắn không tự hết, nên mặc định này không phí.
    # Thực đo: engine TTS chạy tiến trình con ném CalledProcessError với chuỗi
    # "returned non-zero exit status 1" — không khớp mẫu tạm thời nào, mà đó
    # lại là kiểu trục trặc thoáng qua hay gặp nhất.
    return True


def _viet_lang(w: wave.Wave_write, so_mau: int) -> None:
    con = max(0, int(so_mau))
    khoi = b"\0" * (RATE_DUB * 2)  # một giây, không cấp hàng trăm MB một lần
    while con:
        n = min(con, RATE_DUB)
        w.writeframesraw(khoi[:n * 2])
        con -= n


def _tao_track(meta: dict[str, Any], dai: float, voice: str,
                progress: Progress | None) -> tuple[str, int, list[str]]:
    out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    cues = list(meta.get("cues") or [])
    cursor = 0
    loi = 0
    canh_bao: list[str] = []
    meta["tts_retry_policy"] = {
        "max_attempts_per_cue": TTS_SO_LAN_TOI_DA,
        "retry_delay_seconds": TTS_CHO_THU_LAI_GIAY,
        "fail_fast_after_retries": True,
    }
    try:
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE_DUB)
            for i, cue in enumerate(cues):
                bat = max(0, round(float(cue["start"]) * RATE_DUB))
                ket = max(bat + 1, round(float(cue["end"]) * RATE_DUB))
                if bat > cursor:
                    _viet_lang(w, bat - cursor)
                    cursor = bat
                pcm: bytes | None = None
                wav: bytes | None = None
                loi_cue: Exception | None = None
                cue.pop("tts_error", None)
                cue["tts_recovered_after_retry"] = False
                for lan_thu in range(1, TTS_SO_LAN_TOI_DA + 1):
                    cue["tts_attempts"] = lan_thu
                    try:
                        wav = _tong_hop(
                            str(cue["text"]), voice, str(cue["emotion"]))
                        if lan_thu > 1:
                            cue["tts_recovered_after_retry"] = True
                        break
                    except Exception as exc:
                        if (lan_thu < TTS_SO_LAN_TOI_DA
                                and _loi_tts_tam_thoi(exc)):
                            logger.warning(
                                "lồng tiếng câu %d lỗi lần %d, thử lại: %s",
                                i + 1, lan_thu, str(exc)[:160])
                            if progress:
                                try:
                                    progress(
                                        i, len(cues),
                                        f"TTS câu {i + 1} lỗi, đang thử lại…")
                                except Exception:
                                    pass
                            time.sleep(TTS_CHO_THU_LAI_GIAY)
                            continue
                        loi_cue = exc
                        break
                # Căn thời lượng là pha riêng: WAV hỏng hay thiếu ffmpeg thì
                # tổng hợp lại TTS cũng vô ích, nên KHÔNG đọc lại câu. Nhưng
                # ffmpeg quá giờ vì máy đang tải là chuyện tự hết — dùng lại
                # đúng bản WAV đã có mà chạy lại, không tốn thêm lượt TTS.
                if wav is not None and loi_cue is None:
                    for lan_can in range(1, TTS_SO_LAN_TOI_DA + 1):
                        try:
                            pcm, tempo = _pcm_vua_khung(
                                wav, (ket - bat) / RATE_DUB,
                                pitch_relative=cue.get("pitch_relative"),
                                energy_relative_db=float(
                                    cue.get("energy_relative_db") or 0.0))
                            cue["tts_tempo"] = round(tempo, 3)
                            cue["tts_status"] = "ok"
                            if lan_can > 1:
                                cue["tts_recovered_after_retry"] = True
                            if tempo > 2.0:
                                canh_bao.append(
                                    f"câu {i + 1} phải đọc nhanh {tempo:.1f}×")
                            break
                        except Exception as exc:
                            if (lan_can < TTS_SO_LAN_TOI_DA
                                    and _loi_tts_tam_thoi(exc)):
                                logger.warning(
                                    "căn thời lượng câu %d lỗi lần %d, thử lại: %s",
                                    i + 1, lan_can, str(exc)[:160])
                                time.sleep(TTS_CHO_THU_LAI_GIAY)
                                continue
                            loi_cue = exc
                            break
                if loi_cue is not None:
                    loi += 1
                    cue["tts_status"] = "error"
                    cue["tts_recovered_after_retry"] = False
                    cue["tts_error"] = str(loi_cue)[:160]
                    logger.warning(
                        "lồng tiếng câu %d vẫn lỗi sau %d lần: %s",
                        i + 1, int(cue["tts_attempts"]), str(loi_cue)[:160])
                # Chính sách nghiêm chắc chắn sẽ từ chối MP4: dừng tại đây,
                # không đốt tiếp hàng trăm cue hoặc ghi hàng trăm MB im lặng.
                if pcm is None:
                    break
                # Cue chồng nhau: bỏ phần đã đi qua, không làm timeline trôi.
                bo = max(0, cursor - bat) * 2
                if bo < len(pcm):
                    w.writeframesraw(pcm[bo:])
                    cursor += (len(pcm) - bo) // 2
                if progress:
                    try:
                        progress(i + 1, len(cues),
                                 f"đang tổng hợp giọng ({i + 1}/{len(cues)})…")
                    except Exception:
                        pass
            if not loi:
                tong = max(cursor, round(dai * RATE_DUB))
                if tong > cursor:
                    _viet_lang(w, tong - cursor)
    except Exception:
        Path(out).unlink(missing_ok=True)
        raise
    return out, loi, canh_bao


def _bao_dam_khong_thieu_cau_tts(meta: dict[str, Any], so_loi: int,
                                 tong: int) -> None:
    """Thiếu một câu là không xuất phim — nhưng phải nói RÕ câu nào, vì sao.

    ``prosody.json`` (nơi giữ ``tts_error`` từng cue) chỉ được ghi SAU bước này,
    nên nếu lỗi chỉ đếm số lượng thì người dùng mất sạch manh mối: một câu hỏng
    cố định sẽ chặn cả phim mà không ai biết phải sửa gì.
    """
    if not so_loi:
        return
    hong = [c for c in (meta.get("cues") or []) if c.get("tts_status") == "error"]
    da_thu = [c for c in (meta.get("cues") or []) if c.get("tts_status")]
    chua_thu = max(0, tong - len(da_thu))
    so_lan = max((int(c.get("tts_attempts") or 1) for c in hong), default=1)
    chi_tiet = "; ".join(
        f"câu {c.get('index')} tại {float(c.get('start') or 0):.1f}s "
        f"({str(c.get('tts_error') or 'không rõ')[:80]})"
        for c in hong[:3])
    if len(hong) > 3:
        chi_tiet += f"; và {len(hong) - 3} câu nữa"
    dung_som = f" Đã dừng sớm; {chua_thu} câu chưa tổng hợp." if chua_thu else ""
    raise LoiLongTieng(
        f"TTS lỗi {so_loi}/{tong} câu sau khi đã thử {so_lan} lần nên không "
        f"xuất MP4 bị thiếu lời.{dung_som} Phụ đề SRT vẫn được giữ. "
        f"Câu hỏng: {chi_tiet or 'không rõ'}")


#: Trộn nền với TTS. Dùng lại y hệt cho cả lượt đo lẫn lượt ghi, để lượng bù đo
#: được đúng là lượng bù cho hỗn hợp sẽ ghi ra.
_TRON = ("[1:a][2:a]amix=inputs=2:duration=longest:"
         "dropout_transition=0:normalize=0")


def _doc_lufs(loi_ffmpeg: str) -> float | None:
    """Độ to tích hợp trong báo cáo cuối của bộ lọc ebur128."""
    i = loi_ffmpeg.rfind("Integrated loudness")
    if i < 0:
        return None
    m = re.search(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", loi_ffmpeg[i:])
    return float(m.group(1)) if m else None


def _bu_am(lufs_do: float | None) -> float:
    """Số dB cần bù để hỗn hợp đạt DO_TO_MUC_TIEU.

    Đo hỏng, hoặc phim gần như im lặng (dưới -60 LUFS thì phép đo R128 hết đáng
    tin), thì trả 0 — thà giữ nguyên còn hơn khuếch đại một con số vô nghĩa.
    """
    if lufs_do is None or not math.isfinite(lufs_do) or lufs_do < -60.0:
        return 0.0
    return max(-BU_AM_TOI_DA, min(BU_AM_TOI_DA, DO_TO_MUC_TIEU - lufs_do))


def _do_do_to(background: str, track: str, dai: float) -> float | None:
    """Đo hỗn hợp nền + TTS trước khi ghi. Đo hỏng thì trả None, không chặn job."""
    p = _chay(["ffmpeg", "-hide_banner", "-nostats", "-i", background,
               "-i", track, "-filter_complex", _TRON + ",ebur128=peak=true",
               "-f", "null", "-"], timeout=max(300, dai))
    return _doc_lufs(p.stderr.decode("utf-8", "ignore"))


def _mux(duong_video: str, background: str, track: str, dai: float) -> str:
    out = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
    try:
        bu = _bu_am(_do_do_to(background, track, dai))
    except Exception as exc:                       # đo được thì tốt, không thì thôi
        logger.warning("không đo được độ to, giữ nguyên mức: %s", str(exc)[:120])
        bu = 0.0
    lenh_chung = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                  "-i", duong_video, "-i", background, "-i", track,
                  "-filter_complex",
                  f"{_TRON},volume={bu:.2f}dB,"
                  f"alimiter=limit={TRAN_DINH}:level=disabled[dub]",
                  "-map", "0:v:0", "-map", "[dub]",
                  "-map_metadata", "0", "-c:a", "aac", "-b:a", "192k",
                  "-t", f"{dai:.3f}", "-movflags", "+faststart"]
    try:
        p = _chay(lenh_chung + ["-c:v", "copy", out], timeout=max(900, dai * 2))
        if p.returncode:
            # Codec/container gốc không copy được sang MP4 (vd vài AVI/WebM):
            # đổi riêng hình sang H.264; audio vẫn là nền đã tách + TTS.
            p = _chay(lenh_chung + ["-c:v", "libx264", "-preset", "veryfast",
                                    "-crf", "20", out],
                      timeout=max(1800, dai * 4))
        if p.returncode or not Path(out).is_file() or Path(out).stat().st_size < 100:
            raise LoiLongTieng("Không ghép được track lồng tiếng vào video: "
                               + p.stderr.decode("utf-8", "ignore")[:180])
        return out
    except Exception:
        Path(out).unlink(missing_ok=True)
        raise


def _ghi_moc(khuc: str, t0: float, **them: Any) -> None:
    """Ghi SỐ GIÂY của một khúc trong đường lồng tiếng.

    Vì sao cần: trước đây cả đường ống chỉ ghi log khi HỎNG, nên câu hỏi "video
    10 phút sao chạy 23 phút" chỉ trả lời được bằng cách chạy lại từng khúc
    trên máy chủ để bấm giờ — mất cả buổi (đo 21/08/2026). Có mấy dòng này thì
    mở log là thấy, và mọi lần chỉnh tốc độ sau này đều chứng minh được là có
    ăn hay không.
    """
    logger.info({"event": "long_tieng_khuc", "khuc": khuc,
                 "giay": round(time.monotonic() - t0, 1), **them})


def long_tieng(duong_video: str, srt: bytes | str, lang: str, *, voice: str = "",
               progress: Progress | None = None) -> KetQuaLongTieng:
    """Video + SRT → MP4 bỏ lời gốc, giữ nền, thêm TTS + prosody JSON."""
    from services import video_dich as vd
    from services import tach_am_gpu

    if not Path(duong_video).is_file():
        raise LoiLongTieng("Không thấy tệp video để lồng tiếng.")
    raw_srt = srt.decode("utf-8", "replace") if isinstance(srt, bytes) else str(srt)
    doan = vd.doc_phu_de(raw_srt)
    if not doan:
        raise LoiLongTieng("Phụ đề không có câu nào để đọc.")
    voice = voice or chon_giong(lang)
    dai = _thoi_luong(duong_video, doan[-1].ket_thuc)
    meta, raw_pcm = _tao_meta(duong_video, doan, lang, voice)
    track: str | None = None
    background: str | None = None
    video: str | None = None
    prosody: str | None = None
    try:
        prosody = tempfile.NamedTemporaryFile(
            suffix=".prosody.json", delete=False).name
        _t_khuc = time.monotonic()
        _t_tong = _t_khuc
        tach = tach_am_gpu.tach_nen(duong_video, progress=progress)
        _ghi_moc("tach_loi", _t_khuc, model=str(getattr(tach, "model", "")))
        background = tach.background_path
        _kiem_tra_nen_du_dai(background, dai)
        meta["original_dialogue"] = "removed_by_source_separation_best_effort"
        meta["background_audio"] = "preserved_by_source_separation_best_effort"
        meta["separator_model"] = tach.model
        _t_khuc = time.monotonic()
        track, so_loi, canh_bao = _tao_track(meta, dai, voice, progress)
        _ghi_moc("tong_hop_giong", _t_khuc, so_cau=len(doan), so_loi=so_loi)
        _bao_dam_khong_thieu_cau_tts(meta, so_loi, len(doan))
        Path(prosody).write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
        if progress:
            progress(len(doan), len(doan),
                     "đang trộn TTS với nhạc/hiệu ứng và ghép video…")
        _t_khuc = time.monotonic()
        video = _mux(duong_video, background, track, dai)
        _ghi_moc("tron_va_ghep", _t_khuc)
        _ghi_moc("tong_cong", _t_tong, so_cau=len(doan),
                 dai_video_giay=round(float(dai), 1))
        tom_tat = ""
        da_phuc_hoi = sum(bool(c.get("tts_recovered_after_retry"))
                          for c in meta.get("cues") or [])
        if da_phuc_hoi:
            tom_tat = f"{da_phuc_hoi} câu TTS đã phục hồi sau một lần thử lại."
        if canh_bao:
            nhanh = f"{len(canh_bao)} câu phải tăng tốc trên 2×."
            tom_tat = " ".join(x for x in (tom_tat, nhanh) if x)
        return KetQuaLongTieng(video, prosody, voice, len(doan), so_loi, tom_tat)
    except Exception:
        if video:
            Path(video).unlink(missing_ok=True)
        if prosody:
            Path(prosody).unlink(missing_ok=True)
        raise
    finally:
        Path(raw_pcm).unlink(missing_ok=True)
        if track:
            Path(track).unlink(missing_ok=True)
        if background:
            Path(background).unlink(missing_ok=True)

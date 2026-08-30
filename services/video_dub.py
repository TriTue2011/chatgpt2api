"""Lồng tiếng video bằng các engine TTS đã có, kèm ``prosody.json``.

Đường này cố ý độc lập với việc tạo phụ đề: caller đưa SRT đã dịch và video
gốc vào, nhận một video trong đó lời thoại gốc được thay bằng TTS nhưng nhạc và
hiệu ứng vẫn giữ. Muốn làm đúng phải source-separation trước; không được trộn
âm gốc nhỏ đi vì lời cũ sẽ lọt, cũng không được bỏ cả track khiến phim mất nền.

Prosody đo từ track gốc ở đúng mốc từng cue. Khi chưa có diarization, trường
``speaker`` là ``UNKNOWN`` — thà nói chưa biết còn hơn gán nhầm giới tính.

Tốc độ đọc chốt MỘT LẦN cho cả phim (``_tempo_chung``), không tính lại theo
từng khung phụ đề. Tính theo khung thì câu ngắn lọt khung dài bị kéo lê còn câu
dài lọt khung ngắn bị đọc vụt qua — nghe ra ngay là máy đọc.
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
from collections import namedtuple
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, Callable

logger = logging.getLogger(__name__)

RATE_GOC = 16000
RATE_DUB = 24000
#: Tốc độ đọc CHUẨN — đúng nhịp engine TTS trả về, không co không giãn.
TEMPO_CHUAN = 1.0
#: Trần tốc độ chung. Chỉ rời khỏi TEMPO_CHUAN khi lời dịch dài hơn chỗ hình
#: dành cho nó; 1,3× là mức tai còn nghe thoải mái khi nó ĐỀU trên cả phim.
TEMPO_NHANH_NHAT = 1.3
#: Mức trễ cho phép ở mốc mở câu, tính bằng giây. Câu tràn ra ngoài khung thì
#: câu sau vào muộn; khoảng lặng giữa hai câu sẽ nuốt dần chỗ trễ đó.
TRE_TOI_DA = 1.0
#: Câu được phép VÀO SỚM hơn mốc phụ đề tối đa ngần này giây, để MƯỢN chỗ trống
#: mà câu trước để lại và giữ tốc độ 1×. Trước đây con trỏ luôn NHẢY tới đúng
#: mốc câu sau, vứt mất chỗ trống — nên câu dài chỉ còn cách tăng tốc CẢ PHIM.
#: Nay chỗ trống dồn về sau (chặn ngần này để giọng không chạy trước hình quá
#: xa; chủ máy chốt: phim dài hơn lồng tiếng thì chấp nhận, cố giữ 1×). Khoảng
#: lặng NHỎ hơn ngần này bị nuốt hẳn → lồng tiếng liền mạch hơn; khoảng lặng
#: LỚN (đổi cảnh, phim im) vẫn giữ, chỉ kéo câu sớm lại tối đa ngần này.
SOM_TOI_DA = 1.0
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


#: Khoá config giữ giọng lồng tiếng mặc định, tra theo MÃ TIẾNG ĐÍCH. Phải là
#: một bảng chứ không phải một chuỗi: giọng Việt không đọc được tiếng Anh, nên
#: "giọng mặc định" chỉ có nghĩa khi gắn với tiếng đích.
CAU_HINH_DICH = "dich"
KHOA_GIONG_MAC_DINH = "giong_long_tieng"
#: Các tiếng đích lồng tiếng được. Trùng danh sách api/dich.py đang chặn.
TIENG_LONG_DUOC = ("vi", "en", "zh", "ja", "ko")


def _ma_tieng(lang: str) -> str:
    return str(lang or "").lower().split("-", 1)[0]


def bang_giong_mac_dinh() -> dict[str, str]:
    """Cả bảng giọng đã chốt trong Cài đặt, tra theo mã tiếng đích."""
    from services.config import config

    try:
        bang = (config.get().get(CAU_HINH_DICH) or {}).get(KHOA_GIONG_MAC_DINH)
    except Exception as exc:                # config hỏng không được chặn lồng tiếng
        logger.warning("không đọc được giọng mặc định: %s", str(exc)[:120])
        bang = None
    if not isinstance(bang, dict):
        return {}
    return {str(k): str(v) for k, v in bang.items()}


def giong_mac_dinh(lang: str) -> str:
    """Giọng đã chốt cho một tiếng đích; rỗng nghĩa là để máy tự chọn."""
    return bang_giong_mac_dinh().get(_ma_tieng(lang), "")


def dat_giong_mac_dinh(lang: str, voice: str) -> dict[str, str]:
    """Lưu giọng mặc định cho một tiếng đích; ``voice`` rỗng là xoá lựa chọn.

    Chỉ nhận giọng ĐÃ TẢI: lưu một giọng chưa có model thì tới lúc lồng tiếng
    mới vỡ lẽ, mà lúc đó phim đã dịch xong và người dùng đang chờ.
    """
    ma = _ma_tieng(lang)
    if ma not in TIENG_LONG_DUOC:
        raise LoiLongTieng(f"Không lồng tiếng được sang tiếng '{lang}'.")
    bang = bang_giong_mac_dinh()
    if voice:
        row = next((r for r in danh_sach_giong(ma) if r["id"] == voice), None)
        if row is None:
            raise LoiLongTieng(f"Giọng '{voice}' không phù hợp tiếng {ma}.")
        if not row["downloaded"]:
            raise LoiLongTieng(f"Giọng '{voice}' chưa được tải trên máy.")
        bang[ma] = voice
    else:
        bang.pop(ma, None)

    from services.config import config

    cu = config.get().get(CAU_HINH_DICH)
    moi = dict(cu) if isinstance(cu, dict) else {}
    moi[KHOA_GIONG_MAC_DINH] = bang
    config.update({CAU_HINH_DICH: moi})
    return bang


def chon_giong(lang: str, voice: str = "") -> str:
    """Kiểm tra lựa chọn, hoặc lấy giọng mặc định, hoặc giọng khuyến nghị đã tải.

    Đây là điểm đấu nối DUY NHẤT của cả hai đường: trang web truyền ``voice``
    người dùng vừa chọn, còn đường chat bot gọi tay không — nên giọng mặc định
    trong Cài đặt phải chen vào đúng chỗ này thì bot mới dùng tới nó.
    """
    rows = danh_sach_giong(lang)
    if voice:
        row = next((r for r in rows if r["id"] == voice), None)
        if row is None:
            raise LoiLongTieng(f"Giọng '{voice}' không phù hợp tiếng {lang}.")
        if not row["downloaded"]:
            raise LoiLongTieng(f"Giọng '{voice}' chưa được tải trên máy.")
        return voice
    # Cài đặt của chủ máy đứng TRƯỚC bảng điểm máy tự chấm. Nhưng giọng đã lưu
    # có thể bị xoá model sau đó, và khi ấy thà quay về giọng khuyến nghị còn
    # hơn để cả ô lồng tiếng chết vì một cài đặt cũ.
    da_chon = giong_mac_dinh(lang)
    if da_chon:
        row = next((r for r in rows if r["id"] == da_chon), None)
        if row is not None and row["downloaded"]:
            return da_chon
        logger.warning(
            "giọng mặc định %r cho tiếng %s không dùng được, quay về khuyến nghị",
            da_chon, lang)
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
    """Thời lượng THẬT của tệp. ``fallback`` chỉ dùng khi ffprobe không đo được.

    Trước đây trả ``max(đo được, fallback)``. Nghe thì có vẻ an toàn nhưng sai
    hẳn ở chỗ gọi chính: ``long_tieng`` truyền ``fallback`` là mốc kết thúc của
    khung phụ đề CUỐI, mà phụ đề YouTube rất hay chạy quá đuôi phim. Đo thật
    30/08/2026 trên một video 4 phút: phim dài 239,04 giây (luồng tiếng 239,041)
    còn phụ đề kết ở 240,83 giây, nên ``max()`` chốt "video dài 240,83 giây".
    Track nhạc/hiệu ứng tách ra dài 239,03 giây — khớp đúng luồng tiếng gốc,
    không thiếu một mẩu nào — vẫn bị ``_kiem_tra_nen_du_dai`` kết luận là cụt
    1,8 giây, và cả lượt lồng tiếng bị bỏ, người dùng chỉ nhận lại SRT.

    Lấy đúng số đo còn làm phép đo TRÀN ĐUÔI của ``_do_tre`` thành thật: mốc
    hết phim mà nống ra thì phần lời tràn qua đuôi không bị đếm, trong khi
    ``_mux`` vẫn cắt tại đó và lời cuối vẫn mất.
    """
    p = _chay(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "default=noprint_wrappers=1:nokey=1", duong], timeout=60)
    try:
        do_duoc = float(p.stdout.decode().strip())
    except (TypeError, ValueError):
        return fallback
    # ffprobe trả "N/A"/0 cho tệp hỏng hoặc container không ghi thời lượng.
    return do_duoc if do_duoc > 0 else fallback


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


#: Ngắt CÂU khi gộp khung vụn: khoảng lặng dài hơn ngần này giây giữa hai khung
#: coi là hết câu dù chưa có dấu chấm (đổi cảnh, ngập ngừng). Dưới mức này mà
#: chưa có dấu kết câu thì còn là MỘT câu — gộp lại đọc liền, không chen im lặng.
NGAT_CAU_GIAY = 0.8
#: Trần an toàn khi gộp: phụ đề THIẾU dấu câu (ASR thô) sẽ gộp mãi không dừng.
#: Chạm một trong hai trần này thì cắt câu tại đó.
GOP_TOI_DA_GIAY = 12.0
GOP_TOI_DA_KHUNG = 8
#: Ký tự KẾT một câu. KHÔNG gồm dấu phẩy — phẩy là ngắt trong câu, để TTS tự
#: ngân nhịp, không phải chỗ chèn im lặng.
_KET_CAU = tuple(".!?…。！？؟।")

_Cau = namedtuple("_Cau", "bat_dau ket_thuc chu")


def _het_cau(chu: str) -> bool:
    """Chuỗi này đã kết thúc một câu chưa (bỏ ngoặc/nháy đuôi rồi xét)."""
    t = str(chu or "").rstrip().rstrip("\"')]}»”’ ").rstrip()
    return bool(t) and t[-1] in _KET_CAU


def _gop_cau(doan: list[Any]) -> list[Any]:
    """Gộp các khung phụ đề CÙNG MỘT CÂU thành một đơn vị đọc.

    Vì sao: phụ đề hay cắt một câu thành nhiều khung ngắn ("ngày mai" / "trời" /
    "lại sáng"). Đọc TTS từng khung rồi đặt vào từng mốc → chen im lặng GIỮA
    câu, nghe cụt từng chữ. Gộp lại rồi đọc trọn câu một hơi thì liền mạch, và
    câu vẫn đặt ở mốc khung ĐẦU nên vẫn bám hình (yêu cầu chủ máy 28/08).

    Cắt câu tại: dấu kết câu (._KET_CAU), hoặc khoảng lặng ``NGAT_CAU_GIAY``,
    hoặc chạm trần an toàn (phụ đề thiếu dấu câu). Dấu PHẨY không cắt.
    Trả danh sách ``_Cau`` (cùng giao diện bat_dau/ket_thuc/chu như ``Doan``).
    """
    ra: list[_Cau] = []
    gom: list[Any] = []

    def xa():
        if gom:
            chu = " ".join(str(d.chu or "").strip() for d in gom if str(d.chu or "").strip())
            ra.append(_Cau(float(gom[0].bat_dau), float(gom[-1].ket_thuc), chu))
            gom.clear()

    for i, d in enumerate(doan):
        gom.append(d)
        het = _het_cau(d.chu)
        qua_dai = (float(d.ket_thuc) - float(gom[0].bat_dau) >= GOP_TOI_DA_GIAY
                   or len(gom) >= GOP_TOI_DA_KHUNG)
        lang_dai = (i + 1 < len(doan)
                    and float(doan[i + 1].bat_dau) - float(d.ket_thuc) > NGAT_CAU_GIAY)
        if het or qua_dai or lang_dai:
            xa()
    xa()
    return ra


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


def _bo_loc_tts(tempo: float, *,
                pitch_relative: float | None = None,
                energy_relative_db: float = 0.0) -> str:
    """Tạo filter ffmpeg thuần để test được mà không phải giả subprocess.

    ``tempo`` là tốc độ chung của CẢ phim, do :func:`_tempo_chung` chốt — hàm
    này không được tự tính lại theo khung của riêng câu nào.
    """
    # Cao độ để CÙNG MỘT giọng nói cao lên hay trầm xuống, không phải để đổi
    # người. asetrate kéo giãn cả phổ nên dịch luôn formant — thứ mã hoá chiều
    # dài đường thanh, tức tai người nghe ra vóc người khác. rubberband dịch F0
    # riêng và formant=preserved giữ nguyên danh tính giọng đã chọn; nó cũng lo
    # luôn thời lượng nên không cần chuỗi atempo bù qua bù lại nữa.
    nua_cung = max(-PITCH_TOI_DA, min(PITCH_TOI_DA, float(pitch_relative or 0.0)))
    he_so_pitch = 2.0 ** (nua_cung / 12.0)
    gain = max(-6.0, min(6.0, float(energy_relative_db or 0.0)))
    return (f"aresample={RATE_DUB},"
            f"rubberband=tempo={tempo:.6f}:pitch={he_so_pitch:.6f}"
            f":formant=preserved:pitchq=quality,"
            f"volume={gain:.3f}dB")


def _pcm_theo_tempo(wav_bytes: bytes, tempo: float, *,
                    pitch_relative: float | None = None,
                    energy_relative_db: float = 0.0) -> bytes:
    """Đọc câu ở tốc độ chung, giữ nguyên độ dài mà tốc độ đó sinh ra.

    KHÔNG cắt cho vừa khung phụ đề và KHÔNG đệm im lặng cho đầy khung: cắt là
    mất chữ, đệm là ép câu sau phải chờ. Việc đặt câu vào đúng mốc là của
    :func:`_ghi_track`.
    """
    loc = _bo_loc_tts(tempo, pitch_relative=pitch_relative,
                      energy_relative_db=energy_relative_db)
    p = _chay(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
              "-af", loc, "-ac", "1", "-ar", str(RATE_DUB),
              "-f", "s16le", "pipe:1"], input_data=wav_bytes, timeout=120)
    if p.returncode or not p.stdout:
        raise LoiLongTieng("Không căn được tốc độ câu TTS: "
                           + p.stderr.decode("utf-8", "ignore")[:150])
    pcm = p.stdout
    return pcm[:len(pcm) // 2 * 2]


def _do_tre(moc: list[float], giay: list[float], dai_video: float,
            tempo: float) -> tuple[float, float]:
    """Chạy thử cả phim ở một tốc độ: (trễ lớn nhất ở mốc mở câu, phần tràn đuôi).

    Đây là phép đo "tổng thể video" — chính thứ mà cách tính theo từng khung
    không có. Câu dài tràn sang khung sau không tự nó là lỗi: nếu sau đó có một
    khoảng lặng thì con trỏ bắt kịp mốc, và chỗ trễ biến mất.
    """
    con_tro = 0.0
    tre = 0.0
    n = len(moc)
    for i, (bat, dai) in enumerate(zip(moc, giay)):
        dur = dai / max(0.05, tempo)
        # Khung dành cho câu này = tới mốc câu sau (câu cuối: tới hết phim).
        khung = (moc[i + 1] - bat) if i + 1 < n else (dai_video - bat)
        if dur > khung and con_tro < bat:
            # Câu DÀI HƠN KHUNG và câu trước còn để chỗ trống phía trước: MƯỢN
            # chỗ đó, cho câu vào sớm (chặn ở SOM_TOI_DA) để chạy 1×. Đây là #5.
            con_tro = max(con_tro, max(0.0, bat - SOM_TOI_DA))
        elif con_tro < bat:
            # Câu vừa khung: đặt đúng mốc, GIỮ đồng bộ với hình (không kéo sớm).
            con_tro = bat
        if con_tro > bat:
            tre = max(tre, con_tro - bat)
        con_tro += dur
    return tre, max(0.0, con_tro - max(0.0, dai_video))


def _tempo_chung(moc: list[float], giay: list[float],
                 dai_video: float) -> tuple[float, float, float]:
    """MỘT tốc độ đọc cho cả phim: chậm nhất có thể mà lời vẫn không trôi.

    Vì sao không tính theo từng câu: khung phụ đề dài ngắn không đều, nên chia
    thời lượng TTS cho thời lượng từng khung sẽ ra mỗi câu một tốc độ — câu này
    0,7×, câu kia 2,5×. Nghe ra ngay là máy đọc, và đó đúng là thứ chủ máy báo
    lại. Đổi lại, một tốc độ duy nhất cho cả phim thì tai bắt nhịp được sau vài
    câu và không còn nhận ra là có co giãn.

    Sàn là TEMPO_CHUAN: thà để khung thừa im lặng còn hơn kéo giọng chậm ra cho
    đầy khung. Trần là TEMPO_NHANH_NHAT; chạm trần mà vẫn trễ thì đành chịu
    trễ và báo cảnh báo, chứ đọc nhanh hơn nữa là không ai nghe kịp.

    Trả về ``(tempo, trễ lớn nhất, phần tràn qua đuôi phim)``.
    """
    if not giay:
        return TEMPO_CHUAN, 0.0, 0.0

    def dat(t: float) -> bool:
        tre, tran = _do_tre(moc, giay, dai_video, t)
        return tre <= TRE_TOI_DA and tran <= 0.0

    if dat(TEMPO_CHUAN):
        chon = TEMPO_CHUAN
    elif not dat(TEMPO_NHANH_NHAT):
        chon = TEMPO_NHANH_NHAT
    else:
        # Cả hai thước đo đều giảm khi tempo tăng, nên chia đôi tìm được đúng
        # mức chậm nhất còn đạt. 40 vòng cho sai số dưới một phần triệu.
        thap, cao = TEMPO_CHUAN, TEMPO_NHANH_NHAT
        for _ in range(40):
            giua = (thap + cao) / 2.0
            if dat(giua):
                cao = giua
            else:
                thap = giua
        chon = cao
    tre, tran = _do_tre(moc, giay, dai_video, chon)
    return chon, tre, tran


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


@dataclass(frozen=True)
class _CauDaDoc:
    """Một câu đã tổng hợp xong, chờ căn tốc độ chung của cả phim."""

    duong: str
    giay: float


def _tong_hop_moi_cau(cues: list[dict[str, Any]], voice: str, thu_muc: str,
                      progress: Progress | None) -> tuple[list[_CauDaDoc | None], int]:
    """Pha 1 — đọc hết mọi câu ở tốc độ tự nhiên, chưa co giãn gì.

    Phải đọc xong hết mới biết TỔNG thời lượng lời, mà tổng đó mới là căn cứ
    chọn tốc độ. WAV thô ghi ra tệp chứ không giữ trong RAM: một phim dài có
    thể có hàng nghìn câu.
    """
    da_doc: list[_CauDaDoc | None] = []
    loi = 0
    for i, cue in enumerate(cues):
        wav: bytes | None = None
        loi_cue: Exception | None = None
        cue.pop("tts_error", None)
        cue["tts_recovered_after_retry"] = False
        for lan_thu in range(1, TTS_SO_LAN_TOI_DA + 1):
            cue["tts_attempts"] = lan_thu
            try:
                wav = _tong_hop(str(cue["text"]), voice, str(cue["emotion"]))
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
                            progress(i, len(cues),
                                     f"TTS câu {i + 1} lỗi, đang thử lại…")
                        except Exception:
                            pass
                    time.sleep(TTS_CHO_THU_LAI_GIAY)
                    continue
                loi_cue = exc
                break
        # WAV hỏng thì đọc lại cũng ra đúng bản hỏng đó — KHÔNG tốn thêm một
        # lượt tổng hợp, tính luôn là câu lỗi.
        cau: _CauDaDoc | None = None
        if wav is not None and loi_cue is None:
            try:
                giay, _ = _doc_wav_info(wav)
                duong = str(Path(thu_muc) / f"cau-{i + 1:06d}.wav")
                Path(duong).write_bytes(wav)
                cau = _CauDaDoc(duong, giay)
                cue["tts_status"] = "ok"
            except Exception as exc:
                loi_cue = exc
        if loi_cue is not None:
            loi += 1
            cue["tts_status"] = "error"
            cue["tts_recovered_after_retry"] = False
            cue["tts_error"] = str(loi_cue)[:160]
            logger.warning(
                "lồng tiếng câu %d vẫn lỗi sau %d lần: %s",
                i + 1, int(cue["tts_attempts"]), str(loi_cue)[:160])
            # Chính sách nghiêm chắc chắn sẽ từ chối MP4: dừng tại đây, không
            # đốt tiếp hàng trăm cue.
            da_doc.append(None)
            break
        da_doc.append(cau)
        if progress:
            try:
                progress(i + 1, len(cues),
                         f"đang tổng hợp giọng ({i + 1}/{len(cues)})…")
            except Exception:
                pass
    return da_doc, loi


def _ghi_track(w: wave.Wave_write, cues: list[dict[str, Any]],
               da_doc: list[_CauDaDoc | None], tempo: float,
               progress: Progress | None) -> tuple[int, int]:
    """Pha 2 — cùng MỘT tốc độ cho mọi câu, đặt vào đúng mốc mở câu.

    Trả về ``(vị trí con trỏ theo mẫu, số câu lỗi)``.
    """
    cursor = 0
    loi = 0
    for i, (cue, cau) in enumerate(zip(cues, da_doc)):
        if cau is None:            # pha 1 đã đếm câu này là lỗi rồi
            break
        pcm: bytes | None = None
        loi_cue: Exception | None = None
        # Căn tốc độ là pha riêng: WAV hỏng hay thiếu ffmpeg thì tổng hợp lại
        # TTS cũng vô ích, nên KHÔNG đọc lại câu. Nhưng ffmpeg quá giờ vì máy
        # đang tải là chuyện tự hết — dùng lại đúng bản WAV đã có mà chạy lại.
        for lan_can in range(1, TTS_SO_LAN_TOI_DA + 1):
            try:
                pcm = _pcm_theo_tempo(
                    Path(cau.duong).read_bytes(), tempo,
                    pitch_relative=cue.get("pitch_relative"),
                    energy_relative_db=float(
                        cue.get("energy_relative_db") or 0.0))
                if lan_can > 1:
                    cue["tts_recovered_after_retry"] = True
                break
            except Exception as exc:
                if (lan_can < TTS_SO_LAN_TOI_DA
                        and _loi_tts_tam_thoi(exc)):
                    logger.warning(
                        "căn tốc độ câu %d lỗi lần %d, thử lại: %s",
                        i + 1, lan_can, str(exc)[:160])
                    time.sleep(TTS_CHO_THU_LAI_GIAY)
                    continue
                loi_cue = exc
                break
        if pcm is None:
            loi += 1
            cue["tts_status"] = "error"
            cue["tts_recovered_after_retry"] = False
            cue["tts_error"] = str(loi_cue)[:160]
            logger.warning(
                "căn tốc độ câu %d vẫn lỗi sau %d lần: %s",
                i + 1, int(cue.get("tts_attempts") or 1), str(loi_cue)[:160])
            break
        bat = max(0, round(float(cue["start"]) * RATE_DUB))
        # Khung dành cho câu = tới mốc câu sau (câu cuối: coi như vô hạn, không
        # ép). Câu DÀI HƠN KHUNG và con trỏ còn trước mốc → MƯỢN chỗ trống câu
        # trước, cho vào sớm (chặn SOM_TOI_DA) để giữ 1× — khớp đúng _do_tre.
        # Câu vừa khung thì đặt ĐÚNG MỐC, giữ đồng bộ hình.
        dai_pcm = len(pcm) // 2
        if i + 1 < len(cues):
            khung = max(0, round(float(cues[i + 1]["start"]) * RATE_DUB)) - bat
        else:
            khung = dai_pcm + 1     # câu cuối: không bao giờ tính là ép
        if dai_pcm > khung and cursor < bat:
            moc_dat = max(cursor, max(0, round(
                (float(cue["start"]) - SOM_TOI_DA) * RATE_DUB)))
        else:
            moc_dat = max(cursor, bat)
        if moc_dat > cursor:
            _viet_lang(w, moc_dat - cursor)
            cursor = moc_dat
        # Câu trước tràn qua mốc này thì vào muộn, KHÔNG cắt đầu câu: cắt là mất
        # chữ. Chỗ trễ được khoảng lặng phía sau nuốt dần, và _tempo_chung đã
        # chọn tốc độ sao cho nó không vượt TRE_TOI_DA.
        cue["tts_tempo"] = round(tempo, 3)
        cue["tts_start_actual"] = round(cursor / RATE_DUB, 3)
        cue["tts_late_seconds"] = round(
            max(0.0, cursor / RATE_DUB - float(cue["start"])), 3)
        w.writeframesraw(pcm)
        cursor += len(pcm) // 2
        if progress:
            try:
                progress(i + 1, len(cues),
                         f"đang căn giọng vào hình ({i + 1}/{len(cues)})…")
            except Exception:
                pass
    return cursor, loi


def _tao_track(meta: dict[str, Any], dai: float, voice: str,
                progress: Progress | None) -> tuple[str, int, list[str]]:
    out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    cues = list(meta.get("cues") or [])
    canh_bao: list[str] = []
    meta["tts_retry_policy"] = {
        "max_attempts_per_cue": TTS_SO_LAN_TOI_DA,
        "retry_delay_seconds": TTS_CHO_THU_LAI_GIAY,
        "fail_fast_after_retries": True,
    }
    thu_muc = tempfile.TemporaryDirectory(prefix="long-tieng-")
    try:
        da_doc, loi = _tong_hop_moi_cau(cues, voice, thu_muc.name, progress)
        xong = [(float(c["start"]), d.giay)
                for c, d in zip(cues, da_doc) if d is not None]
        tempo, tre, tran = _tempo_chung([x for x, _ in xong],
                                        [y for _, y in xong], dai)
        meta["tts_tempo_policy"] = {
            "mode": "one_rate_for_whole_video",
            "tempo": round(tempo, 4),
            "tempo_floor": TEMPO_CHUAN,
            "tempo_ceiling": TEMPO_NHANH_NHAT,
            "late_budget_seconds": TRE_TOI_DA,
            "max_late_seconds": round(tre, 3),
            "overflow_seconds": round(tran, 3),
        }
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE_DUB)
            cursor, loi_ghi = _ghi_track(w, cues, da_doc, tempo, progress)
            loi += loi_ghi
            if not loi:
                tong = max(cursor, round(dai * RATE_DUB))
                if tong > cursor:
                    _viet_lang(w, tong - cursor)
        if not loi and (tre > TRE_TOI_DA + 0.05 or tran > 0.05):
            canh_bao.append(
                f"lời dịch dài hơn chỗ hình dành cho nó: đã đọc nhanh "
                f"{tempo:.2f}× mà vẫn trễ tới {max(tre, tran):.1f} giây")
    except Exception:
        Path(out).unlink(missing_ok=True)
        raise
    finally:
        thu_muc.cleanup()
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


#: Trộn nền với TTS. Hai lượt dùng cùng bộ lọc nhưng KHÁC chỉ số input: lượt đo
#: chỉ có 2 audio (0, 1), lượt ghi có video đứng trước nên audio là (1, 2).
_AMIX = "amix=inputs=2:duration=longest:dropout_transition=0:normalize=0"


def _tron_audio(nen: int, tts: int) -> str:
    """Bộ lọc trộn cho đúng vị trí hai input trong từng lệnh ffmpeg."""
    return f"[{nen}:a][{tts}:a]{_AMIX}"


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
               "-i", track, "-filter_complex", _tron_audio(0, 1) + ",ebur128=peak=true",
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
                  f"{_tron_audio(1, 2)},volume={bu:.2f}dB,"
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
    # Gộp khung vụn cùng một câu để đọc TRỌN CÂU liền mạch, không chen im lặng
    # giữa câu ("ngày mai (im) trời (im) lại sáng"). Câu vẫn đặt ở mốc khung đầu.
    doan = _gop_cau(doan)
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
            tom_tat = " ".join(x for x in (tom_tat, *canh_bao) if x)
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

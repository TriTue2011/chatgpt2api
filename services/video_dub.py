"""Lồng tiếng video bằng các engine TTS đã có, kèm ``prosody.json``.

Đường này cố ý độc lập với việc tạo phụ đề: caller đưa SRT đã dịch và video
gốc vào, nhận một video có track TTS THAY hoàn toàn track gốc. Nhạc/hiệu ứng
gốc cũng bị bỏ theo đúng lựa chọn "thay âm thanh gốc"; muốn giữ chúng cần một
bước source-separation riêng, không được trộn âm gốc nhỏ đi vì lời cũ sẽ lọt.

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
Progress = Callable[[int, int, str], None]


class LoiLongTieng(RuntimeError):
    """Đầu vào, giọng hoặc ffmpeg không đủ để tạo bản lồng tiếng."""


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
        raise LoiLongTieng("Xử lý âm thanh quá thời gian cho phép.") from exc


def _thoi_luong(duong: str, fallback: float) -> float:
    p = _chay(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "default=noprint_wrappers=1:nokey=1", duong], timeout=60)
    try:
        return max(float(p.stdout.decode().strip()), fallback)
    except (TypeError, ValueError):
        return fallback


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


def _pitch_fft(mau, rate: int) -> float | None:
    """Ước lượng F0 thô cho metadata tương đối; không dùng để nhận dạng người."""
    import numpy as np

    if len(mau) < int(rate * 0.08):
        return None
    # Giới hạn 1,5 s giữa cue để phim dài không làm phép FFT quá lớn.
    n = min(len(mau), int(rate * 1.5))
    bat = max(0, (len(mau) - n) // 2)
    x = np.asarray(mau[bat:bat + n], dtype=np.float32)
    x -= float(x.mean())
    rms = float(np.sqrt(np.mean(x * x)))
    if rms < 0.003:
        return None
    x *= np.hanning(len(x))
    pho = np.abs(np.fft.rfft(x))
    tan = np.fft.rfftfreq(len(x), 1.0 / rate)
    mask = (tan >= 70.0) & (tan <= 350.0)
    if not bool(mask.any()):
        return None
    i = int(np.argmax(pho[mask]))
    return float(tan[mask][i])


def _dac_trung(mau, rate: int, bat: float, ket: float) -> tuple[float, float | None]:
    import numpy as np

    a = max(0, min(len(mau), round(bat * rate)))
    b = max(a, min(len(mau), round(ket * rate)))
    if b <= a:
        return 0.0, None
    x = np.asarray(mau[a:b], dtype=np.float32) / 32768.0
    nang_luong = float(np.sqrt(np.mean(x * x))) if len(x) else 0.0
    return nang_luong, _pitch_fft(x, rate)


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
            "original_audio": "removed",
            "speaker_detection": "unavailable",
            "speaker_note": "one selected voice is used for every cue",
            "analysis_source": "mixed_original_audio",
            "created_at": int(time.time()),
            "cues": tam,
        }, raw)
    except Exception:
        Path(raw).unlink(missing_ok=True)
        raise


def _atempo(tempo: float) -> str:
    """Chuỗi atempo trong miền 0.5..2.0, ghép được mọi hệ số dương hợp lý."""
    tempo = max(0.05, min(20.0, float(tempo)))
    ds: list[float] = []
    while tempo > 2.0:
        ds.append(2.0)
        tempo /= 2.0
    while tempo < 0.5:
        ds.append(0.5)
        tempo /= 0.5
    ds.append(tempo)
    return ",".join(f"atempo={x:.6f}" for x in ds)


def _doc_wav_info(wav_bytes: bytes) -> tuple[float, int]:
    from io import BytesIO

    try:
        with wave.open(BytesIO(wav_bytes), "rb") as w:
            rate = max(1, w.getframerate())
            return w.getnframes() / rate, rate
    except Exception as exc:
        raise LoiLongTieng(f"TTS trả WAV không hợp lệ: {exc}") from exc


def _bo_loc_tts(rate_goc: int, giay_goc: float, giay_dich: float, *,
                pitch_relative: float | None = None,
                energy_relative_db: float = 0.0) -> tuple[str, float]:
    """Tạo filter ffmpeg thuần để test được mà không phải giả subprocess."""
    tempo = giay_goc / max(0.08, giay_dich)
    # Giới hạn để tránh méo giọng vì ước lượng F0 trên track trộn nhạc có thể
    # lệch. asetrate đổi pitch lẫn thời lượng; atempo bù lại phần thời lượng.
    nua_cung = max(-4.0, min(4.0, float(pitch_relative or 0.0)))
    he_so_pitch = 2.0 ** (nua_cung / 12.0)
    gain = max(-6.0, min(6.0, float(energy_relative_db or 0.0)))
    loc = (f"asetrate={round(rate_goc * he_so_pitch)},"
           f"aresample={RATE_DUB},"
           f"{_atempo(tempo / he_so_pitch)},volume={gain:.3f}dB")
    return loc, tempo


def _pcm_vua_khung(wav_bytes: bytes, giay_dich: float, *,
                   pitch_relative: float | None = None,
                   energy_relative_db: float = 0.0) -> tuple[bytes, float]:
    """Khớp thời lượng đồng thời tái tạo cao độ/năng lượng tương đối của cue."""
    giay_goc, rate_goc = _doc_wav_info(wav_bytes)
    loc, tempo = _bo_loc_tts(
        rate_goc, giay_goc, giay_dich,
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
                try:
                    wav = _tong_hop(str(cue["text"]), voice, str(cue["emotion"]))
                    pcm, tempo = _pcm_vua_khung(
                        wav, (ket - bat) / RATE_DUB,
                        pitch_relative=cue.get("pitch_relative"),
                        energy_relative_db=float(
                            cue.get("energy_relative_db") or 0.0))
                    cue["tts_tempo"] = round(tempo, 3)
                    cue["tts_status"] = "ok"
                    if tempo > 2.0:
                        canh_bao.append(f"câu {i + 1} phải đọc nhanh {tempo:.1f}×")
                except Exception as exc:
                    loi += 1
                    pcm = b"\0" * ((ket - bat) * 2)
                    cue["tts_status"] = "error"
                    cue["tts_error"] = str(exc)[:160]
                    logger.warning("lồng tiếng câu %d lỗi: %s",
                                   i + 1, str(exc)[:160])
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
            tong = max(cursor, round(dai * RATE_DUB))
            if tong > cursor:
                _viet_lang(w, tong - cursor)
        if loi == len(cues):
            raise LoiLongTieng("TTS lỗi ở toàn bộ câu thoại; không tạo video im lặng.")
    except Exception:
        Path(out).unlink(missing_ok=True)
        raise
    return out, loi, canh_bao


def _mux(duong_video: str, track: str, dai: float) -> str:
    out = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
    lenh_chung = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                  "-i", duong_video, "-i", track, "-map", "0:v:0", "-map", "1:a:0",
                  "-map_metadata", "0", "-c:a", "aac", "-b:a", "192k",
                  "-t", f"{dai:.3f}", "-movflags", "+faststart"]
    try:
        p = _chay(lenh_chung + ["-c:v", "copy", out], timeout=max(900, dai * 2))
        if p.returncode:
            # Codec/container gốc không copy được sang MP4 (vd vài AVI/WebM):
            # đổi riêng hình sang H.264, vẫn không map track âm thanh gốc.
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


def long_tieng(duong_video: str, srt: bytes | str, lang: str, *, voice: str = "",
               progress: Progress | None = None) -> KetQuaLongTieng:
    """Video + SRT đã dịch → MP4 thay track gốc + sidecar prosody JSON."""
    from services import video_dich as vd

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
    video: str | None = None
    prosody: str | None = None
    try:
        prosody = tempfile.NamedTemporaryFile(
            suffix=".prosody.json", delete=False).name
        track, so_loi, canh_bao = _tao_track(meta, dai, voice, progress)
        Path(prosody).write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
        if progress:
            progress(len(doan), len(doan), "đang ghép track lồng tiếng vào video…")
        video = _mux(duong_video, track, dai)
        tom_tat = ""
        if so_loi:
            tom_tat = f"TTS lỗi {so_loi}/{len(doan)} câu; các khung đó để im lặng."
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

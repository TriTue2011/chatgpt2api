"""Hẹn giờ phát thông báo TTS ra loa — bộ hẹn giờ NHẸ trong tiến trình.

Vd: "phát 'kiểm tra loa' sau 1 phút ra loa phòng khách âm lượng 20%".
Mỗi job: tới giờ thì đọc `text` bằng TTS rồi phát ra loa (tra theo TÊN/id),
có thể đặt âm lượng trước khi phát.

Dùng threading.Timer nên KHÔNG sống qua restart — đủ cho hẹn ngắn ("sau N phút").
Cần bền vững qua restart thì dùng agent_reminders (SQLite) thay cho module này.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_jobs: dict[str, dict[str, Any]] = {}
_MAX_KEEP = 50   # giữ tối đa 50 job gần nhất cho UI xem

# ── Chờ CÓ NGƯỜI mới phát ───────────────────────────────────────────────────
# Chủ máy 03/10/2026: "Trường hợp phát thông báo thì phải xác nhận trong nhà có người không, nếu có phát
# luôn. Không có thì chờ khi nào có người thì phát." Bằng chứng «có người» dùng lại
# `kich_hoat_nha.nha_co_nguoi` (người bấm công tắc / mở cửa trong 6 giờ — đã đo: radar, camera báo cả khi nhà
# vắng nên không tính). Đo 14 ngày tới 03/10 (7h–22h, mỗi nửa giờ): «vắng» chỉ rơi vào chiều ngày thường
# ~13–16h. Hàng chờ nằm trên ĐĨA: chờ cả buổi chiều, container khởi động lại giữa chừng không được mất tin.
GIU_TOI_DA = 24 * 3600     # chờ quá chừng này thì tin đã cũ — bỏ, ghi log


def _duong_cho():
    from pathlib import Path

    from services.config import DATA_DIR
    return Path(DATA_DIR) / "agent" / "loa_cho_nguoi.json"


def co_nguoi_nghe(luc: Optional[float] = None) -> bool:
    """Trong nhà có người nghe không. Không đọc được bằng chứng thì coi như CÓ — thà phát thừa còn hơn nuốt tin."""
    try:
        from services import kich_hoat_nha
        return bool(kich_hoat_nha.nha_co_nguoi(set(), float(luc or time.time())))
    except Exception as exc:  # noqa: BLE001
        logger.info("announce: không xét được có người (%s) — phát luôn", str(exc)[:80])
        return True


def _doc_cho() -> list[dict[str, Any]]:
    import json
    try:
        d = json.loads(_duong_cho().read_text(encoding="utf-8"))
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _ghi_cho(ds: list[dict[str, Any]]) -> None:
    import json
    p = _duong_cho()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ds, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def giu_cho(rec: dict[str, Any], text: str, *, voice: str = "", volume: Optional[float] = None,
            nguon: str = "") -> str:
    """Giữ một thông báo tới khi có người. Trả mã chờ."""
    ma = uuid.uuid4().hex[:10]
    with _lock:
        ds = _doc_cho()
        ds.append({"id": ma, "loa": str(rec.get("id") or rec.get("name") or ""), "ten_loa": rec.get("name"),
                   "text": text, "voice": str(voice or ""), "volume": volume, "luc": time.time(), "nguon": nguon})
        _ghi_cho(ds)
    logger.info("announce: nhà vắng — giữ «%s» chờ có người (%s)", text[:60], rec.get("name"))
    return ma


def dang_cho() -> list[dict[str, Any]]:
    with _lock:
        return list(_doc_cho())


def phat_cho(now: Optional[float] = None) -> int:
    """Heartbeat: có người rồi thì phát các tin đang giữ (cũ trước). Trả số tin đã đưa ra loa."""
    now = float(now or time.time())
    with _lock:
        ds = _doc_cho()
    if not ds:
        return 0
    con = [x for x in ds if now - float(x.get("luc") or 0) < GIU_TOI_DA]
    for x in ds:
        if x not in con:
            logger.warning("announce: bỏ tin chờ quá %d giờ: «%s»", GIU_TOI_DA // 3600, str(x.get("text"))[:60])
    if not con or not co_nguoi_nghe(now):
        if len(con) != len(ds):
            with _lock:
                _ghi_cho([x for x in _doc_cho() if x in con])
        return 0
    with _lock:   # lấy ra TRƯỚC khi phát: phát lỗi cũng không lặp mãi mỗi 5 phút
        _ghi_cho([x for x in _doc_cho() if x not in con and x not in ds])
    n = 0
    for x in con:
        try:
            schedule(x["loa"], x["text"], delay_seconds=0, volume=x.get("volume"), voice=x.get("voice") or "",
                     bo_qua_cho=True)
            n += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("announce: phát tin chờ lỗi (%s): %s", x.get("ten_loa"), str(exc)[:120])
    return n


def _resolve_one(speaker_query: str) -> dict[str, Any]:
    """Tra đúng MỘT loa theo tên/id. Nhiều kết quả = chưa rõ → bắt hỏi lại."""
    from services.voice import speakers as vspk

    hits = vspk.resolve(speaker_query)
    if not hits:
        raise RuntimeError(f"Không tìm thấy loa nào tên '{speaker_query}'.")
    if len(hits) > 1:
        names = ", ".join(str(h.get("name")) for h in hits[:6])
        raise RuntimeError(f"Nhiều loa khớp '{speaker_query}': {names} — nói rõ tên hơn.")
    return hits[0]


def _do_dai_audio(url: str) -> float:
    """Độ dài (giây) của file vừa phát, tra theo tên file trong kho media.

    `play_on()` TRẢ VỀ TRƯỚC KHI loa phát xong — chính `play_text_on` phải
    `time.sleep(độ dài câu 1)` mới dám push câu sau để Cast không cắt giữa. Nên
    muốn trả âm lượng về mức cũ thì phải chờ đúng độ dài này, không thì thông báo
    bị tụt tiếng ngay giữa câu.

    Tên file lấy từ PHẦN ĐƯỜNG DẪN của URL. Từ 08/08 `media_url` luôn ký URL
    (`…/x.wav?exp=…&sig=…&scope=voice`); cắt theo "/" trên cả chuỗi thì tên dính
    luôn `?exp=…`, không thấy file, trả 0 — và loa bị trả âm lượng cũ + xoá file
    NGAY lúc vừa phát. Đo 15/09/2026 trên loa phòng khách: loa báo IDLE/ERROR
    0,4 giây sau lệnh phát, còn âm lượng cũ của loa là 0% nên hoàn toàn im.
    """
    try:
        from urllib.parse import urlsplit

        from services.voice import config as vcfg
        from services.voice import _wav_duration_s  # type: ignore[attr-defined]
        ten = urlsplit(str(url or "")).path.rstrip("/").rsplit("/", 1)[-1]
        if not ten:
            return 0.0
        p = vcfg.media_dir() / ten
        return _wav_duration_s(p.read_bytes()) if p.is_file() else 0.0
    except Exception:
        return 0.0


def _tra_am_luong_sau_khi_phat(rec: dict[str, Any], muc_cu: Optional[float], url: str,
                               xoa_file: Optional[list] = None) -> None:
    """Chờ loa đọc xong rồi: đặt lại âm lượng cũ + xoá file audio tạm.

    Chạy NỀN để không giữ lượt chat. Cả hai việc phải CHỜ vì `play_on()` trả về
    trước khi loa phát xong — xoá file sớm là loa đang kéo dở thì mất tiếng, hạ
    âm lượng sớm là tụt tiếng giữa câu.

    `xoa_file`: các file audio của thông báo PHÁT NGAY — không cần giữ lại nên
    xoá luôn cho gọn kho media. Âm thanh của LỊCH HẸN thì ngược lại: tên có tiền
    tố `lich_`, `cleanup_media` bỏ qua, và chỉ xoá khi xoá lịch.
    """
    from services.voice import speakers as vspk

    def _cho_roi_don() -> None:
        cho = _do_dai_audio(url)
        da_hoi_loa = False
        if str(rec.get("kind") or "") == "cast" and url:
            # Hỏi chính loa đã đọc xong chưa (xem `cho_cast_doc_xong`). Nối loa
            # hỏng thì mới rơi về chờ theo độ dài file như loa không hỏi được.
            try:
                vspk.cho_cast_doc_xong(rec, url, toi_da=cho + 15)
                da_hoi_loa = True
            except Exception as exc:
                logger.info("announce: không hỏi được trạng thái %s (%s)",
                            rec.get("name"), str(exc)[:80])
        if not da_hoi_loa and cho > 0:
            time.sleep(cho + 0.4)      # thêm chút để câu cuối không bị tụt tiếng
        if muc_cu is not None:
            try:
                vspk.set_volume(rec, float(muc_cu))
                logger.info("announce: đã trả âm lượng %s về %.2f",
                            rec.get("name"), float(muc_cu))
            except Exception as exc:
                logger.warning("announce: trả âm lượng %s không được: %s",
                               rec.get("name"), str(exc)[:120])
        for p in (xoa_file or []):
            try:
                if p.is_file() and not p.name.startswith("lich_"):
                    p.unlink()
            except Exception as exc:
                logger.info("announce: chưa xoá được %s (%s)", p, str(exc)[:80])

    t = threading.Thread(target=_cho_roi_don, name="announce-sau-khi-phat", daemon=True)
    t.start()


def _run(jid: str) -> None:
    from services import voice
    from services.voice import speakers as vspk

    with _lock:
        job = _jobs.get(jid)
    if not job or job.get("status") == "cancelled":
        return
    rec = job["rec"]
    if not job.get("bo_qua_cho") and not co_nguoi_nghe():
        giu_cho(rec, job["text"], voice=str(job.get("voice") or ""), volume=job.get("volume"), nguon="announce")
        with _lock:
            job["status"] = "cho_nguoi"
        return
    muc_cu: Optional[float] = None
    try:
        vol = job.get("volume")
        if vol is not None:
            # Đọc mức ĐANG đặt trước khi đổi, để phát xong trả về đúng mức đó.
            try:
                muc_cu = vspk.get_volume(rec)
            except Exception as exc:
                muc_cu = None
                logger.info("announce: không đọc được âm lượng cũ (%s)", str(exc)[:80])
            try:
                vspk.set_volume(rec, float(vol))
            except Exception as exc:
                muc_cu = None
                if vspk.ho_tro_am_luong(rec):
                    # Loa CHỈNH ĐƯỢC âm lượng mà đặt không xong → dừng, đừng đọc
                    # tiếp rồi báo thành công. Người dùng chọn 0% lúc nửa đêm mà
                    # loa phát ở mức cũ là hỏng đúng cái họ vừa chọn, và câu
                    # "[đang đọc …]" khiến họ tin là đã chạy đúng.
                    raise RuntimeError(
                        f"Không đặt được âm lượng cho {rec.get('name')}: "
                        f"{str(exc)[:120]}") from exc
                # Loa DLNA/HA vốn không chỉnh được âm lượng → vẫn đọc như cũ.
                logger.info("announce: bỏ qua đặt âm lượng (%s)", str(exc)[:80])
        da_tao: list = []
        # Phát bằng bản ghi KHÔNG mang âm lượng mặc định: lượt này đã có mức
        # riêng, để nguyên `rec["volume"]` thì `_play_cast` vặn đè lên nó.
        rec_phat = vspk.bo_am_luong_mac_dinh(rec) if vol is not None else rec
        url = voice.play_text_on(job["text"], rec_phat, str(job.get("voice") or ""),
                                 files_out=da_tao)
        # Thông báo phát ngay: đọc xong là xoá file, khỏi để kho media phình.
        _tra_am_luong_sau_khi_phat(rec, muc_cu, str(url or ""), da_tao)
        with _lock:
            job["status"] = "done"
    except Exception as exc:
        # Đặt âm lượng xong mà phát hỏng thì vẫn phải trả mức cũ — không để loa
        # nằm ở mức thông báo chỉ vì lượt đó thất bại.
        if muc_cu is not None:
            try:
                vspk.set_volume(rec, float(muc_cu))
            except Exception:
                pass
        with _lock:
            job["status"] = f"error: {str(exc)[:160]}"
        logger.warning("announce: phát lỗi ra %s: %s", rec.get("name"), exc)


def schedule(speaker_query: str, text: str, *, delay_seconds: float,
             volume: Optional[float] = None, voice: str = "", bo_qua_cho: bool = False) -> dict[str, Any]:
    """Hẹn đọc `text` ra loa `speaker_query` sau `delay_seconds`.

    volume: 0..1 (tỉ lệ) hoặc — với R1 — chỉ số tuyệt đối (>1). Tuỳ chọn.
    voice: tên giọng TTS; rỗng = để `play_text_on` lấy giọng mặc định hệ thống.
        Caller nên truyền `voice.giong_cho_loa(rec, session_id=…)` để giọng riêng
        của loa / của kênh-thread-topic có tác dụng.
    Ném RuntimeError nếu loa không rõ (0 hoặc >1 kết quả)."""
    text = str(text or "").strip()
    if not text:
        raise ValueError("Thiếu nội dung thông báo.")
    rec = _resolve_one(speaker_query)     # ném lỗi sớm nếu loa chưa rõ
    delay = max(0.0, float(delay_seconds))
    jid = uuid.uuid4().hex[:10]
    # PHÁT NGAY thì chạy ĐỒNG BỘ để lỗi tới được người dùng.
    #
    # Đo thật 02/08: chủ máy bảo "phát ngay", bot trả "[đang đọc … ra loa phòng
    # khách]" mà loa im. Log máy chủ có nguyên nhân:
    #   announce: phát lỗi ra loa phòng khách: Chưa đặt voice.public_base_url —
    #   loa trong nhà không tải được file từ localhost.
    # Timer(0) chạy trong thread nền nên `schedule()` trả về TRƯỚC khi biết kết
    # quả; lỗi chỉ vào logger.warning, người dùng nhận một câu báo thành công
    # sai sự thật. Hẹn giờ (delay > 0) thì vẫn phải chạy nền — không chặn lượt.
    timer = None if delay <= 0 else threading.Timer(delay, _run, args=(jid,))
    if timer is not None:
        timer.daemon = True
    with _lock:
        _jobs[jid] = {
            "id": jid,
            "rec": rec,
            "speaker_name": rec.get("name"),
            "text": text,
            "voice": str(voice or ""),
            "volume": None if volume is None else float(volume),
            "fire_at": int(time.time() + delay),
            "status": "scheduled",
            "timer": timer,
            "bo_qua_cho": bool(bo_qua_cho),   # tin lấy ra từ hàng chờ — đã xét có người rồi
        }
        _prune()
    if timer is None:
        _run(jid)
        with _lock:
            trang_thai = str((_jobs.get(jid) or {}).get("status") or "")
        if trang_thai.startswith("error:"):
            raise RuntimeError(trang_thai[len("error:"):].strip())
        return public(jid) or {}
    timer.start()
    return public(jid) or {}


def dat_lich(user_id: str, speaker_query: str, text: str, when: str, *,
             volume: Optional[float] = None, voice_name: str = "") -> dict[str, Any]:
    """Đặt LỊCH đọc thông báo ra loa — sống qua restart.

    Khác `schedule()`: `schedule` dùng `threading.Timer` trong tiến trình nên mất
    sạch khi khởi động lại (đủ cho "sau 1 phút", không đủ cho "8h sáng mai"). Hàm
    này ghi vào SQLite của `agent_reminders` với `mode='loa'` — cùng bảng, cùng
    vòng chạy, cùng phép chống gửi trùng, cùng bộ hiểu thời gian ("mỗi ngày 6h",
    "thứ 2 hàng tuần") và cùng chỗ xem/huỷ lịch. Không dựng bộ hẹn giờ thứ hai.

    Âm thanh được tổng hợp NGAY BÂY GIỜ và ghi ra file có tiền tố `lich_` (nên
    `cleanup_media` không dọn theo tuổi). Tới giờ chỉ việc đẩy URL cho loa — lịch
    vẫn chạy đúng dù lúc đó engine giọng đang lỗi hay model chưa nạp. Đường dẫn
    file nằm trong cột `meta` của dòng lịch.

    Ném RuntimeError/ValueError nếu loa chưa rõ, không hiểu thời điểm, hoặc TTS
    hỏng — để người đặt lịch biết NGAY, không phải chờ tới giờ mới thấy im lặng.
    """
    from services import voice
    from services.agent import reminders as rem

    text = str(text or "").strip()
    if not text:
        raise ValueError("Thiếu nội dung thông báo.")
    rec = _resolve_one(speaker_query)          # ném lỗi sớm nếu loa chưa rõ
    lich = rem.parse_when(str(when or ""))
    if not lich or not lich.get("next_run_at"):
        raise ValueError("Không hiểu thời điểm. VD: '8h sáng mai', 'mỗi ngày 6h', '19:30'.")

    wav = voice.speak(text, voice_name)        # tổng hợp SẴN, lỗi ném ra ngay
    path = voice.save_media(wav, giu_lai=True)
    try:
        row = rem.create(
            user_id, text, lich, mode="loa",
            meta_extra={
                "speaker_id": str(rec.get("id") or ""),
                "speaker_name": str(rec.get("name") or ""),
                "audio_path": str(path),
                "voice": str(voice_name or ""),
                "volume": None if volume is None else float(volume),
            },
        )
    except Exception:
        try:
            path.unlink()                      # tạo lịch hỏng thì đừng để lại file mồ côi
        except Exception:
            pass
        raise
    logger.info("announce: đã đặt lịch %s ra %s (%s)", row.get("id"),
                rec.get("name"), rem._fmt_when(row))
    return row


def cancel(jid: str) -> bool:
    with _lock:
        job = _jobs.get(str(jid or ""))
        if not job:
            return False
        job["status"] = "cancelled"
        t = job.get("timer")
    if t:
        try:
            t.cancel()
        except Exception:
            pass
    return True


def public(jid: str) -> Optional[dict[str, Any]]:
    with _lock:
        job = _jobs.get(str(jid or ""))
        if not job:
            return None
        return {k: job[k] for k in ("id", "speaker_name", "text", "voice", "volume", "fire_at", "status")}


def list_jobs() -> list[dict[str, Any]]:
    with _lock:
        rows = [{k: j[k] for k in ("id", "speaker_name", "text", "voice", "volume", "fire_at", "status")}
                for j in _jobs.values()]
    rows.sort(key=lambda r: r.get("fire_at") or 0, reverse=True)
    return rows


def _prune() -> None:
    """Bỏ bớt job cũ đã xong/huỷ khi vượt trần (giữ job đang chờ)."""
    if len(_jobs) <= _MAX_KEEP:
        return
    done = [(j["fire_at"], j["id"]) for j in _jobs.values()
            if j.get("status") in ("done", "cancelled") or str(j.get("status", "")).startswith("error")]
    done.sort()
    for _, jid in done[: len(_jobs) - _MAX_KEEP]:
        _jobs.pop(jid, None)

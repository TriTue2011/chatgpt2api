"""API giọng nói: TTS/STT kiểu OpenAI + quản lý loa + phục vụ file audio.

  POST /v1/audio/speech            text → WAV (tương thích OpenAI)
  POST /v1/audio/transcriptions    file audio → text (tương thích OpenAI)
  GET  /media/voice/{name}         file audio cho loa LAN kéo về (KHÔNG auth —
                                   loa Cast/DLNA không gửi được header)
  GET  /api/voice/status           trạng thái engine + model
  GET/POST/PATCH/DELETE /api/voice/speakers[...]   sổ loa
  POST /api/voice/speakers/{id}/test   thử kết nối
  POST /api/voice/speakers/{id}/play   phát thử một câu
  POST /api/voice/speakers/import-ha   nhập media_player từ Home Assistant
"""

from __future__ import annotations

import re

import io
import wave

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response, StreamingResponse

from api.support import require_admin

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _wav_stream_bytes(text: str, voice: str):
    """Generator bytes cho StreamingResponse: header WAV (nframes rất lớn để
    trình duyệt phát liền khi data tới) rồi PCM16 theo từng khối sinh ra.

    Chạy trong threadpool của Starlette (generator đồng bộ) — gọi TTS blocking
    an toàn. Rate lấy từ khối đầu (VieNeu 48k / Kokoro 24k / Piper ~22k)."""
    from services import voice as _voice

    header_sent = False
    for rate, pcm in _voice.speak_stream(text, voice):
        if not header_sent:
            h = io.BytesIO()
            with wave.open(h, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(int(rate))
                # nframes lớn → player phát liên tục khi data tới. Trần an toàn:
                # RIFF size = 36 + nframes*2 phải lọt 'L' (<=4.29 tỉ) → 0x3FFFFFFF.
                w.setnframes(0x3FFFFFFF)
            yield h.getvalue()
            header_sent = True
        yield pcm
    if not header_sent:
        # Không có audio nào → trả WAV rỗng hợp lệ để client không treo.
        h = io.BytesIO()
        with wave.open(h, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000)
        yield h.getvalue()


def create_router() -> APIRouter:
    router = APIRouter()

    # ── OpenAI-compatible ────────────────────────────────────────────────
    @router.post("/v1/audio/speech")
    async def audio_speech(request: Request,
                           authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import voice

        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "Body phải là JSON")
        text = str(body.get("input") or body.get("text") or "").strip()
        if not text:
            raise HTTPException(400, "Thiếu 'input'")
        voice_name = str(body.get("voice") or "").strip()
        # stream=true → phát dần theo dòng chảy (chữ tới đâu đọc tới đó).
        if bool(body.get("stream")):
            return StreamingResponse(
                _wav_stream_bytes(text, voice_name), media_type="audio/wav",
                headers={"Cache-Control": "no-store",
                         "X-Accel-Buffering": "no"})
        try:
            wav = await run_in_threadpool(voice.speak, text, voice_name)
        except Exception as exc:
            raise HTTPException(503, str(exc)[:300])
        return Response(content=wav, media_type="audio/wav")

    @router.get("/api/voice/stream")
    async def voice_stream(text: str, voice: str = "",
                           authorization: str | None = Header(default=None),
                           key: str = ""):
        """Đọc `text` theo dòng chảy → WAV chunked. Nhận token qua header
        Authorization HOẶC query `key=` (thẻ <audio src> không gửi được header)."""
        require_admin(authorization or (f"Bearer {key}" if key else None))
        t = (text or "").strip()
        if not t:
            raise HTTPException(400, "Thiếu 'text'")
        return StreamingResponse(
            _wav_stream_bytes(t, str(voice or "").strip()),
            media_type="audio/wav",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @router.post("/v1/audio/transcriptions")
    async def audio_transcriptions(
        file: UploadFile = File(...),
        model: str = Form(default=""),
        language: str = Form(default=""),
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        from services import voice

        data = await file.read()
        if not data:
            raise HTTPException(400, "File rỗng")
        hint = (file.filename or "").rsplit(".", 1)[-1] if file.filename else ""
        try:
            text = await run_in_threadpool(voice.listen, data, hint, language)
        except Exception as exc:
            raise HTTPException(503, str(exc)[:300])
        return {"text": text}

    # ── File audio cho loa (không auth: Cast/DLNA không gửi header) ──────
    @router.get("/media/voice/{name}")
    async def media_voice(name: str):
        from services.voice import config as vcfg

        if not _SAFE_NAME.match(name or ""):
            raise HTTPException(404, "not found")
        path = vcfg.media_dir() / name
        if not path.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(str(path), media_type="audio/wav")

    # ── Trạng thái + sổ loa ──────────────────────────────────────────────
    @router.get("/api/voice/status")
    async def voice_status(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import voice
        return {"ok": True, **voice.status()}

    @router.get("/api/voice/catalog")
    async def voice_catalog(authorization: str | None = Header(default=None)):
        """Danh mục 19 giọng (từ manifest) + giọng nào đã tải về volume."""
        require_admin(authorization)
        from services.voice import config as vcfg
        return {"ok": True, "voices": vcfg.voice_catalog()}

    _PREVIEW_TEXT = (
        "Xin chào, đây là giọng đọc thử của trợ lý. "
        "Bạn nghe rõ và thấy tự nhiên chứ ạ?"
    )
    # Giọng Kokoro chỉ đọc tiếng Anh → câu thử riêng.
    _PREVIEW_TEXT_EN = (
        "Hello! This is a sample of my English voice. "
        "Does it sound clear and natural to you?"
    )

    @router.get("/api/voice/preview")
    async def voice_preview(voice: str = "", stream: int = 0, key: str = "",
                            authorization: str | None = Header(default=None)):
        """Đọc một câu mẫu bằng giọng chỉ định → WAV, để nghe thử ngay trên web.

        stream=1 → phát theo dòng chảy (chữ tổng hợp tới đâu gửi tới đó) nên nghe
        được gần như tức thì thay vì chờ ~3-4s tổng hợp trọn câu. Thẻ <audio> không
        gửi được header nên nhận token qua query `key=` (như /api/voice/stream).
        Giọng chưa tải về sẽ báo lỗi kèm hướng dẫn (không tự tải để tránh treo)."""
        require_admin(authorization or (f"Bearer {key}" if key else None))
        from services import voice as _voice
        from services.voice import config as vcfg

        vname = str(voice or "").strip()
        sample = _PREVIEW_TEXT
        if vname.startswith(vcfg.VIENEU_PREFIX):
            if not vcfg.vieneu_model_ready():
                raise HTTPException(
                    404, "Model VieNeu chưa tải (chạy scripts/download_vieneu_model.py).")
        elif vname.startswith(vcfg.KOKORO_PREFIX):
            if vcfg.kokoro_model_dir() is None:
                raise HTTPException(
                    404, "Model Kokoro chưa tải (chạy scripts/download_kokoro_model.py).")
            sample = _PREVIEW_TEXT_EN
        elif vname and vcfg.voice_model_path(vname) is None:
            raise HTTPException(
                404, f"Giọng '{vname}' chưa tải về (chạy download_piper_voices.py --pack full).")
        if stream:
            return StreamingResponse(
                _wav_stream_bytes(sample, vname), media_type="audio/wav",
                headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
        try:
            wav = await run_in_threadpool(_voice.speak, sample, vname)
        except Exception as exc:
            raise HTTPException(503, str(exc)[:300])
        return Response(content=wav, media_type="audio/wav")

    @router.get("/api/voice/speakers")
    async def speakers_list(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.voice import speakers as vspk
        return {"ok": True, "rows": vspk.list_speakers()}

    @router.post("/api/voice/speakers")
    async def speakers_add(request: Request,
                           authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.voice import speakers as vspk

        body = await request.json()
        try:
            rec = vspk.add(
                str(body.get("name") or ""), str(body.get("kind") or ""),
                host=str(body.get("host") or ""),
                port=int(body.get("port") or 0),
                entity_id=str(body.get("entity_id") or ""),
                note=str(body.get("note") or ""),
                ws_port=int(body.get("ws_port") or 0),
                max_vol=int(body.get("max_vol") or 0),
                control_url=str(body.get("control_url") or ""),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"ok": True, "row": rec}

    @router.patch("/api/voice/speakers/{speaker_id}")
    async def speakers_update(speaker_id: str, request: Request,
                              authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.voice import speakers as vspk

        rec = vspk.update(speaker_id, await request.json())
        if not rec:
            raise HTTPException(404, "Không có loa này")
        return {"ok": True, "row": rec}

    @router.delete("/api/voice/speakers/{speaker_id}")
    async def speakers_delete(speaker_id: str,
                              authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.voice import speakers as vspk
        return {"ok": vspk.remove(speaker_id)}

    @router.post("/api/voice/speakers/import-ha")
    async def speakers_import_ha(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.voice import speakers as vspk

        added = await run_in_threadpool(vspk.import_from_ha)
        return {"ok": True, "added": added, "count": len(added)}

    @router.post("/api/voice/discover")
    async def voice_discover(kind: str = "all",
                             authorization: str | None = Header(default=None)):
        """Dò loa trong LAN theo LOẠI. `kind` = cast | dlna | r1 | all.

        cast/r1: quét TCP cổng cố định (Cast 8009 / R1 8082). dlna: SSDP M-SEARCH
        (cổng động) — trả kèm control_url để phát thẳng; rỗng nếu mạng chặn multicast."""
        require_admin(authorization)
        from services.voice import speakers as vspk
        from services.voice import config as vcfg

        hints: list[str] = []
        try:
            u = vcfg.public_base_url()
            if u:
                hints.append(u)
        except Exception:
            pass
        try:
            hits = await run_in_threadpool(
                vspk.discover_lan, None, hints, str(kind or "all"))
        except Exception as exc:
            raise HTTPException(503, str(exc)[:300])
        return {"ok": True, "found": hits, "count": len(hits)}

    @router.post("/api/voice/speakers/{speaker_id}/music")
    async def speakers_music(speaker_id: str, request: Request,
                             authorization: str | None = Header(default=None)):
        """Mở nhạc theo yêu cầu (YouTube) trên loa R1. Body: {"query","volume"}.

        `volume` tuỳ chọn: ≤1 = tỉ lệ (0.2 = 20%), >1 = chỉ số tuyệt đối (5)."""
        require_admin(authorization)
        from services.voice import speakers as vspk

        rec = vspk.get(speaker_id)
        if not rec:
            raise HTTPException(404, "Không có loa này")
        # Chặn sớm loa không phải R1 — nếu để play_music tự chặn thì set_volume
        # bên dưới đã kịp vặn loa Cast lên (vd volume=5 chỉ số R1 bị kẹp thành 100%).
        if str(rec.get("kind") or "") != "r1":
            raise HTTPException(400, "Mở nhạc theo yêu cầu hiện chỉ hỗ trợ loa R1.")
        try:
            body = await request.json()
        except Exception:
            body = {}
        query = str(body.get("query") or "").strip()
        if not query:
            raise HTTPException(400, "Thiếu 'query' (tên bài / thể loại nhạc)")
        vol = body.get("volume")
        if vol not in (None, ""):
            try:
                await run_in_threadpool(vspk.set_volume, rec, float(vol))
            except Exception as exc:
                raise HTTPException(503, f"Đặt âm lượng lỗi: {str(exc)[:200]}")
        try:
            song = await run_in_threadpool(vspk.play_music, rec, query)
        except Exception as exc:
            raise HTTPException(503, str(exc)[:300])
        return {"ok": True, "song": song}

    @router.post("/api/voice/announce")
    async def voice_announce(request: Request,
                             authorization: str | None = Header(default=None)):
        """Hẹn giờ đọc thông báo TTS ra loa. Body: {speaker,text,delay_seconds,volume}.

        `speaker`: tên/id loa (vd 'loa phòng khách'). `delay_seconds`: hẹn sau bao
        lâu (0 = phát ngay). `volume`: phần trăm 0..100 (vd 20 = 20%), tuỳ chọn."""
        require_admin(authorization)
        from services.voice import announce as vann

        try:
            body = await request.json()
        except Exception:
            body = {}
        speaker = str(body.get("speaker") or "").strip()
        text = str(body.get("text") or "").strip()
        if not speaker or not text:
            raise HTTPException(400, "Cần 'speaker' (tên loa) và 'text' (nội dung)")
        try:
            delay = max(0.0, float(body.get("delay_seconds") or 0))
        except (TypeError, ValueError):
            delay = 0.0
        volume = None
        vol = body.get("volume")
        if vol not in (None, ""):
            try:
                volume = max(0.0, min(100.0, float(vol))) / 100.0
            except (TypeError, ValueError):
                volume = None
        try:
            job = await run_in_threadpool(
                vann.schedule, speaker, text, delay_seconds=delay, volume=volume)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc)[:300])
        return {"ok": True, "job": job}

    @router.get("/api/voice/announce")
    async def voice_announce_list(authorization: str | None = Header(default=None)):
        """Danh sách thông báo đã hẹn (đang chờ / đã phát / lỗi)."""
        require_admin(authorization)
        from services.voice import announce as vann
        return {"ok": True, "jobs": vann.list_jobs()}

    @router.post("/api/voice/speakers/{speaker_id}/test")
    async def speakers_test(speaker_id: str,
                            authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.voice import speakers as vspk

        rec = vspk.get(speaker_id)
        if not rec:
            raise HTTPException(404, "Không có loa này")
        ok, msg = await run_in_threadpool(vspk.test_reachable, rec)
        return {"ok": ok, "message": msg}

    @router.post("/api/voice/speakers/{speaker_id}/volume")
    async def speakers_volume(speaker_id: str, request: Request,
                              authorization: str | None = Header(default=None)):
        """Đặt âm lượng loa Cast ngay lập tức. Body: {"level": 0..100}.
        Kèm {"save": true} thì lưu làm âm lượng mặc định mỗi lần phát."""
        require_admin(authorization)
        from services.voice import speakers as vspk

        rec = vspk.get(speaker_id)
        if not rec:
            raise HTTPException(404, "Không có loa này")
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            level = max(0, min(100, int(body.get("level") or 0))) / 100.0
        except (TypeError, ValueError):
            raise HTTPException(400, "level phải là số 0..100")
        try:
            await run_in_threadpool(vspk.set_volume, rec, level)
        except Exception as exc:
            raise HTTPException(503, str(exc)[:300])
        if bool(body.get("save")):
            vspk.update(speaker_id, {"volume": level})
        return {"ok": True, "level": int(level * 100)}

    @router.post("/api/voice/speakers/{speaker_id}/control")
    async def speakers_control(speaker_id: str, request: Request,
                               authorization: str | None = Header(default=None)):
        """Điều khiển loa Cast: {"action": "pause|resume|stop|on|off|mute|unmute"}.
        on/off như media_player.turn_on/turn_off của Home Assistant."""
        require_admin(authorization)
        from services.voice import speakers as vspk

        rec = vspk.get(speaker_id)
        if not rec:
            raise HTTPException(404, "Không có loa này")
        try:
            body = await request.json()
        except Exception:
            body = {}
        action = str(body.get("action") or "").strip().lower()
        try:
            if action in ("mute", "unmute"):
                await run_in_threadpool(vspk.set_mute, rec, action == "mute")
            elif action in ("pause", "resume", "stop", "on", "off"):
                await run_in_threadpool(vspk.media_control, rec, action)
            else:
                raise HTTPException(400,
                                    "action: pause|resume|stop|on|off|mute|unmute")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(503, str(exc)[:300])
        return {"ok": True, "action": action}

    @router.get("/api/voice/speakers/{speaker_id}/status")
    async def speakers_status(speaker_id: str,
                              authorization: str | None = Header(default=None)):
        """Âm lượng/mute/đang phát gì trên loa Cast."""
        require_admin(authorization)
        from services.voice import speakers as vspk

        rec = vspk.get(speaker_id)
        if not rec:
            raise HTTPException(404, "Không có loa này")
        try:
            st = await run_in_threadpool(vspk.speaker_status, rec)
        except Exception as exc:
            raise HTTPException(503, str(exc)[:300])
        return {"ok": True, **st}

    @router.post("/api/voice/speakers/{speaker_id}/play")
    async def speakers_play(speaker_id: str, request: Request,
                            authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import voice
        from services.voice import speakers as vspk

        rec = vspk.get(speaker_id)
        if not rec:
            raise HTTPException(404, "Không có loa này")
        try:
            body = await request.json()
        except Exception:
            body = {}
        text = str(body.get("text") or "Xin chào, đây là thử nghiệm loa.").strip()
        try:
            url = await run_in_threadpool(voice.play_text_on, text, rec)
        except Exception as exc:
            raise HTTPException(503, str(exc)[:300])
        return {"ok": True, "url": url}

    return router

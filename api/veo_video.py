"""
Veo Video Generation endpoint — OpenAI-compatible /v1/video/generations.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

from fastapi import Header, HTTPException
from pydantic import BaseModel, ConfigDict

from services.config import config
from services.image_providers.veo_video import veo_adapter
from utils.log import logger


class VideoGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str = "veo/veo-3.1-generate-preview"
    prompt: str
    n: int = 1
    aspect_ratio: str = "16:9"
    duration: str | None = None
    resolution: str | None = None
    image: str | None = None  # base64 image for image→video
    last_frame: str | None = None


def _luu_thu_vien(ket_qua: dict[str, Any]) -> dict[str, Any]:
    """Ghi video vừa tạo vào THƯ VIỆN (config.images_dir) và gắn thêm
    `library_url` vào từng item.

    Trước đây video tạo xong chỉ tồn tại trong câu trả lời HTTP: tab Tạo Video
    giữ nó trong bộ nhớ trình duyệt, tải lại trang là mất; còn nhánh bot ghi vào
    data/agent/media/ — thư mục KHÔNG nằm trong vùng /api/images quét, nên
    "Quản lý Video" luôn trống. Đặt ở đây (điểm ra chung của mọi nhánh) thay vì
    ở từng nơi gọi để web, bot và API cùng có một thư viện.

    Không ném lỗi ra ngoài: lưu hỏng thì người dùng vẫn phải nhận được video.
    """
    import base64
    import hashlib
    import time
    from pathlib import Path

    items = (ket_qua or {}).get("data") or []
    if not isinstance(items, list):
        return ket_qua
    thu_muc_ngay = Path(time.strftime("%Y"), time.strftime("%m"), time.strftime("%d"))
    goc = config.images_dir / thu_muc_ngay
    for item in items:
        if not isinstance(item, dict) or item.get("library_url"):
            continue
        raw = b""
        b64 = str(item.get("b64_json") or "")
        if b64:
            try:
                raw = base64.b64decode(b64.split(",", 1)[1] if b64.startswith("data:") else b64)
            except Exception as exc:
                logger.warning({"event": "video_library_decode_failed", "error": str(exc)[:120]})
        if not raw:
            # Nhánh chỉ trả URL (Agnes, Veo trực tiếp) — tải về để thư viện có
            # bản thật, không phải một liên kết sẽ hết hạn.
            url = str(item.get("url") or "")
            if not url.startswith(("http://", "https://")):
                continue
            try:
                import httpx
                with httpx.Client(timeout=120, follow_redirects=True) as client:
                    r = client.get(url)
                    r.raise_for_status()
                    raw = r.content
            except Exception as exc:
                logger.warning({"event": "video_library_download_failed",
                                "error": str(exc)[:120]})
                continue
        try:
            goc.mkdir(parents=True, exist_ok=True)
            ten = f"{int(time.time())}_{hashlib.md5(raw, usedforsecurity=False).hexdigest()[:12]}.mp4"
            (goc / ten).write_bytes(raw)
            item["library_url"] = f"{config.base_url}/images/{thu_muc_ngay.as_posix()}/{ten}"
            logger.info({"event": "video_saved_to_library", "path": f"{thu_muc_ngay.as_posix()}/{ten}",
                         "bytes": len(raw)})
        except Exception as exc:
            logger.warning({"event": "video_library_save_failed", "error": str(exc)[:120]})
    return ket_qua


def _loi_solver(exc: Exception, nhan: str) -> str:
    """Nguyên nhân THẬT của lỗi từ captcha-solver, không phải dòng trạng thái.

    `resp.raise_for_status()` chỉ ném "Server error '502 Bad Gateway' for url …",
    còn lý do thật nằm trong body: {"detail": "429: Account Busy"} hoặc
    {"detail": "Flow generate failed after 1 attempts…"}. Đo thật 31/07: gọi
    tạo video trả về đúng chữ "502 Bad Gateway" nên không thể biết là tài khoản
    đang bận, hết lượt, hay trình duyệt không dựng được trang.
    """
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            chi_tiet = resp.json().get("detail")
        except Exception:
            chi_tiet = (getattr(resp, "text", "") or "")[:300]
        if chi_tiet:
            return f"{nhan} generation failed: {chi_tiet}"
    # httpx.ReadTimeout stringify ra chuỗi RỖNG — đo thật 31/07: flow/veo-3.1-lite
    # hết hạn chờ và thông báo về tay người dùng chỉ là "Flow Video generation
    # failed: " không có chữ nào phía sau. Rơi về tên lớp lỗi cho có nội dung.
    ly_do = str(exc).strip() or type(exc).__name__
    return f"{nhan} generation failed: {ly_do}"


async def handle_video_generation(
    body: dict[str, Any],
    authorization: str | None = None,
) -> dict[str, Any] | Iterator[dict[str, Any]]:
    """Handle POST /v1/video/generations."""
    prompt = str(body.get("prompt") or "")
    if not prompt:
        raise HTTPException(status_code=400, detail={"error": "prompt is required"})

    # Số video yêu cầu. TRẦN ĐẶT THEO TỪNG NHÁNH, không kẹp chung ở đây:
    # Flow có hàng x1/x2/x3/x4 trên giao diện (tín dụng nhân lên theo số video),
    # còn Veo trực tiếp và Agnes chỉ ra 1 video mỗi lượt gọi. Trước đây dòng này
    # là `max(1, min(1, …))` — `min(1, x)` luôn ≤ 1 nên MỌI nhánh đều bị ép về 1.
    # Hậu quả: tab Tạo Video cho chọn x4 và báo "400 tín dụng", nhưng xuống tới
    # Flow thì count=1 ⇒ người dùng nhận 1 video sau khi đã đọc giá của 4 video.
    n_yeu_cau = max(1, int(body.get("n") or 1))
    n = n_yeu_cau
    aspect_ratio = str(body.get("aspect_ratio") or "16:9")
    duration = body.get("duration")
    resolution = body.get("resolution")
    image = body.get("image")
    last_frame = body.get("last_frame")
    negative_prompt = body.get("negative_prompt")
    fps = body.get("fps") or body.get("frame_rate")
    num_frames = body.get("num_frames")
    seed = body.get("seed")
    mode = body.get("mode")
    keyframes = body.get("keyframes")
    model = str(body.get("model") or "veo/veo-3.1-generate-preview")

    if model.startswith("agnes/") or "agnes" in model:
        from services.providers.agnes import agnes_provider
        try:
            return _luu_thu_vien(agnes_provider.generate_video(
                prompt=prompt,
                model=model,
                aspect_ratio=aspect_ratio,
                duration=duration,
                resolution=resolution,
                image=image,
                last_frame=last_frame,
                negative_prompt=negative_prompt,
                fps=fps,
                num_frames=num_frames,
                seed=seed,
                mode=mode,
                keyframes=keyframes,
            ))
        except Exception as exc:
            logger.error({"event": "agnes_video_error", "error": str(exc)})
            raise HTTPException(status_code=502, detail={"error": f"Agnes Video generation failed: {exc}"}) from exc

    if model.startswith("flow/"):
        # Ảnh CUỐI mà không có ảnh ĐẦU: Flow nhận nút "Tạo" nhưng KHÔNG BAO GIỜ
        # sinh xong. Đo thật 31/07 trên flow/veo-3.1-lite: solver gắn ảnh vào ô
        # "Kết thúc" thành công (log kiểm chứng nhãn ô biến mất), bấm Tạo trả
        # ok=True, rồi 300 giây sau giao diện vẫn không chuyển sang thư viện ⇒
        # người gọi chờ 6 phút mới nhận lỗi, và một hồ sơ trình duyệt bị giữ suốt
        # thời gian đó. Chặn ngay ở đây: nói rõ phải thêm ảnh đầu, không mở
        # trình duyệt, không tốn tín dụng. Tab Tạo Video vốn chỉ gửi last_frame
        # kèm image nên chỉ ảnh hưởng bên gọi qua API/bot.
        if last_frame and not image:
            raise HTTPException(status_code=400, detail={"error":
                "Flow cần ẢNH ĐẦU khi đã có ảnh cuối: chế độ 'Khung hình' là nối "
                "từ ảnh đầu sang ảnh cuối. Gửi kèm 'image', hoặc bỏ 'last_frame' "
                "để tạo video chỉ từ mô tả."})
        import httpx
        from services.image_providers.flow_google import (
            _pool_config, _next_account, _reorder_flow_account, _account_key,
        )
        flow_cfg = _pool_config()
        from services.captcha import captcha_base
        solver_url = captcha_base(flow_cfg.get("captcha_solver_url"))

        acc = _next_account()
        if not acc:
            raise HTTPException(status_code=429, detail={"error": "All Flow accounts are exhausted/in cooldown."})

        # Lỗi XẢY RA TRƯỚC KHI BẤM "Tạo" ⇒ chưa tiêu tín dụng ⇒ ĐỔI TÀI KHOẢN rồi
        # thử lại là an toàn. Lỗi sau khi bấm thì KHÔNG được thử lại: tín dụng đã
        # trừ, chạy lại là trừ lần hai.
        #
        # Vì sao cần: `_next_account()` chọn theo ưu tiên CỨNG (index 0 trước), mà
        # nhánh này trước đây thất bại là raise 502 luôn — không đẩy tài khoản hỏng
        # xuống, không thử tài khoản khác. Nên một tài khoản hỏng ở index 0 làm
        # MỌI lượt tạo video hỏng mãi, không tự khỏi. Đo thật 02/08:
        # google-mitbap0610 (index 0) không có khung nhập trên trang dự án →
        # 100% lượt video trả 502, trong khi google-benbap2011 vẫn tạo được bình
        # thường. Nhánh tạo ẢNH đã có `_reorder_flow_account` từ trước; nhánh video
        # thì chưa bao giờ có.
        _LOI_TRUOC_KHI_BAM_TAO = (
            "không vào được màn soạn",      # không có khung nhập / chip sai chế độ
            "không chuyển được sang tab",    # thông báo bản cũ, còn trong log cũ
            "chưa bấm tạo",                  # model_mismatch / model_unverified
            "account busy",                  # hồ sơ trình duyệt đang bị lượt khác giữ
            "signin/rejected",               # Google chặn trình duyệt tự động
            # Trang chưa dựng xong giao diện — xảy ra lúc TẢI TRANG, tức chắc chắn
            # trước mọi cú bấm "Tạo". Đo thật 02/08: Backup trượt (chưa bấm Tạo) →
            # đổi sang Spare 1 → Spare 1 trả "Flow UI never hydrated: timeout
            # 45000ms", chuỗi đó KHÔNG khớp danh sách này nên vòng lặp dừng sớm và
            # bỏ luôn 2 tài khoản còn lại, dù chẳng tài khoản nào tiêu tín dụng.
            "never hydrated",
            "profile is logged out",          # cùng nhóm: chết ở bước tải trang
        )

        def _co_the_thu_tai_khoan_khac(loi: str) -> bool:
            low = (loi or "").lower()
            return any(k in low for k in _LOI_TRUOC_KHI_BAM_TAO)

        # Hạn chờ của ta phải LỚN HƠN ngân sách của solver, không thì ta luôn
        # bỏ cuộc trước và không bao giờ đọc được kết quả. Đo thật 31/07:
        # cả hai đều 300s ⇒ flow/veo-3.1-lite chết ở đúng 300,0s với thông báo
        # rỗng, còn solver vẫn đang giữ hồ sơ trình duyệt nên 3 model sau nhận
        # "Account Busy". `FlowVideoReq.timeout` mặc định 300, trần 600.
        _NGAN_SACH_SOLVER_S = 300
        _da_thu: set[str] = set()
        _loi_cuoi = ""
        async with httpx.AsyncClient(timeout=_NGAN_SACH_SOLVER_S + 60) as client:
          # Tối đa 3 tài khoản: đủ để đi qua một cái hỏng mà không kéo dài vô hạn
          # (mỗi lượt tới 300s). Hết lượt hoặc lỗi không-thể-thử-lại thì raise.
          for _lan_tk in range(3):
            try:
                resp = await client.post(
                    f"{solver_url}/v1/google/flow/generate-video",
                    json={
                        "project_id": acc.get("project_id", ""),
                        "profile": acc.get("profile", "google-fx"),
                        "prompt": prompt,
                        "model": model,
                        "aspect_ratio": aspect_ratio,
                        # captcha-solver khai `FlowVideoReq.duration: str | None`.
                        # `duration` ở đây đọc thẳng từ body thô nên vẫn có thể là
                        # số nguyên; gửi số là solver trả 422 rồi bị bọc thành 502.
                        # Đo thật 31/07: gửi duration=4 → "Input should be a valid string".
                        "duration": None if duration is None else str(duration),
                        # Flow: hàng "Số bản ghi" trên giao diện chỉ có x1..x4.
                        "count": max(1, min(4, n_yeu_cau)),
                        "image": image,
                        "last_frame": last_frame,
                        "headless": False
                    },
                    headers={"authorization": authorization or ""}
                )
                resp.raise_for_status()
                data = resp.json()
                
                try:
                    meta = data.get("data", [{}])[0].get("metadata", {})
                    credits = meta.get("remainingCredits")
                    if credits is not None:
                        from services.config import config
                        providers = config.data.get("providers") or {}
                        flow = providers.get("flow") or {}
                        accounts = flow.get("accounts") or []
                        for a in accounts:
                            if a.get("profile") == acc.get("profile") and a.get("project_id") == acc.get("project_id"):
                                a["remainingCredits"] = credits
                                config.save()
                                break
                except Exception:
                    pass

                # Thành công → đưa tài khoản này lên đầu hàng cho lượt sau.
                _reorder_flow_account(acc, to_front=True)
                return _luu_thu_vien(data)
            except Exception as exc:
                # KHÔNG gán `logger` ở đây. Gán cục bộ giữa hàm biến `logger`
                # thành biến địa phương của CẢ hàm, nên hai khối báo lỗi phía
                # trước/sau (agnes ở trên, veo ở dưới) ném UnboundLocalError
                # ngay trong lúc đang xử lý lỗi ⇒ người dùng nhận HTTP 500
                # "Internal Server Error" trắng thay vì nguyên nhân thật.
                # Đo thật 31/07: agnes/agnes-video-v2.0 trả 500 vì đúng lỗi này.
                _loi_cuoi = _loi_solver(exc, "Flow Video")
                logger.error({
                    "event": "flow_video_error",
                    "profile": acc.get("profile"),
                    "label": acc.get("label"),
                    "try": _lan_tk + 1,
                    "error": str(exc)[:400],
                })
                # Tài khoản này vừa hỏng → đẩy xuống cuối để lượt sau không lấy nó
                # trước nữa. Đây là thứ nhánh video thiếu, khiến một tài khoản hỏng
                # ở index 0 làm mọi lượt video hỏng mãi.
                _reorder_flow_account(acc, to_front=False)
                _da_thu.add(_account_key(acc))
                if not _co_the_thu_tai_khoan_khac(_loi_cuoi):
                    # Có thể đã bấm "Tạo" và tiêu tín dụng → KHÔNG chạy lại.
                    logger.info({"event": "flow_video_khong_thu_lai",
                                 "reason": "loi co the xay ra SAU khi bam Tao",
                                 "error": _loi_cuoi[:200]})
                    break
                ke = _next_account(exclude=_da_thu)
                if not ke:
                    logger.info({"event": "flow_video_het_tai_khoan",
                                 "da_thu": len(_da_thu)})
                    break
                logger.info({"event": "flow_video_doi_tai_khoan",
                             "tu": acc.get("label"), "sang": ke.get("label")})
                acc = ke
          raise HTTPException(status_code=502, detail={"error": _loi_cuoi or "Flow Video failed"})

    # Get credentials from gemini_free config
    providers_cfg = config.data.get("providers") or {}
    provider_config = providers_cfg.get("gemini_free") or {}

    credentials = {
        "apiKey": str(provider_config.get("api_key") or ""),
        "apiKeys": provider_config.get("api_keys") or [],
    }

    # Veo trực tiếp: mỗi lượt gọi API ra đúng 1 video, và ta KHÔNG lặp để nhân
    # lên vì mỗi lượt tiêu một phần hạn mức khoá gemini_free. Tab Tạo Video cũng
    # chỉ cho chọn 1 cho nhánh này (video-model-specs.ts: veo-direct.countOptions).
    n = 1
    all_data = []
    for idx in range(n):
        try:
            result = veo_adapter.generate(
                body={
                    "prompt": prompt,
                    "aspect_ratio": aspect_ratio,
                    "duration": duration,
                    "resolution": resolution,
                    "image": image,
                    "last_frame": last_frame,
                },
                credentials=credentials,
            )
            all_data.extend(result.get("data") or [])
        except Exception as exc:
            logger.error({"event": "veo_generation_error", "error": str(exc)})
            raise HTTPException(
                status_code=500,
                detail={"error": f"Video generation failed: {exc}"},
            ) from exc

    return _luu_thu_vien({
        "created": result.get("created", 0) if all_data else 0,
        "data": all_data,
    })


def _decode_media(b64: str) -> bytes:
    """Nhận b64 hoặc data-URL ('data:video/mp4;base64,...') → bytes."""
    import base64 as _b64
    s = str(b64 or "")
    if "," in s and s.strip().lower().startswith("data:"):
        s = s.split(",", 1)[1]
    return _b64.b64decode(s)


async def handle_video_compose(
    body: dict[str, Any],
    authorization: str | None = None,
) -> dict[str, Any]:
    """POST /v1/video/compose — nối nhiều clip (b64) → 1 video dài + voiceover.

    Body: {"clips":[b64|dataURL,...], "audio": b64?, "aspect_ratio":"9:16"?}
    """
    import base64
    import os
    import tempfile
    import time
    from pathlib import Path

    from fastapi.concurrency import run_in_threadpool
    from services.video import VideoError, concat_clips

    clips_b64 = (body or {}).get("clips") or []
    if not isinstance(clips_b64, list) or not clips_b64:
        raise HTTPException(status_code=400, detail={"error": "clips (list b64) is required"})

    tmp: list[str] = []
    audio_path = None
    try:
        for c in clips_b64:
            fd, p = tempfile.mkstemp(suffix=".mp4"); os.close(fd)
            Path(p).write_bytes(_decode_media(c)); tmp.append(p)
        clip_paths = list(tmp)
        audio_b64 = (body or {}).get("audio")
        if audio_b64:
            fd, ap = tempfile.mkstemp(suffix=".wav"); os.close(fd)
            Path(ap).write_bytes(_decode_media(audio_b64)); tmp.append(ap); audio_path = ap
        try:
            out = await run_in_threadpool(concat_clips, clip_paths, audio_path, None)
        except VideoError as exc:
            raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
        data = base64.b64encode(Path(out).read_bytes()).decode()
        try:
            os.unlink(out)
        except Exception:
            pass
        return {"created": int(time.time()), "data": [{"b64_json": data}]}
    finally:
        for p in tmp:
            try:
                os.unlink(p)
            except Exception:
                pass


async def handle_video_story(
    body: dict[str, Any],
    authorization: str | None = None,
) -> dict[str, Any]:
    """POST /v1/video/story — prompt/scenes → Veo text→video từng cảnh → nối.

    Body: {"prompt": "...", "scenes":[...]?, "n_scenes":3, "duration":6,
           "aspect_ratio":"9:16"}
    """
    import base64
    import os
    import time
    from pathlib import Path

    from fastapi.concurrency import run_in_threadpool
    from services.video import VideoError
    from services.video.shorts import make_story_video

    providers_cfg = config.data.get("providers") or {}
    pc = providers_cfg.get("gemini_free") or {}
    credentials = {"apiKey": str(pc.get("api_key") or ""), "apiKeys": pc.get("api_keys") or []}
    auth_key = str(authorization or "").replace("Bearer ", "").strip()

    scenes = (body or {}).get("scenes") or None
    prompt = str((body or {}).get("prompt") or "")
    if not scenes and not prompt:
        raise HTTPException(status_code=400, detail={"error": "prompt or scenes is required"})
    try:
        n = int((body or {}).get("n_scenes") or 3)
        dur = int((body or {}).get("duration") or 6)
    except (TypeError, ValueError):
        n, dur = 3, 6
    aspect = str((body or {}).get("aspect_ratio") or "9:16")

    try:
        out = await run_in_threadpool(
            lambda: make_story_video(
                credentials, scenes=scenes, prompt=prompt, n_scenes=n,
                auth_key=auth_key, aspect_ratio=aspect, duration=dur,
            )
        )
    except VideoError as exc:
        raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
    data = base64.b64encode(Path(out).read_bytes()).decode()
    try:
        os.unlink(out)
    except Exception:
        pass
    return {"created": int(time.time()), "data": [{"b64_json": data}]}

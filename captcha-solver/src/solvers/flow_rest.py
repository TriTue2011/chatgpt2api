"""Gọi thẳng REST API của Flow — trình duyệt chỉ còn làm máy phát token.

VÌ SAO CÓ FILE NÀY. Đường đang chạy (`flow_google.py`) điều khiển GIAO DIỆN Flow
bằng Chrome: gõ prompt vào Slate editor, bấm dropdown model, bấm nút Tạo, rình
mạng lấy kết quả. Mỗi lượt giữ `browser_pool` 60–300 giây, và vỡ mỗi lần Flow
đổi giao diện — sự cố 08/08/2026 là một yêu cầu tạo ẢNH bấm hụt dropdown rồi
trừ mất tín dụng VIDEO Omni Flash 8 giây.

File này gửi thẳng JSON tới đúng API mà giao diện đó gọi. Trình duyệt còn đúng
hai việc, mỗi việc khoảng một giây: xin `access_token` và đúc token reCAPTCHA.
Không còn DOM, nên không còn cả lớp lỗi "bấm hụt".

ĐO THẬT 09/08/2026, tài khoản `google-benbap115`, project 55575914-…:

  * Tiến trình Python thuần — không cookie, không `x-browser-validation`,
    không `x-client-data` — gọi tới `aisandbox-pa.googleapis.com` KHÔNG bị chặn
    ở tầng vận chuyển. `httpx` mặc định và `curl_cffi(impersonate="chrome")` trả
    kết quả giống hệt nhau, nên dấu vân tay TLS không phải yếu tố. Ghi chú trong
    `services/image_providers/flow_google.py` nói "any non-browser caller bị từ
    chối" là sai ở phần này.
  * Cửa duy nhất là reCAPTCHA. Thiếu token thì 403 "reCAPTCHA evaluation failed".
  * `imageModelName` được kiểm TRƯỚC reCAPTCHA nên đo được trực tiếp:

        NARWHAL          hợp lệ   (đi tiếp tới cửa reCAPTCHA)
        HARBOR_SEAL      hợp lệ   (đi tiếp tới cửa reCAPTCHA)
        IMAGEN_3_5       404      tài khoản này không có
        NANO_BANANA_PRO  400      INVALID_ARGUMENT — KHÔNG phải hằng số có thật
        IMAGEN_4         400      INVALID_ARGUMENT — KHÔNG phải hằng số có thật

    `NANO_BANANA_PRO` đang là model mặc định của `flow/auto` và `flow/banana-pro`
    bên `services/image_providers/flow_google.py`, và là cả giá trị dự phòng
    cuối cùng của `_resolve_model()`. Đường DOM không lộ ra vì nó chỉ dùng chuỗi
    đó làm khoá tra NHÃN dropdown; đường này gửi thẳng nên phải chặn tại chỗ,
    kèm thông báo nêu tên đúng — xem `kiem_model_anh()`.

KHỚP VỚI QUẢN LÝ MODEL — CHƯA. Bảng `_MODEL_ALIASES` bên
`services/image_providers/flow_google.py` đang chào bốn model ảnh, mà ba trong
số đó hỏng nếu đi đường này: `flow/banana-pro` và `flow/auto` cùng trỏ vào
`NANO_BANANA_PRO` (400), `flow/imagen-4` trỏ vào `IMAGEN_3_5` (404 trên tài
khoản đã đo). Chỉ `flow/banana-2` → `NARWHAL` là chạy. Sửa bảng đó phải sửa
ĐỒNG THỜI bảng nhãn dropdown trong `flow_google.py` của bộ lái, nếu không đường
DOM sẽ bấm hụt — đúng cơ chế đã gây sự cố 08/08/2026, và
`test/test_flow_khong_tao_nham_loai.py` canh chính ràng buộc đó. Chưa làm ở đây
vì chưa đo được `NARWHAL` và `HARBOR_SEAL` ứng với nhãn nào.

NGUỒN THÂN YÊU CẦU. Dựng theo bản gỡ rối của VEO3 AI Studio 1.08 (ứng dụng
Electron gọi cùng API này). Những trường chưa đo được trực tiếp — hằng số tỷ lệ
khung hình — đều ghi rõ là "theo bản gỡ rối, chưa đo".

CHƯA LÀM: tạo video (`v1/video:batchAsyncGenerateVideo*`), nâng ảnh
(`flow/upsampleImage`), sửa video (`…EditVideo`). Thêm sau, theo đúng khuôn ở
đây — phần dùng chung (`lay_bearer`, `_lay_recaptcha`, `_post`,
`upload_anh_tham_chieu`) đã sẵn cho cả hai loại.
"""

from __future__ import annotations

import base64
import logging
import random
import re
import time
import uuid
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_HOST = "https://aisandbox-pa.googleapis.com"
TOOL = "PINHOLE"

# Token OAuth của Flow sống khoảng một giờ (đo: hạn 2026-08-09T22:24:30Z, lấy
# lúc ~21:2x). Cache ngắn hơn hẳn để không bao giờ dùng token sắp hết hạn.
_TOKEN_SONG_S = 45 * 60
_token_cache: dict[str, tuple[str, float]] = {}

# Hai tên đã đo là KHÔNG tồn tại. Danh sách này chỉ để chặn cái đã biết sai —
# tên lạ vẫn cho đi qua, vì Flow thêm model mới liên tục và chặn cứng sẽ khoá
# mất model mới ngay ngày nó ra.
MODEL_ANH_DA_DO_LA_SAI = {
    "NANO_BANANA_PRO": "400 INVALID_ARGUMENT (đo 09/08/2026)",
    "IMAGEN_4": "400 INVALID_ARGUMENT (đo 09/08/2026)",
}
MODEL_ANH_DA_DO_LA_DUNG = ("NARWHAL", "HARBOR_SEAL")

# Tỷ lệ khung hình ảnh — theo bản gỡ rối VEO3 AI Studio 1.08, CHƯA đo trực tiếp
# (API kiểm trường này sau cửa reCAPTCHA nên phép đo hôm 09/08 chưa chạm tới).
# Lưu ý: dạng chữ ở đây là FOUR_THREE / THREE_FOUR, khác dạng 4_3 / 3_4 mà
# `services/image_providers/flow_google.py` đang dùng. Bên đó chỉ dùng chuỗi làm
# khoá tra nhãn dropdown nên chưa bao giờ tới API; đừng đồng bộ hai bảng cho tới
# khi đo xong bên nào đúng.
TY_LE_ANH = {
    "1:1": "IMAGE_ASPECT_RATIO_SQUARE",
    "16:9": "IMAGE_ASPECT_RATIO_LANDSCAPE",
    "9:16": "IMAGE_ASPECT_RATIO_PORTRAIT",
    "4:3": "IMAGE_ASPECT_RATIO_LANDSCAPE_FOUR_THREE",
    "3:4": "IMAGE_ASPECT_RATIO_PORTRAIT_THREE_FOUR",
}


class LoiFlowRest(RuntimeError):
    """Lỗi từ API Flow, giữ nguyên mã HTTP để bên gọi phân biệt được.

    429 và lỗi hết ngạch phải phân biệt được với hỏng thật, vì bên
    `services/image_providers/flow_google.py` dựa vào chuỗi thông báo để quyết
    định cho tài khoản nghỉ (cooldown) hay đẩy xuống cuối danh sách.
    """

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


# ── Dựng thân yêu cầu (hàm thuần, không I/O — test bám vào đây) ────────────

def kiem_model_anh(model: str) -> str:
    """Trả tên model ảnh, ném lỗi nếu là tên ĐÃ ĐO là không tồn tại."""
    ten = (model or "").strip().upper()
    if not ten:
        return MODEL_ANH_DA_DO_LA_DUNG[0]
    if ten in MODEL_ANH_DA_DO_LA_SAI:
        raise ValueError(
            f"'{ten}' không phải model ảnh có thật của Flow — API trả "
            f"{MODEL_ANH_DA_DO_LA_SAI[ten]}. Tên đã đo là dùng được: "
            f"{', '.join(MODEL_ANH_DA_DO_LA_DUNG)}."
        )
    return ten


def _ngu_canh(project_id: str, tier: str, session_id: str,
              recaptcha: str | None) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "projectId": project_id,
        "tool": TOOL,
        "userPaygateTier": tier,
        "sessionId": session_id,
    }
    if recaptcha:
        ctx["recaptchaContext"] = {
            "token": recaptcha,
            "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB",
        }
    return ctx


def than_tao_anh(
    *,
    project_id: str,
    prompt: str,
    model: str,
    aspect_ratio: str = "16:9",
    count: int = 1,
    media_ids: list[str] | None = None,
    recaptcha: str | None = None,
    session_id: str | None = None,
    batch_id: str | None = None,
    seeds: list[int] | None = None,
) -> dict[str, Any]:
    """Thân cho `v1/projects/{id}/flowMedia:batchGenerateImages`.

    `count` ảnh được tạo bằng cách nhân bản phần tử trong `requests`, mỗi bản
    một seed riêng — đúng cách app làm, và tiết kiệm hơn hẳn cách hiện tại là
    bắn `count` lời gọi song song qua giao diện.
    """
    ten_model = kiem_model_anh(model)
    sid = session_id or str(int(time.time() * 1000))
    ctx = _ngu_canh(project_id, "PAYGATE_TIER_ONE", sid, recaptcha)
    so = max(1, int(count))
    hat = seeds or [random.randint(0, 99998) for _ in range(so)]
    yeu_cau = [
        {
            "clientContext": dict(ctx),
            "imageAspectRatio": TY_LE_ANH.get(aspect_ratio, aspect_ratio),
            "structuredPrompt": {"parts": [{"text": prompt}]},
            "imageModelName": ten_model,
            "seed": hat[i % len(hat)],
            "imageInputs": [
                {"imageInputType": "IMAGE_INPUT_TYPE_REFERENCE", "name": m}
                for m in (media_ids or [])
            ],
        }
        for i in range(so)
    ]
    return {
        "clientContext": dict(ctx),
        "mediaGenerationContext": {"batchId": batch_id or str(uuid.uuid4())},
        "useNewMedia": True,
        "requests": yeu_cau,
    }


# ── Trình duyệt: chỉ để lấy token ─────────────────────────────────────────

_JS_LAY_TOKEN = (
    "(async()=>{try{const r=await fetch('/fx/api/auth/session');"
    "const d=await r.json();return d.access_token||null;}catch(e){return null;}})()"
)


async def _bearer_tu_trang(page, profile: str) -> str:
    cache = _token_cache.get(profile)
    if cache and cache[1] > time.time():
        return cache[0]
    if "labs.google" not in (page.url or ""):
        await page.goto("https://labs.google/fx/tools/flow",
                        wait_until="domcontentloaded", timeout=30_000)
    token = await page.evaluate(_JS_LAY_TOKEN)
    if not token:
        # Lùi về cách cũ: rình header Authorization của chính trang.
        from .flow_google import _capture_bearer
        token = await _capture_bearer(page, timeout_s=25.0)
    _token_cache[profile] = (str(token), time.time() + _TOKEN_SONG_S)
    return str(token)


async def lay_bearer(profile: str, headless: bool = True) -> str:
    """`access_token` của Flow. Còn hạn trong cache thì KHÔNG mở trình duyệt.

    Tách khỏi việc đúc reCAPTCHA vì hai thứ có tuổi thọ chênh nhau rất xa: token
    này sống ~1 giờ, token reCAPTCHA sống ~2 phút.
    """
    cache = _token_cache.get(profile)
    if cache and cache[1] > time.time():
        return cache[0]
    from ..browser_pool import pool
    async with pool.page(profile=profile, headless=headless) as page:
        return await _bearer_tu_trang(page, profile)


async def _lay_recaptcha(profile: str, headless: bool, action: str) -> str:
    """Đúc token reCAPTCHA. LUÔN phải mở trang, và phải gọi NGAY TRƯỚC lệnh gửi.

    Token sống khoảng hai phút. Nếu đúc trước rồi mới đi đẩy ảnh tham chiếu lên
    (mỗi ảnh một lời gọi HTTP) thì với bộ ảnh lớn, token có thể hết hạn đúng lúc
    gửi lệnh tạo — hỏng với thông báo "reCAPTCHA evaluation failed" trông y hệt
    lỗi mất phiên, rất khó lần ra. Vì vậy thứ tự bắt buộc là: lấy bearer → đẩy
    ảnh → đúc reCAPTCHA → gửi lệnh. Ứng dụng gốc cũng làm đúng thứ tự này.
    """
    from ..browser_pool import pool
    from .flow_google import _get_recaptcha_token

    async with pool.page(profile=profile, headless=headless) as page:
        if "labs.google" not in (page.url or ""):
            await page.goto("https://labs.google/fx/tools/flow",
                            wait_until="domcontentloaded", timeout=30_000)
        token, sitekey = await _get_recaptcha_token(page, action=action)
    logger.info("flow_rest đúc reCAPTCHA profile=%s sitekey=%s", profile, sitekey[:16])
    return token


# ── Gọi API ───────────────────────────────────────────────────────────────

def _thong_bao_loi(r: httpx.Response) -> str:
    try:
        return str((r.json().get("error") or {}).get("message") or r.text[:200])
    except ValueError:
        return r.text[:200]


async def _post(url: str, bearer: str, than: dict[str, Any], timeout: float) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=than, headers={
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/json",
        })
    if r.status_code != 200:
        raise LoiFlowRest(r.status_code, _thong_bao_loi(r))
    return r.json()


async def upload_anh_tham_chieu(*, bearer: str, project_id: str, du_lieu: bytes,
                                timeout: float = 120) -> str:
    """Đẩy một ảnh lên Flow, trả `mediaId`. Gửi nguyên file, không resize."""
    dap = await _post(f"{API_HOST}/v1/flow/uploadImage", bearer, {
        "clientContext": {"projectId": project_id, "tool": TOOL},
        "imageBytes": base64.b64encode(du_lieu).decode("ascii"),
    }, timeout)
    for khoa in ("name", "mediaId", "id"):
        if dap.get(khoa):
            return str(dap[khoa])
    tim = re.search(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}",
                    str(dap))
    if tim:
        return tim.group(0)
    raise LoiFlowRest(502, f"đáp upload không có mediaId: {str(dap)[:200]}")


async def tao_anh(*, profile: str, project_id: str, prompt: str,
                  model: str = "NARWHAL", aspect_ratio: str = "16:9",
                  count: int = 1, anh_tham_chieu: list[bytes] | None = None,
                  headless: bool = True, timeout: float = 180) -> dict[str, Any]:
    """Tạo ảnh. Đồng bộ — đáp trả luôn media và link xem trước."""
    bat_dau = time.time()
    ten_model = kiem_model_anh(model)  # ném sớm, trước khi tốn một lượt mở trình duyệt
    bearer = await lay_bearer(profile, headless)

    media_ids = [
        await upload_anh_tham_chieu(bearer=bearer, project_id=project_id, du_lieu=b)
        for b in (anh_tham_chieu or [])
    ]
    # Đúc reCAPTCHA SAU khi đẩy ảnh xong — xem `_lay_recaptcha`.
    recaptcha = await _lay_recaptcha(profile, headless, "IMAGE_GENERATION")
    dap = await _post(
        f"{API_HOST}/v1/projects/{project_id}/flowMedia:batchGenerateImages",
        bearer,
        than_tao_anh(project_id=project_id, prompt=prompt, model=model,
                     aspect_ratio=aspect_ratio, count=count, media_ids=media_ids,
                     recaptcha=recaptcha),
        timeout,
    )
    ten = [m["name"] for m in (dap.get("media") or []) if m.get("name")]
    link = re.findall(r'"(https://flow-content\.google/image/[^"]+)"', str(dap))
    if not ten:
        raise LoiFlowRest(502, f"đáp không có media: {str(dap)[:300]}")
    return {
        "media_ids": ten,
        "urls": link,
        "model": ten_model,
        "project_id": project_id,
        "elapsed_ms": int((time.time() - bat_dau) * 1000),
    }



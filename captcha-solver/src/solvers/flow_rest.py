"""Gọi thẳng REST API của Flow — trình duyệt chỉ còn làm máy phát token.

VÌ SAO CÓ FILE NÀY. Đường đang chạy (`flow_google.py`) điều khiển GIAO DIỆN Flow
bằng Chrome: gõ prompt vào Slate editor, bấm dropdown model, bấm nút Tạo, rình
mạng lấy kết quả. Mỗi lượt giữ `browser_pool` 60–300 giây, và vỡ mỗi lần Flow
đổi giao diện — sự cố 08/08/2026 là một yêu cầu tạo ẢNH bấm hụt dropdown rồi
trừ mất tín dụng VIDEO Omni Flash 8 giây.

File này gửi thẳng JSON tới đúng API mà giao diện đó gọi. Trình duyệt còn đúng
hai việc, mỗi việc khoảng một giây: xin `access_token` và đúc token reCAPTCHA.
Không còn DOM, nên không còn cả lớp lỗi "bấm hụt".

CHẠY THẬT LẦN ĐẦU 09/08/2026: `POST /v1/google/flow/rest/generate-image` trong
container trả **HTTP 200 sau 35 giây**, kèm `mediaId` thật. Đây là câu trả lời
cho ẩn số để ngỏ suốt quá trình: token reCAPTCHA đúc trong trình duyệt của
container DÙNG ĐƯỢC cho request phát từ chính tiến trình đó, dù request không đi
qua ngữ cảnh trang. Kiến trúc "trình duyệt làm máy phát token" chạy được.

Đáp của lệnh tạo chỉ có `mediaId`, KHÔNG có link ảnh — link phải đổi thêm một
lượt qua `media.getMediaUrlRedirect`; xem `lay_link_media()`.

ĐO THẬT 09/08/2026, tài khoản `google-benbap115`, project 55575914-…:

  * Tiến trình Python thuần — không cookie, không `x-browser-validation`,
    không `x-client-data` — gọi tới `aisandbox-pa.googleapis.com` KHÔNG bị chặn
    ở tầng vận chuyển. `httpx` mặc định và `curl_cffi(impersonate="chrome")` trả
    kết quả giống hệt nhau, nên dấu vân tay TLS không phải yếu tố. Ghi chú trong
    `services/image_providers/flow_google.py` nói "any non-browser caller bị từ
    chối" là sai ở phần này.
  * Cửa duy nhất là reCAPTCHA. Thiếu token thì 403 "reCAPTCHA evaluation failed".
  * `imageModelName` được kiểm TRƯỚC reCAPTCHA nên đo được trực tiếp:

        GEM_PIX_2        hợp lệ   (đi tiếp tới cửa reCAPTCHA)
        NARWHAL          hợp lệ   (đi tiếp tới cửa reCAPTCHA)
        HARBOR_SEAL      hợp lệ   (đi tiếp tới cửa reCAPTCHA)
        GEM_PIX          404      có thật nhưng tài khoản này không có
        IMAGEN_3_5       404      có thật nhưng tài khoản này không có
        NANO_BANANA_PRO  400      INVALID_ARGUMENT — KHÔNG phải hằng số có thật
        IMAGEN_4         400      INVALID_ARGUMENT — KHÔNG phải hằng số có thật
        GEM_PIX_3        400      INVALID_ARGUMENT — chưa tồn tại

KHỚP VỚI QUẢN LÝ MODEL — RỒI, từ 09/08/2026. Bảng ánh xạ hiện tại, đã đo:

        flow/banana-pro     → GEM_PIX_2
        flow/auto           → GEM_PIX_2
        flow/banana-2       → NARWHAL
        flow/banana-2-lite  → HARBOR_SEAL

`flow/imagen-4` đã bỏ khỏi Quản lý Model. `NANO_BANANA_PRO` — tên mà
`flow/banana-pro` trỏ vào suốt thời gian trước — hoá ra chưa bao giờ là hằng số
có thật; đường DOM che mất vì nó chỉ dùng chuỗi đó làm khoá tra NHÃN dropdown
chứ không gửi xuống API. `kiem_model_anh()` chặn tại chỗ kèm thông báo nêu tên
đúng, phòng cấu hình cũ còn sót.

ĐƯỜNG VIDEO — đo 09/08/2026, ba trong bốn endpoint đạt ngay, một sai:

  * `batchAsyncGenerateVideoText`, `…StartImage`, `…ReferenceImages` đều đạt.
  * `…StartAndEndImage` đòi CẢ HAI ảnh. Thiếu `endImage` là 400 "Request
    contains an invalid argument" — không nói thiếu trường nào.
    `cropCoordinates` thì tuỳ chọn: có hay không, số nguyên hay số thực đều qua.
  * Khoá model hỏng ở đường video trả **404**, không phải 400 như đường ảnh, nên
    rất dễ tưởng là lỗi tài khoản. Đo được: `abra_t2v_5s`, `abra_r2v_5s`,
    `veo_3_1_r2v`, `veo_3_1_r2v_fast` đều 404. Omni Flash chỉ có 4s/6s/8s —
    và 5 giây từng là mặc định khi bên gọi không nêu thời lượng, tức nhánh mặc
    định của Omni Flash trước đây trỏ thẳng vào model không tồn tại.
  * `upload_anh_tham_chieu()` đã chạy thật và trả về mediaId hợp lệ.

NGUỒN THÂN YÊU CẦU. Dựng theo bản gỡ rối của VEO3 AI Studio 1.08 (ứng dụng
Electron gọi cùng API này). Những trường chưa đo được trực tiếp — hằng số tỷ lệ
khung hình — đều ghi rõ là "theo bản gỡ rối, chưa đo".

CHƯA LÀM: nâng ảnh (`flow/upsampleImage`), sửa video (`…EditVideo`), và giọng
đọc trong chế độ thành phần (`referenceAudio`). Thêm sau khi cần, theo đúng
khuôn ở đây.
"""

from __future__ import annotations

import asyncio
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

# Các tên đã đo là KHÔNG tồn tại. Danh sách này chỉ để chặn cái đã biết sai —
# tên lạ vẫn cho đi qua, vì Flow thêm model mới liên tục và chặn cứng sẽ khoá
# mất model mới ngay ngày nó ra.
MODEL_ANH_DA_DO_LA_SAI = {
    "NANO_BANANA_PRO": "400 INVALID_ARGUMENT (đo 09/08/2026), thay bằng GEM_PIX_2",
    "IMAGEN_4": "400 INVALID_ARGUMENT (đo 09/08/2026)",
    "GEM_PIX_3": "400 INVALID_ARGUMENT (đo 09/08/2026), chưa tồn tại",
}
# Thứ tự có nghĩa: phần tử đầu là model mạnh nhất, dùng khi bên gọi không nêu tên.
MODEL_ANH_DA_DO_LA_DUNG = ("GEM_PIX_2", "NARWHAL", "HARBOR_SEAL")

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
TY_LE_VIDEO = {
    "16:9": "VIDEO_ASPECT_RATIO_LANDSCAPE",
    "9:16": "VIDEO_ASPECT_RATIO_PORTRAIT",
}

# Bốn chế độ video và endpoint tương ứng.
CHE_DO_VIDEO = {
    "text_to_video": "batchAsyncGenerateVideoText",
    "image_start": "batchAsyncGenerateVideoStartImage",
    "image_start_end": "batchAsyncGenerateVideoStartAndEndImage",
    "component": "batchAsyncGenerateVideoReferenceImages",
}

# Khoá model video theo nhãn trên giao diện. ĐO THẲNG VÀO API 09/08/2026 trên
# endpoint `v1/video:batchAsyncGenerateVideoText`. Lưu ý khác biệt với đường
# ảnh: khoá video không dùng được trả 404 "Requested entity was not found",
# KHÔNG phải 400 — nên không phân biệt được "không tồn tại" với "tài khoản
# không có". Với ta thì hai cái đó như nhau: gửi lên là hỏng.
#
# Đạt (403, tức qua kiểm tham số):
#   veo_3_1_t2v, veo_3_1_t2v_fast, veo_3_1_t2v_lite, veo_3_1_t2v_lite_low_priority
#   veo_3_1_i2v_lite_low_priority, veo_3_1_interpolation_lite_low_priority
#   veo_3_1_r2v_lite, veo_3_1_r2v_lite_low_priority
#   abra_t2v_4s, abra_t2v_6s, abra_t2v_8s, abra_r2v_8s
#
# Trả 404 (KHÔNG dùng được): abra_t2v_5s, abra_r2v_5s, veo_3_1_r2v,
# veo_3_1_r2v_fast
MODEL_VIDEO_T2V = {
    "Omni Flash": "abra_t2v_{giay}s",
    "Veo 3.1 - Lite": "veo_3_1_t2v_lite",
    "Veo 3.1 - Fast": "veo_3_1_t2v_fast",
    "Veo 3.1 - Quality": "veo_3_1_t2v",
    "Veo 3.1 - Lite [Lower Priority]": "veo_3_1_t2v_lite_low_priority",
}
# Chế độ "thành phần" nghèo model hơn hẳn: bản Fast và Quality của r2v đều trả
# 404. Giữ nguyên ánh xạ để `chon_model_video` báo lỗi nêu đúng tên thay vì lặng
# lẽ hạ xuống Lite — người dùng chọn Quality mà nhận Lite là đúng kiểu hỏng đã
# gây sự cố 08/08/2026, chỉ khác chiều.
MODEL_VIDEO_R2V = {
    "Omni Flash": "abra_r2v_{giay}s",
    "Veo 3.1 - Lite": "veo_3_1_r2v_lite",
    "Veo 3.1 - Fast": "veo_3_1_r2v_fast",
    "Veo 3.1 - Quality": "veo_3_1_r2v",
    "Veo 3.1 - Lite [Lower Priority]": "veo_3_1_r2v_lite_low_priority",
}

# Khoá đã đo là gửi lên sẽ 404. Chặn tại chỗ kèm tên thay thế, vì thông báo gốc
# của Google ("Requested entity was not found") không nói model nào sai.
MODEL_VIDEO_DA_DO_LA_KHONG_CO = {
    "abra_t2v_5s": "Omni Flash chỉ có 4s, 6s, 8s — không có 5s",
    "abra_r2v_5s": "Omni Flash chỉ có 4s, 6s, 8s — không có 5s",
    "veo_3_1_r2v": "chế độ thành phần không có bản Quality; dùng Lite",
    "veo_3_1_r2v_fast": "chế độ thành phần không có bản Fast; dùng Lite",
}
# Thời lượng Omni Flash có thật. 5 giây KHÔNG có, mà 5 lại từng là giá trị mặc
# định khi bên gọi không nêu thời lượng — tức nhánh mặc định của Omni Flash
# trước đây trỏ thẳng vào một model không tồn tại.
GIAY_OMNI_FLASH = (4, 6, 8, 10)
GIAY_OMNI_FLASH_MAC_DINH = 8

# Đường VIDEO có gửi `userPaygateTier`, và giá trị đúng là ONE — đọc được từ
# telemetry thật của giao diện Flow 09/08/2026:
#     MEDIA_GENERATION_PAYGATE_TIER = "PAYGATE_TIER_ONE"
#     MEDIA_GENERATION_SETTINGS = {"modelKey":"abra_t2v_10s", ...}
# Bản gỡ rối VEO3 AI Studio ghi TIER_TWO và ta bê nguyên sang: 403 "The caller
# does not have permission". Bỏ hẳn trường cũng 403. Đường ẢNH thì ngược lại —
# bản chụp request thật cho thấy ảnh KHÔNG gửi trường này.
TIER_VIDEO = "PAYGATE_TIER_ONE"
MODEL_VIDEO_MAC_DINH = {
    "text_to_video": "veo_3_1_t2v_lite_low_priority",
    "component": "veo_3_1_r2v_lite_low_priority",
    "image_start": "veo_3_1_i2v_lite_low_priority",
    "image_start_end": "veo_3_1_interpolation_lite_low_priority",
}

# Toạ độ cắt phủ trọn khung — app gửi đúng giá trị này cho ảnh đầu/cuối.
_CAT_TRON_KHUNG = {"top": 0, "left": 0, "bottom": 1, "right": 1}


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


def _ngu_canh(project_id: str, session_id: str,
              recaptcha: str | None, tier: str | None = None) -> dict[str, Any]:
    """`clientContext` — dựng theo BẢN CHỤP REQUEST THẬT của giao diện Flow
    (09/08/2026), không phải theo bản gỡ rối nữa.

    Client thật gửi ĐÚNG bốn trường: projectId, tool, sessionId, recaptchaContext.
    KHÔNG có `userPaygateTier`. Bản gỡ rối VEO3 AI Studio có trường đó
    (PAYGATE_TIER_ONE cho ảnh, TIER_TWO cho video) và ta bê nguyên sang — đường
    ảnh may mắn được Google bỏ qua, còn đường video trả thẳng 403 "The caller
    does not have permission". Khai một bậc trả phí mà tài khoản không có thì bị
    từ chối, hợp lý.

    `sessionId` có dấu chấm phẩy đứng trước, kể cả ở đường ảnh — bản chụp cho
    thấy ";1786253707634". Trước đây ta gửi ảnh không có dấu này.
    """
    ctx: dict[str, Any] = {
        "projectId": project_id,
        "tool": TOOL,
        "sessionId": session_id,
    }
    if tier:
        ctx["userPaygateTier"] = tier
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
    sid = session_id or (";" + str(int(time.time() * 1000)))
    ctx = _ngu_canh(project_id, sid, recaptcha)
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


def tach_prompt_theo_anh(prompt: str, anh: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chế độ "thành phần": cắt prompt thành các mảnh text xen ảnh tham chiếu.

    Tên file (bỏ đuôi) chính là từ khoá tìm trong prompt. Ảnh nào tên không xuất
    hiện trong prompt thì KHÔNG có mảnh `reference` nào trỏ tới — nó chỉ nằm ở
    `referenceImages`. Đây là hành vi của app, và cũng là chỗ người dùng hay
    hiểu nhầm: đặt tên file không khớp prompt thì ảnh gần như không tác dụng.

    Mỗi `mediaId` chỉ được nhắc một lần dù tên xuất hiện nhiều lần.
    """
    moc: list[dict[str, str]] = []
    for a in anh:
        ten_tep = str(a.get("name") or a.get("fileName") or "")
        tu_khoa = re.sub(r"\.[^/.]+$", "", ten_tep)
        if tu_khoa and a.get("mediaId"):
            moc.append({"token": tu_khoa, "handle": ten_tep, "mediaId": str(a["mediaId"])})
    if not moc:
        return [{"text": prompt}]

    # Tên dài trước, để "Lan Anh" không bị "Lan" cắt mất.
    moc.sort(key=lambda m: len(m["token"]), reverse=True)
    mau = re.compile(r"\b(" + "|".join(re.escape(m["token"]) for m in moc) + r")\b",
                     re.IGNORECASE)

    phan: list[dict[str, Any]] = []
    da_dung: set[str] = set()
    vi_tri = 0
    for khop in mau.finditer(prompt):
        m = next((x for x in moc if x["token"].lower() == khop.group(1).lower()), None)
        if m is None or m["mediaId"] in da_dung:
            continue
        if khop.start() > vi_tri:
            phan.append({"text": prompt[vi_tri:khop.start()]})
        phan.append({"reference": {"media": {"handle": m["handle"],
                                             "mediaId": m["mediaId"]}}})
        da_dung.add(m["mediaId"])
        vi_tri = khop.end()
    if vi_tri < len(prompt):
        phan.append({"text": prompt[vi_tri:]})
    return phan or [{"text": prompt}]


def chon_model_video(che_do: str, nhan: str | None, duration: str | None) -> str:
    """Khoá model theo chế độ + nhãn giao diện.

    Hai chế độ khung hình bỏ qua nhãn: app gán cứng biến thể Lite ưu tiên thấp,
    nên chọn "Veo 3.1 - Quality" ở đó cũng không đổi được gì. Giữ nguyên hành vi
    vì đo cho thấy đúng hai khoá đó là dùng được.

    Ném `ValueError` khi khoá tính ra nằm trong nhóm đã đo là 404. Thà hỏng ngay
    ở đây với thông báo nêu tên thay thế, còn hơn để Google trả "Requested entity
    was not found" — câu đó không nói model nào sai, và ở đường video thì khoá
    hỏng trả 404 chứ không phải 400 nên càng dễ tưởng là lỗi tài khoản.
    """
    if che_do in ("image_start", "image_start_end"):
        return MODEL_VIDEO_MAC_DINH[che_do]
    bang = MODEL_VIDEO_R2V if che_do == "component" else MODEL_VIDEO_T2V
    khoa = bang.get(nhan or "", MODEL_VIDEO_MAC_DINH.get(che_do, ""))
    if "{giay}" in khoa:
        so = re.sub(r"[^0-9]", "", str(duration or ""))
        giay = int(so) if so else GIAY_OMNI_FLASH_MAC_DINH
        if giay not in GIAY_OMNI_FLASH:
            raise ValueError(
                f"Omni Flash không có bản {giay} giây. Thời lượng có thật: "
                f"{', '.join(f'{g}s' for g in GIAY_OMNI_FLASH)}."
            )
        khoa = khoa.format(giay=giay)
    if khoa in MODEL_VIDEO_DA_DO_LA_KHONG_CO:
        con_dung = sorted(v for v in bang.values()
                          if "{giay}" not in v and v not in MODEL_VIDEO_DA_DO_LA_KHONG_CO)
        raise ValueError(
            f"'{khoa}' không dùng được ({MODEL_VIDEO_DA_DO_LA_KHONG_CO[khoa]}). "
            f"Khoá còn dùng được cho chế độ {che_do}: {', '.join(con_dung)}."
        )
    return khoa


def than_tao_video(
    *,
    project_id: str,
    prompt: str,
    che_do: str = "text_to_video",
    model_key: str,
    aspect_ratio: str = "16:9",
    count: int = 1,
    anh: list[dict[str, Any]] | None = None,
    recaptcha: str | None = None,
    session_id: str | None = None,
    batch_id: str | None = None,
    seeds: list[int] | None = None,
    tier: str = TIER_VIDEO,
) -> dict[str, Any]:
    """Thân cho `v1/video:batchAsyncGenerateVideo*`. Xem `CHE_DO_VIDEO` để biết
    chế độ nào đi tới endpoint nào."""
    if che_do not in CHE_DO_VIDEO:
        raise ValueError(f"chế độ video lạ: {che_do!r}; "
                         f"chỉ có {', '.join(CHE_DO_VIDEO)}")
    anh = anh or []
    # ĐO 09/08/2026: endpoint …StartAndEndImage đòi CẢ HAI ảnh. Thiếu `endImage`
    # thì trả 400 "Request contains an invalid argument" — không nói thiếu
    # trường nào. (`cropCoordinates` thì tuỳ chọn: có hay không, số nguyên hay
    # số thực, đều qua.) Ba chế độ còn lại có ảnh cũng phải có ít nhất một, nếu
    # không thân yêu cầu thiếu hẳn trường ảnh và Google trả đúng 400 đó.
    can_it_nhat = {"image_start": 1, "image_start_end": 2, "component": 1}.get(che_do, 0)
    if len(anh) < can_it_nhat:
        raise ValueError(
            f"chế độ {che_do} cần {can_it_nhat} ảnh, mới nhận được {len(anh)}. "
            f"{'Ảnh đầu và ảnh cuối đều bắt buộc.' if che_do == 'image_start_end' else ''}"
        )
    sid = session_id or (";" + str(int(time.time() * 1000)))
    ctx = _ngu_canh(project_id, sid, recaptcha, tier)

    goc: dict[str, Any] = {
        "aspectRatio": TY_LE_VIDEO.get(aspect_ratio, "VIDEO_ASPECT_RATIO_LANDSCAPE"),
        "videoModelKey": model_key,
        "metadata": {},
    }
    if che_do == "component":
        goc["textInput"] = {"structuredPrompt": {"parts": tach_prompt_theo_anh(prompt, anh)}}
        goc["referenceImages"] = [
            {"mediaId": a["mediaId"], "imageUsageType": "IMAGE_USAGE_TYPE_ASSET"}
            for a in anh if a.get("mediaId")
        ]
    else:
        goc["textInput"] = {"structuredPrompt": {"parts": [{"text": prompt}]}}
        if che_do == "image_start":
            goc["startImage"] = {"mediaId": anh[0]["mediaId"]}
        elif che_do == "image_start_end":
            # Số lượng ảnh đã được chốt ở đầu hàm nên khỏi phải thử lại ở đây.
            # `cropCoordinates` là tuỳ chọn (đo 09/08) — giữ lại vì app gốc gửi,
            # và nó nói rõ ý định "dùng trọn khung, không cắt".
            goc["startImage"] = {"mediaId": anh[0]["mediaId"],
                                 "cropCoordinates": dict(_CAT_TRON_KHUNG)}
            goc["endImage"] = {"mediaId": anh[1]["mediaId"],
                               "cropCoordinates": dict(_CAT_TRON_KHUNG)}

    so = max(1, int(count))
    hat = seeds or [random.randint(0, 99998) for _ in range(so)]
    return {
        "mediaGenerationContext": {
            "batchId": batch_id or str(uuid.uuid4()),
            "audioFailurePreference": "RETURN_SILENCED_VIDEOS",
        },
        "clientContext": dict(ctx),
        "requests": [{**goc, "seed": hat[i % len(hat)]} for i in range(so)],
        "useV2ModelConfig": True,
    }


def doc_gen_ids(dap: dict[str, Any]) -> list[str]:
    """Lấy ID theo dõi từ đáp của lệnh tạo video.

    App ưu tiên `metadata.primaryMediaId`, lùi về `name`. Giữ thứ tự và bỏ trùng.
    """
    ra: list[str] = []
    for wf in (dap.get("workflows") or []):
        ma = ((wf.get("metadata") or {}).get("primaryMediaId")) or wf.get("name")
        if ma and ma not in ra:
            ra.append(str(ma))
    return ra


def doc_link_anh(dap: dict[str, Any]) -> list[str]:
    """Link ảnh nằm ở `media[].image.generatedImage.fifeUrl`.

    Bản chụp request thật 09/08/2026 cho thấy đáp của lệnh tạo ĐÃ kèm link, nên
    không phải đi đổi id lấy link nữa. Trước đây ta tưởng không có, vì dò regex
    trên `str(dap)` — mà `str()` của dict Python dùng NHÁY ĐƠN, còn regex thì
    tìm nháy kép, nên không bao giờ khớp. Đọc theo cấu trúc thay vì dò chuỗi.

    Link đã ký (`Expires` + `Signature`) và CDN trả `access-control-allow-origin: *`
    nên tải được bằng HTTP thường, không cần cookie hay bearer.
    """
    ra: list[str] = []
    for m in (dap.get("media") or []):
        u = ((m.get("image") or {}).get("generatedImage") or {}).get("fifeUrl")
        if u and u not in ra:
            ra.append(str(u))
    return ra


def gom_ket_qua(trang_thai: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Gộp bảng tiến độ thành (danh sách item xong, danh sách lý do hỏng).

    Hình dạng item phải là `{"url": ...}` vì `api/veo_video.py` đọc thẳng
    `data[0]["url"]` và `_luu_thu_vien()` cũng dựa vào đó để tải video về thư
    viện. Đổi tên trường ở đây là làm hỏng cả hai chỗ mà không ai báo.
    """
    xong: list[dict[str, Any]] = []
    hong: list[str] = []
    for gen_id, tt in trang_thai.items():
        if tt.get("status") == "COMPLETED" and tt.get("url"):
            xong.append({"url": tt["url"], "id": gen_id})
        elif tt.get("status") == "FAILED":
            hong.append(f"{gen_id}: {tt.get('reason') or 'không rõ lý do'}")
    return xong, hong


def con_dang_chay(trang_thai: dict[str, dict[str, Any]]) -> bool:
    """Còn ID nào chưa ngã ngũ không (chưa COMPLETED và chưa FAILED)."""
    return any(tt.get("status") not in ("COMPLETED", "FAILED")
               for tt in trang_thai.values())


def doc_trang_thai(dap: dict[str, Any], gen_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Chuẩn hoá đáp của lệnh tra tiến độ thành {gen_id: {status, url, reason}}."""
    ra = {g: {"status": "PROCESSING", "url": None, "reason": None} for g in gen_ids}
    for m in (dap.get("media") or []):
        ten = m.get("name")
        if not ten or ten not in ra:
            continue
        tt = ((m.get("mediaMetadata") or {}).get("mediaStatus") or {})
        trang_thai = str(tt.get("mediaGenerationStatus") or "")
        if "SUCCESSFUL" in trang_thai or "COMPLETED" in trang_thai:
            ra[ten] = {"status": "COMPLETED", "url": m.get("videoUrl"), "reason": None}
        elif "FAILED" in trang_thai:
            ra[ten] = {
                "status": "FAILED",
                "url": None,
                "reason": tt.get("failureReason") or tt.get("errorMessage")
                or "Google báo thất bại, không nêu lý do",
            }
    return ra


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


_JS_LINK_MEDIA = """
async (ten_media) => {
  const ra = {};
  for (const ten of ten_media) {
    try {
      const r = await fetch(
        'https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name=' +
        encodeURIComponent(ten));
      ra[ten] = r.ok ? r.url : null;
    } catch (e) { ra[ten] = null; }
  }
  return ra;
}
"""


async def lay_link_media(profile: str, ten_media: list[str],
                         headless: bool = True) -> dict[str, str]:
    """`mediaId` → link CDN đã ký. Cần trình duyệt vì trpc dựa vào cookie.

    Đáp của lệnh tạo ảnh chỉ có `mediaId`, KHÔNG có link (đo 09/08/2026 trên
    lượt tạo thật đầu tiên). Link lấy qua `media.getMediaUrlRedirect` — đúng
    endpoint mà ứng dụng gốc dùng cho video, hoá ra dùng được cho cả ảnh: nó
    chuyển hướng sang `https://flow-content.google/image/<id>?Expires=…&
    Signature=…` và thân là JPEG thật.

    Link đã ký nên tải được từ bất kỳ đâu, không cần cookie — bên gọi cứ HTTP
    thường mà lấy. Chỉ riêng bước ĐỔI id lấy link là cần phiên đăng nhập.

    Gom cả danh sách vào MỘT lượt mở trang: mở trình duyệt là phần đắt nhất,
    còn mỗi lượt fetch bên trong chỉ vài chục mili giây.
    """
    if not ten_media:
        return {}
    from ..browser_pool import pool
    async with pool.page(profile=profile, headless=headless) as page:
        if "labs.google" not in (page.url or ""):
            await page.goto("https://labs.google/fx/tools/flow",
                            wait_until="domcontentloaded", timeout=30_000)
        ra = await page.evaluate(_JS_LINK_MEDIA, list(ten_media))
    return {k: v for k, v in (ra or {}).items() if v}


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
    if not ten:
        raise LoiFlowRest(502, f"đáp không có media: {str(dap)[:300]}")

    # Đáp của lệnh tạo KHÔNG kèm link (đo trên lượt tạo thật đầu tiên
    # 09/08/2026). Vẫn thử moi từ thân phòng khi Flow đổi ý, rồi mới đi đổi id
    # lấy link — một `mediaId` không có link thì bên gọi chẳng làm gì được.
    link = doc_link_anh(dap)
    if not link:
        # Đáp thiếu link thì mới phải mở trình duyệt đổi id — tốn thêm vài giây
        # nên chỉ dùng làm đường lui.
        bang = await lay_link_media(profile, ten, headless)
        link = [bang[t] for t in ten if bang.get(t)]
    return {
        "media_ids": ten,
        "urls": link,
        "model": ten_model,
        "project_id": project_id,
        "elapsed_ms": int((time.time() - bat_dau) * 1000),
    }


async def tao_video(*, profile: str, project_id: str, prompt: str,
                    che_do: str = "text_to_video", model_label: str | None = None,
                    model_key: str | None = None, aspect_ratio: str = "16:9",
                    duration: str | None = None, count: int = 1,
                    anh: list[dict[str, Any]] | None = None,
                    headless: bool = True, timeout: float = 180,
                    cho_xong: bool = False, cho_toi_da: float = 600,
                    nhip: float = 5,
                    tier: str = TIER_VIDEO) -> dict[str, Any]:
    """Gửi lệnh tạo video. Mặc định trả ngay `gen_ids`, KHÔNG chờ video xong.

    Đường DOM hiện tại giữ một request HTTP mở suốt 300 giây và đã đo được là
    chết đúng mốc đó với thông báo rỗng. Ở đây lệnh gửi xong là trả (1-2 giây),
    hợp với hàng đợi tác vụ sẵn có.

    `cho_xong=True` thì hàm tự tra tiến độ mỗi `nhip` giây cho tới khi xong hoặc
    quá `cho_toi_da`, rồi trả thêm khoá `data` đúng hình dạng mà
    `api/veo_video.py` đang đợi. Chỉ bật khi bên gọi thật sự không có hàng đợi —
    bật mặc định là dựng lại đúng cái bẫy 300 giây vừa bỏ đi.

    `anh` là danh sách {name, mediaId} — dùng `upload_anh_tham_chieu` để lấy
    `mediaId` trước. Với chế độ "component", `name` phải là tên file vì nó chính
    là từ khoá tìm trong prompt.
    """
    bat_dau = time.time()
    khoa = model_key or chon_model_video(che_do, model_label, duration)
    bearer = await lay_bearer(profile, headless)
    # Đúc reCAPTCHA ngay trước khi gửi — ảnh tham chiếu (nếu có) đã được bên gọi
    # đẩy lên từ trước nên không còn gì chen vào giữa.
    recaptcha = await _lay_recaptcha(profile, headless, "VIDEO_GENERATION")
    dap = await _post(
        f"{API_HOST}/v1/video:{CHE_DO_VIDEO[che_do]}",
        bearer,
        than_tao_video(project_id=project_id, prompt=prompt, che_do=che_do,
                       model_key=khoa, aspect_ratio=aspect_ratio, count=count,
                       anh=anh, recaptcha=recaptcha, tier=tier),
        timeout,
    )
    gen_ids = doc_gen_ids(dap)
    if not gen_ids:
        raise LoiFlowRest(502, f"đáp không có Generation ID: {str(dap)[:300]}")
    ket: dict[str, Any] = {
        "gen_ids": gen_ids,
        "project_id": project_id,
        "video_model_key": khoa,
        "che_do": che_do,
        "elapsed_ms": int((time.time() - bat_dau) * 1000),
    }
    if not cho_xong:
        return ket

    han = time.time() + cho_toi_da
    trang_thai: dict[str, dict[str, Any]] = {}
    while time.time() < han:
        await asyncio.sleep(nhip)
        trang_thai = await trang_thai_video(profile=profile, project_id=project_id,
                                            gen_ids=gen_ids, headless=headless)
        if not con_dang_chay(trang_thai):
            break
    xong, hong = gom_ket_qua(trang_thai)
    ket["data"] = xong
    ket["elapsed_ms"] = int((time.time() - bat_dau) * 1000)
    if hong:
        ket["that_bai"] = hong
    if not xong:
        # Không có video nào ra thì đây là hỏng thật — phải ném, nếu không bên
        # gọi nhận `data: []` rồi coi như thành công và ghi một mục rỗng vào
        # thư viện.
        if hong:
            raise LoiFlowRest(502, "Google báo thất bại: " + "; ".join(hong))
        raise LoiFlowRest(504, f"hết {int(cho_toi_da)}s chờ Google dựng video "
                               f"(gen_ids={', '.join(gen_ids)})")
    return ket


async def trang_thai_video(*, profile: str, project_id: str, gen_ids: list[str],
                           headless: bool = True, timeout: float = 60) -> dict[str, Any]:
    """Tra tiến độ. Dùng token đã cache nên thường KHÔNG mở trình duyệt.

    Lệnh này không cần reCAPTCHA (chỉ đọc), nên chừng nào token còn hạn thì cả
    vòng chờ chạy hoàn toàn bằng HTTP.
    """
    bearer = await lay_bearer(profile, headless)
    dap = await _post(f"{API_HOST}/v1/video:batchCheckAsyncVideoGenerationStatus",
                      bearer,
                      {"media": [{"name": g, "projectId": project_id} for g in gen_ids]},
                      timeout)
    return doc_trang_thai(dap, gen_ids)

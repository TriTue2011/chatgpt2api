"""Ảnh Flow trên flow.google.com (Angular), dùng cookie thay cho OAuth cũ.

Hợp đồng đo 07/09/2026 từ request thật và client wO1vlb:
ogiZ0b = FlowService.BatchGenerateImages, maseQ = FlowService.UploadImage.
Mảng JSON là protobuf: chỉ số Python = số trường protobuf - 1.
"""
from __future__ import annotations

import base64
import json
import random
import time
import uuid
from urllib.parse import quote, urlsplit

from .flow_rest import LoiFlowRest, TY_LE_ANH, kiem_model_anh


# Client _.nTa: LANDSCAPE=3, LANDSCAPE_4_3=5, SQUARE=1,
# PORTRAIT_3_4=4, PORTRAIT=2. Không suy enum theo thứ tự dropdown.
ASPECTS = {"16:9": 3, "4:3": 5, "1:1": 1, "3:4": 4, "9:16": 2}
ASPECTS.update({TY_LE_ANH[label]: value for label, value in list(ASPECTS.items())})

READY = """() => location.hostname === 'accounts.google.com' ||
    location.pathname === '/about' ||
    (!!window.grecaptcha?.enterprise?.execute && !!window.WIZ_global_data?.SNlM0e)"""

POST_RPC = """async ({rpc, body, timeout}) => {
    const at = window.WIZ_global_data?.SNlM0e;
    if (!at) return {status: 401, text: ''};
    const form = new URLSearchParams({at,
        'f.req': JSON.stringify([[[rpc, JSON.stringify(body), null, 'generic']]])});
    const query = new URLSearchParams({rpcids: rpc, 'source-path': location.pathname, rt: 'c'});
    const response = await fetch('/_/AiSandboxAngularFrontend/data/batchexecute?' + query, {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'},
        body: form, signal: AbortSignal.timeout(timeout),
    });
    if (new URL(response.url).hostname !== location.hostname)
        return {status: 401, text: ''};
    return {status: response.status, text: await response.text()};
}"""


def context(project_id: str, recaptcha: str) -> list:
    # clientContext.tool=22 (PINHOLE), projectId=6, recaptchaContext=11.
    return [None, 22, None, None, None, project_id, None, None, None, None, [recaptcha, 1]]


def image_body(project_id: str, prompt: str, model: str, aspect_ratio: str,
               count: int, recaptcha: str, media_ids: list[str]) -> list:
    model = kiem_model_anh(model)
    if aspect_ratio not in ASPECTS:
        raise ValueError(f"Tỷ lệ ảnh Flow không hợp lệ: {aspect_ratio}")
    ctx = context(project_id, recaptcha)
    requests = []
    for _ in range(max(1, min(4, count))):
        # imageInputs=3: name=1, imageInputType=5 (REFERENCE=1).
        requests.append([
            None, None, [[name, None, None, None, 1] for name in media_ids] or None,
            random.randint(0, 2**31 - 1), ASPECTS[aspect_ratio], model, None,
            ctx, [[[prompt]]], None, None, None, str(uuid.uuid4()), str(uuid.uuid4()),
        ])
    return [None, requests, 1, ctx, [str(uuid.uuid4())]]


def upload_body(project_id: str, raw: bytes, recaptcha: str) -> list:
    import io
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as image:
        mime = Image.MIME.get(image.format)
    if not mime:
        raise ValueError("Không xác định được định dạng ảnh tham chiếu")
    return [context(project_id, recaptcha), base64.b64encode(raw).decode("ascii"),
            mime, True, None, None, None, False]


def rpc_result(text: str, rpc: str) -> list:
    # XSSI + từng khối [độ dài, JSON]; JSON nằm trên một dòng, không cắt theo
    # số ký tự vì độ dài trên dây tính byte UTF-8.
    for line in text.splitlines():
        if not line.startswith("[["):
            continue
        try:
            rows = json.loads(line)
        except ValueError:
            continue
        for row in rows:
            if not isinstance(row, list) or len(row) < 3 or row[1] != rpc:
                continue
            if row[0] == "wrb.fr" and isinstance(row[2], str):
                try:
                    result = json.loads(row[2])
                except ValueError:
                    break
                if isinstance(result, list):
                    return result
            code = row[2] if row[0] == "er" else None
            if len(row) > 5 and isinstance(row[5], list) and row[5]:
                code = row[5][0]
            if not isinstance(code, int):
                code = None
            status = {3: 400, 7: 403, 8: 429, 16: 401}.get(code, 502)
            raise LoiFlowRest(status, f"Flow RPC {rpc}: HTTP {status} (mã {code})")
    raise LoiFlowRest(502, f"Flow RPC {rpc} không trả kết quả hợp lệ")


async def post_rpc(page, rpc: str, body: list, timeout: float) -> list:
    result = await page.evaluate(POST_RPC, {
        "rpc": rpc, "body": body, "timeout": int(timeout * 1000),
    })
    status = result.get("status", 502)
    if status != 200:
        # Không đưa HTML/CSRF/cookie trong phản hồi vào nhật ký.
        raise LoiFlowRest(status, f"Flow RPC {rpc}: HTTP {status}")
    return rpc_result(result.get("text", ""), rpc)


async def open_project(page, project_id: str, profile: str) -> None:
    url = f"https://flow.google.com/project/{quote(project_id, safe='')}"
    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    await page.wait_for_function(READY, timeout=30_000)
    if urlsplit(page.url).path == "/about":
        # Trang marketing cũng xuất hiện khi phiên Google còn sống. Bấm CTA
        # một lần để mở ứng dụng; không bấm lặp ở màn mật khẩu/captcha.
        clicked = await page.evaluate("""() => {
            const button = Array.from(document.querySelectorAll('button')).find(
                b => /Tạo bằng Google Flow|Create with Google Flow/.test(b.innerText));
            if (button) button.click();
            return !!button;
        }""")
        if clicked:
            await page.wait_for_url(lambda u: urlsplit(u).path != "/about", timeout=30_000)
            if urlsplit(page.url).hostname == "flow.google.com":
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_function(READY, timeout=30_000)
    current = urlsplit(page.url)
    if current.hostname != "flow.google.com" or current.path != urlsplit(url).path:
        raise LoiFlowRest(401, f"Phiên Google Flow của {profile} cần đăng nhập lại Google.")


def image_result(result: list) -> tuple[list[str], list[str]]:
    ids, urls = [], []
    try:
        for media in result[0]:
            name, url = media[0], media[6][0][13]
            if not isinstance(name, str) or not isinstance(url, str) or not url.startswith("https://"):
                raise ValueError("missing image")
            ids.append(name)
            urls.append(url)
    except (IndexError, TypeError, ValueError) as exc:
        raise LoiFlowRest(502, "Flow trả kết quả thiếu mã hoặc link ảnh") from exc
    if not urls:
        raise LoiFlowRest(502, "Flow không trả ảnh nào")
    return ids, urls


async def generate_image(*, profile: str, project_id: str, prompt: str, model: str,
                         aspect_ratio: str, count: int, anh_tham_chieu: list[bytes] | None,
                         headless: bool, timeout: float) -> dict:
    from ..browser_pool import pool
    from .flow_google import _get_recaptcha_token

    started = time.monotonic()
    model = kiem_model_anh(model)
    if aspect_ratio not in ASPECTS:
        raise ValueError(f"Tỷ lệ ảnh Flow không hợp lệ: {aspect_ratio}")
    async with pool.page(profile=profile, headless=headless) as page:
        await open_project(page, project_id, profile)
        ids = []
        for raw in anh_tham_chieu or []:
            token, _ = await _get_recaptcha_token(page, action="UPLOAD_IMAGE")
            uploaded = await post_rpc(page, "maseQ", upload_body(project_id, raw, token), timeout)
            try:
                name = uploaded[0][0]
                if not isinstance(name, str) or not name:
                    raise ValueError("missing mediaId")
            except (IndexError, TypeError, ValueError) as exc:
                raise LoiFlowRest(502, "Flow upload không trả mã ảnh tham chiếu") from exc
            ids.append(name)
        # Token tạo ảnh luôn được lấy SAU khi upload hoàn tất.
        token, _ = await _get_recaptcha_token(page, action="IMAGE_GENERATION")
        result = await post_rpc(page, "ogiZ0b", image_body(
            project_id, prompt, model, aspect_ratio, count, token, ids), timeout)
    media_ids, urls = image_result(result)
    return {"media_ids": media_ids, "urls": urls, "model": model, "project_id": project_id,
            "elapsed_ms": int((time.monotonic() - started) * 1000)}

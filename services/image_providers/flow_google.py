"""Google Labs Flow image adapter — proxies to the captcha-solver service.

Đoạn này TỪNG viết rằng không thể gọi thẳng API của Flow bằng HTTP thường, phải
điều khiển giao diện qua trình duyệt. Sai — đo ngày 09-10/08/2026: gọi thẳng
`aisandbox-pa.googleapis.com` chạy tốt, chỉ cần bearer lấy từ phiên đã đăng nhập
cộng một token reCAPTCHA Enterprise (cả hai vẫn lấy qua trình duyệt, nhưng lượt
TẠO ẢNH thì đi bằng HTTP thuần).

Nay adapter gọi đường REST của captcha-solver. Lý do đổi, đều là số đo thật trên
cùng model Nano Banana Pro cùng một tài khoản:

                    xin 16:9        xin 9:16       thời gian
    REST        1376x768  ĐÚNG   768x1376 ĐÚNG      30-33s
    giao diện    720x1280  SAI    720x1280           73-94s

Đường giao diện phải BẤM vào ô chọn khung hình, và cú bấm đó trượt: Flow nhớ lựa
chọn của lượt trước theo từng hồ sơ nên một lượt video dọc để lại 9:16, rồi mọi
lượt ảnh sau đó im lặng ra ảnh dọc. Nó còn lấy ảnh bằng `src` của thẻ <img> đang
hiện trên trang — tức bản đã co để vừa khung xem, mất ~7% mỗi chiều. Đường REST
gửi thẳng hằng số khung hình và tên model nên cả họ lỗi "bấm hụt" không tồn tại,
và link ảnh là link gốc đã ký trên CDN.

Phần xoay tài khoản, thời gian nghỉ sau lỗi, và ghi tài khoản vào nhật ký nằm ở
`build_url`/`build_headers` nên không dính gì tới việc gọi đường nào — đổi đường
không chạm vào chúng.

VIDEO thì CHƯA đổi: đường REST cho video còn trả 403 "The caller does not have
permission" sau khi đã qua cửa reCAPTCHA, chưa lý giải được. Video vẫn đi bằng
giao diện, nơi nó đã dựng ra MP4 thật.

Provider config (config.json):

    "providers": {
        "flow": {
            "enabled": true,
            "captcha_solver_url": "http://127.0.0.1:8010",
            "captcha_solver_api_key": "<bearer key>",
            "accounts": [
                {"profile": "google-fx",   "project_id": "54468d77-...."},
                {"profile": "google-fx-2", "project_id": "8a9bc1de-...."}
            ]
        }
    }

Each account is its own browser profile + Flow project. Adapter rotates
round-robin; on quota/rate errors we mark an account "cooldown" for an
hour and prefer the next one. Add new accounts by sending the captcha-
solver a manual-login session with a new profile name and signing in.

Model aliases (case-insensitive, matches the Flow UI labels). Tên nội bộ ở cột
phải đã được ĐO THẲNG vào API ngày 09/08/2026 — xem chú thích ở `_MODEL_ALIASES`:

    flow/banana-pro     → GEM_PIX_2    (Nano Banana Pro)
    flow/auto           → GEM_PIX_2    (mặc định, model mạnh nhất)
    flow/banana-2       → NARWHAL      (Nano Banana 2)
    flow/banana-2-lite  → HARBOR_SEAL  (Nano Banana 2 Lite)

`flow/imagen-4` đã bỏ: Flow không còn chào model này và tên nội bộ IMAGEN_3_5
trả 404 trên tài khoản đang dùng.

Anything else after `flow/` is forwarded verbatim as the imageModelName,
so future models work without code changes.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from curl_cffi import requests

from services.config import config
from services.image_providers._base import BaseImageAdapter, now_sec
from utils.log import logger


# ĐO THẲNG VÀO API 09/08/2026 (tài khoản google-benbap115). Flow kiểm
# `imageModelName` TRƯỚC cửa reCAPTCHA nên đọc được kết quả từng tên mà không
# tốn tín dụng nào:
#
#     GEM_PIX_2        hợp lệ
#     NARWHAL          hợp lệ
#     HARBOR_SEAL      hợp lệ
#     GEM_PIX          có thật nhưng tài khoản không có (404)
#     IMAGEN_3_5       có thật nhưng tài khoản không có (404)
#     NANO_BANANA_PRO  400 INVALID_ARGUMENT — KHÔNG phải hằng số có thật
#     GEM_PIX_3        400 INVALID_ARGUMENT — chưa tồn tại
#
# `NANO_BANANA_PRO` từng là mặc định của `auto`/`best`/`banana-pro` ở đây suốt
# một thời gian dài mà không ai thấy sai, vì đường DOM chỉ dùng chuỗi này làm
# khoá tra NHÃN dropdown chứ không bao giờ gửi nó xuống API. Đường REST
# (`captcha-solver/src/solvers/flow_rest.py`) gửi thẳng, nên tên sai là 400 ngay.
_MODEL_ALIASES = {
    "banana": "NARWHAL",
    "banana-2": "NARWHAL",
    "narwhal": "NARWHAL",
    "banana-2-lite": "HARBOR_SEAL",
    "harbor-seal": "HARBOR_SEAL",
    # `auto` và chuỗi rỗng rơi về model mạnh nhất để người dùng không cần biết
    # bí danh vẫn có Nano Banana Pro.
    "auto": "GEM_PIX_2",
    "": "GEM_PIX_2",
    "best": "GEM_PIX_2",
    "banana-pro": "GEM_PIX_2",
    "nano-banana-pro": "GEM_PIX_2",
    "gem-pix-2": "GEM_PIX_2",
}

# Model ảnh Flow đã bỏ. Giữ danh sách này để `_resolve_model` nói thẳng "model
# đã bị bỏ" thay vì để tên rơi xuống nhánh "tên lạ" rồi gửi một chuỗi vô nghĩa
# xuống API. Cấu hình đang chạy là dữ liệu chứ không phải mã: gỡ khỏi bảng bí
# danh không gỡ được khỏi Quản lý Model của một hệ thống đang chạy.
_MODEL_ANH_DA_NGHI = {
    "imagen-4": "IMAGEN_3_5 trả 404 khi đo 09/08/2026",
    "imagen4": "IMAGEN_3_5 trả 404 khi đo 09/08/2026",
    "imagen": "IMAGEN_3_5 trả 404 khi đo 09/08/2026",
    "imagen-3-5": "IMAGEN_3_5 trả 404 khi đo 09/08/2026",
    "imagen3_5": "IMAGEN_3_5 trả 404 khi đo 09/08/2026",
}

# All Flow models we expose. Used by list_models() so the chatgpt2api UI
# dropdown shows the same options the Flow website does.
# `internal` PHẢI khớp `_MODEL_ALIASES` ở trên — đó là tên thật gửi xuống bộ lái.
# Trước đây `imagen-4` ghi "IMAGEN_4" ở đây trong khi alias gửi "IMAGEN_3_5"; hai
# bảng nói khác nhau nên bảng nhãn bên bộ lái trông như đã đủ, và một yêu cầu
# tạo ảnh đã lặng lẽ dựng thành video (sự cố 08/08/2026).
# Flow chỉ còn BA model ảnh (09/08/2026). `flow/auto` đứng cuối không phải model
# của Flow — nó là chỗ giữ chỗ do ta tạo ra để xoay model, và `backend_router`
# xử lý nó như placeholder (bỏ qua khi lọc danh sách đã tick). Giữ trong bảng
# này để thông báo lỗi vẫn nêu nó ra như một giá trị hợp lệ để truyền vào.
FLOW_MODELS = [
    {"id": "flow/banana-pro",    "label": "Nano Banana Pro",    "internal": "GEM_PIX_2"},
    {"id": "flow/banana-2",      "label": "Nano Banana 2",      "internal": "NARWHAL"},
    {"id": "flow/banana-2-lite", "label": "Nano Banana 2 Lite", "internal": "HARBOR_SEAL"},
    # Không phải model Flow — xem ghi chú ngay trên.
    {"id": "flow/auto",          "label": "Auto (xoay model)",  "internal": "GEM_PIX_2"},
]

_ASPECT_FROM_SIZE: dict[tuple[int, int], str] = {
    (1024, 1024): "IMAGE_ASPECT_RATIO_SQUARE",
    (1792, 1024): "IMAGE_ASPECT_RATIO_LANDSCAPE",
    (1024, 1792): "IMAGE_ASPECT_RATIO_PORTRAIT",
    (1280, 896):  "IMAGE_ASPECT_RATIO_LANDSCAPE",
    (896, 1280):  "IMAGE_ASPECT_RATIO_PORTRAIT",
}

# Friendly aspect strings ("16:9", "4:3", ...) → Flow API constant.
#
# ĐO THẲNG VÀO API 10/08/2026. Tỷ lệ được kiểm TRƯỚC cửa reCAPTCHA và Google báo
# lỗi kèm TÊN TRƯỜNG ("Invalid value at 'requests[0].image_aspect_ratio'"), nên
# quét được miễn phí:
#
#     SQUARE / LANDSCAPE / PORTRAIT                     hợp lệ
#     LANDSCAPE_FOUR_THREE / PORTRAIT_THREE_FOUR        hợp lệ
#     LANDSCAPE_4_3 / PORTRAIT_3_4                      KHÔNG tồn tại
#
# Hai dạng cuối là thứ bảng này dùng suốt thời gian qua. Đường DOM che mất vì nó
# chỉ dùng chuỗi làm khoá tra NHÃN dropdown, không bao giờ gửi xuống API — y hệt
# cách `NANO_BANANA_PRO` sống sót. Bảng nhãn bên bộ lái đã sửa theo cùng lượt.
_ASPECT_FROM_LABEL: dict[str, str] = {
    "16:9":     "IMAGE_ASPECT_RATIO_LANDSCAPE",
    "4:3":      "IMAGE_ASPECT_RATIO_LANDSCAPE_FOUR_THREE",
    "1:1":      "IMAGE_ASPECT_RATIO_SQUARE",
    "square":   "IMAGE_ASPECT_RATIO_SQUARE",
    "3:4":      "IMAGE_ASPECT_RATIO_PORTRAIT_THREE_FOUR",
    "9:16":     "IMAGE_ASPECT_RATIO_PORTRAIT",
    "portrait": "IMAGE_ASPECT_RATIO_PORTRAIT",
    "landscape": "IMAGE_ASPECT_RATIO_LANDSCAPE",
}

# Đường REST nhận NHÃN ("16:9") rồi tự tra sang hằng số, nên phải đi ngược lại.
# Không đảo `_ASPECT_FROM_LABEL` bằng vòng lặp: nó có bí danh (`portrait`,
# `landscape`, `square`) trỏ trùng hằng số, đảo ra sẽ nhận nhãn nào tuỳ thứ tự
# khoá — đúng loại phụ thuộc ngầm mà đọc mã không thấy.
_ASPECT_LABEL_FROM_CONST: dict[str, str] = {
    "IMAGE_ASPECT_RATIO_LANDSCAPE": "16:9",
    "IMAGE_ASPECT_RATIO_LANDSCAPE_FOUR_THREE": "4:3",
    "IMAGE_ASPECT_RATIO_SQUARE": "1:1",
    "IMAGE_ASPECT_RATIO_PORTRAIT_THREE_FOUR": "3:4",
    "IMAGE_ASPECT_RATIO_PORTRAIT": "9:16",
}


def _resolve_model(model: str) -> str:
    """Map a 'flow/<alias>' model string to the Flow imageModelName.

    Tên lạ vẫn được cho đi qua (viết hoa nguyên văn) để model ảnh mới của Flow
    dùng được ngay mà không cần sửa mã. Nhưng tên model VIDEO thì chặn: Flow đặt
    cả hai loại chung một không gian tên `flow/`, nên một cấu hình lệch có thể
    đẩy `flow/veo-3.1-fast` vào đây, và cho qua sẽ gửi `imageModelName:
    "VEO-3.1-FAST"` — một giá trị Flow không hiểu, hỏng mà không nói vì sao.

    Model ảnh ĐÃ NGHỈ cũng chặn, cùng lý do. Cấu hình đang chạy là dữ liệu, không
    phải mã: gỡ `flow/imagen-4` khỏi bảng bí danh không gỡ nó khỏi Quản lý Model
    của một hệ thống đang chạy. Cho nó rơi xuống nhánh "tên lạ" sẽ gửi
    `imageModelName: "IMAGEN-4"` — một chuỗi vô nghĩa — rồi nhận 400 không nêu
    trường nào sai. Thà nói thẳng là model đã bị Flow bỏ.
    """
    raw = (model or "").strip().lower()
    if raw.startswith("flow/"):
        raw = raw[len("flow/"):]
    if raw in _MODEL_ALIASES:
        return _MODEL_ALIASES[raw]
    if raw in _MODEL_ANH_DA_NGHI:
        raise ValueError(
            f"'flow/{raw}' là model ảnh Flow ĐÃ BỎ ({_MODEL_ANH_DA_NGHI[raw]}). "
            f"Model ảnh còn dùng được: "
            f"{', '.join(sorted(m['id'] for m in FLOW_MODELS))}. Nếu đây là model "
            f"đang chọn trong Quản lý Model thì đổi lại."
        )
    from utils.helper import VIDEO_GEN_MODELS
    if f"flow/{raw}" in VIDEO_GEN_MODELS:
        raise ValueError(
            f"'flow/{raw}' là model TẠO VIDEO, không tạo được ảnh. Model ảnh của "
            f"Flow: {', '.join(sorted(m['id'] for m in FLOW_MODELS))}. Nếu đây là "
            f"model mặc định đang đặt trong Quản lý Model thì đổi lại bằng một "
            f"model ảnh."
        )
    # Default to the strongest model when no alias is given.
    return raw.upper() if raw else "GEM_PIX_2"


def _resolve_aspect(size: str | None) -> str:
    """Convert size string OR aspect label to Flow's IMAGE_ASPECT_RATIO_*.

    Accepts: "16:9", "4:3", "1:1", "3:4", "9:16", "1024x1024" (WxH),
    "landscape" / "portrait" / "square". Default is 16:9 landscape.
    """
    if not size:
        return "IMAGE_ASPECT_RATIO_LANDSCAPE"
    s = str(size).strip().lower()
    if s in _ASPECT_FROM_LABEL:
        return _ASPECT_FROM_LABEL[s]
    if "x" in s:
        try:
            w, h = (int(x) for x in s.split("x"))
            mapped = _ASPECT_FROM_SIZE.get((w, h))
            if mapped:
                return mapped
            if w == h:
                return "IMAGE_ASPECT_RATIO_SQUARE"
            return "IMAGE_ASPECT_RATIO_LANDSCAPE" if w > h else "IMAGE_ASPECT_RATIO_PORTRAIT"
        except (TypeError, ValueError):
            pass
    return "IMAGE_ASPECT_RATIO_LANDSCAPE"


# ── Account pool (in-process state) ───────────────────────────────────────
#
# Selection model: STRICT PRIORITY (Main → Backup → Spare 1 → …).
# Account at index 0 (Main) is always tried first. We only fall through
# to index 1 (Backup) when Main is in cooldown OR was already-tried in
# this request. Same for index 2, 3, etc.
#
# Cooldown auto-resets when the timer expires — the account silently
# re-enters the pool at its priority slot. No manual unlock needed.

_pool_lock = threading.Lock()
# Account state by composite key (profile + project) so we don't collide
# across accounts that happen to share a profile.
_account_state: dict[str, dict[str, float]] = {}

# Default cooldown when no explicit config — 1 hour (Flow Pro quota
# typically resets hourly). Override via providers.flow.cooldown_seconds.
_DEFAULT_COOLDOWN_S = 3600.0


def _account_key(account: dict[str, Any]) -> str:
    return f"{account.get('profile', '')}::{account.get('project_id', '')}"


def _pool_config() -> dict[str, Any]:
    providers = config.data.get("providers") or {}
    cfg = providers.get("flow") or {}
    return cfg if isinstance(cfg, dict) else {}


def _cooldown_seconds() -> float:
    """Cooldown after a 429 / quota error, in seconds.

    Reads providers.flow.cooldown_seconds from the live config so admins
    can tune it per environment via the Settings → Flow card."""
    cfg = _pool_config()
    raw = cfg.get("cooldown_seconds")
    try:
        val = float(raw)
        if val > 0:
            return val
    except (TypeError, ValueError):
        pass
    return _DEFAULT_COOLDOWN_S


def _accounts() -> list[dict[str, Any]]:
    cfg = _pool_config()
    raw = cfg.get("accounts") or []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for a in raw:
        if isinstance(a, dict) and a.get("project_id"):
            out.append({
                "profile": str(a.get("profile") or "google-fx"),
                "project_id": str(a["project_id"]),
                "label": str(a.get("label") or a.get("name") or a.get("profile") or "google-fx"),
            })
    return out


def _next_account(exclude: set[str] | None = None) -> dict[str, Any] | None:
    """Pick the highest-priority healthy account.

    Strict priority: index 0 (Main) is always tried first. We only move
    on to index 1 (Backup) when index 0 is in cooldown OR `exclude` (the
    caller already tried it in this request and got a quota error).
    """
    accounts = _accounts()
    if not accounts:
        return None
    exclude = exclude or set()
    now = time.time()
    with _pool_lock:
        for idx in range(len(accounts)):
            acc = accounts[idx]
            key = _account_key(acc)
            if key in exclude:
                continue
            state = _account_state.get(key, {})
            cooldown_until = state.get("cooldown_until", 0)
            if cooldown_until and now < cooldown_until:
                continue
            return acc
        # All accounts are in cooldown OR excluded — the pool is fully
        # exhausted. Return None so the dispatcher reports a clear
        # error to the caller (rather than silently picking a dead one).
        return None


def _mark_quota_exhausted(account: dict[str, Any]) -> None:
    cooldown_s = _cooldown_seconds()
    with _pool_lock:
        key = _account_key(account)
        _account_state.setdefault(key, {})["cooldown_until"] = time.time() + cooldown_s
    logger.warning({"event": "flow_account_cooldown", "account": account.get("label"),
                    "cooldown_s": cooldown_s})


def _reorder_flow_account(account: dict[str, Any], to_front: bool) -> None:
    """Persistently move a Flow account to the FRONT (healthy) or BACK (dead)
    of config.providers.flow.accounts — same rotation as ChatGPT's
    promote/demote. After the first failure a logged-out account sinks to the
    bottom so subsequent requests stop wasting ~60s hydration-timeout on it;
    a working account rises to #1. No-op if already at the target slot (avoids
    needless config writes / model-cache invalidation)."""
    key = _account_key(account)
    providers = dict(config.data.get("providers") or {})
    flow = dict(providers.get("flow") or {})
    accts = list(flow.get("accounts") or [])
    idx = next((i for i, a in enumerate(accts) if _account_key(a) == key), None)
    if idx is None:
        return
    target = 0 if to_front else len(accts) - 1
    if idx == target:
        return
    item = accts.pop(idx)
    accts.insert(0, item) if to_front else accts.append(item)
    flow["accounts"] = accts
    providers["flow"] = flow
    try:
        config.update({"providers": providers})
        logger.info({"event": "flow_account_reorder", "account": account.get("label"),
                     "to": "front" if to_front else "back"})
    except Exception as exc:
        logger.warning({"event": "flow_account_reorder_failed", "error": str(exc)})


# ── Adapter ──────────────────────────────────────────────────────────────

class FlowImageAdapter(BaseImageAdapter):
    """OpenAI-image-compatible adapter that calls the captcha-solver Flow endpoint."""

    no_auth = False

    def get_key_count(self, credentials: dict[str, Any] | None) -> int:
        """Tell the dispatch layer how many accounts to retry across."""
        return max(1, len(_accounts()))

    # Track which account each request has tried so retries skip dead ones.
    # Keyed by Python object id of the credentials dict (one per request).
    _tried_by_req: dict[int, set[str]] = {}

    def _current_account(
        self,
        key_try: int,
        credentials: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Strict-priority pick. On retry, exclude the account from the
        previous try so the dispatcher actually rotates to the next
        priority slot instead of looping on the same dead Main."""
        req_key = id(credentials) if credentials is not None else 0
        # key_try == 0 marks the start of a new request — reset the
        # excluded set so prior request's exclusions don't leak (id can
        # be reused after the previous credentials dict is GC'd).
        if key_try == 0:
            self._tried_by_req[req_key] = set()
        excluded = self._tried_by_req.setdefault(req_key, set())
        acc = _next_account(exclude=excluded)
        if acc:
            excluded.add(_account_key(acc))
        # Belt-and-braces GC for the pathological case (no key_try=0 ever
        # arrives so the set grows forever).
        if len(excluded) > 16:
            self._tried_by_req.pop(req_key, None)
        return acc

    def build_url(
        self,
        model: str,
        credentials: dict[str, Any] | None,
        key_try: int = 0,
    ) -> str:
        cfg = _pool_config()
        from services.captcha import captcha_base
        base = captcha_base(cfg.get("captcha_solver_url"))  # /api/captcha (proxy) → internal
        if not base:
            raise RuntimeError(
                "flow provider missing captcha_solver_url in config.providers.flow"
            )
        # Stash the chosen account on the credentials dict so build_body
        # can read it without re-rotating. Xoá account của lần thử trước
        # trước: khi mọi account còn lại vừa vào cooldown, giữ lại giá trị cũ
        # sẽ làm retry gửi lại ĐÚNG profile vừa báo quota.
        if credentials is not None:
            credentials.pop("_flow_account", None)
        account = self._current_account(key_try, credentials=credentials)
        if credentials is not None and account is not None:
            credentials["_flow_account"] = account
        return f"{base}/v1/google/flow/rest/generate-image"

    def build_body(self, model: str, body: dict[str, Any]) -> dict[str, Any]:
        """Build the captcha-solver Flow request.

        Accepts standard OpenAI image params (`size`, `n`, `model`) plus
        a few Flow-specific overrides via `extra_body` so HA/n8n callers
        can pick aspect ratio / model / count without learning the Flow
        constants:

            "extra_body": {
                "aspect_ratio": "16:9",       # or "4:3" / "1:1" / "3:4" / "9:16"
                "flow_model":   "banana-pro", # alias from _MODEL_ALIASES
                "count":        1             # 1-4
            }

        Defaults: 16:9 landscape, Nano Banana Pro, 1 image.
        """
        prompt = str(body.get("prompt") or "")
        extra = body.get("extra_body") or {}
        if not isinstance(extra, dict):
            extra = {}

        # Aspect: prefer explicit extra_body.aspect_ratio, else fall back to
        # standard OpenAI `size` (defaults to landscape 16:9).
        aspect_in = extra.get("aspect_ratio") or extra.get("aspect") or body.get("size")
        aspect = _resolve_aspect(str(aspect_in) if aspect_in else None)

        # Model: extra_body.flow_model wins over the top-level model (since
        # callers using OpenAI clients often hard-code model="flow/auto"
        # but still want to override per-call from HA).
        model_in = extra.get("flow_model") or extra.get("model") or model
        flow_model = _resolve_model(str(model_in))

        # Count: extra_body.count or OpenAI `n`, clamped 1-4.
        count_in = extra.get("count") or extra.get("n") or body.get("n") or 1
        try:
            count = max(1, min(4, int(count_in)))
        except (TypeError, ValueError):
            count = 1

        out: dict[str, Any] = {
            "prompt": prompt,
            # REST nhận NHÃN, không nhận hằng số IMAGE_ASPECT_RATIO_*. Gửi sai
            # dạng là Google trả 400 kèm tên trường, không âm thầm ra sai khung.
            "aspect_ratio": _ASPECT_LABEL_FROM_CONST.get(aspect, "16:9"),
            "model": flow_model,
            "count": count,
            # Không còn bước chuẩn bị giao diện nào nên lượt tạo nhanh hơn nhiều
            # (đo 30-33s so với 73-94s của đường cũ); vẫn để rộng vì Nano Banana
            # Pro có lúc chậm.
            "timeout": 280,
            # Trình duyệt chỉ còn dùng để lấy bearer + token reCAPTCHA, không
            # phải để bấm gì, nên không cần hiện màn hình.
            "headless": True,
        }
        # Img2img: REST nhận MẢNG base64 (`images_b64`), khác đường cũ chỉ nhận
        # một tấm — sửa ảnh nhiều tấm nay không bị cắt còn một.
        import base64 as _b64
        from services.image_providers._base import first_image_bytes_mime
        raw, mime = first_image_bytes_mime(body.get("images") or [])
        if raw:
            out["images_b64"] = [_b64.b64encode(bytes(raw)).decode("ascii")]
        return out

    def build_headers(
        self,
        credentials: dict[str, Any] | None,
        request_body: dict[str, Any],
        model: str,
        body: dict[str, Any],
    ) -> dict[str, str]:
        cfg = _pool_config()
        api_key = str(cfg.get("captcha_solver_api_key") or "")
        account = (credentials or {}).get("_flow_account") or _next_account()
        if account:
            request_body["project_id"] = account["project_id"]
            request_body["profile"] = account["profile"]
            logger.info({"event": "flow_account_chosen",
                         "label": account.get("label"),
                         "profile": account["profile"]})
            # Báo lên request_context để Agent runs hiện ĐÚNG tài khoản đã dùng.
            # Trước đây chỉ Gemini web và OpenAI OAuth gọi `note_provider_account`,
            # nên mọi lượt đi qua Flow đều hiện "—" ở cột tài khoản: người vận
            # hành thấy ảnh sinh ra mà không biết tài khoản nào đã sinh, và khi
            # một tài khoản bị chặn thì không lần ra được nó từ lịch sử chạy.
            # `set_dest` cũng nối vào dest_trail, nên nhiều tài khoản trong cùng
            # một lượt (xoay vòng sau lỗi) đều được ghi lại chứ không chỉ cái cuối.
            try:
                from services.request_context import note_provider_account
                note_provider_account(
                    "flow",
                    str(account.get("label") or account["profile"]),
                    model=model,
                    account_id=str(account["profile"]),
                    project_id=str(account.get("project_id") or ""),
                )
            except Exception:
                pass
        else:
            # `_next_account()` trả None trong HAI trường hợp khác nhau hẳn:
            # chưa khai tài khoản nào, HOẶC có tài khoản nhưng đang trong thời
            # gian nghỉ (cooldown 1 giờ sau một lượt thất bại). Đo thật 31/07:
            # tài khoản duy nhất đang cooldown mà lỗi vẫn nói "chưa khai tài
            # khoản" ⇒ người đọc đi thêm tài khoản đã tồn tại. Phân biệt rõ.
            so_tk = len(_accounts())
            if so_tk:
                raise RuntimeError(
                    f"cả {so_tk} tài khoản Google Flow đang trong thời gian nghỉ "
                    f"(cooldown {_cooldown_seconds()}s sau lượt thất bại trước). "
                    "Chờ hết cooldown hoặc thêm tài khoản dự phòng."
                )
            raise RuntimeError(
                "no Google Flow accounts configured. "
                "Add at least one under providers.flow.accounts."
            )
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def parse_response(self, response: Any) -> dict[str, Any] | None:
        """Capture binary image body + quota errors before the generic
        dispatcher takes over (it would treat a 502 as fatal but here a
        quota 502 just means rotate to the next account)."""
        if not hasattr(response, "status_code"):
            return None
        if response.status_code >= 400:
            text = ""
            try:
                text = response.text[:600]
            except Exception:
                pass
            lower = text.lower()
            # Common Flow quota / rate signals.
            if (
                "quota" in lower
                or "rate" in lower
                or "usage_limit" in lower
                or response.status_code == 429
            ):
                # The credentials carry the account we just used.
                account = (
                    (response.request._flow_account if hasattr(response.request, "_flow_account") else None)
                    if hasattr(response, "request") else None
                )
                if account:
                    _mark_quota_exhausted(account)
                raise RuntimeError(f"flow quota/rate: HTTP {response.status_code}: {text[:200]}")
            return None
        # Đường REST luôn trả JSON: {"media_ids": [...], "urls": [...], "model",
        # "project_id", "elapsed_ms"}. Không còn nhánh nhận thẳng byte ảnh — đó
        # là của đường giao diện với cờ `return_binary`.
        try:
            payload = response.json()
        except Exception:
            return None
        urls = [str(u) for u in (payload.get("urls") or []) if u]
        if not urls:
            return {"data": []}
        meta_chung = {
            "model": payload.get("model"),
            "media_ids": payload.get("media_ids"),
            "elapsed_ms": payload.get("elapsed_ms"),
        }
        data: list[dict[str, Any]] = []
        for url in urls:
            try:
                # Link CDN đã ký sẵn (`Expires` + `Signature`) và trả
                # `access-control-allow-origin: *` — tải được bằng HTTP thường,
                # không cần cookie hay bearer. Vẫn đi qua net_guard: URL là dữ
                # liệu từ captcha-solver/upstream, không được phép biến thành
                # fetch loopback hoặc metadata service nếu upstream lỗi/bị giả.
                from services.image_providers._base import url_to_base64
                image_b64 = url_to_base64(url, timeout=60)
                if not image_b64:
                    raise RuntimeError("Flow CDN trả dữ liệu ảnh rỗng")
                data.append({
                    "b64_json": image_b64,
                    "_flow_meta": meta_chung,
                })
            except Exception as exc:
                logger.warning({"event": "flow_download_failed", "url": url[:120], "error": str(exc)})
        return {"data": data}

    def normalize(self, parsed: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
        data = parsed.get("data") or []
        # Ảnh Flow (Imagen/Google Labs) nay cũng mang watermark ngôi sao như
        # Gemini (xác nhận 14/08/2026) — gỡ tại adapter, dò không thấy thì giữ nguyên.
        from services.gemini_watermark import strip_watermark_b64_items
        strip_watermark_b64_items(data, origin="flow")
        return {"created": now_sec(), "data": data}

    # ── Health-based rotation hooks (called by the image dispatcher) ──────
    # Same idea as ChatGPT's promote/demote: a working account floats to #1,
    # a logged-out one sinks to the bottom of the config list so the next
    # request stops burning ~60s on the dead profile first.

    def on_key_success(self, credentials: dict[str, Any] | None) -> None:
        account = (credentials or {}).get("_flow_account")
        if account:
            _reorder_flow_account(account, to_front=True)

    def on_key_failed(self, credentials: dict[str, Any] | None, status: int, text: str) -> None:
        account = (credentials or {}).get("_flow_account")
        if not account:
            return
        low = str(text or "").lower()
        # Cùng tín hiệu quota/rate mà parse_response() dùng — nhưng dispatcher
        # (openai_v1_image_generations) chặn resp.status_code>=400 TRƯỚC khi
        # gọi parse_response, nên nhánh _mark_quota_exhausted() trong đó
        # không bao giờ chạy tới. Đặt cooldown ở đây để tài khoản hết hạn
        # ngạch không bị hot-retry mỗi request (đốt ~60s hydration timeout).
        if status == 429 or "quota" in low or "rate" in low or "usage_limit" in low:
            _mark_quota_exhausted(account)
        # "account nào lỗi bị đẩy xuống cuối" — demote on any account-health
        # failure (logout, browser crash, hydration timeout, 5xx) so a
        # consistently-failing account sinks to the back and the working one
        # (which gets promoted on success) floats to #1. Skip 400 (bad
        # request/argument — not the account's fault) so a malformed call
        # doesn't reshuffle the pool.
        if status == 400:
            return
        _reorder_flow_account(account, to_front=False)
        # Logout / hydration-timeout → tự khôi phục phiên ở nền + báo Telegram
        # (đăng nhập lại Google). Bỏ qua quota (credit/limit) — không phải mất
        # phiên. Debounce 30ph/profile trong hàm recovery.
        looks_logged_out = any(k in low for k in (
            "hydrat", "logged out", "logout", "manual-login", "session",
            "sign in", "signin", "đăng nhập", "401", "403"))
        is_quota = any(k in low for k in ("quota", "credit", "limit", "insufficient"))
        profile = str((account or {}).get("profile") or "").strip()
        if profile and profile.startswith("google-") and looks_logged_out and not is_quota:
            try:
                import threading as _t
                from services.account_recovery import flow_recover_and_notify
                _t.Thread(target=flow_recover_and_notify,
                          args=(profile, str(text)[:60]), daemon=True).start()
            except Exception:
                pass

    def test_connection(self, credentials: dict[str, Any] | None = None) -> bool:
        cfg = _pool_config()
        from services.captcha import captcha_base
        base = captcha_base(cfg.get("captcha_solver_url"))  # /api/captcha (proxy) → internal
        if not base:
            return False
        try:
            r = requests.get(f"{base}/health", timeout=5)
            return r.status_code == 200
        except Exception:
            return False


flow_image_adapter = FlowImageAdapter()

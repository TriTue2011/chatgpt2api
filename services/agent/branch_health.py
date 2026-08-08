"""Kiểm tra sức khoẻ các nhánh Agent — nhánh nào trỏ vào chỗ rỗng.

Vì sao cần: nhánh trỏ sai KHÔNG báo lỗi, nó chỉ lặng lẽ không chạy. Đã dính
hai lần trong thực tế:

  - ``vision`` đặt là ``'AI vision'`` — một cái NHÃN, không phải model id.
    Nằm im hàng tháng; OCR sách giáo khoa không chạy mà không ai biết, vì lỗi
    hiện ra dưới dạng "Gemini connection failed" chứ không phải "model sai".
  - ``code_reviewer`` đặt ``claude/auto``. Tra ``list_accounts()`` thấy 0 tài
    khoản claude → tưởng hỏng, hoá ra Claude Web lưu ở ``providers.claude.
    profiles`` chứ không ở kho tài khoản. Suýt đổi nhầm cấu hình đang chạy tốt.

Bài học thứ hai quan trọng hơn thứ nhất: **thông tin xác thực nằm ở BA nơi
khác nhau tuỳ backend**. Kiểm một nơi rồi kết luận là báo đỏ nhầm:

  1. ``account_service.list_accounts()``  → Codex, Gemini token (OAuth/token)
  2. ``providers.<tên>.profiles``         → Claude Web, Gemini Web (hồ sơ
                                             trình duyệt, tự lấy cookie)
  3. ``providers.<tên>.api_key``          → Serper, Brave, SuperCode (dán tay)

Hàm này KHÔNG gọi model (tốn tiền và chậm) — chỉ đối chiếu cấu hình với danh
sách model thật và nguồn xác thực. Muốn biết chắc chạy được thì vẫn phải gọi
thử một lượt.
"""
from __future__ import annotations

import logging
from typing import Any

from services.agent.branches import BRANCHES, branch_model
from services.config import config

logger = logging.getLogger(__name__)

# Tiền tố model → tên provider trong config. Lấy từ backend_router, nhưng chỉ
# giữ những cái cần cho việc kiểm xác thực.
_PREFIX_PROVIDER: tuple[tuple[str, str], ...] = (
    ("claude/", "claude"),
    ("clf/", "claude"),
    ("cc/", "claude"),
    ("gma/", "gemini_web_api"),
    ("gemini-web/", "gemini_web_api"),
    ("gemini_free/", "gemini_free"),
    ("gemini/", "gemini_free"),
    ("flow/", "flow"),
    ("agnes/", "agnes"),
    ("sc/", "supercode"),
    ("nv/", "nvidia_nim"),
)

# Tiền tố dùng kho tài khoản thay vì providers.*
_PREFIX_ACCOUNT_TYPE: tuple[tuple[str, str], ...] = (
    ("cx/", "codex"),
    ("codex/", "codex"),
    ("oai/", "openai_api"),
)


def _model_ids() -> set[str]:
    """Danh sách model id thật. Rỗng = không tra được (đừng vội báo đỏ)."""
    try:
        import json
        import urllib.request

        base = str(config.get().get("api_base_url", "")).strip().rstrip("/") or \
            "http://127.0.0.1/v1"
        req = urllib.request.Request(
            f"{base}/models",
            headers={"Authorization": f"Bearer {config.auth_key}"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
        return {str(m.get("id") or "") for m in data.get("data") or []}
    except Exception as exc:
        logger.warning("branch_health: không lấy được danh sách model: %s", exc)
        return set()


def _auth_status(model: str) -> tuple[str, str]:
    """(trạng thái, giải thích) về nguồn xác thực cho model này.

    Trả ``("khong_ro", …)`` khi không biết backend nào — KHÔNG đoán là hỏng.
    """
    m = (model or "").strip()
    if not m:
        return ("trong", "nhánh để trống")

    providers = config.data.get("providers") or {}

    for prefix, name in _PREFIX_PROVIDER:
        if m.startswith(prefix):
            cfg = providers.get(name) or {}
            profiles = cfg.get("profiles")
            if isinstance(profiles, list) and profiles:
                return ("ok", f"{len(profiles)} hồ sơ trình duyệt ({name})")
            if str(cfg.get("api_key") or "").strip():
                return ("ok", f"có api_key ({name})")
            if str(cfg.get("session_key") or "").strip():
                return ("ok", f"có session_key ({name})")
            if cfg.get("enabled") is False:
                return ("tat", f"provider {name} đang tắt")
            return ("thieu_xac_thuc", f"provider {name} chưa có hồ sơ/khoá nào")

    for prefix, acc_type in _PREFIX_ACCOUNT_TYPE:
        if m.startswith(prefix):
            try:
                from services.account_service import account_service
                accs = [
                    a for a in account_service.list_accounts()
                    if str(a.get("type") or a.get("account_type") or "") == acc_type
                ]
            except Exception as exc:
                return ("khong_ro", f"không đọc được kho tài khoản: {exc}")
            if accs:
                return ("ok", f"{len(accs)} tài khoản {acc_type}")
            return ("thieu_xac_thuc", f"không có tài khoản {acc_type} nào")

    return ("khong_ro", "chưa biết backend nào giữ xác thực cho tiền tố này")


def _ghim_mot_model(model: str) -> bool:
    """True nếu nhánh trỏ vào MỘT model cụ thể — tức là không có dự phòng.

    Không tính là ghim cứng: rỗng (đã báo riêng), `auto`, `<provider>/auto`, và
    tên COMBO (không có tiền tố backend — combo tự xoay qua nhiều model).

    Có tính: `gma/3.1-pro`, `claude/sonnet-5`, `flow/veo-3.1-fast`, `gma/image`.
    `gma/image` là chọn năng lực chứ không phải ghim phiên bản, nhưng nó CŨNG
    không có gì thay thế khi hỏng — nên vẫn hiện ra là đúng, không phải nhiễu.
    """
    m = str(model or "").strip().lower()
    if not m or m == "auto" or m.endswith("/auto"):
        return False
    if "/" not in m:
        return False          # combo / nhãn — đã có nhánh kiểm riêng ở trên
    return True


def check() -> dict[str, Any]:
    """Quét mọi nhánh. Trả {ok, branches: [...], tom_tat}."""
    ids = _model_ids()
    rows: list[dict[str, Any]] = []
    for name, (label, default) in BRANCHES.items():
        model = branch_model(name)
        auth, auth_note = _auth_status(model)

        listed = model in ids if ids else None
        has_prefix = "/" in model

        if not model:
            state, note = ("trong", "chưa đặt model (dùng mặc định hoặc tắt)")
        elif auth == "thieu_xac_thuc":
            state, note = ("thieu_xac_thuc", auth_note)
        elif auth == "tat":
            state, note = ("tat", auth_note)
        elif not has_prefix and listed is False:
            # Id không có tiền tố (combo như "AI vision", "code") thì PHẢI nằm
            # trong /v1/models mới gọi được — không có backend nào nhận nó.
            state, note = ("model_khong_ton_tai",
                           f"'{model}' không có trong /v1/models và không có tiền tố backend")
        elif has_prefix and listed is False:
            # ĐỪNG báo hỏng ở đây. /v1/models KHÔNG liệt kê hết alias ảo: đo
            # thật 2026-07-28 — 'claude/auto' vắng mặt nhưng gọi vẫn chạy
            # (trả lời trong 5 giây), trong khi 'cx/auto' lại có trong danh
            # sách. Chốt "không tồn tại" dựa vào đây là báo động nhầm, mà một
            # bộ kiểm hay kêu oan thì người ta sẽ bỏ qua cả lúc nó kêu đúng.
            state, note = ("ok", f"{auth_note} · alias không liệt kê trong /v1/models")
        else:
            state, note = ("ok", auth_note)

        rows.append({
            "branch": name, "label": label, "model": model,
            "default": default, "state": state, "note": note,
            "auth": auth,
            "ghim_cung": _ghim_mot_model(model),
        })

    bad = [r for r in rows if r["state"] in ("model_khong_ton_tai", "thieu_xac_thuc")]
    ghim = [r for r in rows if r["ghim_cung"] and r["state"] == "ok"]
    return {
        "ok": not bad,
        "checked_models": len(ids),
        "branches": rows,
        # KHÔNG tính vào `ok`: ghim cứng vẫn CHẠY ĐƯỢC, chỉ là không có dự
        # phòng. Cho nó làm đỏ cả bộ kiểm là biến một cảnh báo hữu ích thành
        # tiếng ồn, rồi người ta bỏ qua cả lúc nó kêu đúng.
        "canh_bao_ghim_cung": [
            {"branch": r["branch"], "model": r["model"]} for r in ghim
        ],
        "tom_tat": (
            "Tất cả nhánh đều trỏ vào model có thật và có nguồn xác thực."
            if not bad else
            "Có nhánh sẽ KHÔNG chạy: " + ", ".join(f"{r['branch']} ({r['note']})" for r in bad)
        ) + (
            ""
            if not ghim else
            " · Nhánh ghim MỘT model cụ thể (hết lượt là không có gì thay thế): "
            + ", ".join(f"{r['branch']}={r['model']}" for r in ghim)
            + ". Nên đổi sang '<provider>/auto' hoặc một combo."
        ),
    }


__all__ = ["check"]

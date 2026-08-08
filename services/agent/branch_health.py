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

import hmac
import logging
import os
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


# ── Khoá captcha-solver của provider lệch với CAPTCHA_SOLVER_API_KEY ────────
# Cùng họ lỗi với phần trên: cấu hình sai KHÔNG báo sai cấu hình, nó báo một
# triệu chứng ở chỗ khác. Ở đây triệu chứng là "không lấy được session" / HTTP
# 401 từ solver, nên người ta đi tìm phía đăng nhập chứ không nghĩ tới khoá.
# Đã mất thời gian chẩn đoán hai lần trong một tuần: Flow (07/08) rồi Claude
# (08/08/2026).
#
# Đọc ``config.data`` chứ KHÔNG phải ``config.get()``. ``get()`` tự điền
# ``providers.flow.captcha_solver_api_key`` từ biến môi trường (config.py:1100)
# và không ghi ngược vào ``self.data``; trong khi MỌI nơi gọi thật —
# ``api/claude._claude_cfg``, ``flow_google._pool_config``,
# ``api/gemini_web._solver_cfg`` — đều đọc ``config.data``. So với ``get()`` là
# so với thứ trang Cài đặt hiển thị, không phải thứ đang chạy; đúng khe hở đã
# để lọt lần trước.
#
# CHỈ so khi provider trỏ vào solver NỘI BỘ. ``captcha_base()`` giữ nguyên một
# URL HTTPS lạ (services/captcha.py:23) — tức là solver riêng được hỗ trợ thật,
# và khoá riêng của nó KHÔNG có lý do gì phải trùng ``CAPTCHA_SOLVER_API_KEY``.
# Báo lệch cho trường hợp đó là kêu oan, mà bộ kiểm kêu oan thì sẽ bị bỏ qua cả
# lúc kêu đúng. Dùng thẳng ``captcha_base`` để luật "thế nào là nội bộ" chỉ nằm
# một chỗ, sửa ở đó thì đây theo.
#
# Trạng thái: key_match · key_mismatch · provider_key_missing ·
# CAPTCHA_SOLVER_API_KEY_missing · independent_solver_not_compared (solver
# riêng — ghi nhận, không cảnh báo) · not_configured (bỏ qua hẳn).
_KHONG_CANH_BAO = frozenset({"key_match", "independent_solver_not_compared"})

_CAU_CANH_BAO: dict[str, str] = {
    "key_mismatch":
        "{p} dùng captcha solver nhưng key khác CAPTCHA_SOLVER_API_KEY; "
        "tự khôi phục session có thể thất bại 401.",
    "provider_key_missing":
        "{p} khai captcha_solver_url nhưng không có captcha_solver_api_key; "
        "lệnh gọi solver sẽ đi không kèm Authorization.",
    "CAPTCHA_SOLVER_API_KEY_missing":
        "{p} cần captcha solver nhưng biến môi trường CAPTCHA_SOLVER_API_KEY "
        "chưa đặt; không có gì để đối chiếu.",
}


def kiem_khoa_captcha() -> dict[str, Any]:
    """Đối chiếu khoá solver của từng provider với ``CAPTCHA_SOLVER_API_KEY``.

    Chỉ xét provider CÓ khai dùng solver, và trong đó chỉ SO những provider
    trỏ vào solver nội bộ. Provider không khai thì im lặng — một bộ kiểm hay
    kêu oan sẽ bị bỏ qua cả lúc kêu đúng.

    KHÔNG trả về giá trị khoá, hash, tiền tố hay độ dài. Chỉ trả tên provider
    và một nhãn trạng thái.
    """
    from services.captcha import INTERNAL, captcha_base

    env_key = os.getenv("CAPTCHA_SOLVER_API_KEY", "").strip()
    providers = config.data.get("providers") or {}
    if not isinstance(providers, dict):
        providers = {}

    da_kiem: list[dict[str, str]] = []
    for ten, cfg in sorted(providers.items()):
        if not isinstance(cfg, dict):
            continue
        url = str(cfg.get("captcha_solver_url") or "").strip()
        key = str(cfg.get("captcha_solver_api_key") or "").strip()
        if not url and not key:
            continue                      # not_configured — không dùng solver

        if captcha_base(url) != INTERNAL:
            trang_thai = "independent_solver_not_compared"
        elif not env_key:
            trang_thai = "CAPTCHA_SOLVER_API_KEY_missing"
        elif not key:
            trang_thai = "provider_key_missing"
        # So trên BYTES: `compare_digest` ném TypeError khi chuỗi có ký tự
        # ngoài ASCII ("comparing strings with non-ASCII characters is not
        # supported"), mà đây là bộ kiểm sức khoẻ — một khoá có dấu sẽ biến
        # nó thành HTTP 500 thay vì một dòng cảnh báo.
        elif hmac.compare_digest(key.encode("utf-8"), env_key.encode("utf-8")):
            trang_thai = "key_match"
        else:
            trang_thai = "key_mismatch"
        da_kiem.append({"provider": str(ten), "status": trang_thai})

    return {
        "expected_key_configured": bool(env_key),
        # Cần `checked` để phân biệt "không cảnh báo vì mọi thứ khớp" với
        # "không cảnh báo vì chẳng quét provider nào" — hai tình huống trông
        # giống hệt nhau nếu chỉ nhìn `warnings` rỗng.
        "checked": da_kiem,
        "warnings": [r for r in da_kiem if r["status"] not in _KHONG_CANH_BAO],
    }


def check() -> dict[str, Any]:
    """Quét mọi nhánh. Trả {ok, branches: [...], captcha_solver, tom_tat}."""
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
    captcha = kiem_khoa_captcha()
    return {
        # KHÔNG tính lệch khoá captcha vào `ok`: về kiến trúc, một provider
        # được phép dùng solver riêng với khoá riêng hợp lệ. Nó là cảnh báo,
        # không phải kết luận hỏng.
        "ok": not bad,
        "checked_models": len(ids),
        "branches": rows,
        "captcha_solver": captcha,
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
        ) + (
            ""
            if not captcha["warnings"] else
            " · " + " ".join(
                _CAU_CANH_BAO[w["status"]].format(p=w["provider"])
                for w in captcha["warnings"]
            )
        ),
    }


__all__ = ["check"]
